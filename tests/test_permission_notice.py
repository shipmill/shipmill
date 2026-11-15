"""Spec 060: the gate's sweep files one item per installation for the App's owner when an
optional permission a repo of the installation needs is missing. The notice's seams (the
installation's reads, the gate's writer) are fakes; ApiReads runs against a fake Api, so no
test reaches GitHub"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipmill import cli_command
from shipmill.agents import Login, RoleName
from shipmill.app import (
    NOTICE_PERMISSIONS,
    OPTIONAL_PERMISSIONS,
    PERMISSIONS,
    Access,
    Answer,
    AppRecord,
    Identity,
    Installation,
)
from shipmill.errors import ReleaseError
from shipmill.gate import Action, Decision, state_dir, tick_lines
from shipmill.github import PROPOSAL_LABEL, Forbidden
from shipmill.gitrepo import Git
from shipmill.permission_notice import (
    LABEL,
    NO_APP,
    ROLE_LABEL,
    VERIFIED,
    ApiReads,
    Candidate,
    Filed,
    Listed,
    Notice,
    Seams,
    carrier,
    notice,
    open_reads,
    sweep_permissions,
)
from shipmill.roles import ResolvedRole
from shipmill.walk import SWEEP, Swept

from . import test_units  # its TestLongBodies' gh, read off the module so its tests aren't collected here
from .conftest import POLICY
from .test_app import FakeSigner, key_file
from .test_gate import checkout
from .test_gate_walk import INCIDENT, LATER, NOW, REPO, Source, cfg, tick

__all__ = ["checkout"]  # the fixture, imported for the tests below

APP_ID = 7
APP = Identity(APP_ID, "demo-agent", 99, Path("/k.pem"))
[DEPLOYMENTS] = OPTIONAL_PERMISSIONS
MARKER = "<!-- shipmill-permission: deployments read -->"
PAGE = "https://github.com/settings/installations/77"
SESSION = {p.key: p.access for p in PERMISSIONS}
GRANTING = {**SESSION, "deployments": Access.READ}
GATE = POLICY + f'\n[agents]\nprompt = "/t"\napp_id = {APP_ID}\n'
ENVIRONMENTS = '\n[environments.production]\nlane = "stable"\nworkflow = "deploy.yml"\n'
NEEDING = GATE + ENVIRONMENTS
HOME = '\n[product]\nrepos = ["romamo/alpha"]\n'
USER_APP = AppRecord("demo-agent", "romamo", False)
ORG_APP = AppRecord("demo-agent", "shipmill", True)
MAINTAINERS = (ResolvedRole(RoleName("maintainer"), (Login("amy"), Login("bob")), (), False),)


@dataclass
class FakeReads:
    """The installation as the notice reads it: each repo's config and its marked issues"""

    configs: dict[str, str | None]
    filed: dict[str, list[Filed]] = field(default_factory=dict)
    granted: Mapping[str, Access] = field(default_factory=lambda: dict(SESSION))
    app: AppRecord = USER_APP
    log: list[str] = field(default_factory=list)
    archived: frozenset[str] = frozenset()

    @property
    def installation(self) -> Installation:
        return Installation("demo-agent", 77, self.granted, PAGE)

    def repos(self) -> tuple[Listed, ...]:
        self.log.append("repos")
        return tuple(Listed(name, name in self.archived) for name in self.configs)

    def issues(self, repo: str) -> tuple[Filed, ...]:
        self.log.append(f"issues {repo}")
        return tuple(self.filed.get(repo, []))

    def config(self, repo: str) -> str | None:
        self.log.append(f"config {repo}")
        return self.configs[repo]


@dataclass
class FakeWriter:
    """GitHub as the App in one repo; a filed issue shows in the reads' next sweep"""

    reads: FakeReads
    repo: str
    created: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = field(default_factory=list)
    closed: list[tuple[int, str]] = field(default_factory=list)

    def create_issue(self, title: str, body: str, labels: Sequence[str] = (), assignees: Sequence[str] = ()) -> int:
        number = 100 + len(self.created)
        self.created.append((title, body, tuple(labels), tuple(assignees)))
        self.reads.filed.setdefault(self.repo, []).append(Filed(self.repo, number, body.splitlines()[0], True))
        return number

    def close_issue(self, number: int, comment: str) -> None:
        self.closed.append((number, comment))
        found = self.reads.filed[self.repo]
        found[:] = [Filed(f.repo, f.number, f.marker, False) if f.number == number else f for f in found]


