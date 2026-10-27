"""Spec 040's migration: the legacy reading of [agents] prompt, whose one minor release is over
(S-040-6), `[agents] prs`, refused since (S-040-9), and the agent-autonomy upgrade that writes
the levels the prompt's words gave into [autonomy] (S-040-7)"""

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from shipmill.agents import PRS_REMOVED, AgentsConfig, app_id_of
from shipmill.autonomy import Autonomy, AutonomyPolicy, Hold, Source, Stage, StageKind
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, doctor
from shipmill.errors import ReleaseError
from shipmill.github import UPGRADE_LABEL
from shipmill.policy import Policy
from shipmill.upgrades import UpgradeId, body, find, lands, propose, title

from .conftest import POLICY, FakeGitHub, Repo
from .test_decide_cli import commit

ROOT = Path(__file__).resolve().parents[1]
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


# -- the legacy reading's window closed (S-040-6, #735) --------------------------------------

MERGES = [
    "/shipmill:github-issue-triage {repo} triage the new issues; merge when green",
    "/shipmill:github-issue-triage {repo} Merge  When\tGreen",
    "/shipmill:github-issue-triage {repo} triage and land",
    "/shipmill:github-issue-triage {repo} LAND the green ones, then tag 2.4.0",
    "/shipmill:github-issue-triage {repo} land.",
]


@pytest.mark.parametrize("prompt", MERGES)
def test_s040_6_a_prompt_that_merges_when_green_or_lands_reads_no_stage(prompt: str) -> None:
    # the one minor release 0.78.0 opened is over: an absent key takes its default, whatever the prompt says
    autonomy = parsed(agents(prompt))
    assert (autonomy.triage, autonomy.fix, autonomy.land) == (Autonomy.ACT, Autonomy.ACT, Autonomy.PROPOSE)
    rows = {r.stage: r for r in autonomy.levels(Hold())}
    assert (rows["land"].configured, rows["land"].effective, rows["land"].source.value) == (
        "propose",
        "propose",
        "default",
    )
    assert {r.source.value for r in autonomy.levels(HELD)} <= {"default", "hold"}


def test_s040_6_no_source_names_the_prompt() -> None:
    assert [s.value for s in Source] == ["default", "config", "hold"]


@pytest.mark.parametrize("key", ["triage", "fix", "land"])
def test_s040_6_a_config_that_sets_an_agent_stage_reads_the_key(key: str) -> None:
    autonomy = parsed(agents("triage {repo}; merge when green") + f'\n[autonomy]\n{key} = "observe"\n')
    assert autonomy.configured(Stage(StageKind(key))) is Autonomy.OBSERVE
    assert autonomy.land is (Autonomy.OBSERVE if key == "land" else Autonomy.PROPOSE)


def test_s040_6_the_agents_section_carries_the_configs_levels_not_the_prompts() -> None:
    policy = Policy.parse(tomllib.loads(POLICY + agents("triage {repo}; merge when green")), "shipmill.toml")
    assert policy.agents is not None and policy.agents.autonomy == policy.autonomy == AutonomyPolicy()


def test_s040_6_autonomy_command_and_decide_levels_read_no_prompt(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + agents("/shipmill:github-issue-triage {repo} merge when green"))
    assert main(["--repo", str(repo.root), "autonomy", "--json"], github=repo.github) == 0
    stages = {s["stage"]: s for s in json.loads(capsys.readouterr().out)["stages"]}
    assert stages["land"] == {"stage": "land", "configured": "propose", "effective": "propose", "source": "default"}
    assert main(["--repo", str(repo.root), "decide", "levels", "--json"]) == 0
    zones = {z["zone"]: z for z in json.loads(capsys.readouterr().out)["zones"]}
    assert (zones["land"]["level"], zones["land"]["source"]) == ("ask", "autonomy")  # propose maps to ask


