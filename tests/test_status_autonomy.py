"""Spec 040: `shipmill status` shows every stage's level, and reads the open pull requests by
[autonomy] land"""

import json
import subprocess
from pathlib import Path

import pytest

from shipmill.autonomy import Autonomy, AutonomyPolicy, EnvironmentName
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.status import Pull, Row, Verdict, read_autonomy, read_pulls, report
from tests.test_status_picture import (
    AGENTS,
    AUTONOMY,
    OBSERVE,
    REPO,
    URL,
    Fake,
    facts,
    gate,
    host,
    lines,
    repo_with_release,
)

FIX = "                 fix: "
HOLD = Row("HOLD", "#3", "freeze; opened by @a", False, f"gh issue close 3 -R {REPO}")
OPEN = Row("PRS_OPEN", REPO, "#408 #409", False)
MERGE = (
    'merge each pull request named once you have read it, or set land = "act" in [autonomy] in .github/shipmill.toml'
)


def autonomy_line(found: list[str]) -> int:
    (at,) = [i for i, line in enumerate(found) if line.startswith("  autonomy ")]
    return at


def test_s040_10_the_autonomy_line_follows_the_repo_line_with_every_stage() -> None:
    text = lines(facts())
    assert text[1].startswith("  repo ")
    assert text[2] == AUTONOMY
    deploy = AutonomyPolicy(
        triage=Autonomy.PROPOSE, deploy={EnvironmentName("production"): Autonomy.PROPOSE}, explicit=frozenset()
    )
    shown = lines(facts(autonomy=deploy, environments=(EnvironmentName("staging"),)))
    assert shown[2] == (
        "  autonomy       triage propose · fix act · land propose · release act · deploy.production propose"
        " · deploy.staging act · rollback act · intake propose · upgrade propose"
    )
    assert not shown[3].startswith(FIX)  # the autonomy line carries no fix


def test_s040_10_a_held_stage_says_so_and_the_hold_line_keeps_its_fix() -> None:
    text = lines(facts(HOLD))
    assert text[2] == (
        "  autonomy       triage propose (held) · fix propose (held) · land propose · release propose (held)"
        " · rollback propose (held) · intake propose · upgrade propose"
    )
    at = text.index(f"  hold           #3 {URL}/issues/3")
    assert text[at + 1] == f"{FIX}gh issue close 3 -R {REPO}"


def test_s040_6_status_marks_no_stage_from_the_prompt_and_brings_no_upgrade_fix(tmp_path: Path) -> None:
    # the legacy reading's window closed (#735): a prompt that merges when green reads land at its default
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "shipmill.toml").write_text(
        '[agents]\nprompt = "triage, then merge when green"\n', encoding="utf-8"
    )
    policy, _ = read_autonomy(tmp_path)
    assert policy == AutonomyPolicy()
    for found in (lines(facts(autonomy=policy)), lines(facts(HOLD, autonomy=policy))):
        at = autonomy_line(found)
        assert "prompt" not in found[at] and " · land propose · " in found[at]
        assert not found[at + 1].startswith(FIX)