class Refusing(FakeWriter):
    def create_issue(self, title: str, body: str, labels: Sequence[str] = (), assignees: Sequence[str] = ()) -> int:
        raise Forbidden("gh issue create failed: Resource not accessible by integration (HTTP 403)")


def run(reads: FakeReads, repo: str = REPO, dry_run: bool = False) -> tuple[Notice, FakeWriter]:
    writer = FakeWriter(reads, repo)
    return notice(reads, lambda: writer, repo, APP_ID, ("amy", "bob"), dry_run), writer


@dataclass
class Opened:
    """The seams the gate is given, each opening logged"""

    reads: FakeReads
    writer: FakeWriter
    opened: list[str] = field(default_factory=list)

    def seams(self) -> Seams:
        def reads(identity: Identity) -> FakeReads:
            self.opened.append("reads")
            return self.reads

        def writer(identity: Identity) -> FakeWriter:
            self.opened.append("writer")
            return self.writer

        return Seams(reads, writer)


def swept(git: Git, opened: Opened, source: Source | None = None, app: bool = True, **flags: Any) -> Decision:
    return tick(
        git,
        source or Source(),
        agents=cfg(app_id=APP_ID) if app else cfg(),
        app=lambda app_id: APP,
        app_env=lambda identity: {},
        roles=lambda config, login: MAINTAINERS,
        permissions=opened.seams(),
        **flags,
    )


def stored(git: Git) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((state_dir(git) / SWEEP).read_text())
    return found


# -- filing


def test_s060_2_the_carriers_sweep_files_one_issue_in_its_own_repo(checkout: Git) -> None:
    reads = FakeReads({REPO: NEEDING})
    opened = Opened(reads, FakeWriter(reads, REPO))
    decision = swept(checkout, opened)
    [(title, body, labels, assignees)] = opened.writer.created
    assert body.split("\n", 1)[0] == MARKER
    assert title == "Grant the App Deployments: read and accept it on its installation"
    assert labels == (LABEL, ROLE_LABEL) == ("shipmill-permission", "role:maintainer")
    assert assignees == ("amy", "bob")  # the users the maintainer role resolves to on this tick
    assert decision.permissions == "permissions: filed #100 Deployments: read"


def test_s060_2_gh_assigns_the_issue_as_it_creates_it(tmp_path: Path) -> None:
    gh = test_units.TestLongBodies.gh(tmp_path)
    assert gh.create_issue("t", f"{MARKER}\nbody", (PROPOSAL_LABEL,), ("amy", "bob")) == 7
    [created] = [line for line in (tmp_path / "args").read_text().splitlines() if line.startswith("issue create")]
    assert created.endswith(f"--label {PROPOSAL_LABEL} --assignee amy --assignee bob")
    assert (tmp_path / "stdin").read_text().split("\n", 1)[0] == MARKER


def test_s060_3_the_body_names_the_permission_its_use_the_repos_the_links_and_the_check() -> None:
    other = "romamo/api"
    for app, link in (
        (USER_APP, "https://github.com/settings/apps/demo-agent/permissions"),
        (ORG_APP, "https://github.com/organizations/shipmill/settings/apps/demo-agent/permissions"),
    ):
        reads = FakeReads({other: NEEDING, REPO: NEEDING}, app=app)
        _, writer = run(reads, other)  # romamo/api comes first by name: the carrier
        [(_, body, _, _)] = writer.created
        assert "**Deployments: read**" in body and DEPLOYMENTS.serves in body
        assert f"- `{other}`: its `[environments]`" in body and f"- `{REPO}`: its `[environments]`" in body
        assert "One accept covers every repo of the installation." in body
        assert f"1. In the App's settings, set Deployments to read: {link}\n" in body
        assert f"2. Accept the new permission on the installation's page: {PAGE}\n" in body
        check = body.split("## Check\n", 1)[1]
        assert f"`{cli_command()} doctor` in `{other}` shows the `app` row as PASS for Deployments: read" in check


