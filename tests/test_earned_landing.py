"""Spec 083's earned level in `decide classify --pr`: a zone the base bounds in [decisions.earned]
lands at the bound when every piece of evidence holds, and at the base's level otherwise"""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.github import FileChange, GhCli, PullChange
from shipmill.landing import Classic

from .conftest import POLICY, Repo
from .test_area_record import LINE, FakeReads, history, later
from .test_decide_cli import BASE, HEAD, FakePulls, commit
from .test_merge_checks import FakeRules, checks_rule

LEVELS = '\n[decisions]\nprotected = "ask"\nsecurity = "ask"\n'
BOUNDS = '\n[decisions.earned]\nprotected = "act"\nsecurity = "notify"\nmax_lines = 200\n'
EARNED = POLICY + LEVELS + BOUNDS
REVIEW = "# Review\n\n## Protected areas\n\n- `**`: every path the maintainer reviews\n"
CI = """\
name: CI
on: pull_request
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - run: uv run pytest -q
  build:
    runs-on: ubuntu-latest
    steps:
      - run: uv build
"""
DEPLOY = """\
name: Deploy
on: push
jobs:
  ship:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - run: ./deploy.sh
"""
FILES = {"REVIEW.md": REVIEW, ".github/workflows/ci.yml": CI}
SOURCE = "src/release/a.py"
NOTE = " (earned act from ask by [decisions.earned])"
ORDER = ["checks", "size", "record", "kind"]


@dataclass
class Pull(FakePulls):
    """A pull request whose files GitHub lists whole, each with its changed lines"""

    listed: int | None = None

    def pull_change(self, number: int) -> PullChange:
        change = super().pull_change(number)
        return replace(change, changed=len(self.files) if self.listed is None else self.listed)


@dataclass
class Rules(FakeRules):
    """The default branch's ruleset requires `check`, whose job runs pytest"""

    rules: list[dict[str, Any]] | ReleaseError = field(default_factory=lambda: [checks_rule(1, "check")])
    sets: dict[int, dict[str, Any]] = field(default_factory=lambda: {1: {"name": "main"}})


def one(path: str = SOURCE, lines: int | None = 40, status: str = "modified") -> FileChange:
    return FileChange(path, status, "@@ -1 +1 @@\n+A = 9", None, lines)


