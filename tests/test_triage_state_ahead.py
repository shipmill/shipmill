"""#1469: triage_state.py starts its follow-up calls on threads and reads every answer in its own
order, so its output, stderr, and exit code are the same whichever call answers first"""

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "triage_state.py"
REPO = ("o", "r")

# A stand-in for gh: it answers each call by its kind from a JSON file, after a delay its seed
# picks, so the calls a run starts at once answer in a different order on each seed
FAKE_GH = '''#!{python}
import json, os, random, sys, time


def kind(argv):
    """What a gh call asks for, as the key of its answer"""
    if argv[:2] != ["api", "graphql"]:
        return argv[1].split("?")[0] + "?" + argv[1].split("?")[1]
    query = next(a for a in argv if a.startswith("query="))
    values = dict(a.split("=", 1) for a in argv[2:] if not a.startswith("query=") and "=" in a)
    if "tags: refs" in query and "open: issues" in query:
        return "first"
    if "open: issues" in query:
        return "open:" + values["cursor"]
    if "decided: pullRequests" in query:
        return "decided"
    if "comments(last: $size" in query:
        return "comments:" + values["number"]
    if "CONNECTED_EVENT], first: $size" in query:
        return "timeline:" + values["number"] + ":" + values["cursor"]
    return "unknown"


def answer(argv, data, seed):
    key = kind(argv)
    rng = random.Random(seed + key)
    time.sleep(rng.uniform(0, 0.15))
    if key not in data:
        return 3, "", "fake gh: no answer for " + key + "\\n"
    code, out = data[key]
    return code, json.dumps(out), ("gh: refused " + key + "\\n" if code else "")


if __name__ == "__main__":
    data = json.load(open(os.environ["FAKE_GH_DATA"]))
    code, out, err = answer(sys.argv[1:], data, os.environ.get("FAKE_GH_SEED", ""))
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(kind(sys.argv[1:]) + "\\n")
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.exit(code)
'''

TAGS = [
    ("v1.1.0", "2026-08-01T10:00:00Z"),
    ("v1.2.0", "2026-09-01T10:00:00Z"),
    ("v1.3.0", "2026-10-01T10:00:00Z"),
]
NOBODY = {"author": {"__typename": "User", "login": "amy"}, "authorAssociation": "OWNER"}


@pytest.fixture(scope="module")
def ts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("triage_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def comment(body: str, at: str = "2026-09-10T10:00:00Z") -> dict[str, Any]:
    return {"body": body, "createdAt": at, **NOBODY}


def issue(number: int, body: str = "", comments: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"issue {number}",
        "body": body,
        **NOBODY,
        "milestone": None,
        "labels": {"pageInfo": {"hasNextPage": False}, "nodes": extra.pop("labels", [])},
        "assignees": {"nodes": []},
        "comments": {"nodes": comments or []},
        "timelineItems": extra.pop("timeline", {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}),
        "blockedBy": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []},
        "subIssues": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []},
        "parent": None,
    }


def postponed(number: int, at: str, paths: str) -> dict[str, Any]:
    body = f"Triage: postpone, no goal it serves yet.\n\nRevisit on: {paths}"
    return issue(number, comments=[comment(body, at)], labels=[{"name": "postponed"}])