@pytest.mark.parametrize("where", [REPO, "romamo/other"], ids=["own", "another"])
@pytest.mark.parametrize("still_open", [True, False], ids=["open", "closed"])
def test_s060_4_an_issue_with_the_marker_anywhere_in_the_installation_files_no_second(
    where: str, still_open: bool
) -> None:
    """Closed as completed or as not planned reads the same: closed, so never filed again"""
    reads = FakeReads({REPO: NEEDING, "romamo/other": NEEDING}, {where: [Filed(where, 5, MARKER, still_open)]})
    done, writer = run(reads)
    assert writer.created == [] and writer.closed == []
    assert done.parts == (f"Deployments: read in {where}#5{'' if still_open else ' (closed)'}",)


def test_s060_4_a_later_sweep_files_no_second_issue(checkout: Git) -> None:
    reads = FakeReads({REPO: NEEDING})
    opened = Opened(reads, FakeWriter(reads, REPO))
    swept(checkout, opened)
    later = swept(checkout, opened, sweep_now=True, now=LATER)
    assert len(opened.writer.created) == 1
    assert later.permissions == f"permissions: Deployments: read in {REPO}#100"


def test_s060_5_no_repo_needing_the_permission_files_nothing() -> None:
    reads = FakeReads({REPO: GATE, "romamo/other": GATE})
    done, writer = run(reads)
    assert writer.created == []
    assert done.line() == "permissions: Deployments: read needed by no repo"


# -- later sweeps


@pytest.mark.parametrize("config", [NEEDING, GATE], ids=["carrier", "no-longer-carrier"])
def test_s060_6_a_granted_permission_closes_its_open_issue_in_the_gates_repo(config: str) -> None:
    reads = FakeReads({REPO: config}, {REPO: [Filed(REPO, 5, MARKER, True)]}, GRANTING)
    done, writer = run(reads)
    [(number, comment)] = writer.closed
    assert number == 5 and comment.split("\n", 1)[0] == VERIFIED == "<!-- shipmill:verified -->"
    assert "grants Deployments: read now" in comment
    assert done.line() == "permissions: closed #5"
    assert "repos" not in reads.log  # nothing missing: no other repo is read


def test_s060_6_a_gate_whose_repo_doesnt_hold_the_issue_writes_nothing() -> None:
    reads = FakeReads(
        {REPO: NEEDING, "romamo/other": NEEDING}, {"romamo/other": [Filed("romamo/other", 5, MARKER, True)]}
    )
    reads.granted = GRANTING
    done, writer = run(reads)
    assert writer.created == [] and writer.closed == []
    assert done.line() == "permissions: none missing"


def test_s060_6_a_closed_issue_or_a_granted_one_still_missing_is_left_as_it_is() -> None:
    reads = FakeReads({REPO: NEEDING}, {REPO: [Filed(REPO, 5, MARKER, False)]}, GRANTING)
    done, writer = run(reads)
    assert writer.closed == [] and done.line() == "permissions: none missing"
    still = FakeReads({REPO: NEEDING}, {REPO: [Filed(REPO, 5, MARKER, True)]})
    done, writer = run(still)
    assert writer.closed == [] and writer.created == []  # open and still missing: nothing written


# -- when it runs


def test_s060_7_a_tick_that_doesnt_sweep_reads_no_installation(checkout: Git) -> None:
    reads = FakeReads({REPO: NEEDING})
    opened = Opened(reads, FakeWriter(reads, REPO))
    source = Source({1: [INCIDENT]})
    swept(checkout, opened, source)
    assert opened.opened == ["reads", "writer"]
    opened.opened.clear()
    reads.log.clear()
    for when, signature in ((LATER, "sig"), (LATER, "moved")):
        source.signature = signature  # no change, then a change: neither sweeps
        decision = swept(checkout, opened, source, now=when)
        assert decision.permissions is None
    assert opened.opened == [] and reads.log == []
    assert stored(checkout)["permissions"] == {"parts": ["filed #100 Deployments: read"]}  # the last sweep's, kept


def test_s060_7_a_gate_without_app_id_reads_and_writes_nothing_and_says_so(checkout: Git) -> None:
    reads = FakeReads({REPO: NEEDING})
    opened = Opened(reads, FakeWriter(reads, REPO))
    decision = swept(checkout, opened, app=False)
    assert opened.opened == [] and reads.log == []
    assert decision.permissions == NO_APP == "permissions: none read, [agents] sets no app_id"
    assert "permissions" not in stored(checkout)