def test_s040_10_status_reads_the_checkouts_autonomy(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    config = tmp_path / ".github" / "shipmill.toml"
    assert read_autonomy(tmp_path) == (AutonomyPolicy(), ())  # no config: every default
    config.write_text(
        '[agents]\nprompt = "merge when green"\n[autonomy]\nland = "observe"\n'
        '[environments.production]\nlane = "stable"\n',
        encoding="utf-8",
    )
    set_, environments = read_autonomy(tmp_path)
    assert (set_.land, environments) == (Autonomy.OBSERVE, (EnvironmentName("production"),))
    config.write_text('[autonomy]\nland = "merge"\n', encoding="utf-8")
    with pytest.raises(ReleaseError, match="land must be one of"):
        read_autonomy(tmp_path)


@pytest.mark.parametrize(
    ("toml", "error"),
    [
        ('[autonomy]\ndeploy.production = "act"\n', "deploy.production names no environment in"),
        ('[autonomy]\ndeploy.production = "act"\n[environments]\nproduction = 1\n', "production must be a table"),
        ('environments = "production"\n', "environments must be a table"),
    ],
)
def test_s040_10_status_refuses_environments_shipmill_autonomy_refuses(tmp_path: Path, toml: str, error: str) -> None:
    # the CLI's run() turns a ReleaseError into exit 2, before watch_state.py runs
    root = repo_with_release(tmp_path / "repo")
    (root / ".github").mkdir()
    (root / ".github" / "shipmill.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(ReleaseError, match=error):
        read_autonomy(root)
    fake = Fake(0)
    for shown in (["--json"], []):
        with pytest.raises(ReleaseError, match=error):
            main(["--repo", str(root), "status", *shown], state=fake, login=host)
    assert fake.seen == []


class Held(Fake):
    """watch_state.py with an open hold among its rows"""

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[1].endswith("watch_state.py") and "--json" in cmd:
            self.seen.append(cmd)
            held = {"state": "HOLD", "subject": "#3", "detail": "freeze", "agent": False, "fix": "gh issue close 3"}
            return subprocess.CompletedProcess(cmd, self.code, json.dumps(held) + "\n", "")
        return super().__call__(cmd)


def test_s040_10_json_carries_the_same_stages_after_watch_states_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo_with_release(tmp_path / "repo")
    (root / ".github").mkdir()
    (root / ".github" / "shipmill.toml").write_text(
        '[agents]\nprompt = "land them"\n[autonomy]\nland = "act"\n', encoding="utf-8"
    )
    fake = Held(0)
    assert main(["--repo", str(root), "status", "--json"], state=fake, login=host) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert printed[0]["state"] == "HOLD"  # watch_state.py's lines first, as they were
    last = printed[-1]
    assert (last["state"], last["subject"], last["agent"]) == ("AUTONOMY", REPO, False)
    stages = {s["stage"]: s for s in last["autonomy"]}
    assert list(stages) == ["triage", "fix", "land", "release", "rollback", "intake", "upgrade"]
    assert stages["land"] == {"stage": "land", "configured": "act", "effective": "propose", "source": "hold"}
    assert stages["fix"] == {"stage": "fix", "configured": "act", "effective": "propose", "source": "hold"}
    assert stages["intake"]["source"] == "default"
    assert "land propose (held)" in last["detail"] and "prompt" not in last["detail"]
    assert last.get("fix") is None
    assert len(fake.seen) == 1  # the hold comes from watch_state.py's rows: no read of its own


def test_s040_11_under_observe_open_pull_requests_wait_on_you_with_the_land_fix() -> None:
    found = facts(OPEN, autonomy=OBSERVE)
    done = report(found)
    assert done.verdict is Verdict.WAITS
    fix = f'set land = "propose" or "act" in [autonomy], or land them by hand: /shipmill:github-pr-triage {REPO}'
    assert [(r.text, r.fix) for r in done.reasons] == [
        ("pull request #409 #408 wait to land: [autonomy] land is observe, so no session lands them", fix)
    ]
    text = lines(found)
    assert f"{FIX}{fix}" in text


def test_s040_11_under_propose_the_ready_ones_wait_on_you_to_merge_and_the_rest_are_the_gates() -> None:
    pulls = [Pull(409, False, "CLEAN", "main", ready=True), Pull(408, False, "CLEAN", "main")]
    found = facts(OPEN, pulls=pulls)
    done = report(found)
    assert done.verdict is Verdict.WAITS
    assert [(r.text, r.fix) for r in done.reasons] == [
        ("pull request #409 labelled shipmill-ready wait on you to merge", MERGE)
    ]
    text = lines(found)
    at = text.index(f"  to land        #408 {URL}/pull/408")
    assert text[at + 1 : at + 3] == [f"  to merge       #409 {URL}/pull/409", f"{FIX}{MERGE}"]
    # none labelled: all the gate's work, and a repo without the label reads the same
    plain = report(facts(OPEN, pulls=[Pull(409, False, "CLEAN", "main")]))
    assert (plain.verdict, plain.working) == (Verdict.WORKING, ["pull request #409 #408 to land"])
    assert report(facts(OPEN, gate=gate(agents=AGENTS))).verdict is Verdict.WORKING


def test_s040_11_under_act_every_open_pull_request_is_the_gates_work() -> None:
    pulls = [Pull(409, False, "CLEAN", "main", ready=True)]
    found = facts(OPEN, pulls=pulls, autonomy=AutonomyPolicy(land=Autonomy.ACT), gate=gate(agents=AGENTS))
    done = report(found)
    assert (done.verdict, done.reasons, done.working) == (Verdict.WORKING, [], ["pull request #409 #408 to land"])
    assert not any(line.startswith("  to merge") for line in lines(found))
    # under a hold, act lowers to propose: the ready one is yours to merge
    held = report(facts(HOLD, OPEN, pulls=pulls, autonomy=AutonomyPolicy(land=Autonomy.ACT)))
    assert "pull request #409 labelled shipmill-ready wait on you to merge" in [r.text for r in held.reasons]
    assert "  landing        propose (held): the gate reviews and labels shipmill-ready, a person merges" in lines(
        facts(HOLD, autonomy=AutonomyPolicy(land=Autonomy.ACT), gate=gate(agents=AGENTS))
    )


def test_s040_11_the_ready_label_comes_from_the_one_pull_request_read() -> None:
    seen: list[list[str]] = []

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        out = [
            {"number": 9, "isDraft": False, "mergeStateStatus": "CLEAN", "baseRefName": "main", "labels": []},
            {
                "number": 8,
                "isDraft": False,
                "mergeStateStatus": "CLEAN",
                "baseRefName": "main",
                "labels": [{"id": "x", "name": "shipmill-ready", "description": "", "color": "0e8a16"}],
            },
        ]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    assert [p.ready for p in read_pulls(REPO, run)] == [False, True]
    assert len(seen) == 1
