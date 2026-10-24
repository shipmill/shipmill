"""Spec 038, #589 (S-038-26): one product, a home repo and two components, driven from a fault
in component A to its fix in component B and back, over one scripted forge with no network.

Every write goes through the real `shipmill gh` (in process, its gh replaced by the forge):
A's session's as `shipmill gh` in A's checkout, the coordinator's as `shipmill gh --product`
in the home repo's checkout, chains.py link's and upstream_state.py's included, so the token
each write carries is the one GitHub minted for it. A's triage is the real triage_state.py,
run as the watch runs it, over a stand-in gh answering from the same forge"""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from shipmill.app_gh import named_repo, product_refusal
from shipmill.cli import main

from .test_app import APP_ID, GRANTED, REPO, FakeSigner
from .test_app_gh import WITH_APP, checkout
from .test_app_token import FAKE_GH as RECORDING_GH
from .test_app_token import executable
from .test_chains import UVX, gh_call
from .test_chains_e2e import FAKE_GH
from .test_product_token import ASKED, ProductApi

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "github-issue-triage" / "scripts"
WATCH = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
COMMENTS = ROOT / "skills" / "github-issue-triage" / "references" / "comments.md"
HOME = REPO  # romamo/demo: the product's home repo, whose gate is the coordinator
A, B = "romamo/api", "romamo/web"  # the two components, under the App's one romamo installation
SLUG = "demo-agent"  # the App's bot, as GraphQL spells its login
BOT = f"{SLUG}[bot]"
COMPONENT = WITH_APP + f'\n[product]\nhome = "{HOME}"\n'
COORDINATOR = WITH_APP + f'\n[product]\nrepos = ["{A}", "{B}"]\n'
SESSION = dict(GRANTED)  # a session's one-repo token asks these


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scripts() -> tuple[ModuleType, ModuleType, ModuleType]:
    """chains.py, upstream_state.py, and watch_state.py, as the skills run them"""
    sys.path.insert(0, str(SCRIPTS))  # they import each other, as when run from their folder
    try:
        return (
            load("chains_coordinator_e2e", SCRIPTS / "chains.py"),
            load("upstream_state_coordinator_e2e", SCRIPTS / "upstream_state.py"),
            load("watch_state_coordinator_e2e", WATCH),
        )
    finally:
        sys.path.remove(str(SCRIPTS))


# -- the forge ------------------------------------------------------------------------------


@dataclass
class Note:
    body: str
    at: str
    login: str
    bot: bool
    association: str

    def node(self) -> dict[str, Any]:
        author = {"__typename": "Bot" if self.bot else "User", "login": self.login}
        return {"body": self.body, "createdAt": self.at, "author": author, "authorAssociation": self.association}


@dataclass
class Ticket:
    repo: str
    number: int
    title: str
    body: str
    labels: list[str]
    login: str
    bot: bool
    association: str
    comments: list[Note] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    subs: list[str] = field(default_factory=list)
    state: str = "OPEN"
    reason: str | None = None
    closed_at: str | None = None
    closer: tuple[str, bool] | None = None
    pr: int | None = None

    @property
    def ref(self) -> str:
        return f"{self.repo}#{self.number}"

    @property
    def id(self) -> str:
        return f"I_{self.ref}"


@dataclass(frozen=True)
class Call:
    """One gh command `shipmill gh` ran: the token it carried, GH_REPO, and its arguments"""

    token: str
    target: str | None
    args: tuple[str, ...]