def test_s060_7_a_dry_run_writes_nothing_and_names_what_it_would_file(checkout: Git) -> None:
    reads = FakeReads({REPO: NEEDING}, {REPO: [Filed(REPO, 3, "<!-- shipmill-permission: x read -->", True)]})
    opened = Opened(reads, FakeWriter(reads, REPO))
    decision = swept(checkout, opened, dry_run=True, sweep_now=True)
    assert "writer" not in opened.opened and opened.writer.created == []
    assert decision.permissions == "permissions: would file Deployments: read"
    assert tick_lines(decision, None, (), (), True)[0].endswith("; permissions: would file Deployments: read")
    assert not (state_dir(checkout) / SWEEP).exists()
    granted = FakeReads({REPO: NEEDING}, {REPO: [Filed(REPO, 5, MARKER, True)]}, GRANTING)
    done, writer = run(granted, dry_run=True)
    assert writer.closed == [] and done.line() == "permissions: would close #5"


# -- where it shows


def test_s060_8_the_decision_line_and_sweep_json_carry_the_notice(checkout: Git) -> None:
    reads = FakeReads({REPO: NEEDING})
    decision = swept(checkout, Opened(reads, FakeWriter(reads, REPO)))
    assert tick_lines(decision, None, (), (), False)[0].endswith("; permissions: filed #100 Deployments: read")
    assert stored(checkout)["permissions"] == {"parts": ["filed #100 Deployments: read"]}
    for kept in (Notice(("closed #5",)), Notice(error="refused"), None):
        Swept(NOW, (), None, None, kept).save(state_dir(checkout) / SWEEP)
        assert Swept.load(state_dir(checkout) / SWEEP) == Swept(NOW, (), None, None, kept)


def test_s060_8_a_refused_write_is_the_lines_and_the_tick_goes_on(checkout: Git, tmp_path: Path) -> None:
    reads = FakeReads({REPO: NEEDING})
    failed = swept(checkout, Opened(reads, Refusing(reads, REPO)), Source({1: [INCIDENT]}))
    other = Git(tmp_path / "other")
    other.root.mkdir()
    other.run("init", "-q")
    other.run("remote", "add", "origin", f"https://github.com/{REPO}.git")
    plain = tick(other, Source({1: [INCIDENT]}), agents=cfg(app_id=APP_ID), app=lambda a: APP, app_env=lambda i: {})
    assert (failed.action, failed.work, failed.walk) == (plain.action, plain.work, plain.walk)
    assert failed.action is Action.LAUNCH
    error = "gh issue create failed: Resource not accessible by integration (HTTP 403)"
    assert failed.permissions == f"permissions failed: {error}"
    assert stored(checkout)["permissions"] == {"error": error}


# -- the carrier


@pytest.mark.parametrize(
    ("home", "expected"),
    [(True, "romamo/zeta"), (False, "romamo/alpha")],
    ids=["a-home-first", "else-first-by-name"],
)
def test_s060_12_every_candidates_gate_picks_the_same_carrier(home: bool, expected: str) -> None:
    zeta = NEEDING + (HOME if home else "")
    texts = {"romamo/zeta": zeta, "Romamo/Beta": NEEDING, "romamo/alpha": NEEDING}
    lines = {}
    for gate in texts:  # each gate reads the same installation
        done, writer = run(FakeReads(dict(texts)), gate)
        lines[gate] = (done.line(), len(writer.created))
    assert lines[expected] == ("permissions: filed #100 Deployments: read", 1)
    others = {g: v for g, v in lines.items() if g != expected}
    assert others == {g: (f"permissions: carried by {expected}", 0) for g in others}


def test_s060_12_the_first_by_name_ignores_case_and_two_homes_fall_back_to_it() -> None:
    assert carrier([Candidate("romamo/beta", False), Candidate("Romamo/Alpha", False)]).repo == "Romamo/Alpha"
    two = [Candidate("romamo/zeta", True), Candidate("romamo/omega", True), Candidate("romamo/Beta", False)]
    assert carrier(two).repo == "romamo/Beta"
    assert carrier([Candidate("romamo/zeta", True), Candidate("romamo/beta", False)]).repo == "romamo/zeta"


