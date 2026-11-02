"""Spec 053, #897: github-ship-watch reports an approved spec nobody split (SPEC_UNSPLIT), the
gate takes it up in tier 6 and hands it to github-issue-triage, and the skills say how. The
specs are read from a real git origin; gh is a stand-in on PATH or a read the test passes"""

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
from typing import Any

import pytest

from shipmill.findings import Finding
from shipmill.gate import prompt
from shipmill.status import SPEC_UNSPLIT, Row, report
from shipmill.walk import TIERS, Changes, Handed, Rows, Swept, tier_of, walk

from .test_status_picture import REPO, facts
from .test_triage_state import first_page, forward, open_issue

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
WATCH = SKILLS / "github-ship-watch" / "scripts" / "watch_state.py"
TRIAGE = SKILLS / "github-issue-triage" / "scripts" / "triage_state.py"
NOW = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.UTC)
FIX = "/shipmill:github-issue-triage o/r"
SAID = "approved, no build issues, no open issue follows it"
PULL = 40  # the pull request that added each spec, as the stand-in GitHub answers


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_unsplit", WATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def spec_text(number: int, status: str, issues: str = "") -> str:
    """A spec as specs.py parses it: its title, status, and sections"""
    verified = f"- S-{number:03d}-1: checked\n" if status == "built" else ""
    return (
        f"# S-{number:03d}: Spec {number}\n\nstatus: {status}\n\n## Problem\n\nx\n\n## Behaviour\n\nx\n\n"
        f"## Acceptance criteria\n\n- S-{number:03d}-1: it works\n\n## Out of scope\n\n- none\n\n"
        f"## Decisions relied on\n\n- none\n\n## Issues\n\n{issues}\n## Verification\n\n{verified}"
    )


SPECS = {
    "docs/specs/001-unsplit.md": spec_text(1, "approved"),
    "docs/specs/002-draft.md": spec_text(2, "draft"),
    "docs/specs/003-built.md": spec_text(3, "built", "- o/r#30: S-003-1\n"),
    "docs/specs/004-split.md": spec_text(4, "approved", "- o/r#31: S-004-1\n"),
    "docs/specs/005-short-ref.md": spec_text(5, "approved", "- #32: S-005-1\n"),  # specs.py reads #N too
    "docs/specs/TEMPLATE.md": "# S-NNN: <title>\n\nstatus: approved\n",
    "docs/specs/README.md": "status: approved\n",
}


