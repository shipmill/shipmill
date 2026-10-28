"""Spec 040's legacy reading of [agents] prompt, with no end date (D-59), and the agent-autonomy
upgrade that writes its levels into [autonomy]"""

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from shipmill import cli_command
from shipmill.agents import AgentsConfig
from shipmill.autonomy import Autonomy, AutonomyPolicy, Hold, Stage, StageKind, lands
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.doctor import doctor
from shipmill.errors import ReleaseError
from shipmill.github import UPGRADE_LABEL
from shipmill.policy import Policy
from shipmill.upgrades import UpgradeId, body, find, propose, title

from .conftest import POLICY, FakeGitHub, Repo
from .test_decide_cli import commit

LAND = Stage(StageKind.LAND)
HELD = Hold(("#88 deploy broke login",))
FRAGMENTS = POLICY.replace("[changelog]\n", '[changelog]\nfragments = "changelog.d"\n')  # no other upgrade pending


def agents(prompt: str) -> str:
    return f"\n[agents]\nprompt = {json.dumps(prompt)}\n"


def parsed(text: str) -> AutonomyPolicy:
    return Policy.parse(tomllib.loads(POLICY + text), "shipmill.toml").autonomy


def write(root: Path, text: str) -> Path:
    path = root / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


# -- the legacy reading (S-040-6) ------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "/shipmill:github-issue-triage {repo} triage the new issues; merge when green",
        "/shipmill:github-issue-triage {repo} Merge  When\tGreen",
        "/shipmill:github-issue-triage {repo} triage and land",
        "/shipmill:github-issue-triage {repo} LAND the green ones, then tag 2.4.0",
        "/shipmill:github-issue-triage {repo} land.",
    ],
)
def test_s040_6_a_prompt_that_merges_when_green_or_lands_reads_land_as_act(prompt: str) -> None:
    autonomy = parsed(agents(prompt))
    assert autonomy.configured(LAND) is Autonomy.ACT
    assert autonomy.is_read_from_prompt(LAND)
    assert (autonomy.triage, autonomy.fix) == (Autonomy.ACT, Autonomy.ACT)  # only land is read
    rows = {r.stage: r for r in autonomy.levels(Hold())}
    assert (rows["land"].configured, rows["land"].effective, rows["land"].source.value) == ("act", "act", "prompt")
    assert rows["triage"].source.value == "default"


@pytest.mark.parametrize(
    "prompt",
    [
        "/shipmill:github-issue-triage {repo} triage the new issues; do not merge",
        "/shipmill:github-issue-triage {repo} triage the new issues",
        "/shipmill:github-issue-triage {repo} keep landing pages; the landed fix; island; it lands",
        "/shipmill:github-issue-triage {repo} merge when CI is green",
    ],
)
def test_s040_6_other_words_read_no_stage_from_the_prompt(prompt: str) -> None:
    autonomy = parsed(agents(prompt))
    assert autonomy.configured(LAND) is Autonomy.PROPOSE
    assert not autonomy.from_prompt
    assert {r.stage: r.source.value for r in autonomy.levels(Hold())}["land"] == "default"


def test_s040_6_the_match_is_literal_so_a_negated_land_reads_act_too() -> None:
    # recorded as a decision for the maintainer: the spec's words, "land" in the prompt, read literally
    assert lands("do not land")


@pytest.mark.parametrize("key", ["triage", "fix", "land"])
def test_s040_6_a_config_that_sets_any_agent_stage_reads_nothing_from_the_prompt(key: str) -> None:
    level = "observe" if key == "land" else "act"
    autonomy = parsed(agents("triage {repo}; merge when green") + f'\n[autonomy]\n{key} = "{level}"\n')
    assert autonomy.land is (Autonomy.OBSERVE if key == "land" else Autonomy.PROPOSE)
    assert not autonomy.from_prompt


def test_s040_6_a_config_without_agents_reads_no_prompt() -> None:
    autonomy = parsed("")
    assert autonomy.land is Autonomy.PROPOSE and not autonomy.from_prompt


def test_s040_6_the_hold_lowers_a_prompt_read_act_and_shows_source_hold() -> None:
    autonomy = parsed(agents("triage {repo}; merge when green"))
    assert autonomy.effective(LAND, HELD) is Autonomy.PROPOSE
    row = {r.stage: r for r in autonomy.levels(HELD)}["land"]
    assert (row.configured, row.effective, row.source.value) == ("act", "propose", "hold")


def test_s040_6_autonomy_command_and_decide_levels_read_the_prompt(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + agents("/shipmill:github-issue-triage {repo} merge when green"))
    assert main(["--repo", str(repo.root), "autonomy", "--json"], github=repo.github) == 0
    stages = {s["stage"]: s for s in json.loads(capsys.readouterr().out)["stages"]}
    assert stages["land"] == {"stage": "land", "configured": "act", "effective": "act", "source": "prompt"}
    assert main(["--repo", str(repo.root), "decide", "levels", "--json"]) == 0
    zones = {z["zone"]: z for z in json.loads(capsys.readouterr().out)["zones"]}
    assert (zones["land"]["level"], zones["land"]["source"]) == ("act", "autonomy")