@pytest.mark.parametrize(
    "config",
    [
        None,  # no config: no gate
        "name = [\n",  # doesn't parse
        POLICY + ENVIRONMENTS,  # no [agents]
        POLICY + '\n[agents]\nprompt = "/t"\n' + ENVIRONMENTS,  # no app_id
        POLICY + '\n[agents]\nprompt = "/t"\napp_id = 8\n' + ENVIRONMENTS,  # another App's
        GATE,  # doesn't need it
    ],
    ids=["missing", "unparsable", "no-agents", "no-app-id", "another-app", "not-needed"],
)
def test_s060_13_a_repo_whose_config_doesnt_turn_it_on_for_this_app_is_no_candidate(config: str | None) -> None:
    """romamo/aaa comes first by name, so as a candidate it would carry the item"""
    reads = FakeReads({"romamo/aaa": config, REPO: NEEDING})
    done, writer = run(reads)
    assert done.line() == "permissions: filed #100 Deployments: read"
    [(_, body, _, _)] = writer.created
    assert "romamo/aaa" not in body


def test_s060_13_an_archived_repo_is_no_candidate_but_its_item_still_counts() -> None:
    """An archived repo is read-only, so its gate can't file: as the carrier, no gate would ever
    file the item. Its issues still hold an item already filed"""
    reads = FakeReads({"romamo/aaa": NEEDING + HOME, REPO: NEEDING}, archived=frozenset({"romamo/aaa"}))
    done, writer = run(reads)
    assert done.line() == "permissions: filed #100 Deployments: read"
    [(_, body, _, _)] = writer.created
    assert "romamo/aaa" not in body
    held = FakeReads(
        {"romamo/aaa": NEEDING, REPO: NEEDING},
        {"romamo/aaa": [Filed("romamo/aaa", 5, MARKER, False)]},
        archived=frozenset({"romamo/aaa"}),
    )
    done, writer = run(held)
    assert writer.created == [] and done.line() == "permissions: Deployments: read in romamo/aaa#5 (closed)"


# -- the installation-wide token


@dataclass
class InstallationApi:
    """GitHub's API for the notice's reads: the App, its installation, the token, the repos,
    their configs and issues; every call is logged"""

    minted: dict[str, object] = field(
        default_factory=lambda: {"metadata": "read", "contents": "read", "issues": "read"}
    )
    mint_status: int = 201
    calls: list[str] = field(default_factory=list)
    posts: list[Mapping[str, object]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        self.calls.append(f"GET {path} {'jwt' if token and token.count('.') == 2 else token}")
        if path == "/app":
            return Answer(200, json.dumps({"slug": "demo-agent", "owner": {"login": "romamo", "type": "User"}}))
        if path == f"/repos/{REPO}/installation":
            return Answer(200, json.dumps({"id": 77, "permissions": {k: str(v) for k, v in SESSION.items()}}))
        if path.startswith("/installation/repositories"):
            listed = [{"full_name": REPO, "archived": False}, {"full_name": "romamo/old", "archived": True}]
            return Answer(200, json.dumps({"total_count": 2, "repositories": listed}))
        if path.startswith(f"/repos/{REPO}/issues?"):
            pull = {"number": 9, "state": "open", "body": MARKER, "pull_request": {}}
            return Answer(200, json.dumps([{"number": 4, "state": "closed", "body": f"{MARKER}\r\ntext"}, pull]))
        if path.startswith("/repos/romamo/old/issues?"):
            return Answer(200, "[]")
        if path.startswith((f"/repos/{REPO}/contents/", "/repos/romamo/old/contents/")):
            return Answer(404, '{"message": "Not Found"}')
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, token: str, body: Mapping[str, object]) -> Answer:
        self.calls.append(f"POST {path}")
        self.posts.append(body)
        if self.mint_status != 201:
            return Answer(self.mint_status, '{"message": "Resource not accessible by integration"}')
        return Answer(201, json.dumps({"token": "ghs_installation-wide", "permissions": self.minted}))


def test_s060_14_the_installation_wide_token_asks_only_metadata_contents_and_issues_read(tmp_path: Path) -> None:
    api = InstallationApi()
    identity = Identity(APP_ID, "demo-agent", 99, key_file(tmp_path))
    reads = open_reads(identity, REPO, FakeSigner(), api, lambda: NOW)
    [body] = api.posts
    assert body == {"permissions": {"metadata": "read", "contents": "read", "issues": "read"}}  # no repositories
    assert {p.key: str(p.access) for p in NOTICE_PERMISSIONS} == body["permissions"]
    assert "ghs_installation-wide" not in repr(reads)
    assert reads.repos() == (Listed(REPO, False), Listed("romamo/old", True))
    assert reads.issues(REPO) == (Filed(REPO, 4, MARKER, False),)  # the pull request is no issue
    assert all(call.startswith("GET") or call == "POST /app/installations/77/access_tokens" for call in api.calls)