def classify(
    repo: Repo,
    capsys: pytest.CaptureFixture[str],
    pulls: FakePulls,
    rules: FakeRules | None = None,
    reads: FakeReads | None = None,
    *args: str,
) -> dict[str, Any]:
    given = args or ("--pr", "7")
    argv = ["--repo", str(repo.root), "decide", "classify", *given, "--json"]
    assert main(argv, pulls=pulls, record_reads=reads or FakeReads(), rules_reader=rules or Rules()) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def zones(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {z["zone"]: z for z in found["zones"]}


def evidence(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["name"]: e for e in found["landing"]["evidence"]}


# -- S-083-8: every piece of evidence holds -----------------------------------------------------


def test_s083_8_protected_at_ask_earns_act_with_the_earned_object_reason_and_landing(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, EARNED, **FILES)
    rules = Rules()
    found = classify(repo, capsys, Pull((one(),)), rules)
    protected = zones(found)["protected"]
    assert set(zones(found)) == {"protected"}
    assert protected["level"] == "act"
    assert protected["earned"] == {"from": "ask", "to": "act"}
    assert protected["reason"].endswith(NOTE)
    assert protected["paths"] == [{"path": SOURCE, "level": "act", "source": "config", "glob": None}]
    assert found["level"] == "act"
    assert found["landing"] == {
        "level": "act",
        "earned": True,
        "evidence": [
            {"name": "checks", "holds": True, "detail": "check"},
            {"name": "size", "holds": True, "detail": "40 of at most 200 lines"},
            {"name": "record", "holds": True, "detail": "no raised area"},
            {"name": "kind", "holds": True, "detail": "no ceiling path"},
        ],
    }
    assert rules.reads == ["rules o/demo main", "ruleset 1", "protection main"]


def test_s083_8_text_prints_the_landing_level_and_one_line_per_piece_of_evidence(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, EARNED, **FILES)
    argv = ["--repo", str(repo.root), "decide", "classify", "--pr", "7"]
    assert main(argv, pulls=Pull((one(),)), record_reads=FakeReads(), rules_reader=Rules()) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "level: act"
    assert out[1].startswith("zone: protected at act: ") and out[1].endswith(NOTE)
    assert out[2:] == [
        "landing: act",
        "checks: holds: check",
        "size: holds: 40 of at most 200 lines",
        "record: holds: no raised area",
        "kind: holds: no ceiling path",
    ]


def test_s083_8_a_zone_no_bound_lowers_gains_no_earned_key(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + LEVELS + '\n[decisions.earned]\nsecurity = "notify"\n', **FILES)
    found = classify(repo, capsys, Pull((one(),)))
    assert zones(found)["protected"]["level"] == "ask"
    assert "earned" not in zones(found)["protected"]
    assert found["landing"]["earned"] is False
    assert all(e["holds"] for e in found["landing"]["evidence"])


# -- S-083-9: one piece of evidence fails -------------------------------------------------------


def kept(found: dict[str, Any], failing: str) -> dict[str, Any]:
    """protected stays at ask with no earned object, landing.earned is false, and only the
    named entry fails; that entry is returned"""
    protected = zones(found)["protected"]
    assert protected["level"] == "ask"
    assert "earned" not in protected
    assert not protected["reason"].endswith(NOTE)
    assert found["landing"]["level"] == "ask"
    assert found["landing"]["earned"] is False
    assert [e["name"] for e in found["landing"]["evidence"]] == ORDER
    assert {e["name"] for e in found["landing"]["evidence"] if not e["holds"]} == {failing}
    return evidence(found)[failing]


def test_s083_9_201_lines_over_max_lines_200_keeps_ask(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, EARNED, **FILES)
    found = classify(repo, capsys, Pull((one(lines=120), one("src/release/b.py", 81))))
    assert kept(found, "size")["detail"] == "201 of at most 200 lines"


@pytest.mark.parametrize(
    ("rules", "detail"),
    [
        (Rules(rules=[], classic=Classic(True, None)), "main requires no status check"),
        (Rules(rules=[checks_rule(1, "build")]), "no check main requires proves (`build` build only)"),
        (
            Rules(rules=ReleaseError("gh api rules failed: HTTP 502")),
            "the required checks can't be read: can't read main's rulesets: gh api rules failed: HTTP 502",
        ),
        (
            Rules(classic=ReleaseError("GET protection answered 403")),
            "the required checks can't be read: can't read main's classic protection: GET protection answered 403",
        ),
    ],
)
def test_s083_9_no_proving_check_or_a_failed_rules_read_keeps_ask(
    repo: Repo, capsys: pytest.CaptureFixture[str], rules: Rules, detail: str
) -> None:
    commit(repo, EARNED, **FILES)
    assert kept(classify(repo, capsys, Pull((one(),)), rules), "checks")["detail"] == detail


def test_s083_9_a_rules_reading_that_fails_on_the_checkout_keeps_ask(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, EARNED, **FILES, **{".github/workflows/bad.yml": "on: pull_request\n"})
    (repo.root / ".github/workflows/bad.yml").write_bytes(b"\xff\xfe")
    entry = kept(classify(repo, capsys, Pull((one(),))), "checks")
    assert entry["detail"].startswith("the required checks can't be read: .github/workflows/bad.yml is not UTF-8")


def test_s083_9_a_pull_request_in_a_raised_area_keeps_ask(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    history(repo)
    later(repo)
    reads = FakeReads()
    reads.incident(212, LINE)
    commit(repo, EARNED, **FILES)
    found = classify(repo, capsys, Pull((one("src/app/a.py"),)), reads=reads)
    assert kept(found, "record")["detail"] == "src/app raised"


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("pyproject.toml", "pyproject.toml is of the dependencies kind"),
        ("src/release/migrations/0002.py", "src/release/migrations/0002.py is of the infrastructure kind"),
    ],
)
def test_s083_9_a_ceiling_path_keeps_ask_naming_the_path_and_its_kind(
    repo: Repo, capsys: pytest.CaptureFixture[str], path: str, detail: str
) -> None:
    commit(repo, EARNED, **FILES)
    found = classify(repo, capsys, Pull((one(), one(path, 1))))
    assert kept(found, "kind")["detail"] == detail