def answers() -> dict[str, Any]:
    """Five open issues on two pages: #10's triage comment is past its first 50 comments, #11's
    closing pull request past its first page of cross-references, #12 and #13 postponed on
    two base tags, and #14 a spec's build issue, which reads the decided pull requests"""
    notes = [comment(f"note {i}") for i in range(50)]
    many = issue(10, comments=notes)
    cursor = {"hasNextPage": True, "endCursor": "t1"}
    linked = issue(11, timeline={"pageInfo": cursor, "nodes": []})
    pr = {"number": 20, "state": "MERGED", "title": "Fix it", "body": "Fixes #11", "isDraft": False}
    pr |= {"author": {"__typename": "User", "login": "amy"}, "labels": {"nodes": []}}
    crossed = {"willCloseTarget": True, "isCrossRepository": False, "source": pr}
    build = issue(14, body="Builds part of spec S-001, `docs/specs/001-x.md`: one part")
    first = {
        "open": {"pageInfo": {"hasNextPage": True, "endCursor": "p1"}, "nodes": [many, linked]},
        "tags": {
            "pageInfo": {"hasPreviousPage": False, "startCursor": None},
            "nodes": [{"name": n, "target": {"tagger": {"date": d}}} for n, d in TAGS],
        },
        "closed": {"nodes": []},
        "vetoable": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []},
    }
    later = [postponed(12, "2026-09-10T10:00:00Z", "`src/a/**`"), postponed(13, "2026-08-10T10:00:00Z", "`docs/**`")]
    second = {"open": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [*later, build]}}
    every = {
        "pageInfo": {"hasPreviousPage": False, "startCursor": None},
        "nodes": [comment("Triage: implement."), *notes],
    }
    decided = {"decided": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}
    page = "?per_page=100&page=1"
    return {
        "first": [0, {"data": {"repository": first}}],
        "open:p1": [0, {"data": {"repository": second}}],
        "comments:10": [0, {"data": {"repository": {"issue": {"comments": every}}}}],
        "timeline:11:t1": [0, {"data": {"repository": {"issue": {"timelineItems": {
            "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [crossed]}}}}}],
        "decided": [0, {"data": {"repository": decided}}],
        f"repos/o/r/compare/v1.2.0...v1.3.0{page}": [0, {"files": [{"filename": "src/a/x.py"}]}],
        f"repos/o/r/compare/v1.1.0...v1.3.0{page}": [0, {"files": [{"filename": "src/b.py"}]}],
    }  # fmt: skip


EXPECTED = [
    {"number": 11, "state": "DONE_NOT_CLOSED", "title": "issue 11", "note": "#20:merged"},
    {"number": 12, "state": "REVISIT", "title": "issue 12", "note": "postponed before v1.3.0; src/a/x.py changed"},
    {"number": 14, "state": "NEW", "title": "issue 14", "note": "", "specs": ["docs/specs/001-x.md"]},
    {"number": 10, "state": "NEEDS_PR", "title": "issue 10", "note": ""},
    {"number": 13, "state": "POSTPONED", "title": "issue 13", "note": "waits on docs/**"},
]


def fake_gh(tmp_path: Path, data: dict[str, Any]) -> tuple[Path, Path, Path]:
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    gh = fakes / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o700)
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps(data), encoding="utf-8")
    return fakes, answers_file, tmp_path / "gh.log"


def run_script(fakes: Path, answers_file: Path, log: Path, seed: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_GH_DATA": str(answers_file),
        "FAKE_GH_LOG": str(log),
        "FAKE_GH_SEED": seed,
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), "o/r", "--json"], capture_output=True, text=True, check=False, env=env
    )


def test_1469_the_full_output_is_the_same_whichever_call_answers_first(tmp_path: Path) -> None:
    fakes, answers_file, log = fake_gh(tmp_path, answers())
    outputs = set()
    for seed in ("a", "b", "c", "d"):
        log.unlink(missing_ok=True)
        proc = run_script(fakes, answers_file, log, seed)
        assert proc.returncode == 1, proc.stderr
        assert proc.stderr == ""
        assert [json.loads(line) for line in proc.stdout.splitlines()] == EXPECTED
        outputs.add(proc.stdout)
        # every call the run reads is made once, and none it doesn't read
        assert sorted(log.read_text(encoding="utf-8").splitlines()) == sorted(answers())
    assert len(outputs) == 1


def test_1469_a_call_started_ahead_fails_where_the_run_reads_it(tmp_path: Path) -> None:
    data = answers()
    data["comments:10"] = [1, {"message": "boom"}]
    fakes, answers_file, log = fake_gh(tmp_path, data)
    proc = run_script(fakes, answers_file, log, "a")
    assert proc.returncode == 2
    # gh's own stderr, once, as the run printed it before it started calls ahead
    assert proc.stderr == "gh: refused comments:10\n"
    assert proc.stdout == ""


class Gh:
    """An Execute for the in-process runs: the fake gh's answers, each after its delay"""

    def __init__(self, data: dict[str, Any], seed: str, delays: dict[str, float] | None = None) -> None:
        self.fake: dict[str, Any] = {"__name__": "fake_gh"}
        exec(FAKE_GH.format(python=sys.executable).split("\n", 1)[1], self.fake)
        self.data = data
        self.seed = seed
        self.delays = delays or {}
        self.lock = threading.Lock()
        self.calls: list[str] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        key = self.fake["kind"](cmd[1:])
        time.sleep(self.delays.get(key, 0))
        code, out, err = self.fake["answer"](cmd[1:], self.data, self.seed)
        with self.lock:
            self.calls.append(key)
        return subprocess.CompletedProcess(cmd, code, out, err)


@pytest.mark.parametrize("seed", ["a", "b", "c"])
def test_1469_fetch_reads_the_same_data_with_its_calls_started_ahead(ts: ModuleType, seed: str) -> None:
    alone = Gh(answers(), seed)
    one_by_one = ts.fetch("o/r", 20, run=lambda q, v: ts.gh_graphql(q, v, alone))
    together = Gh(answers(), seed)
    ahead = ts.Ahead(together)
    fetched = ts.fetch("o/r", 20, run=ahead.graphql, ahead=ahead)
    assert fetched == one_by_one
    assert sorted(together.calls) == sorted(alone.calls)
    assert alone.calls[:2] == ["first", "open:p1"]  # the run itself still pages in its order


def test_1469_compares_started_ahead_fail_in_the_order_the_run_reads_them(
    ts: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    data = answers()
    page = "?per_page=100&page=1"
    first, second = f"repos/o/r/compare/v1.1.0...v1.3.0{page}", f"repos/o/r/compare/v1.2.0...v1.3.0{page}"
    data[first], data[second] = [1, {}], [1, {}]
    gh = Gh(data, "a", delays={first: 0.3})  # the one read first answers last
    ahead = ts.Ahead(gh)
    connection = data["first"][1]["data"]["repository"]["tags"]
    revisits = ts.Revisits("o", "r", connection, execute=ahead)
    items = [postponed(13, "2026-08-10T10:00:00Z", "`docs/**`"), postponed(12, "2026-09-10T10:00:00Z", "`src/a/**`")]
    revisits.start(ahead, items, "Triage:", "postponed")
    stable = ts.latest_stable(connection["nodes"])
    with pytest.raises(SystemExit) as exc:
        ts.classify_open(items[0], "Triage:", "postponed", {}, stable, REPO, revisits=revisits)
    assert exc.value.code == 2
    assert capsys.readouterr().err == f"gh: refused {first}\nerror: gh api {first} exited 1\n"


def test_1469_a_call_started_ahead_and_never_read_prints_nothing(
    ts: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = Gh({"first": [1, {}]}, "a")
    ahead = ts.Ahead(gh)
    ahead.start_graphql(ts.QUERY, {"owner": "o", "name": "r"})
    proc = ahead(["gh", "api", "repos/o/r/compare/a...b?per_page=100&page=1"])  # not started: runs now
    assert proc.returncode == 3
    ahead.pool.shutdown(wait=True)
    assert sorted(gh.calls) == ["first", "repos/o/r/compare/a...b?per_page=100&page=1"]
    assert capsys.readouterr() == ("", "")


def test_1469_a_graphql_call_is_found_whatever_order_its_variables_come_in(ts: ModuleType) -> None:
    gh = Gh({"comments:10": [0, {"data": {"repository": {"issue": None}}}]}, "a")
    ahead = ts.Ahead(gh)
    ahead.start_graphql(ts.COMMENTS_PAGE, {"number": 10, "size": 100, "owner": "o", "name": "r"})
    answer = ahead.graphql(ts.COMMENTS_PAGE, {"owner": "o", "name": "r", "number": 10, "size": 100})
    assert answer == {"data": {"repository": {"issue": None}}}
    assert gh.calls == ["comments:10"]
