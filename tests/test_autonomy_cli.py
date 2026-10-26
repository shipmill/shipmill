"""Spec 040: `shipmill autonomy`, and doctor's report of the agent stages"""

import json
from typing import Any

import pytest

from shipmill.cli import main
from shipmill.doctor import doctor
from shipmill.errors import ReleaseError

from .conftest import POLICY, Repo
from .test_decide_cli import CONFIG, commit

ENVIRONMENTS = """
[environments.staging]
lane = "rc"
workflow = "deploy.yml"

[environments.production]
from = "staging"
workflow = "deploy.yml"
"""
AGENTS = '\n[agents]\nprompt = "/shipmill:github-issue-triage {repo} triage the new issues"\n'


def autonomy(repo: Repo, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert main(["--repo", str(repo.root), "autonomy", *args, "--json"], github=repo.github) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def stages(found: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    return {s["stage"]: (s["configured"], s["effective"], s["source"]) for s in found["stages"]}


def test_s040_4_autonomy_json_lists_every_stage_with_configured_effective_and_source(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    config = POLICY + ENVIRONMENTS + '\n[autonomy]\nland = "act"\nrollback = "observe"\ndeploy.production = "propose"\n'
    commit(repo, config)
    found = autonomy(repo, capsys)
    assert found["hold"] == []
    assert all(set(s) == {"stage", "configured", "effective", "source"} for s in found["stages"])
    assert stages(found) == {
        "triage": ("act", "act", "default"),
        "fix": ("act", "act", "default"),
        "land": ("act", "act", "config"),
        "release": ("act", "act", "default"),
        "deploy.production": ("propose", "propose", "config"),
        "deploy.staging": ("act", "act", "default"),  # declared, unlisted in [autonomy]: act (D-7)
        "rollback": ("observe", "observe", "config"),
        "intake": ("propose", "propose", "default"),
        "upgrade": ("propose", "propose", "default"),
    }
    assert list(stages(found)) == [
        "triage", "fix", "land", "release", "deploy.production", "deploy.staging", "rollback", "intake", "upgrade",
    ]  # fmt: skip


def test_s040_4_the_hold_lowers_each_act_and_names_its_issues(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + '\n[autonomy]\nfix = "observe"\nland = "act"\nupgrade = "act"\n')
    repo.github.holds = ["#88 deploy broke login", "#89 also"]
    found = autonomy(repo, capsys)
    assert found["hold"] == ["#88 deploy broke login", "#89 also"]
    assert stages(found) == {
        "triage": ("act", "propose", "hold"),
        "fix": ("observe", "observe", "config"),  # the hold never raises a level
        "land": ("act", "propose", "hold"),
        "release": ("act", "propose", "hold"),
        "rollback": ("act", "propose", "hold"),
        "intake": ("propose", "propose", "default"),  # never acts: nothing to lower
        "upgrade": ("act", "propose", "hold"),
    }


def test_s040_4_the_text_form_prints_the_hold_then_a_row_per_stage(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    repo.github.holds = ["#88 deploy broke login"]
    assert main(["--repo", str(repo.root), "autonomy"], github=repo.github) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "hold: #88 deploy broke login"
    assert out[1].split() == ["triage", "act", "propose", "hold"]
    assert out[3].split() == ["land", "propose", "propose", "default"]
    assert len(out) == 1 + 7
    long = POLICY + "\n[environments.github-pages-preview]\nlane = 'rc'\nworkflow = 'd.yml'\n"
    commit(repo, long)
    assert main(["--repo", str(repo.root), "autonomy"], github=repo.github) == 0
    out = capsys.readouterr().out.splitlines()
    assert len({line.index(" act ") for line in out if " act " in line}) == 1  # a long name keeps the columns


def test_s040_4_a_hold_that_cannot_be_read_stops_it(repo: Repo) -> None:
    commit(repo)

    class Unreadable:
        def open_issues(self, label: str) -> list[str]:
            raise ReleaseError(f"gh issue list --label {label}: HTTP 502")

    with pytest.raises(ReleaseError, match="HTTP 502"):
        main(["--repo", str(repo.root), "autonomy"], github=Unreadable())  # type: ignore[arg-type]


def test_s040_5_autonomy_reads_the_config_at_the_ref_default_origin_head(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo)
    raised = POLICY + '\n[autonomy]\nland = "act"\n'
    repo.write(CONFIG, raised)  # a change's checkout raises land; origin/HEAD doesn't
    assert stages(autonomy(repo, capsys))["land"] == ("propose", "propose", "default")
    assert stages(autonomy(repo, capsys, "--ref", "origin/HEAD"))["land"] == ("propose", "propose", "default")
    repo.git.run("add", "-A")
    repo.git.run("commit", "-q", "-m", "raise land")
    branch = repo.git.sha()
    assert stages(autonomy(repo, capsys, "--ref", branch))["land"] == ("act", "act", "config")
    assert stages(autonomy(repo, capsys))["land"] == ("propose", "propose", "default")


def test_s040_5_a_ref_the_checkout_lacks_exits_2(repo: Repo) -> None:
    commit(repo)
    # run() turns a ReleaseError into exit 2
    with pytest.raises(ReleaseError, match="nope is not in"):
        main(["--repo", str(repo.root), "autonomy", "--ref", "nope"], github=repo.github)


def test_s040_5_a_malformed_config_at_the_ref_exits_2(repo: Repo) -> None:
    commit(repo, POLICY + '\n[autonomy]\nland = "merge"\n')
    with pytest.raises(ReleaseError, match=r"land must be one of \['observe', 'propose', 'act'\], got 'merge'"):
        main(["--repo", str(repo.root), "autonomy"], github=repo.github)


# -- doctor ----------------------------------------------------------------------------------


def autonomy_checks(repo: Repo) -> list[tuple[str, str]]:
    return [(c.status, c.detail) for c in doctor(repo.root, repo.github) if c.name == "autonomy"]


def test_s040_17_doctor_lists_the_agent_stages_in_its_autonomy_pass_line(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + '\n[autonomy]\nfix = "observe"\n')
    [(status, detail)] = autonomy_checks(repo)
    assert status == "PASS"
    assert "; triage act, fix observe, land propose in agent sessions;" in detail
    repo.github.holds = ["#7 Investigating"]
    [(status, detail)] = autonomy_checks(repo)
    assert "; triage propose, fix observe, land propose in agent sessions;" in detail


def test_s040_17_doctor_warns_when_an_agent_stage_is_set_without_agents(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + '\n[autonomy]\nrelease = "act"\n')
    assert [s for s, _ in autonomy_checks(repo)] == ["PASS"]  # a release-side key alone is read without [agents]
    repo.write(repo.policy_file, POLICY + '\n[autonomy]\nland = "act"\n')
    [_, (status, detail)] = autonomy_checks(repo)
    assert (status, detail) == (
        "WARN",
        "[autonomy] sets land, but nothing reads it without [agents]: the agent stages bound agent sessions only;"
        " add [agents] or delete it",
    )
    repo.write(repo.policy_file, POLICY + '\n[autonomy]\ntriage = "act"\nfix = "act"\nland = "propose"\n')
    [_, (status, detail)] = autonomy_checks(repo)
    assert status == "WARN" and detail.startswith("[autonomy] sets triage, fix, land, but nothing reads them")
    repo.write(repo.policy_file, POLICY + AGENTS + '\n[autonomy]\ntriage = "act"\nfix = "act"\nland = "propose"\n')
    assert [s for s, _ in autonomy_checks(repo)] == ["PASS"]
