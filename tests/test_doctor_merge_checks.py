"""Spec 080's merge-checks row in shipmill doctor, and the setup's Autonomy step that shows it:
the lines `shipmill merge-checks` prints, judged at the configured land, only with [agents]
(S-080-15, S-080-17)"""

import re
from pathlib import Path

import pytest

from shipmill.autonomy import Autonomy
from shipmill.cli import main
from shipmill.doctor import CALLER, Check, doctor
from shipmill.merge_checks import ROW, report

from .conftest import POLICY, Repo
from .test_merge_checks import CI, SLUG, FakeRules, checks_rule
from .test_product import WELL_FORMED

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/t"\n'


def configure(repo: Repo, config: str) -> None:
    repo.write(".github/workflows/ci.yml", CI)
    repo.write(repo.policy_file, config)


def build_only() -> FakeRules:
    return FakeRules(rules=[checks_rule(1, "build")], sets={1: {"name": "main"}})


def rows(repo: Repo, reader: FakeRules | None) -> list[Check]:
    return [c for c in doctor(repo.root, repo.github, repo=SLUG, rules=lambda: reader) if c.name == ROW]


def test_s080_15_doctor_prints_the_merge_checks_lines_at_the_configured_land(repo: Repo) -> None:
    # proves: S-080-15
    configure(repo, POLICY + AGENTS + '\n[autonomy]\nland = "act"\n')
    repo.github.holds = ["88 hold everything"]  # the configured level counts, never the hold's
    found = rows(repo, build_only())
    expected = report(repo.root, SLUG, "main", Autonomy.ACT, build_only()).lines()
    assert [(c.status, c.detail) for c in found] == expected
    assert found[-1].status == "WARN"
    assert found[-1].detail.startswith("main requires 1 check and none runs tests")
    configure(repo, POLICY + AGENTS)  # land unset: propose
    assert [(c.status, c.detail) for c in rows(repo, build_only())][-1] == (
        "PASS",
        "main requires 1 check; none proves (`build` build only); land is propose",
    )


def test_s080_15_without_gh_the_row_warns(repo: Repo) -> None:
    # proves: S-080-15
    configure(repo, POLICY + AGENTS)
    assert rows(repo, None) == [
        Check(
            "WARN",
            ROW,
            "can't read the required checks: gh isn't installed; the checks stay unjudged; no required check was"
            " read; land is propose",
        )
    ]


def test_s080_15_without_agents_no_row_and_no_rules_read(repo: Repo) -> None:
    # proves: S-080-15
    configure(repo, POLICY)
    assert not (repo.root / CALLER).exists()  # no release workflow: the landing row reads nothing either
    reader = build_only()
    built: list[FakeRules] = []

    def rules() -> FakeRules:
        built.append(reader)
        return reader

    found = doctor(repo.root, repo.github, repo=SLUG, rules=rules)
    assert [c for c in found if c.name == ROW] == []
    assert built == [] and reader.reads == []


def test_s080_15_a_checkout_that_cant_be_read_warns(repo: Repo) -> None:
    # proves: S-080-15
    configure(repo, POLICY + AGENTS)
    repo.write(".github/workflows/js.yml", "on: pull_request\njobs:\n  js:\n    steps:\n      - run: npm test\n")
    repo.write("package.json", "{")
    (row,) = rows(repo, build_only())
    assert row.status == "WARN"
    assert row.detail.startswith("can't read the checks gating a merge: .github/workflows/js.yml job js:")
    assert "package.json is not JSON" in row.detail


def test_s080_15_a_warn_on_the_row_leaves_the_exit_code(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    # proves: S-080-15
    configure(repo, POLICY + AGENTS + '\n[autonomy]\nland = "act"\n')
    repo.write("docs/product.md", WELL_FORMED)
    code = main(["--repo", str(repo.root), "doctor"], environ={"PATH": ""}, rules_reader=build_only())
    lines = capsys.readouterr().out.splitlines()
    mine = [line for line in lines if line.split(" ", 1)[-1].startswith(f"{ROW}:")]
    assert mine and all(line.startswith("WARN ") for line in mine)  # the fixture's origin isn't on GitHub
    assert code == (1 if any(line.startswith("FAIL ") for line in lines) else 0)


def _autonomy_step(setup: str) -> str:
    step = re.search(r"1\. \*\*Autonomy\.\*\*(.*?)\n2\. \*\*Config\.\*\*", setup, re.DOTALL)
    assert step is not None
    return " ".join(step.group(1).split())


def test_s080_17_setup_runs_merge_checks_before_its_question_and_shows_it_with_land() -> None:
    # proves: S-080-17
    step = _autonomy_step((ROOT / "skills" / "shipmill-setup" / "SKILL.md").read_text(encoding="utf-8"))
    run = step.index("Before you ask, run `$CR merge-checks --land act`")
    assert run < step.index('Recommend "Recommended for the first weeks"')
    assert "Show its lines with the `land` lines below, in a gate session inside the needs-decision question" in step
    land = re.search(r"- \*\*land:\*\* (.*?)(?= - \*\*|$)", step)
    assert land is not None and "show the output of `$CR merge-checks --land act`" in land.group(1)
    assert (
        'When its last line is a WARN, put that warning beside every option that sets `land = "act"`: the "Ship by'
        ' itself" profile and Custom\'s `land = "act"`'
    ) in step


def test_s080_17_install_lists_the_row_among_doctors_checks() -> None:
    # proves: S-080-17
    install = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    checks = install[install.index("`doctor` must pass every line. It checks:") :]
    checks = " ".join(checks[: checks.index("\n\n", checks.index("\n- "))].split())
    assert "With an `[agents]` section, a `merge-checks` row: the lines `$CR merge-checks` prints" in checks
    assert "judged at the configured `[autonomy] land`" in checks