class Forge:
    """GitHub across the product's three repos: issues, comments, labels, both link forms, and
    closes, each event a minute after the last. It answers the GraphQL of chains.py and
    upstream_state.py, the gh commands `shipmill gh` runs (recorded with their token), and
    triage_state.py through the stand-in gh"""

    def __init__(self, tmp: Path, ch: ModuleType, us: ModuleType) -> None:
        self.tmp, self.ch, self.us = tmp, ch, us
        self.tickets: dict[str, Ticket] = {}
        self.minute = 0
        self.calls: list[Call] = []  # every gh command `shipmill gh` ran
        self.files = {f"{B}:src/orders.ts": "export const PAGE = 100\n"}

    def now(self) -> str:
        self.minute += 1
        return f"2026-10-24T{10 + self.minute // 60:02d}:{self.minute % 60:02d}:00Z"

    def find(self, owner: str, name: str, number: int) -> Ticket:
        return next(
            t for t in self.tickets.values() if t.repo.lower() == f"{owner}/{name}".lower() and t.number == number
        )

    def by_id(self, node: str) -> Ticket:
        return next(t for t in self.tickets.values() if t.id == node)

    def open(
        self, repo: str, title: str, body: str, labels: list[str], login: str, bot: bool, association: str
    ) -> Ticket:
        number = 1 + max((t.number for t in self.tickets.values() if t.repo == repo), default=0)
        ticket = Ticket(repo, number, title, body, labels, login, bot, association)
        self.tickets[ticket.ref] = ticket
        return ticket

    def close(self, ref: str, login: str, bot: bool, reason: str = "COMPLETED", pr: int | None = None) -> None:
        ticket = self.tickets[ref]
        ticket.state, ticket.reason, ticket.closed_at = "CLOSED", reason, self.now()
        ticket.closer, ticket.pr = (login, bot), pr

    # -- `shipmill gh`'s gh, as a GhRunner

    def gh(self, default: str) -> Any:
        """The gh `shipmill gh` runs in a checkout whose origin is default: it records the
        command and its token, then does what gh would, printing gh's output"""

        def run(argv: Sequence[str], env: Mapping[str, str]) -> int:
            args = list(argv[1:])
            target = env.get("GH_REPO")
            self.calls.append(Call(env["GH_TOKEN"], target, tuple(args)))
            repo = named_repo(args) or target or default
            return self.command(repo, args)

        return run

    def command(self, repo: str, args: list[str]) -> int:
        if args[:2] == ["api", "graphql"]:
            response = self.graphql(*gh_call(args))
            print(json.dumps(response))
            return 1 if response.get("errors") else 0
        if args[0] == "api":  # a REST read, such as a file's contents
            owner, name, rest = args[1].removeprefix("repos/").split("/", 2)
            path = rest.removeprefix("contents/")
            print(json.dumps({"path": path, "content": self.files[f"{owner}/{name}:{path}"]}))
            return 0
        flags = dict(zip(args[2::2], args[3::2], strict=False))
        if args[:2] == ["issue", "create"]:
            body = Path(flags["--body-file"]).read_text(encoding="utf-8")
            labels = [flags["--label"]] if "--label" in flags else []
            ticket = self.open(repo, flags["--title"], body, labels, SLUG, True, "NONE")
            print(f"https://github.com/{repo}/issues/{ticket.number}")
            return 0
        number = int(args[2])
        owner, _, name = repo.partition("/")
        ticket = self.find(owner, name, number)
        flags = dict(zip(args[3::2], args[4::2], strict=False))
        if args[:2] == ["issue", "comment"]:
            body = Path(flags["--body-file"]).read_text(encoding="utf-8")
            ticket.comments.append(Note(body, self.now(), SLUG, True, "NONE"))
            return 0
        if args[:2] == ["issue", "close"]:
            self.close(
                ticket.ref, SLUG, True, {"completed": "COMPLETED", "not planned": "NOT_PLANNED"}[flags["--reason"]]
            )
            return 0
        raise AssertionError(f"gh {' '.join(args)}: not a command this forge knows")

    # -- GraphQL: chains.py link's and upstream_state.py's queries

    def native(self, ref: str) -> dict[str, Any]:
        t = self.tickets[ref]
        return {
            "number": t.number,
            "state": t.state,
            "stateReason": t.reason,
            "closedAt": t.closed_at,
            "repository": {"nameWithOwner": t.repo},
        }

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        ch, us = self.ch, self.us
        page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
        if query == ch.RESOLVE:
            t = self.find(variables["owner"], variables["name"], variables["number"])
            return {"data": {"repository": {"issueOrPullRequest": {"__typename": "Issue", "id": t.id, "body": t.body}}}}
        if query == ch.BLOCKED_BY:
            nodes = [{"id": self.tickets[r].id} for r in self.by_id(variables["id"]).blocked_by]
            return {"data": {"node": {"blockedBy": {**page, "nodes": nodes}}}}
        if query == ch.PARENT:
            child = self.by_id(variables["id"])
            parent = next((t for t in self.tickets.values() if child.ref in t.subs), None)
            return {"data": {"node": {"parent": None if parent is None else {"id": parent.id}}}}
        if query == ch.ADD_BLOCKED_BY:
            self.by_id(variables["issue"]).blocked_by.append(self.by_id(variables["blocking"]).ref)
            return {"data": {"addBlockedBy": {"issue": {"id": variables["issue"]}}}}
        if query == ch.ADD_SUB_ISSUE:
            self.by_id(variables["issue"]).subs.append(self.by_id(variables["sub"]).ref)
            return {"data": {"addSubIssue": {"issue": {"id": variables["issue"]}}}}
        if query == ch.UPDATE_BODY:
            self.by_id(variables["id"]).body = variables["body"]
            return {"data": {"updateIssue": {"issue": {"id": variables["id"]}}}}
        if query == us.REPORTS:
            repo = f"{variables['owner']}/{variables['name']}".lower()
            found: list[dict[str, Any]] = [
                {"number": t.number, "author": self.author(t), "authorAssociation": t.association}
                for t in self.tickets.values()
                if t.repo.lower() == repo and t.state == "OPEN" and "upstream" in t.labels
            ]
            return {"data": {"repository": {"issues": {**page, "nodes": found}}}}
        if query == us.REPORT:
            t = self.find(variables["owner"], variables["name"], variables["number"])
            issue = {
                "number": t.number,
                "body": t.body,
                "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in t.labels]},
                "comments": {
                    "pageInfo": {"hasPreviousPage": False, "startCursor": None},
                    "nodes": [c.node() for c in t.comments],
                },
                "subIssues": {"pageInfo": {"hasNextPage": False}, "nodes": [self.native(s) for s in t.subs]},
            }
            return {"data": {"repository": {"issue": issue}}}
        count = sum(1 for key in variables if key.startswith("o"))
        assert query == us.children_query(count), f"an unexpected query: {query[:80]}"
        data = {}
        for i in range(count):
            t = self.find(variables[f"o{i}"], variables[f"n{i}"], variables[f"k{i}"])
            data[f"c{i}"] = {"issueOrPullRequest": {"__typename": "Issue", "state": t.state, "stateReason": t.reason}}
        return {"data": data}

    @staticmethod
    def author(t: Ticket) -> dict[str, Any]:
        return {"__typename": "Bot" if t.bot else "User", "login": t.login}

    # -- triage_state.py, through the stand-in gh

    def answers(self) -> dict[str, Any]:
        page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
        first = {}
        for repo in sorted({t.repo for t in self.tickets.values()}):
            mine = sorted((t for t in self.tickets.values() if t.repo == repo), key=lambda t: -t.number)
            first[repo] = {
                "open": {**page, "nodes": [self.open_node(t) for t in mine if t.state == "OPEN"]},
                "tags": {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": []},
                "closed": {"nodes": [self.closed_node(t) for t in mine if t.state == "CLOSED"]},
            }
        items = {ref: {"__typename": "Issue", **self.native(ref)} for ref in self.tickets}
        comments = {
            ref: {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": [c.node() for c in t.comments]}
            for ref, t in self.tickets.items()
        }
        return {"first": first, "items": items, "comments": comments}

    def open_node(self, t: Ticket) -> dict[str, Any]:
        page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
        return {
            "number": t.number,
            "title": t.title,
            "body": t.body,
            "author": self.author(t),
            "authorAssociation": t.association,
            "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in t.labels]},
            "assignees": {"nodes": []},
            "comments": {"nodes": [c.node() for c in t.comments]},
            "timelineItems": {**page, "nodes": []},
            "blockedBy": {**page, "nodes": [self.native(r) for r in t.blocked_by]},
            "subIssues": {**page, "nodes": [self.native(r) for r in t.subs]},
        }

    def closed_node(self, t: Ticket) -> dict[str, Any]:
        assert t.closer is not None
        who, bot = t.closer
        closer = None if t.pr is None else {"__typename": "PullRequest", "number": t.pr, "merged": True}
        return {
            "number": t.number,
            "title": t.title,
            "stateReason": t.reason,
            "body": t.body,
            "labels": {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in t.labels]},
            "comments": {"nodes": [c.node() for c in t.comments[-5:]]},
            "refs": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []},
            "timelineItems": {
                "nodes": [
                    {
                        "createdAt": t.closed_at,
                        "actor": {"__typename": "Bot" if bot else "User", "login": who},
                        "closer": closer,
                    }
                ]
            },
        }