def test_s083_9_gh_reads_each_files_lines_and_the_pull_requests_file_count(tmp_path: Path) -> None:
    """GhCli.pull_change: a file's additions plus deletions, None for a count GitHub doesn't
    give, and the pull request's changed_files"""
    base = {"sha": "t" * 40, "repo": {"full_name": "o/demo"}}
    pull = json.dumps({"head": {"sha": HEAD}, "base": base, "labels": [], "body": "", "changed_files": 3})
    files = (
        json.dumps({"filename": "a.py", "status": "modified", "patch": "+a", "additions": 30, "deletions": 10}),
        json.dumps({"filename": "b.py", "status": "modified", "patch": "+b", "additions": 2}),
    )
    script = tmp_path / "gh"
    script.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *compare/*) echo {'a' * 40} ;;\n"
        f"  *pulls/5/files*) printf '%s\\n' '{files[0]}' '{files[1]}' ;;\n"
        f"  *pulls/5) echo '{pull}' ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    change = GhCli(tmp_path, gh=str(script)).pull_change(5)
    assert [f.lines for f in change.files] == [40, None]
    assert change.changed == 3


@pytest.mark.parametrize(
    ("files", "listed", "detail"),
    [
        ((one(lines=None),), None, f"GitHub gives no count of {SOURCE}'s changed lines"),
        ((one(),), 3001, "GitHub lists 1 of the 3001 files the pull request changes"),
    ],
)
def test_s083_9_a_size_that_cant_be_measured_keeps_ask(
    repo: Repo, capsys: pytest.CaptureFixture[str], files: tuple[FileChange, ...], listed: int | None, detail: str
) -> None:
    commit(repo, EARNED, **FILES)
    found = classify(repo, capsys, Pull(files, listed=listed))
    assert kept(found, "size")["detail"] == f"{detail}, so its size can't be measured"


def test_s083_9_a_renamed_files_old_path_counts_for_its_kind(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, EARNED, **FILES)
    renamed = FileChange(SOURCE, "renamed", "", "uv.lock", 0)
    found = classify(repo, capsys, Pull((renamed,)))
    assert kept(found, "kind")["detail"] == "uv.lock is of the dependencies kind"


# -- S-083-10: what never earns ------------------------------------------------------------------

CEILING = [
    (".github/shipmill.toml", "controls"),
    ("REVIEW.md", "controls"),
    (".github/workflows/ci.yml", "controls"),
    (".github/workflows/deploy.yml", "controls"),
    (".github/actions/setup/action.yml", "controls"),
    ("infra/main.tf", "infrastructure"),
    ("db/migrations/0001.sql", "infrastructure"),
    ("uv.lock", "dependencies"),
    ("web/package.json", "dependencies"),
]


@pytest.mark.parametrize(("path", "kind"), CEILING)
def test_s083_10_no_ceiling_path_earns_whatever_the_evidence(
    repo: Repo, capsys: pytest.CaptureFixture[str], path: str, kind: str
) -> None:
    commit(repo, EARNED, **FILES)
    texts = {
        (HEAD, ".github/workflows/ci.yml"): CI,
        (BASE, ".github/workflows/ci.yml"): CI,
        (HEAD, ".github/workflows/deploy.yml"): DEPLOY,
        (BASE, ".github/shipmill.toml"): EARNED,
        (HEAD, ".github/shipmill.toml"): EARNED + "\n[land]\n",
    }
    status = "added" if path == ".github/workflows/deploy.yml" else "modified"
    found = classify(repo, capsys, Pull((one(path, 1, status),), texts))
    assert found["landing"]["earned"] is False
    assert evidence(found)["kind"] == {"name": "kind", "holds": False, "detail": f"{path} is of the {kind} kind"}
    assert [e["name"] for e in found["landing"]["evidence"] if not e["holds"]] == ["kind"]
    for zone in found["zones"]:
        assert "earned" not in zone
        assert not zone["reason"].endswith(NOTE)
    assert zones(found)["protected"]["level"] == "ask"


def test_s083_10_a_path_a_part_sets_at_never_stays_never(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    part = '\n[decisions.paths.protected]\n"src/release/keys/**" = "never"\n'
    commit(repo, EARNED + part, **FILES)
    found = classify(repo, capsys, Pull((one("src/release/keys/k.py", 2), one(lines=2))))
    assert all(e["holds"] for e in found["landing"]["evidence"])
    assert zones(found)["protected"]["level"] == "never"
    assert "earned" not in zones(found)["protected"]
    assert found["landing"] == found["landing"] | {"level": "never", "earned": False}


def test_s083_10_files_never_earns_and_reads_no_rules(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, EARNED, **FILES)
    rules = Rules()
    found = classify(repo, capsys, Pull(), rules, None, "--files", SOURCE)
    assert zones(found)["protected"]["level"] == "ask"
    assert "earned" not in zones(found)["protected"]
    assert "landing" not in found
    assert rules.reads == []


def test_s083_10_a_pull_request_that_adds_the_table_is_judged_without_it(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    before = POLICY + LEVELS
    commit(repo, before, **FILES)
    texts = {(BASE, ".github/shipmill.toml"): before, (HEAD, ".github/shipmill.toml"): EARNED}
    rules = Rules()
    found = classify(repo, capsys, Pull((one(".github/shipmill.toml", 6), one()), texts), rules)
    assert zones(found)["decision-policy"]["level"] == "never"
    assert zones(found)["protected"]["level"] == "ask"
    assert found["level"] == "never"
    assert found["landing"]["level"] == "never"
    assert found["landing"]["earned"] is False
    assert evidence(found)["checks"] == {
        "name": "checks",
        "holds": False,
        "detail": "not read: [decisions.earned] is not set",
    }
    assert rules.reads == []  # the base has no [decisions.earned]: no rules read