def test_s040_6_doctor_warns_for_a_stage_read_from_the_prompt_naming_the_line(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + agents("/shipmill:github-issue-triage {repo} merge when green"))
    found = [(c.status, c.detail) for c in doctor(repo.root, repo.github) if c.name == "autonomy"]
    assert found[0][0] == "PASS" and "land act in agent sessions" in found[0][1]
    assert found[1:] == [
        (
            "WARN",
            'land reads act from [agents] prompt ("merge when green" or "land"), which nothing checks: add'
            f' land = "act" to [autonomy], or run `{cli_command()} upgrade --apply agent-autonomy`',
        )
    ]
    repo.write(repo.policy_file, POLICY + agents("triage {repo}; merge when green") + '\n[autonomy]\nland = "act"\n')
    assert [c.status for c in doctor(repo.root, repo.github) if c.name == "autonomy"] == ["PASS"]


# -- [agents] prs, deprecated (S-040-9) ------------------------------------------------------


@pytest.mark.parametrize(("value", "land"), [("true", "propose"), ("false", "propose"), ("true", "observe")])
def test_s040_9_prs_in_the_config_makes_doctor_warn_naming_autonomy_land(repo: Repo, value: str, land: str) -> None:
    text = POLICY + agents("triage {repo}") + f"prs = {value}\n" + f'\n[autonomy]\nland = "{land}"\n'
    repo.write(repo.policy_file, text)
    found = [(c.status, c.detail) for c in doctor(repo.root, repo.github) if c.name == "autonomy"]
    assert found[1:] == [
        (
            "WARN",
            f"[agents] prs is deprecated and ignored: [autonomy] land ({land}) decides whether the gate works on"
            " open pull requests, under propose or act, not under observe; delete prs",
        )
    ]
    repo.write(repo.policy_file, POLICY + agents("triage {repo}") + f'\n[autonomy]\nland = "{land}"\n')
    assert [c.status for c in doctor(repo.root, repo.github) if c.name == "autonomy"] == ["PASS"]


def test_s040_9_prs_is_accepted_and_ignored() -> None:
    policy = Policy.parse(tomllib.loads(POLICY + agents("triage {repo}") + "prs = true\n"), "shipmill.toml")
    assert policy.agents is not None and policy.agents.prs is True
    assert policy.agents.autonomy == policy.autonomy  # the gate reads the levels doctor and status read


@pytest.mark.parametrize("value", ["true", "false"])
def test_d59_a_config_from_before_spec_040_keeps_loading_and_landing(tmp_path: Path, value: str) -> None:
    # a connected repo that never took the agent-autonomy upgrade: prs set, the levels in the prompt
    write(tmp_path, POLICY + agents("/shipmill:github-issue-triage {repo} merge when green") + f"prs = {value}\n")
    loaded = AgentsConfig.load(tmp_path)
    assert loaded.autonomy.configured(LAND) is Autonomy.ACT
    assert loaded.autonomy.is_read_from_prompt(LAND)


# -- the agent-autonomy upgrade (S-040-7) ----------------------------------------------------


def listed(root: Path, capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    assert main(["--repo", str(root), "upgrade", "--json"], github=FakeGitHub()) == 0
    found: list[dict[str, Any]] = json.loads(capsys.readouterr().out)
    return found


def test_s040_7_upgrade_lists_agent_autonomy_for_a_config_without_the_three_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, FRAGMENTS + agents("triage {repo}; merge when green"))
    [record] = listed(tmp_path, capsys)
    assert record["id"] == "agent-autonomy" and record["table"] == "autonomy"
    assert record["lines"] == ['triage = "act"', 'fix = "act"', 'land = "act"']  # the legacy reading's values
    write(tmp_path, FRAGMENTS + agents("triage {repo}") + '\n[autonomy]\nrelease = "act"\n')
    [record] = listed(tmp_path, capsys)
    assert record["lines"] == ['triage = "act"', 'fix = "act"', 'land = "propose"']
    for key in ("triage", "fix", "land"):  # any of the three keys decides it
        write(tmp_path, FRAGMENTS + agents("triage {repo}") + f'\n[autonomy]\n{key} = "observe"\n')
        assert listed(tmp_path, capsys) == [], key
    write(tmp_path, FRAGMENTS)  # no [agents]: nothing reads the agent stages, so nothing to propose
    assert listed(tmp_path, capsys) == []


def test_s040_7_upgrade_text_lists_each_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path, FRAGMENTS + agents("triage {repo}; land"))
    assert main(["--repo", str(tmp_path), "upgrade"], github=FakeGitHub()) == 0
    out = capsys.readouterr().out
    assert out.startswith("agent-autonomy (shipmill 0.78.0): ")  # the release that adds it, not 0.77.0
    assert '  adds: [autonomy] triage = "act"\n  adds: [autonomy] fix = "act"\n  adds: [autonomy] land = "act"\n' in out


