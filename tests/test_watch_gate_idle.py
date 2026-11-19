"""Spec 061: watch_state.py lists each hand the gate marked idle in its handed.json as a
GATE_IDLE row, reported and never an action, read from the state directory of the gate's
folder. The reports run as subprocesses with a fake gh on PATH and HOME in the test's folder"""

import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from shipmill.walk import HANDED, Hand, Handed, Head

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
UTC = dt.timezone.utc  # noqa: UP017 (the script runs under 3.10 too)
NOW = dt.datetime(2026, 11, 13, 14, 5, tzinfo=UTC)
# two idle hands, the newer first in the file, and one not idle (S-061-20)
HANDS: dict[str, dict[str, object]] = {
    "PRS_OPEN #12": {
        "session": "9d2f4c1a",
        "at": "2026-10-20T09:00:00+00:00",
        "head": "a" * 40,
        "rollup": "SUCCESS",
        "idle": True,
    },
    "ISSUES VERIFY_DUE #842": {"session": "5c1e9a7b", "at": "2026-10-02T14:05:00+00:00", "idle": True},
    "ISSUES NEW #900": {"session": "77aa00bb", "at": "2026-11-13T13:00:00+00:00"},
}
DETAIL = re.compile(
    r"idle since (?P<at>\d{4}-\d\d-\d\d \d\d:\d\d) UTC \(\d+ (?:min|h|d) ago\): session (?P<session>\S+)"
    r" wrote nothing on it; waits for a change"
)
# answers each read the full report makes of a repo with no environments and no workflows,
# and the marketplace read of shipmill's latest release
FAKE_GH = """#!{python}
import json, os, sys
args = sys.argv[1:]
page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
if args[:2] == ["repo", "view"]:
    print(json.dumps({"defaultBranchRef": {"name": "main"}, "deleteBranchOnMerge": True}))
elif args[:2] in (["issue", "list"], ["run", "list"], ["pr", "list"]):
    print("[]")
elif args[:2] == ["api", "graphql"] and any("open:" in a for a in args):
    repository = {
        "open": {**page, "nodes": []},
        "tags": {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": []},
        "closed": {"nodes": []},
        "vetoable": {**page, "nodes": []},
    }
    print(json.dumps({"data": {"repository": repository}}))
elif args[:2] == ["api", "graphql"] and any("issues(" in a for a in args):  # intake_state.py (spec 074)
    print(json.dumps({"data": {"repository": {"hasDiscussionsEnabled": False, "issues": {**page, "nodes": []}}}}))
elif args[:1] == ["api"] and "marketplace.json" in " ".join(args):
    source = {"source": "github", "repo": "shipmill/shipmill", "ref": "v0.137.0"}
    print(json.dumps({"plugins": [{"name": "shipmill", "source": source}]}))
else:
    sys.stderr.write("unexpected gh call: " + " ".join(args) + "\\n")
    sys.exit(1)
"""


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_gate_idle", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


class Host:
    """A checkout cloned from a bare origin, a fake gh, and HOME in tmp_path"""

    def __init__(self, tmp_path: Path) -> None:
        git = shutil.which("git")
        assert git is not None
        fakes = tmp_path / "fakes"
        fakes.mkdir()
        (fakes / "gh").write_text(FAKE_GH.replace("{python}", sys.executable), encoding="utf-8")
        (fakes / "gh").chmod(0o700)
        self.tmp = tmp_path
        self.env = {
            "PATH": os.pathsep.join([str(fakes), str(Path(git).parent), "/usr/bin", "/bin"]),
            "HOME": str(tmp_path),
        }
        self.origin, self.work = tmp_path / "origin.git", tmp_path / "work"
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=tmp_path)
        self.git("clone", "-q", str(self.origin), str(self.work), cwd=tmp_path)
        (self.work / ".github").mkdir()
        (self.work / ".github" / "shipmill.toml").write_text('mode = "off"\n', encoding="utf-8")
        self.git("switch", "-q", "-c", "main")
        self.git("add", ".github/shipmill.toml")
        self.git("commit", "-q", "-m", "start")
        self.git("push", "-q", "origin", "main")

    def git(self, *cmd: str, cwd: Path | None = None) -> None:
        base = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*base, *cmd], cwd=cwd or self.work, env=self.env, check=True)

    def handed(self, data: object, checkout: Path | None = None) -> Path:
        """handed.json in the state directory of the checkout (the work checkout by default)"""
        path = (checkout or self.work) / ".git" / "shipmill" / HANDED
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return path

    def watch(self, *flags: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT), "o/r", "--repo-dir", str(self.work), "--json", *flags]
        return subprocess.run(cmd, capture_output=True, text=True, env=self.env, check=False)