@pytest.mark.parametrize("granted", [{"issues": "write"}, {"administration": "read"}, {"contents": "admin"}])
def test_s060_14_a_token_granting_more_is_refused(tmp_path: Path, granted: dict[str, object]) -> None:
    api = InstallationApi(minted={"metadata": "read", **granted})
    identity = Identity(APP_ID, "demo-agent", 99, key_file(tmp_path))
    with pytest.raises(ReleaseError, match="broader than the notice asks; refusing it"):
        open_reads(identity, REPO, FakeSigner(), api, lambda: NOW)


def test_s060_14_the_token_reaches_no_session_and_every_write_goes_through_the_gates_writer(
    checkout: Git, tmp_path: Path
) -> None:
    api = InstallationApi()
    identity = Identity(APP_ID, "demo-agent", 99, key_file(tmp_path))
    held: list[ApiReads] = []
    written: list[Identity] = []
    reads_seen = FakeReads({REPO: NEEDING})
    writer = FakeWriter(reads_seen, REPO)

    def reads(who: Identity) -> ApiReads:
        opened = open_reads(who, REPO, FakeSigner(), api, lambda: NOW)
        held.append(opened)
        return opened

    def as_gate(who: Identity) -> FakeWriter:
        written.append(who)
        return writer

    envs: list[Mapping[str, str]] = []

    def app_env(who: Identity) -> dict[str, str]:
        env = {"GH_TOKEN_HELPER": "bin/gh"}
        envs.append(env)
        return env

    decision = tick(
        checkout,
        Source({1: [INCIDENT]}),
        agents=cfg(app_id=APP_ID),
        app=lambda app_id: identity,
        app_env=app_env,
        roles=lambda config, login: MAINTAINERS,
        permissions=Seams(reads, as_gate),
    )
    assert decision.action is Action.LAUNCH and len(held) == 1
    # the only repo's config isn't on the fake API: no candidate, so nothing filed and nothing written
    assert decision.permissions is not None and written == []
    assert all("ghs_installation-wide" not in value for env in envs for value in env.values())
    for path in state_dir(checkout).rglob("*"):
        if path.is_file():
            assert "ghs_installation-wide" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_s060_15_a_refused_token_files_nothing_names_the_failure_and_the_tick_goes_on(
    checkout: Git, tmp_path: Path
) -> None:
    api = InstallationApi(mint_status=403)
    identity = Identity(APP_ID, "demo-agent", 99, key_file(tmp_path))
    reads_seen = FakeReads({REPO: NEEDING})
    writer = FakeWriter(reads_seen, REPO)
    decision = tick(
        checkout,
        Source({1: [INCIDENT]}),
        agents=cfg(app_id=APP_ID),
        app=lambda app_id: identity,
        app_env=lambda who: {},
        permissions=Seams(lambda who: open_reads(who, REPO, FakeSigner(), api, lambda: NOW), lambda who: writer),
    )
    assert decision.action is Action.LAUNCH and decision.work == (INCIDENT,)
    assert writer.created == []
    assert decision.permissions is not None and decision.permissions.startswith("permissions failed: POST ")
    assert "answered 403" in decision.permissions
    assert stored(checkout)["permissions"]["error"] == decision.permissions.removeprefix("permissions failed: ")


def test_s060_15_a_refused_read_files_nothing() -> None:
    @dataclass
    class Unreadable(FakeReads):
        def repos(self) -> tuple[Listed, ...]:
            raise ReleaseError("GET /installation/repositories?per_page=100&page=1 answered 403: refused")

    reads = Unreadable({REPO: NEEDING})
    writer = FakeWriter(reads, REPO)
    seams = Seams(lambda who: reads, lambda who: writer)
    done = sweep_permissions(seams, APP, REPO, (), False)
    assert writer.created == [] and done.line.startswith("permissions failed: GET /installation/repositories")
    assert done.stored == Notice(error=done.line.removeprefix("permissions failed: "))


# -- docs


def test_s060_11_install_md_says_the_gate_files_the_item_and_a_not_planned_close_declines_it() -> None:
    doc = (Path(__file__).resolve().parents[1] / "docs" / "install.md").read_text(encoding="utf-8")
    assert "`shipmill-permission`" in doc
    flat = " ".join(doc.split())
    assert "files one item per installation" in flat
    assert "closing it as not planned declines it" in flat