ODD = (
    "# the release policy  (two spaces, kept)\r\n"
    + FRAGMENTS.replace("\n", "\r\n").replace('name = "demo"', 'name   =   "demo"   # odd spacing')
    + "\r\n[autonomy]   # how far shipmill goes\r\n"
    + 'release = "propose"  # a person releases\r\n'
    + "deploy.production   = 'act'\r\n"
    + "# a comment about [agents], left above it\r\n"
    + "\r\n[agents]\r\n"
    + 'prompt = """\r\n/shipmill:github-issue-triage {repo}\r\n[autonomy]\r\nmerge when green"""\r\n'
)


def test_s040_7_apply_writes_the_three_keys_and_keeps_every_other_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    environment = "\r\n[environments.production]\r\nlane = 'stable'\r\nworkflow = 'd.yml'\r\n"
    text = ODD.replace("\r\n[agents]\r\n", environment + "\r\n[agents]\r\n", 1)
    path = write(tmp_path, text)
    assert main(["--repo", str(tmp_path), "upgrade", "--apply", "agent-autonomy", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["lines"] == ['triage = "act"', 'fix = "act"', 'land = "act"']
    after = path.read_bytes().decode("utf-8")
    added = 'triage = "act"\r\nfix = "act"\r\nland = "act"\r\n'
    anchor = "deploy.production   = 'act'\r\n"
    assert after == text.replace(anchor, anchor + added, 1)  # after the table's last line, the comment below it kept
    autonomy = Policy.parse(tomllib.loads(after), "shipmill.toml").autonomy
    assert (autonomy.triage, autonomy.fix, autonomy.land) == (Autonomy.ACT, Autonomy.ACT, Autonomy.ACT)
    assert not autonomy.from_prompt  # the keys now say it, so the prompt is read no more
    with pytest.raises(ReleaseError, match="agent-autonomy is already decided"):
        main(["--repo", str(tmp_path), "upgrade", "--apply", "agent-autonomy"])


def test_s040_7_apply_creates_autonomy_at_the_end_when_the_file_has_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = FRAGMENTS + agents("triage {repo}; do not merge").rstrip("\n")  # no newline at the end of the file
    path = write(tmp_path, text)
    assert main(["--repo", str(tmp_path), "upgrade", "--apply", "agent-autonomy"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == [
        f"added {line} to [autonomy] in {CONFIG_PATH}" for line in ('triage = "act"', 'fix = "act"', 'land = "propose"')
    ]
    assert path.read_bytes().decode("utf-8") == (
        text + '\n\n[autonomy]\ntriage = "act"\nfix = "act"\nland = "propose"\n'
    )


def test_s040_7_apply_adds_autonomy_beside_a_sub_table_only(tmp_path: Path) -> None:
    environments = "\n[environments.production]\nlane = 'stable'\nworkflow = 'd.yml'\n"
    text = FRAGMENTS + environments + "\n[autonomy.deploy]\nproduction = 'propose'\n" + agents("triage {repo}")
    path = write(tmp_path, text)
    assert main(["--repo", str(tmp_path), "upgrade", "--apply", "agent-autonomy"]) == 0
    after = path.read_bytes().decode("utf-8")
    assert after == text + '\n[autonomy]\ntriage = "act"\nfix = "act"\nland = "propose"\n'
    assert Policy.parse(tomllib.loads(after), "x").autonomy.deploy  # the deploy level is kept


def test_s040_7_apply_refuses_a_config_without_agents(tmp_path: Path) -> None:
    write(tmp_path, FRAGMENTS)
    with pytest.raises(ReleaseError, match=r"agent-autonomy doesn't apply: \.github/shipmill\.toml has no \[agents\]"):
        main(["--repo", str(tmp_path), "upgrade", "--apply", "agent-autonomy"])


def test_s040_7_a_decided_issue_closes_naming_the_key_the_config_sets() -> None:
    upgrade = find(UpgradeId("agent-autonomy"))
    github = FakeGitHub()
    number = github.create_issue(title(upgrade), body(upgrade), (UPGRADE_LABEL,))
    raw = tomllib.loads(FRAGMENTS + agents("triage {repo}") + '\n[autonomy]\nland = "propose"\n')
    assert [p.issue for p in propose(raw, Autonomy.PROPOSE, github, "")] == [number]
    assert github.closed[number] == (
        "`[autonomy]` in `.github/shipmill.toml` sets `land`: agent-autonomy is decided, so this issue is done."
    )


def test_s040_7_the_issue_body_carries_the_configs_values() -> None:
    upgrade = find(UpgradeId("agent-autonomy"))
    raw = tomllib.loads(FRAGMENTS + agents("triage {repo}; merge when green"))
    text = body(upgrade, raw)
    assert '```toml\n[autonomy]\ntriage = "act"\nfix = "act"\nland = "act"\n```' in text
    assert "It adds these lines under `[autonomy]` (the table too, when the file has none)" in text
    assert "sets any of `triage`, `fix`, `land`, to any value" in text