def test_s040_6_doctor_warns_for_no_stage_from_the_prompt(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + agents("/shipmill:github-issue-triage {repo} merge when green"))
    found = [(c.status, c.detail) for c in doctor(repo.root, repo.github) if c.name == "autonomy"]
    assert [status for status, _ in found] == ["PASS"]
    assert "land propose in agent sessions" in found[0][1]


# -- [agents] prs, refused (S-040-9, #735) ---------------------------------------------------

PRS_REFUSED = (
    "[agents] prs was removed (spec 040): [autonomy] land decides whether the gate works on open pull requests;"
    " delete prs"
)


def test_s040_9_the_message_names_the_key_and_autonomy_land() -> None:
    assert PRS_REMOVED == PRS_REFUSED


@pytest.mark.parametrize("value", ["true", "false", '"yes"', "1"])
def test_s040_9_every_reader_of_agents_refuses_prs(repo: Repo, value: str) -> None:
    # the policy (plan, doctor, status, watch), the gate's [agents] alone, and app_id_of
    repo.write(repo.policy_file, POLICY + agents("triage {repo}") + f"prs = {value}\n")
    for read in (lambda: AgentsConfig.load(repo.root), lambda: app_id_of(repo.root)):
        with pytest.raises(ReleaseError) as caught:
            read()
        assert str(caught.value) == PRS_REFUSED
    with pytest.raises(ReleaseError) as caught:
        main(["--repo", str(repo.root), "plan"], github=repo.github)
    assert str(caught.value) == PRS_REFUSED


def test_s040_9_prs_is_refused_before_the_unknown_keys_error() -> None:
    text = POLICY + agents("triage {repo}") + "prs = true\nmerge = true\n"
    with pytest.raises(ReleaseError) as caught:
        Policy.parse(tomllib.loads(text), "shipmill.toml")
    assert str(caught.value) == PRS_REFUSED


@pytest.mark.parametrize("value", ["true", "false"])
def test_s040_9_the_cli_exits_2_naming_autonomy_land(repo: Repo, value: str) -> None:
    repo.write(repo.policy_file, POLICY + agents("triage {repo}") + f"prs = {value}\n")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(repo.root), "plan"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stderr) == (2, f"shipmill: {PRS_REFUSED}\n")


def test_s040_9_doctor_fails_the_policy_with_the_refusal(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + agents("triage {repo}") + 'prs = true\n\n[autonomy]\nland = "act"\n')
    assert doctor(repo.root) == [Check("FAIL", "policy", PRS_REFUSED)]


def test_s040_9_shipmills_own_config_sets_no_prs() -> None:
    AgentsConfig.load(ROOT)  # refused if it did
    assert "prs" not in tomllib.loads((ROOT / CONFIG_PATH).read_text("utf-8"))["agents"]


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


@pytest.mark.parametrize("prompt", MERGES)
def test_s040_7_the_upgrade_proposes_land_act_for_a_prompt_that_merged(prompt: str) -> None:
    # accepting it keeps a repo landing as it did while the prompt was read (#735)
    raw = tomllib.loads(FRAGMENTS + agents(prompt))
    assert '```toml\n[autonomy]\ntriage = "act"\nfix = "act"\nland = "act"\n```' in body(
        find(UpgradeId("agent-autonomy")), raw
    )


def test_s040_7_the_match_is_literal_so_a_negated_land_proposes_act_too() -> None:
    # the spec's words, "land" in the prompt, read literally; "landing", "lands", "island" are not "land"
    assert lands("do not land")
    assert not lands("keep landing pages; the landed fix; island; it lands; merge when CI is green")


def test_s040_7_the_upgrade_promises_no_later_cut_off() -> None:
    upgrade = find(UpgradeId("agent-autonomy"))
    text = " ".join((upgrade.changes, upgrade.why, upgrade.declined))
    assert "next minor" not in text and "Until" not in text
    assert "takes its default" in text


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
