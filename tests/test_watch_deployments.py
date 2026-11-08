"""#973: the watch's deployments reads on a repo with [environments], run as the full report
runs them, with a fake gh on PATH. A token without deployments: read (the gate's App) gets
GitHub's 403 on them: one DEPLOYMENTS_FORBIDDEN notice row, and the rest of the report stands"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
CONFIG = """mode = "off"

[environments.staging]

[environments.production]
from = "staging"
"""
FORBIDDEN = "gh: Resource not accessible by integration (HTTP 403)"
# answers each read the full report makes of a repo with environments and no workflows: one
# open issue (NEW), one open pull request, and the deployments reads as FAKE_DEPLOYMENTS says
FAKE_GH = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
issue = {
    "number": 12, "title": "a bug", "body": "it breaks", "author": {"__typename": "User", "login": "maria"},
    "authorAssociation": "OWNER", "labels": {"pageInfo": {"hasNextPage": False}, "nodes": []},
    "assignees": {"nodes": []}, "comments": {"nodes": []}, "timelineItems": {**page, "nodes": []},
}
pull = {
    "number": 3, "isDraft": False, "isCrossRepository": False, "labels": [], "headRefOid": "a" * 40,
    "assignees": [], "author": {"login": "amy", "is_bot": False},
}
if args[:2] == ["repo", "view"]:
    print(json.dumps({"defaultBranchRef": {"name": "main"}, "deleteBranchOnMerge": True}))
elif args[:2] == ["issue", "list"] or args[:2] == ["run", "list"]:
    print("[]")
elif args[:2] == ["pr", "list"]:
    print("[]" if "--state" in args else json.dumps([pull]))
elif args[:2] == ["api", "graphql"] and any("open:" in a for a in args):
    repository = {
        "open": {**page, "nodes": [issue]},
        "tags": {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": []},
        "closed": {"nodes": []},
        "vetoable": {**page, "nodes": []},
    }
    print(json.dumps({"data": {"repository": repository}}))
elif args[:1] == ["api"] and "/deployments" in " ".join(args):
    mode = os.environ["FAKE_DEPLOYMENTS"]
    if mode == "403" or (mode == "statuses-403" and "/statuses" in " ".join(args)):
        print(json.dumps({"message": "Resource not accessible by integration", "status": "403"}))
        sys.stderr.write("gh: Resource not accessible by integration (HTTP 403)\\n")
        sys.exit(1)
    if mode == "500":
        sys.stderr.write("gh: Server Error (HTTP 500)\\n")
        sys.exit(1)
    if mode == "other-403":
        sys.stderr.write("gh: Must have admin rights to Repository. (HTTP 403)\\n")
        sys.exit(1)
    if "/statuses" in " ".join(args):
        print("[]")
    else:
        print(json.dumps([{"id": 1, "ref": "v1.0.0", "sha": "b" * 40, "created_at": "2026-11-01T00:00:00Z"}]))
else:
    sys.stderr.write("unexpected gh call: " + " ".join(args) + "\\n")
    sys.exit(1)
"""


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_deployments", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def report(tmp_path: Path, deployments: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """The full report (--no-host) of a checkout with two environments, and every gh call"""
    git = shutil.which("git")
    assert git is not None
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(FAKE_GH.replace("{python}", sys.executable), encoding="utf-8")
    (fakes / "gh").chmod(0o700)
    log = tmp_path / "gh.log"
    log.touch()
    env = {
        "PATH": os.pathsep.join([str(fakes), str(Path(git).parent), "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "FAKE_LOG": str(log),
        "FAKE_DEPLOYMENTS": deployments,
    }
    origin, work = tmp_path / "origin.git", tmp_path / "work"

    def sh(*cmd: str, cwd: Path = work) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd], cwd=cwd, env=env, check=True)

    sh("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    sh("clone", "-q", str(origin), str(work), cwd=tmp_path)
    (work / ".github").mkdir()
    (work / ".github" / "shipmill.toml").write_text(CONFIG, encoding="utf-8")
    sh("switch", "-q", "-c", "main")
    sh("add", ".github/shipmill.toml")
    sh("commit", "-q", "-m", "start")
    sh("push", "-q", "origin", "main")
    cmd = [sys.executable, str(SCRIPT), "o/r", "--repo-dir", str(work), "--json", "--no-host"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    return proc, [json.loads(line) for line in log.read_text().splitlines()]


def rows(proc: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in proc.stdout.splitlines()]


@pytest.mark.parametrize("deployments", ["403", "statuses-403"])
def test_973_a_forbidden_deployments_read_is_one_notice_row_and_the_report_stands(
    tmp_path: Path, deployments: str
) -> None:
    proc, _ = report(tmp_path, deployments)
    assert proc.returncode in (0, 1), proc.stderr
    found = rows(proc)
    forbidden = [r for r in found if r["state"] == "DEPLOYMENTS_FORBIDDEN"]
    assert len(forbidden) == 1  # one per repo, however many environments
    (row,) = forbidden
    assert row["subject"] == "o/r" and row["agent"] is False
    assert "deployments: read" in str(row["detail"]) and "staging, production" in str(row["detail"])
    assert "deployments: read" in str(row["fix"]) and "installation" in str(row["fix"])
    # the issue and pull request rows are still there
    assert ("ISSUES", "NEW #12") in [(r["state"], r["detail"]) for r in found]
    assert ("PRS_OPEN", "#3") in [(r["state"], r["detail"]) for r in found]
    # and no environment's deploy or promotion row stands on what wasn't read
    assert not [r for r in found if r["state"] in ("UNHEALTHY", "PROMOTION_DUE")]


@pytest.mark.parametrize("deployments", ["500", "other-403"])
def test_973_any_other_deployments_failure_still_stops_the_watch(tmp_path: Path, deployments: str) -> None:
    proc, calls = report(tmp_path, deployments)
    assert proc.returncode == 2
    assert "repos/o/r/deployments" in proc.stderr
    assert proc.stdout == ""
    if deployments == "500":  # a server error is read once more first (S-011-11)
        reads = [c for c in calls if "repos/o/r/deployments" in c]
        assert len(reads) == 2


def test_973_readable_deployments_give_no_forbidden_row(tmp_path: Path) -> None:
    proc, _ = report(tmp_path, "ok")
    assert proc.returncode in (0, 1), proc.stderr
    assert "DEPLOYMENTS_FORBIDDEN" not in [r["state"] for r in rows(proc)]


def test_973_the_row_is_a_notice_never_an_agents_or_an_action(ws: ModuleType) -> None:
    # D-58's tiers: no tier lists it, so no session starts for it, and it never sets exit 1
    assert "DEPLOYMENTS_FORBIDDEN" not in ws.AGENT | ws.ACTION
    assert all("DEPLOYMENTS_FORBIDDEN" not in states for states in ws.TIERS.values())
    assert "DEPLOYMENTS_FORBIDDEN" in ws.FIXED  # it carries its fix