# -- the checkouts and their sessions ----------------------------------------------------


@dataclass
class Product:
    """The forge, GitHub's App API, the host, and a checkout per repo; each session runs its
    `shipmill gh` and scripts from its own checkout"""

    forge: Forge
    api: ProductApi
    home: Path  # the host's home, with the App's key at its default path
    fakes: Path
    checkouts: dict[str, Path]
    ws: ModuleType

    def environ(self) -> dict[str, str]:
        return {"PATH": os.pathsep.join([str(self.fakes), "/usr/bin", "/bin"]), "RECORD": str(self.fakes)}

    def shipmill(self, repo: str, *argv: str) -> int:
        """`shipmill --repo <repo's checkout> <argv>`, in process"""
        code: int = main(
            ["--repo", str(self.checkouts[repo]), *argv],
            api=self.api,
            signer=FakeSigner(),
            environ=self.environ(),
            home=self.home,
            gh_runner=self.forge.gh(repo),
        )
        return code

    def execute(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """The commands chains.py and upstream_state.py run: git, plain gh (the host's login,
        for reads), and the plugin's pinned `shipmill gh`"""
        if cmd[0] == "git":
            return subprocess.run(cmd, capture_output=True, text=True, check=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            if cmd[0] == "gh":
                response = self.forge.graphql(*gh_call(cmd[1:]))
                print(json.dumps(response))
                code = 1 if response.get("errors") else 0
            else:
                assert cmd[:2] == UVX and cmd[2] == "--repo", cmd
                repo = next(r for r, top in self.checkouts.items() if str(top.resolve()) == cmd[3])
                code = self.shipmill(repo, *cmd[4:])
        return subprocess.CompletedProcess(cmd, code, out.getvalue(), "")

    def body(self, name: str, text: str) -> str:
        path = self.forge.tmp / "bodies" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def link(self, ch: ModuleType, repo: str, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ch.main(["link", *argv], run=self.forge.graphql, checkout=self.checkouts[repo], execute=self.execute)
        assert code == 0
        return out.getvalue()

    def upstream(self, us: ModuleType) -> tuple[int, dict[str, tuple[str, str]]]:
        """upstream_state.py in the home repo's checkout, as the coordinator's watch runs it"""
        top = self.checkouts[HOME]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code: int = us.main([HOME, "--json", "--bot-login", BOT], us.default_readers(HOME, top, self.execute), top)
        rows = [json.loads(line) for line in out.getvalue().splitlines()]
        return code, {r["ref"]: (r["state"], r["note"]) for r in rows}

    def triage(self, repo: str) -> tuple[int, dict[str, tuple[str, str]]]:
        """triage_state.py on repo as its watch runs it: the command watch_state.py builds from
        the checkout's config, its [product] home as --home"""
        config = (self.checkouts[repo] / ".github" / "shipmill.toml").read_text(encoding="utf-8")
        home = self.ws.product_home(config, self.checkouts[repo] / ".github" / "shipmill.toml")
        data = self.forge.tmp / "gh.json"
        data.write_text(json.dumps(self.forge.answers()), encoding="utf-8")
        bin_dir = self.forge.tmp / "triage-gh"
        if not bin_dir.exists():
            bin_dir.mkdir()
            executable(bin_dir / "gh", FAKE_GH.format(python=sys.executable))
        env = {"PATH": os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]), "FAKE_GH_DATA": str(data)}
        cmd = self.ws.triage_command(repo, BOT, True, home)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        assert proc.returncode in (0, 1), proc.stderr
        rows = [json.loads(line) for line in proc.stdout.splitlines()]
        return proc.returncode, {f"{repo}#{r['number']}": (r["state"], r["note"]) for r in rows}


@pytest.fixture
def product(tmp_path: Path, scripts: tuple[ModuleType, ModuleType, ModuleType]) -> Product:
    ch, us, ws = scripts
    fakes, home = tmp_path / "fakes", tmp_path / "home"
    fakes.mkdir()
    executable(fakes / "gh", RECORDING_GH)  # on PATH for `shipmill gh` to find; the forge runs instead
    key = home / ".config" / "shipmill" / f"app-{APP_ID}.pem"
    key.parent.mkdir(parents=True)
    key.write_text("not a real key\n", encoding="utf-8")
    key.chmod(0o600)
    checkouts = {}
    for repo, config in ((HOME, COORDINATOR), (A, COMPONENT), (B, COMPONENT)):
        folder = tmp_path / repo.replace("/", "-")
        folder.mkdir()
        checkouts[repo] = checkout(folder, config, origin=f"https://github.com/{repo}.git")
    # the App on the home repo and both components, a session's permissions on each
    api = ProductApi(granted={A: dict(GRANTED), B: dict(GRANTED)}, now=dt.datetime.now(dt.UTC))
    return Product(Forge(tmp_path, ch, us), api, home, fakes, checkouts, ws)


def template(heading: str, start: str) -> str:
    """The first comments.md line after heading that starts with start"""
    after = COMMENTS.read_text(encoding="utf-8").split(f"\n## {heading}\n", 1)[1]
    return next(line for line in after.splitlines() if line.startswith(start))


def minted(api: ProductApi) -> dict[str, dict[str, Any]]:
    """Each token GitHub minted, by value: the repositories and permissions it was asked for"""
    return {f"token-{i}": dict(body) for i, (_, body) in enumerate(api.posts, start=1)}


# -- the run ------------------------------------------------------------------------------------

REPORT = """Checkout fails for an order of more than 100 lines. It holds #1.

## Reproduce

POST /orders with 101 lines returns 502; with 100 lines it returns 201

## Touches

The orders page of the web app, which pages the order's lines

## Suspected code

Guess: the page size the web app caps an order's lines at
"""


def test_s038_26_a_fault_in_one_component_is_routed_to_another_and_closed_back(
    product: Product, scripts: tuple[ModuleType, ModuleType, ModuleType]
) -> None:
    ch, us, _ = scripts
    forge = product.forge
    issue = forge.open(A, "Checkout fails on a big order", "", [], "maria", False, "OWNER")
    waiting = issue.ref
    verdict = product.body("t1", "Triage: **implement**.")
    assert product.shipmill(A, "gh", "issue", "comment", "1", "--body-file", verdict) == 0

    # 1. A's session traces it to B's code and reports it in its own repo (resolve, Phase 2)
    filed = ["issue", "create", "--label", "upstream", "--title", "Orders over 100 lines fail"]
    assert product.shipmill(A, "gh", *filed, "--body-file", product.body("report", REPORT)) == 0
    report = f"{A}#2"
    assert forge.tickets[report].labels == ["upstream"]
    assert product.link(ch, A, waiting, "--blocked-by", report) == (
        f"linked: {waiting} is blocked by {report}\nadded to {waiting}: Depends on {report}\n"
    )
    hold = f"On hold: waits on {report}, the upstream report of orders over 100 lines"
    assert product.shipmill(A, "gh", "issue", "comment", "1", "--body-file", product.body("hold", hold)) == 0
    routed = template("Upstream report", "Triage: **upstream**. Routed by").replace("{owner/home}", HOME)
    assert product.shipmill(A, "gh", "issue", "comment", "2", "--body-file", product.body("t2", routed)) == 0
    # A's session can't link to B's repo, nor write there (S-038-10, S-038-11)
    calls = len(forge.calls)
    with pytest.raises(SystemExit) as refused:
        product.link(ch, A, waiting, "--blocked-by", f"{B}#9")
    assert refused.value.code == 2 and len(forge.calls) == calls

    code, rows = product.triage(A)
    assert code == 0  # nothing for A's gate to start: it waits outside
    assert rows[report] == ("UPSTREAM", f"routed by {HOME}")
    assert rows[waiting][0] == "BLOCKED" and report in rows[waiting][1]

    # 2. The coordinator routes it: reads B's code, files the fix in B, links it under the report
    assert product.upstream(us) == (1, {report: ("ROUTE_DUE", "no children")})
    assert product.shipmill(HOME, "gh", "--product", B, "api", f"repos/{B}/contents/src/orders.ts") == 0
    quoted = REPORT.split("\n", 1)[1]
    routed_body = f"Routed from {report}, an upstream report of the product's {A}:\n\n{quoted}"
    filed = ["issue", "create", "-R", B, "--title", "Page an order's lines past 100"]
    assert product.shipmill(HOME, "gh", "--product", B, *filed, "--body-file", product.body("routed", routed_body)) == 0
    fix = f"{B}#1"
    assert product.link(ch, HOME, "--product", report, "--child", fix) == (
        f"linked: {fix} is a sub-issue of {report}\nadded to {report}: Depends on {fix}\n"
    )
    assert product.upstream(us) == (0, {report: ("ROUTED", f"children 0/1 closed {fix}:open")})
    # B's own session takes the routed issue up, in its own repo, like any other
    assert product.triage(B) == (1, {fix: ("NEW", "")})
    assert product.triage(A)[1][waiting][0] == "BLOCKED"

    # 3. B's pull request merges and closes it
    forge.close(fix, SLUG, True, pr=12)
    assert product.upstream(us) == (1, {report: ("CLOSE_DUE", f"completed, children 1/1 closed {fix}:closed")})

    # 4. The coordinator closes the report as completed, with its summary (comments.md)
    line = template("Upstream report", "- {owner/repo#C}:")
    item = line.replace("{owner/repo#C}", fix).replace("{completed | not planned}", "completed")
    item = item.replace("{by owner/repo#PR | with no pull request}", f"by {B}#12")
    summary = f"Every issue this was routed to is closed:\n\n{item}\n\nThe orders page now pages an order's lines.\n"
    posted = ["issue", "comment", "2", "-R", A, "--body-file", product.body("summary", summary)]
    assert product.shipmill(HOME, "gh", "--product", A, *posted) == 0
    assert product.shipmill(HOME, "gh", "--product", A, "issue", "close", "2", "-R", A, "--reason", "completed") == 0
    closed = forge.tickets[report]
    assert (closed.state, closed.reason) == ("CLOSED", "COMPLETED")
    assert closed.comments[-1].body.startswith(
        f"Every issue this was routed to is closed:\n\n- {fix}: completed, by {B}#12"
    )
    assert product.upstream(us) == (0, {})

    # A's issue reads UNBLOCKED in its own repo: its session reads the summary and resumes
    code, rows = product.triage(A)
    assert code == 1
    assert rows[waiting][0] == "UNBLOCKED" and f"{report}:closed" in rows[waiting][1]
    assert report not in rows  # a report the coordinator closed is never a SUSPECT_CLOSE

    # Along the way: every write carried a token GitHub minted for it, and named only its scope
    tokens = minted(product.api)
    session = {t for t, asked in tokens.items() if asked["permissions"] == SESSION}
    coordinator = {t for t, asked in tokens.items() if asked["permissions"] == ASKED}
    assert session | coordinator == set(tokens) and session and coordinator
    assert all(tokens[t]["repositories"] == ["api"] for t in session)  # A's session: romamo/api alone
    assert all(tokens[t]["repositories"] == ["api", "web"] for t in coordinator)
    a_calls = [c for c in forge.calls if c.token in session]
    product_calls = [c for c in forge.calls if c.token in coordinator]
    assert len(a_calls) + len(product_calls) == len(forge.calls)
    # A's session: no -R and no GH_REPO but its own repo, and every mutation on its own issues
    assert a_calls and all(c.target is None and named_repo(list(c.args)) in (None, A) for c in a_calls)
    for c in a_calls:
        if c.args[:2] == ("api", "graphql"):
            query, variables = gh_call(list(c.args))
            ids = [v for k, v in variables.items() if k in ("id", "issue", "blocking", "sub")]
            assert ids and all(forge.by_id(str(i)).repo == A for i in ids), c
    # the product token: issues and reads only, never contents or a pull request
    assert {c.args[0] for c in product_calls} == {"issue", "api"}
    for c in product_calls:
        assert product_refusal(list(c.args)) is None and c.target in (A, B)
        if c.args[:2] == ("api", "graphql"):
            query, _ = gh_call(list(c.args))
            assert query in (ch.ADD_SUB_ISSUE, ch.UPDATE_BODY) or not query.lstrip().startswith("mutation"), c
        elif c.args[0] == "api":
            assert "/contents/" in c.args[1] and len(c.args) == 2  # a GET: no -X, -f, or --input
        else:
            assert c.args[1] in ("create", "comment", "close"), c

    def mutations(calls: list[Call]) -> list[str]:
        queries = [gh_call(list(c.args))[0] for c in calls if c.args[:2] == ("api", "graphql")]
        return [q for q in queries if q.lstrip().startswith("mutation")]

    assert mutations(a_calls) == [ch.ADD_BLOCKED_BY, ch.UPDATE_BODY]  # A's link, in A
    assert mutations(product_calls) == [ch.ADD_SUB_ISSUE, ch.UPDATE_BODY]  # the coordinator's link, on A's report
    issue_writes = [c.args[:2] for c in product_calls if c.args[0] == "issue"]
    assert issue_writes == [("issue", "create"), ("issue", "comment"), ("issue", "close")]
    # upstream_state.py read each component's reports with the product token, the home repo's with plain gh
    read = {c.target for c in product_calls if c.args[:2] == ("api", "graphql") and us.REPORTS in c.args[3]}
    assert read == {A, B}
    assert all(tokens[t]["permissions"]["contents"] == "read" for t in coordinator)
    assert all(tokens[t]["permissions"]["pull_requests"] == "read" for t in coordinator)
    assert not any(c.args[0] == "pr" for c in forge.calls)
