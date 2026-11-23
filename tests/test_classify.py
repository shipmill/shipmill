"""D-99 (#1457): a pull request that raises an [autonomy] stage's level is decision-policy"""

from typing import Any

import pytest

from shipmill.github import FileChange

from .conftest import POLICY, Repo
from .test_decide_cli import BASE, CONFIG, HEAD, FakePulls, commit, config_change, patch, run, zones_of

ENVIRONMENTS = '\n[environments.production]\nworkflow = "deploy.yml"\n'


def classify(repo: Repo, capsys: pytest.CaptureFixture[str], before: str, after: str) -> dict[str, Any]:
    commit(repo)
    return run(repo, capsys, "classify", "--pr", "7", pulls=config_change(POLICY + before, POLICY + after))


def reason(found: dict[str, Any], zone: str) -> str:
    [detected] = [z for z in found["zones"] if z["zone"] == zone]
    text: str = detected["reason"]
    return text


def test_d99_raising_land_is_decision_policy(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    found = classify(repo, capsys, "", '\n[autonomy]\nland = "act"\n')
    assert zones_of(found) == {"decision-policy": "never", "security": "ask"}
    assert "land propose -> act" in reason(found, "decision-policy")


def test_d99_the_reason_names_each_raised_stage(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    before = '\n[autonomy]\ntriage = "observe"\nfix = "propose"\nrelease = "act"\n'
    after = '\n[autonomy]\ntriage = "act"\nfix = "act"\nrelease = "propose"\n'
    found = classify(repo, capsys, before, after)
    assert zones_of(found) == {"decision-policy": "never", "security": "ask"}
    why = reason(found, "decision-policy")
    assert "triage observe -> act" in why
    assert "fix propose -> act" in why
    assert "release" not in why  # lowered


def test_d99_lowering_a_level_stays_security(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    found = classify(repo, capsys, '\n[autonomy]\nland = "act"\n', '\n[autonomy]\nland = "observe"\n')
    assert zones_of(found) == {"security": "ask"}


def test_d99_a_reorder_or_a_comment_keeps_the_levels(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    before = '\n[autonomy]\ntriage = "act"\nland = "act"\n'
    after = '\n[autonomy]\n# merged on green\nland = "act"\ntriage = "act"  # always\n'
    assert classify(repo, capsys, before, after)["zones"] == []


def test_d99_writing_what_the_prompt_already_gives_stays_security(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    agents = '\n[agents]\nprompt = "Triage, fix, and merge when green"\n'
    after = agents + '\n[autonomy]\ntriage = "act"\nfix = "act"\nland = "act"\n'
    assert zones_of(classify(repo, capsys, agents, after)) == {"security": "ask"}


def test_d99_a_prompt_that_starts_to_land_is_a_raise(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    before = '\n[agents]\nprompt = "Triage and fix"\n'
    after = '\n[agents]\nprompt = "Triage, fix, and land"\n'
    found = classify(repo, capsys, before, after)
    assert zones_of(found) == {"decision-policy": "never", "security": "ask"}
    assert "land propose -> act" in reason(found, "decision-policy")


def test_d99_upgrade_and_revert_are_stages_too(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    found = classify(repo, capsys, "", '\n[autonomy]\nupgrade = "act"\nrevert = "propose"\n')
    assert zones_of(found) == {"decision-policy": "never", "security": "ask"}
    why = reason(found, "decision-policy")
    assert "upgrade propose -> act" in why
    assert "revert observe -> propose" in why


def test_d99_a_deploy_stage_rises_or_comes_at_its_default(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    held = ENVIRONMENTS + '\n[autonomy.deploy]\nproduction = "propose"\n'
    raised = classify(repo, capsys, held, ENVIRONMENTS + '\n[autonomy.deploy]\nproduction = "act"\n')
    assert zones_of(raised) == {"decision-policy": "never", "security": "ask"}
    assert "deploy.production propose -> act" in reason(raised, "decision-policy")
    new = classify(repo, capsys, "", ENVIRONMENTS + '\n[autonomy.deploy]\nproduction = "act"\n')
    assert zones_of(new) == {"security": "ask"}  # a new stage at its default (D-7) raises nothing


def test_d99_an_added_config_is_read_against_the_defaults(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo)
    added = FakePulls(
        (FileChange(CONFIG, "added", patch("x")),), {(HEAD, CONFIG): POLICY + '\n[autonomy]\nland = "act"\n'}
    )
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=added)) == {
        "decision-policy": "never",
        "security": "ask",
    }
    removed = FakePulls(
        (FileChange(CONFIG, "removed", patch("x")),), {(BASE, CONFIG): POLICY + '\n[autonomy]\nland = "observe"\n'}
    )
    assert zones_of(run(repo, capsys, "classify", "--pr", "7", pulls=removed)) == {"security": "ask"}


def test_d99_levels_that_cant_be_read_count_as_a_raise(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    found = classify(repo, capsys, "", '\n[autonomy]\nland = "always"\n')
    assert zones_of(found) == {"decision-policy": "never", "security": "ask"}
    assert "[autonomy] levels can't be read" in reason(found, "decision-policy")
