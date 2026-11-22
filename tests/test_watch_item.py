"""#1469: watch_state.py --item N prints the full report's rows `shipmill status --item N`
reads (the hold, the items waiting on a decision, the pull requests to land and parked, and
the agent and GATE_IDLE rows naming #N), exactly as the full report prints them, and skips
the reads that can't give one. The reports run as subprocesses with a fake gh on PATH that
logs every call, and HOME in the test's folder"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill import item_status
from shipmill.status import parse_rows

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
BOT = "shipmill-app[bot]"
CONFIG = """mode = "off"

[environments.staging]

[agents]
prompt = "/triage {repo}"
app_id = 1
"""
# the gate kept a pull request and an issue idle (spec 061)
HANDS = {
    "PRS_OPEN #3": {
        "session": "9d2f4c1a",
        "at": "2026-10-20T09:00:00+00:00",
        "head": "a" * 40,
        "rollup": None,
        "idle": True,
    },
    "ISSUES NEW #12": {"session": "5c1e9a7b", "at": "2026-10-02T14:05:00+00:00", "idle": True},
}
# A repo with a hold (#40), an incident (#30), an issue waiting on its question (#20), a new
# issue (#12), and four open pull requests: one to land (#3), a person's (#4), one waiting on
# its question (#5), and the App's own draft (#6). It answers each read the full report makes
FAKE_GH = """#!{python}
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
QUESTION = "<!-- shipmill:needs-decision -->\\n@alice Decision needed: which way?"
page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
labels = lambda *names: {"pageInfo": {"hasNextPage": False}, "nodes": [{"name": n} for n in names]}
app = {"__typename": "Bot", "login": "shipmill-app"}
asked = {"body": QUESTION, "createdAt": "2026-11-20T10:00:00Z", "author": app, "authorAssociation": "NONE"}
def issue(number, title, *names, comments=()):
    return {"number": number, "title": title, "body": "", "author": {"__typename": "User", "login": "maria"},
            "authorAssociation": "OWNER", "labels": labels(*names), "assignees": {"nodes": []},
            "comments": {"nodes": list(comments)}, "timelineItems": {**page, "nodes": []}}
listed = lambda number, title, *names: {
    "number": number, "title": title, "body": "", "createdAt": "2026-11-20T09:00:00Z", "closedAt": None,
    "stateReason": None, "author": {"login": "maria"}, "labels": [{"name": n} for n in names],
    "closedByPullRequestsReferences": []}
def pull(number, *names, draft=False, author="amy", assignees=()):
    return {"number": number, "isDraft": draft, "isCrossRepository": False, "labels": [{"name": n} for n in names],
            "headRefOid": "a" * 40, "assignees": [{"login": a} for a in assignees],
            "author": {"login": author, "is_bot": author.startswith("app/")}}
joined = " ".join(args)
if args[:2] == ["repo", "view"]:
    print(json.dumps({"defaultBranchRef": {"name": "main"}, "deleteBranchOnMerge": True}))
elif args[:2] == ["issue", "list"]:
    found = []
    if "shipmill-hold" in args and "open" in args:
        found = [listed(40, "hold everything", "shipmill-hold")]
    elif "incident" in args and "open" in args:
        found = [listed(30, "staging is down", "incident")]
    print(json.dumps(found))
elif args[:2] == ["run", "list"]:
    print("[]")
elif args[:2] == ["pr", "list"]:
    if "--state" in args:
        print("[]")
    else:
        prs = [pull(3), pull(4, "role:maintainer", assignees=("a",)), pull(5, "needs-decision"),
               pull(6, draft=True, author="app/shipmill-app")]
        print(json.dumps(prs))