def git(*cmd: str, cwd: Path) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *cmd], cwd=cwd, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def origin(tmp_path: Path, specs: dict[str, str] = SPECS) -> tuple[Path, dict[str, str]]:
    """A checkout whose origin/main holds the specs, each added by its own commit; the working
    tree then drops them all, so only a read of origin/main finds them"""
    bare, work = tmp_path / "origin.git", tmp_path / "work"
    git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    git("clone", "-q", str(bare), str(work), cwd=tmp_path)
    git("checkout", "-q", "-b", "main", cwd=work)
    git("commit", "-q", "--allow-empty", "-m", "start", cwd=work)
    added: dict[str, str] = {}
    for path, text in specs.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text, encoding="utf-8")
        git("add", path, cwd=work)
        git("commit", "-q", "-m", f"add {path}", cwd=work)
        added[path] = git("rev-parse", "HEAD", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    git("rm", "-q", "-r", "docs", cwd=work)  # the working tree is never read
    return work, added


def pulls(by_sha: dict[str, list[dict[str, Any]]], ran: list[list[str]]) -> Any:
    """A gh read answering `gh api repos/o/r/commits/<sha>/pulls` for the commits given"""

    def read(cmd: list[str]) -> str:
        ran.append(cmd)
        found = re.fullmatch(r"repos/o/r/commits/([0-9a-f]{40})/pulls", cmd[2])
        assert cmd[:2] == ["gh", "api"] and found is not None, cmd
        return json.dumps(by_sha.get(found.group(1), []))

    return read


def merged(number: int) -> dict[str, Any]:
    return {"number": number, "merged_at": "2026-11-01T14:23:03Z"}


def line(number: int, state: str, note: str = "", **extra: Any) -> str:
    return json.dumps({"number": number, "state": state, "title": "t", "note": note, **extra})


def test_s053_11_an_approved_spec_nobody_split_is_an_issues_row_with_triage_as_its_fix(
    ws: ModuleType, tmp_path: Path
) -> None:
    work, added = origin(tmp_path)
    ran: list[list[str]] = []
    triage = line(9, "NEW")  # an open issue that follows no spec
    path = "docs/specs/001-unsplit.md"
    by_sha = {added[path]: [merged(PULL), {"number": 41, "merged_at": None}]}
    (row,) = ws.spec_rows("o/r", work, "main", triage, pulls(by_sha, ran))
    assert (row.state, row.subject, row.fix) == ("ISSUES", path, FIX)
    assert row.detail == f"SPEC_UNSPLIT S-001 Spec 1 ({path}): {SAID}"
    assert row.json()["agent"] is True and row.state in ws.ACTION  # an action: the watch exits 1
    assert row.text().startswith(f"ISSUES         {path} SPEC_UNSPLIT S-001 Spec 1")
    # the pull request that added it is read once, for the one spec the reads before left
    assert ran == [["gh", "api", f"repos/o/r/commits/{added[path]}/pulls"]]


def test_s053_11_the_spec_rows_read_nothing_of_github_when_every_approved_spec_is_split(
    ws: ModuleType, tmp_path: Path
) -> None:
    split = {p: t for p, t in SPECS.items() if "001" not in p}
    work, _ = origin(tmp_path, split)
    ran: list[list[str]] = []
    assert ws.spec_rows("o/r", work, "main", "", pulls({}, ran)) == []
    assert ran == []


def test_s053_11_a_spec_no_merged_pull_request_added_is_still_reported(ws: ModuleType, tmp_path: Path) -> None:
    work, _ = origin(tmp_path)  # pushed straight to main: GitHub associates no merged pull request
    held = line(9, "BLOCKED", f"o/r#{PULL}:open")
    (row,) = ws.spec_rows("o/r", work, "main", held, pulls({}, []))
    assert row.subject == "docs/specs/001-unsplit.md"


# The stand-in gh for a whole --tier 6 run: triage_state.py's one GraphQL query, from a file,
# and the commits' pull requests, from FAKE_PULLS; any other call fails the run
FAKE_GH = """#!{python}
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["api", "graphql"]:
    print(json.dumps({{"data": {{"repository": json.loads(open(os.environ["FAKE_FIRST"]).read())}}}}))
elif args[0] == "api" and re.fullmatch(r"repos/o/r/commits/[0-9a-f]{{40}}/pulls", args[1]):
    print(json.dumps(json.loads(os.environ["FAKE_PULLS"]).get(args[1].split("/")[4], [])))
else:
    sys.stderr.write("unexpected gh call: " + " ".join(args) + "\\n")
    sys.exit(1)
"""


def native(item: dict[str, Any], body: str = "") -> dict[str, Any]:
    """An open issue as triage_state.py's first query reads it, with its forge relations"""
    return {**item, "body": body, "blockedBy": forward([]), "subIssues": forward([]), "parent": None}


def tier_6(
    tmp_path: Path, work: Path, first: dict[str, Any], by_sha: dict[str, Any]
) -> tuple[int, list[Any], list[Any]]:
    """watch_state.py --tier 6 as the gate runs it: its exit code, its rows, and its gh calls"""
    git_path = shutil.which("git")
    assert git_path is not None
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    (fakes / "gh").chmod(0o700)
    (tmp_path / "first.json").write_text(json.dumps(first), encoding="utf-8")
    (tmp_path / "known.json").write_text(
        json.dumps({"default_branch": "main", "held": False, "prs": [], "incidents": [], "runs": []}), encoding="utf-8"
    )
    log = tmp_path / "gh.log"
    log.touch()
    env = {
        "PATH": os.pathsep.join([str(fakes), str(Path(git_path).parent), "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "FAKE_LOG": str(log),
        "FAKE_FIRST": str(tmp_path / "first.json"),
        "FAKE_PULLS": json.dumps(by_sha),
    }
    cmd = [sys.executable, str(WATCH), "o/r", "--repo-dir", str(work), "--json", "--tier", "6"]
    done = subprocess.run(
        [*cmd, "--known", str(tmp_path / "known.json")], capture_output=True, text=True, env=env, check=False
    )
    assert done.returncode in (0, 1), done.stderr
    rows = [json.loads(r) for r in done.stdout.splitlines()]
    return done.returncode, rows, [json.loads(c) for c in log.read_text().splitlines()]


def test_s053_11_a_tier_6_read_reports_it_and_exits_1(tmp_path: Path) -> None:
    work, added = origin(tmp_path)
    code, rows, calls = tier_6(tmp_path, work, first_page([]), {added["docs/specs/001-unsplit.md"]: [merged(PULL)]})
    assert code == 1
    assert [(r["state"], r["subject"], r["detail"], r["agent"], r["fix"]) for r in rows] == [
        (
            "ISSUES",
            "docs/specs/001-unsplit.md",
            f"SPEC_UNSPLIT S-001 Spec 1 (docs/specs/001-unsplit.md): {SAID}",
            True,
            FIX,
        )
    ]
    assert [c[:2] for c in calls] == [
        ["api", "graphql"],
        ["api", f"repos/o/r/commits/{added[rows[0]['subject']]}/pulls"],
    ]


@pytest.mark.parametrize(
    ("triage", "spec"),
    [
        (line(9, "BLOCKED", f"o/r#{PULL}:open"), "001"),  # its feature issue holds on its spec PR
        (line(9, "UNBLOCKED", f"O/R#{PULL}:merged"), "001"),  # merged, not split yet: UNBLOCKED is triage's
        (line(9, "BLOCKED", f"children 0/1 closed o/r#7:open o/r#{PULL}:merged"), "001"),
        (line(9, "NEW", specs=["docs/specs/001-unsplit.md"]), "001"),  # an open issue's body links it
        (line(9, "UNTRUSTED", specs=["docs/specs/001-unsplit.md"]), "001"),  # whoever opened it
    ],
    ids=["blocked", "unblocked", "parent", "linked", "linked-untrusted"],
)
def test_s053_12_an_approved_spec_an_open_issue_follows_is_no_row(
    ws: ModuleType, tmp_path: Path, triage: str, spec: str
) -> None:
    work, added = origin(tmp_path)
    by_sha = {added[f"docs/specs/{spec}-unsplit.md"]: [merged(PULL)]}
    ran: list[list[str]] = []
    assert ws.spec_rows("o/r", work, "main", triage, pulls(by_sha, ran)) == []
    if "specs" in triage:
        assert ran == []  # a link in a body costs no read of the pull request


@pytest.mark.parametrize(
    "triage",
    [
        line(9, "BLOCKED", f"o/r#{PULL + 1}:open"),  # another pull request
        line(9, "BLOCKED", f"o/r#{PULL}0:open"),  # #400, not #40
        line(9, "BLOCKED", f"x-o/r#{PULL}:open"),  # another repo
        line(9, "IN_PROGRESS", f"#{PULL}:open"),  # not a hold
        line(9, "NEW", specs=["docs/specs/004-split.md"]),  # another spec
    ],
    ids=["other-pull", "longer-number", "other-repo", "in-progress", "other-spec"],
)
def test_s053_12_an_issue_that_follows_something_else_leaves_the_row(
    ws: ModuleType, tmp_path: Path, triage: str
) -> None:
    work, added = origin(tmp_path)
    by_sha = {added["docs/specs/001-unsplit.md"]: [merged(PULL)]}
    rows = ws.spec_rows("o/r", work, "main", triage, pulls(by_sha, []))
    assert [r.subject for r in rows] == ["docs/specs/001-unsplit.md"]


def test_s053_12_a_shallow_clone_is_refused_not_read_as_the_wrong_pull_request(ws: ModuleType, tmp_path: Path) -> None:
    # a shallow clone's boundary commit reads as adding every file, so git log would name the
    # tip's pull request, not the spec's, and report a spec its feature issue holds on
    work, added = origin(tmp_path)
    shallow = tmp_path / "shallow"
    git("clone", "-q", "--depth", "1", (tmp_path / "origin.git").as_uri(), str(shallow), cwd=tmp_path)
    by_sha = {added["docs/specs/001-unsplit.md"]: [merged(PULL)]}
    held = line(9, "BLOCKED", f"o/r#{PULL}:open")
    assert ws.spec_rows("o/r", work, "main", held, pulls(by_sha, [])) == []  # the full history reads it right
    with pytest.raises(ws.Refused, match="--unshallow"):
        ws.spec_rows("o/r", shallow, "main", held, pulls(by_sha, []))


def test_s053_12_a_draft_built_or_split_spec_is_no_row(ws: ModuleType, tmp_path: Path) -> None:
    work, _ = origin(tmp_path)
    found = ws.unsplit_specs(ws.branch_specs(work, "main"))
    # draft 002, built 003, and the split 004 and 005 are out, and so are TEMPLATE.md and README.md
    assert [path for path, _ in found] == ["docs/specs/001-unsplit.md"]
    assert [p for p, _ in ws.branch_specs(work, "main")] == sorted(p for p in SPECS if re.search(r"/\d{3}-", p))


def test_s053_12_triage_state_prints_the_specs_an_open_issue_links(tmp_path: Path) -> None:
    body = (
        "Spec: docs/specs/001-unsplit.md, approved by the merge of o/r#40.\n"
        "See https://github.com/o/r/blob/main/docs/specs/004-split.md and docs/specs/001-unsplit.md again;"
        " not mydocs/specs/006-x.md nor docs/specs/007-y.md.bak"
    )
    first = first_page([native(open_issue(9), body), native(open_issue(8))])
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
    (fakes / "gh").chmod(0o700)
    (tmp_path / "first.json").write_text(json.dumps(first), encoding="utf-8")
    env = {
        "PATH": os.pathsep.join([str(fakes), "/usr/bin", "/bin"]),
        "FAKE_LOG": str(tmp_path / "gh.log"),
        "FAKE_FIRST": str(tmp_path / "first.json"),
        "FAKE_PULLS": "{}",
    }
    done = subprocess.run(
        [sys.executable, str(TRIAGE), "o/r", "--json"], capture_output=True, text=True, env=env, check=False
    )
    assert done.returncode in (0, 1), done.stderr
    lines = {json.loads(r)["number"]: json.loads(r) for r in done.stdout.splitlines()}
    assert lines[9]["specs"] == ["docs/specs/001-unsplit.md", "docs/specs/004-split.md"]
    assert "specs" not in lines[8]  # a line without a spec path has none


def test_s053_12_a_malformed_specs_list_is_refused(ws: ModuleType, tmp_path: Path) -> None:
    work, _ = origin(tmp_path)
    with pytest.raises(ws.Refused, match="specs"):
        ws.spec_rows("o/r", work, "main", line(9, "NEW", specs="docs/specs/001-unsplit.md"), pulls({}, []))


def unsplit_finding(path: str = "docs/specs/001-unsplit.md") -> Finding:
    return Finding("ISSUES", path, f"SPEC_UNSPLIT S-001 Spec 1 ({path}): {SAID}", True, (), FIX)


def test_s053_13_the_gate_takes_spec_unsplit_up_in_tier_6_after_the_states_before_it() -> None:
    found = unsplit_finding()
    assert found.kind == "ISSUES SPEC_UNSPLIT" and found.kind in TIERS[6] and tier_of(found) == 6
    unblocked = Finding("ISSUES", "o/r", "UNBLOCKED #9", True, (), FIX)
    needs_pr = Finding("ISSUES", "o/r", "NEEDS_PR #12", True, (), FIX)
    source = Rows((needs_pr, found, unblocked))
    walked = walk(source, Changes("sig"), Swept(NOW, (), None), Handed(), NOW, dt.timedelta(hours=24), False)
    assert (walked.item, walked.tier) == (unblocked, 6)
    # with UNBLOCKED handed, the spec comes next, before NEEDS_PR
    handed = Handed().handing(unblocked, "s1", NOW)
    walked = walk(source, Changes("sig"), Swept(NOW, (), None), handed, NOW, dt.timedelta(hours=24), False)
    assert (walked.item, walked.tier) == (found, 6)


def test_s053_13_the_session_is_handed_the_spec_and_github_issue_triage() -> None:
    text = prompt("/shipmill:github-ship-watch {repo}", "o/r", [unsplit_finding()], NOW)
    assert "- ISSUES SPEC_UNSPLIT docs/specs/001-unsplit.md (tier 6)\n  fix: /shipmill:github-issue-triage o/r" in text
    assert "Spec 1" not in text  # the brief names the kind and the subject, never the detail


def test_s053_13_shipmill_status_lists_it_to_split() -> None:
    # D-55: shipmill status reports the pipeline, so the row has a line of its own there
    path = "docs/specs/001-unsplit.md"
    row = Row("ISSUES", path, f"{SPEC_UNSPLIT} S-001 Spec 1 ({path}): {SAID}", True, FIX)
    shown = report(facts(row)).text(REPO).splitlines()
    at = next(i for i, text in enumerate(shown) if re.fullmatch(rf"\s+to split\s+S-001 {re.escape(path)}", text))
    assert shown[at + 1].split() == ["fix:", *FIX.split()]


def folded(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_s053_14_the_spec_gate_opens_a_spec_pr_with_spec_open_and_takes_spec_unsplit_up() -> None:
    gate = folded(SKILLS / "github-issue-triage" / "references" / "spec-gate.md")
    steps = gate.split("## The gate", 1)[1].split("## Status", 1)[0]
    assert "4. **Open the spec PR with `shipmill spec open`.**" in steps
    assert "`shipmill spec open docs/specs/NNN-<slug>.md --issue N`" in steps
    assert "5. **Wait for the merge.**" in steps and "6. **" not in steps  # the manual steps 4 and 5 are one
    section = gate.split("## An approved spec nobody split", 1)[1].split("\n## ", 1)[0]
    for said in (
        "SPEC_UNSPLIT",
        "**Find the feature issue.**",
        "**With none, file one as the App**",
        "the merged pull request whose merge approved it",
        "**Link the spec in the issue's body**",
        "[When the spec merges](#when-the-spec-merges)",
        "D-16",
    ):
        assert said in section, said


def test_s053_14_the_skills_list_the_row() -> None:
    watch = folded(SKILLS / "github-ship-watch" / "SKILL.md")
    assert "| ISSUES `SPEC_UNSPLIT` |" in watch
    assert "spec-gate.md#an-approved-spec-nobody-split" in watch
    triage = folded(SKILLS / "github-issue-triage" / "SKILL.md")
    close_the_loop = triage.split("### 7. Close the loop", 1)[1].split("## Chains", 1)[0]
    assert "- **SPEC_UNSPLIT**" in close_the_loop and "An approved spec nobody split" in close_the_loop
    assert "`shipmill spec open docs/specs/NNN-<slug>.md --issue N`" in triage
    assert "SPEC_UNSPLIT" in WATCH.read_text(encoding="utf-8").split('"""', 2)[1]  # the script's help