def rows(proc: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    assert proc.returncode in (0, 1), proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def idle(found: list[dict[str, object]]) -> list[dict[str, object]]:
    return [r for r in found if r["state"] == "GATE_IDLE"]


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def test_s061_20_the_idle_hands_are_two_rows_oldest_first(ws: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / HANDED
    path.write_text(json.dumps(HANDS), encoding="utf-8")
    assert [(r.state, r.subject, r.detail) for r in ws.idle_rows(path, NOW)] == [
        (
            "GATE_IDLE",
            "ISSUES VERIFY_DUE #842",
            "idle since 2026-10-02 14:05 UTC (42 d ago): session 5c1e9a7b wrote nothing on it; waits for a change",
        ),
        (
            "GATE_IDLE",
            "PRS_OPEN #12",
            "idle since 2026-10-20 09:00 UTC (24 d ago): session 9d2f4c1a wrote nothing on it; waits for a change",
        ),
    ]


def test_s061_20_the_rows_read_handed_json_as_the_gate_writes_it(ws: ModuleType, tmp_path: Path) -> None:
    # the gate's own writer, at another offset than UTC: the row's time is in UTC
    at = dt.datetime(2026, 10, 2, 17, 5, tzinfo=dt.timezone(dt.timedelta(hours=3)))
    hands = {
        "ISSUES VERIFY_DUE #842": Hand("5c1e9a7b", at, idle=True),
        "PRS_OPEN #12": Hand("9d2f4c1a", NOW, Head("a" * 40, None)),
    }
    Handed(hands).save(tmp_path / HANDED)
    (row,) = ws.idle_rows(tmp_path / HANDED, NOW)
    assert (row.subject, row.detail.split(" (")[0]) == ("ISSUES VERIFY_DUE #842", "idle since 2026-10-02 14:05 UTC")


def test_s061_20_the_full_report_gives_the_two_gate_idle_rows(host: Host) -> None:
    host.handed(HANDS)
    found = idle(rows(host.watch()))
    assert [r["subject"] for r in found] == ["ISSUES VERIFY_DUE #842", "PRS_OPEN #12"]
    details = [DETAIL.fullmatch(str(r["detail"])) for r in found]
    assert [(m["at"], m["session"]) for m in details if m] == [
        ("2026-10-02 14:05", "5c1e9a7b"),
        ("2026-10-20 09:00", "9d2f4c1a"),
    ]


def test_s061_21_a_gate_idle_row_is_no_agents_and_changes_no_exit_code(host: Host) -> None:
    before = host.watch()
    host.handed(HANDS)
    after = host.watch()
    found = idle(rows(after))
    assert len(found) == 2 and all(r["agent"] is False and r["fix"] is None for r in found)
    assert after.returncode == before.returncode
    assert [r for r in rows(after) if r["state"] != "GATE_IDLE"] == rows(before)
    no_host = host.watch("--no-host")
    assert idle(rows(no_host)) == found


def test_s061_21_tier_sweep_and_host_reads_print_no_gate_idle_row(ws: ModuleType, host: Host) -> None:
    host.handed(HANDS)
    known = host.tmp / "known.json"
    known.write_text(
        json.dumps({"default_branch": "main", "held": False, "prs": [], "incidents": [], "runs": []}), encoding="utf-8"
    )
    for flags in (["--sweep"], ["--tier", "3", "--known", str(known)], ["--host", "sessions"], ["--host", "shipmill"]):
        assert not idle(rows(host.watch(*flags))), flags
    printed = {state for states in ws.TIERS.values() for state in states}
    assert "GATE_IDLE" not in printed | set(ws.SWEPT)
    assert "GATE_IDLE" not in ws.ACTION | ws.AGENT | ws.FIXED


@pytest.mark.parametrize("hands", [None, {}, {"ISSUES NEW #900": HANDS["ISSUES NEW #900"]}])
def test_s061_21_no_handed_json_or_no_idle_hand_gives_no_row(host: Host, hands: object) -> None:
    if hands is not None:
        host.handed(hands)
    assert not idle(rows(host.watch("--no-host")))


def test_s061_20_the_hands_are_read_from_the_gate_folders_state_directory(host: Host) -> None:
    # the gate's checkout where shipmill-setup puts it (#1156), a clone with its own git
    # directory: its handed.json is read, not the person's checkout's
    gate = host.tmp / ".local" / "share" / "shipmill" / "gates" / "o" / "r"
    gate.parent.mkdir(parents=True)
    host.git("clone", "-q", str(host.origin), str(gate), cwd=host.tmp)
    host.handed({"ISSUES NEW #900": HANDS["ISSUES NEW #900"] | {"idle": True}})
    host.handed(HANDS, gate)
    assert [r["subject"] for r in idle(rows(host.watch("--no-host")))] == ["ISSUES VERIFY_DUE #842", "PRS_OPEN #12"]


def folded(*parts: str) -> str:
    return " ".join((ROOT.joinpath(*parts)).read_text(encoding="utf-8").split())


def test_s061_19_the_docs_say_what_spec_061s_docs_list_says(ws: ModuleType) -> None:
    triage = ("skills", "github-issue-triage")
    comments = folded(*triage, "references", "comments.md")
    # both postpone templates carry the Revisit on: line, and a Depends on line is the other form
    assert comments.count("Revisit on: `") == 2
    assert "Revisit on: `docs/product.md`, `docs/product/**`" in comments
    # a wait on an issue goes through chains.py link, which writes the line too (#1205)
    assert "which writes the blocked-by relation and the body's `Depends on` line" in comments
    assert "put the `Depends on #N` line in the issue's body by hand" in comments
    for path in ((*triage, "SKILL.md"), (*triage, "references", "triage-rubric.md")):
        text = folded(*path)
        assert "changed a path its postpone comment's `Revisit on:` line names" in text, path
        assert "without that line, any stable release did (spec 061)" in text, path
    setup = folded("skills", "shipmill-setup", "SKILL.md")
    assert "by their issues and pull requests, one by one (spec 061, D-87)" in setup
    assert "past `retry_hours` it is handed to no session and waits until it changes" in setup
    watch = folded("skills", "github-ship-watch", "SKILL.md")
    assert "| GATE_IDLE |" in watch and "follow as `TO_MERGE #N`" in watch
    assert "answering or changing the subject on GitHub (a comment, a label, an edit, a push), or closing it" in watch
    assert ws.__doc__ is not None
    help_text = " ".join(ws.__doc__.split())
    agents = help_text.split("Agents (all reported, never an action by itself):")[1].split("Gate setup")[0]
    assert "GATE_IDLE one row per hand the gate marked idle (spec 061)" in agents
    spec046 = folded("docs", "specs", "046-gate-work-queue.md")
    assert spec046.count("Amended by spec 061 (#1161)") == 2
    assert "keeps an idle subject's hand past `retry_hours`" in spec046


MALFORMED = [
    "{not json",
    "[]",
    json.dumps({"ISSUES VERIFY_DUE #842": "5c1e9a7b"}),
    json.dumps({"ISSUES VERIFY_DUE #842": {"session": "5c1e9a7b"}}),
    json.dumps({"ISSUES VERIFY_DUE #842": {"session": "", "at": "2026-10-02T14:05:00+00:00"}}),
    json.dumps({"ISSUES VERIFY_DUE #842": {"session": "s", "at": "2026-10-02T14:05:00"}}),  # no offset
    json.dumps({"ISSUES VERIFY_DUE #842": {"session": "s", "at": "yesterday"}}),
    json.dumps({"ISSUES VERIFY_DUE #842": {"session": "s", "at": "2026-10-02T14:05:00+00:00", "idle": "yes"}}),
    json.dumps({"ISSUES VERIFY_DUE #842": {"session": "s", "at": "2026-10-02T14:05:00+00:00", "more": 1}}),
    json.dumps({"PRS_OPEN #12": {"session": "s", "at": "2026-10-02T14:05:00+00:00", "head": "a" * 40}}),
    json.dumps({"PRS_OPEN #12": {"session": "s", "at": "2026-10-02T14:05:00+00:00", "head": "a", "rollup": 1}}),
    json.dumps({"0123abcd": {"session": "s", "at": "2026-10-02T14:05:00+00:00", "idle": True}}),  # a fingerprint
]


@pytest.mark.parametrize("text", MALFORMED)
def test_s061_22_a_malformed_handed_json_is_refused_naming_its_path(ws: ModuleType, tmp_path: Path, text: str) -> None:
    path = tmp_path / HANDED
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ws.Refused, match=re.escape(str(path))) as refused:
        ws.idle_rows(path, NOW)
    assert refused.value.code == 2


def test_s061_22_the_watch_exits_2_on_a_malformed_handed_json(host: Host) -> None:
    path = host.handed("[]")
    for flags in ([], ["--no-host"]):
        proc = host.watch(*flags)
        assert proc.returncode == 2 and proc.stdout == ""
        assert proc.stderr.startswith(f"error: {path}: ")