elif args[:2] == ["api", "graphql"] and "open:" in joined:
    nodes = [issue(12, "a bug"), issue(20, "which way", "needs-decision", comments=[asked]),
             issue(30, "staging is down", "incident"), issue(40, "hold everything", "shipmill-hold")]
    repository = {
        "open": {**page, "nodes": nodes},
        "tags": {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": []},
        "closed": {"nodes": []},
        "vetoable": {**page, "nodes": []},
    }
    print(json.dumps({"data": {"repository": repository}}))
elif args[:2] == ["api", "graphql"] and "issueOrPullRequest" in joined:
    repository = {}
    for n in re.findall(r"n(\\d+): issueOrPullRequest", joined):
        nodes = [{"author": {"__typename": "Bot", "login": "shipmill-app"}, "authorAssociation": "NONE",
                  "body": QUESTION}] if n == "5" else []
        repository["n" + n] = {"comments": {"pageInfo": {"hasPreviousPage": False}, "nodes": nodes}}
    print(json.dumps({"data": {"repository": repository}}))
elif args[:2] == ["api", "graphql"] and "issues(" in joined:  # intake_state.py (spec 074)
    print(json.dumps({"data": {"repository": {"hasDiscussionsEnabled": False, "issues": {**page, "nodes": []}}}}))
elif args[:2] == ["api", "graphql"] and "folder:" in joined:  # the postmortems
    print(json.dumps({"data": {"repository": {"ref": {"oid": "c" * 40}, "folder": None}}}))
elif args[:2] == ["api", "graphql"]:  # chains.py: no item is readable, so the walk is one CHAIN_UNREADABLE row
    sys.stderr.write("gh: no chains here\\n")
    sys.exit(1)
elif args[:1] == ["api"] and "/deployments" in joined:
    print("[]")
elif args[:1] == ["api"] and "/commits/" in joined:  # base_red.py: a green default head (spec 079)
    print(json.dumps({"sha": "c" * 40, "statuses": [], "total_count": 0}) if "/status?" in joined else "")
elif args[:1] == ["api"] and "/issues?" in joined:  # base_red.py's open items, the direction issues
    print("")
else:
    sys.stderr.write("unexpected gh call: " + joined + "\\n")
    sys.exit(1)
"""


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_item", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


class Host:
    """A checkout cloned from a bare origin, the gate's handed.json in it, a fake gh, and HOME
    in tmp_path"""

    def __init__(self, tmp_path: Path) -> None:
        git = shutil.which("git")
        assert git is not None
        fakes = tmp_path / "fakes"
        fakes.mkdir()
        (fakes / "gh").write_text(FAKE_GH.replace("{python}", sys.executable), encoding="utf-8")
        (fakes / "gh").chmod(0o700)
        self.log = tmp_path / "gh.log"
        self.env = {
            "PATH": os.pathsep.join([str(fakes), str(Path(git).parent), "/usr/bin", "/bin"]),
            "HOME": str(tmp_path),
            "FAKE_LOG": str(self.log),
        }
        origin, self.work = tmp_path / "origin.git", tmp_path / "work"
        self.git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
        self.git("clone", "-q", str(origin), str(self.work), cwd=tmp_path)
        (self.work / ".github").mkdir()
        (self.work / ".github" / "shipmill.toml").write_text(CONFIG, encoding="utf-8")
        self.git("switch", "-q", "-c", "main")
        self.git("add", ".github/shipmill.toml")
        self.git("commit", "-q", "-m", "start")
        self.git("push", "-q", "origin", "main")
        handed = self.work / ".git" / "shipmill" / "handed.json"
        handed.parent.mkdir(parents=True)
        handed.write_text(json.dumps(HANDS), encoding="utf-8")

    def git(self, *cmd: str, cwd: Path | None = None) -> None:
        base = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*base, *cmd], cwd=cwd or self.work, env=self.env, check=True)

    def watch(self, *flags: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        """One run as shipmill status makes it, and every gh call it made"""
        self.log.write_text("", encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), "o/r", "--repo-dir", str(self.work), "--json", "--no-host"]
        proc = subprocess.run([*cmd, *flags, "--bot-login", BOT], capture_output=True, text=True, env=self.env)
        calls = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return proc, calls


@pytest.fixture(scope="module")
def host(tmp_path_factory: pytest.TempPathFactory) -> Host:
    return Host(tmp_path_factory.mktemp("item"))


@pytest.fixture(scope="module")
def full(host: Host) -> list[str]:
    proc, _ = host.watch()
    assert proc.returncode in (0, 1), proc.stderr
    return proc.stdout.splitlines()


def read_by_status(line: str, number: int) -> bool:
    """Whether shipmill status --item number reads the row: the rows its explanation reads
    whole, and the agent and GATE_IDLE rows naming the item (item_status.names)"""
    (row,) = parse_rows(line + "\n")
    whole = {"HOLD", "NEEDS_DECISION", "PRS_OPEN", "PRS_PARKED"}
    return row.state in whole or item_status.names(row, number) and (row.agent or row.state == item_status.GATE_IDLE)


def test_the_fixture_has_a_row_of_each_kind_the_explanation_reads(full: list[str]) -> None:
    states = {json.loads(line)["state"] for line in full}
    assert {"HOLD", "NEEDS_DECISION", "PRS_OPEN", "PRS_PARKED", "AGENT_DRAFT", "GATE_IDLE", "ISSUES"} <= states
    assert "INCIDENT_OPEN" in states  # an agent's row naming an issue, from the operations section
    assert {"CHAIN_UNREADABLE", "TRIAGE_MODE", "BRANCH_DELETE_OFF"} - states == {"BRANCH_DELETE_OFF"}  # --item skips


@pytest.mark.parametrize("number", [3, 4, 5, 6, 12, 20, 30, 40, 99])
def test_1469_item_prints_the_full_reports_rows_status_reads_byte_for_byte(
    ws: ModuleType, host: Host, full: list[str], number: int
) -> None:
    proc, _ = host.watch("--item", str(number))
    assert proc.returncode in (0, 1), proc.stderr
    assert proc.stdout.splitlines() == [line for line in full if read_by_status(line, number)]
    # exit 1 as the full report's rule reads the rows it prints: one of them needs action
    assert (proc.returncode == 1) == any(json.loads(line)["state"] in ws.ACTION for line in proc.stdout.splitlines())


@pytest.mark.parametrize(
    ("number", "named"),
    [
        (12, [("ISSUES", "o/r"), ("GATE_IDLE", "ISSUES NEW #12")]),
        (3, [("GATE_IDLE", "PRS_OPEN #3")]),
        (6, [("AGENT_DRAFT", "o/r")]),
        (30, [("INCIDENT_OPEN", "#30"), ("ISSUES", "o/r")]),  # a new issue too
        (99, []),
    ],
)
def test_1469_item_adds_the_rows_naming_it_to_the_whole_ones(
    host: Host, number: int, named: list[tuple[str, str]]
) -> None:
    proc, _ = host.watch("--item", str(number))
    found = [(r["state"], r["subject"]) for r in map(json.loads, proc.stdout.splitlines())]
    assert [f for f in found if f[0] not in {"HOLD", "NEEDS_DECISION", "PRS_OPEN", "PRS_PARKED"}] == named
    assert [f[0] for f in found if f not in named] == ["HOLD", "PRS_OPEN", "PRS_PARKED", "NEEDS_DECISION"]


def test_1469_item_skips_the_reads_no_row_it_prints_comes_from(host: Host) -> None:
    _, full_calls = host.watch()
    _, item_calls = host.watch("--item", "12")
    shown = [" ".join(c) for c in item_calls]
    skipped = (
        "/deployments",
        "Ready to",
        "run list",
        "--label opportunity --label planned",
        "--state closed --label incident",
    )
    for read in skipped:
        assert any(read in " ".join(c) for c in full_calls), read
        assert not any(read in c for c in shown), read
    assert len(item_calls) < len(full_calls)


@pytest.mark.parametrize("flags", [["--tier", "3"], ["--sweep"], ["--host", "sessions"]])
def test_1469_item_goes_without_tier_sweep_and_host(flags: list[str]) -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), "o/r", "--item", "12", *flags], capture_output=True, text=True)
    assert proc.returncode == 2 and "--item reads the full report's rows" in proc.stderr


@pytest.mark.parametrize("given", ["0", "-3", "x"])
def test_1469_item_is_a_number(given: str) -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), "o/r", "--item", given], capture_output=True, text=True)
    assert proc.returncode == 2 and "--item" in proc.stderr


def test_1469_the_item_rule_is_shipmill_status_own(ws: ModuleType) -> None:
    assert ws.OWN_NUMBER.pattern == item_status.OWN_NUMBER.pattern
    whole = {"HOLD", "NEEDS_DECISION", "PRS_OPEN", "PRS_PARKED"}  # what item_status reads whole
    assert whole == ws.ITEM_WHOLE
