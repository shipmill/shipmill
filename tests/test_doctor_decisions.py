"""Spec 030: doctor's decisions block, for a config with [agents]; without [agents], one WARN
when [decisions] is set, as nothing reads it then"""

from shipmill import cli_command
from shipmill.config import CONFIG_PATH
from shipmill.decide import Zone
from shipmill.doctor import Check, doctor
from shipmill.errors import ReleaseError

from .conftest import FakeGitHub, Repo

AGENTS = '\n[agents]\nprompt = "/t"\n'
APP = '\n[agents]\nprompt = "/t"\napp_id = 7\n'


def configure(repo: Repo, text: str) -> None:
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + text)


def block(repo: Repo, github: FakeGitHub | None = None) -> list[Check]:
    return [c for c in doctor(repo.root, github or repo.github) if c.name == "decisions"]


def test_s030_19_one_pass_line_per_zone_with_its_level_and_source(repo: Repo) -> None:
    configure(repo, APP + '\n[decisions]\ntriage-verdict = "ask"\n')
    repo.github.repo_labels = {"decided"}
    found = block(repo)
    assert found[0] == Check(
        "PASS", "decisions", "veto_hours 24 (default): the maintainer may veto a notify decision for 24 hours"
    )
    zones = [c for c in found if c.detail.split(" ")[0] in set(Zone)]
    assert [c.detail.split(" ")[0] for c in zones] == [z.value for z in Zone]  # every zone, at its default too
    assert {c.status for c in zones} == {"PASS"}
    details = {c.detail for c in zones}
    assert "triage-verdict ask (config)" in details
    assert "implementation act (default)" in details
    assert "direction never (default)" in details
    assert "decision-policy never (fixed)" in details
    assert found[-1] == Check("PASS", "decisions", "the decided label exists")
    assert [c for c in found if c.status != "PASS"] == []  # raised above its default, an App, the label
    assert repo.github.label_reads == 1


def test_s030_19_a_zone_below_its_default_warns_naming_both_levels(repo: Repo) -> None:
    configure(repo, APP + '\n[decisions]\nveto_hours = 48\ncontract-addition = "act"\nprotected = "notify"\n')
    repo.github.repo_labels = {"decided"}
    found = block(repo)
    assert found[0].detail.startswith("veto_hours 48 (config)")
    warned = [c.detail for c in found if c.status == "WARN"]
    assert warned == [
        '[decisions] contract-addition = "act" is below its default notify, so agents involve you less there'
        " than shipmill ships; delete the key to restore the default",
        '[decisions] protected = "notify" is below its default ask, so agents involve you less there'
        " than shipmill ships; delete the key to restore the default",
    ]
    assert Check("PASS", "decisions", "contract-addition act (config)") in found  # the zone's PASS line stays


def test_s030_19_an_unset_app_id_warns_pointing_at_the_hooks_line(repo: Repo) -> None:
    configure(repo, AGENTS)
    repo.github.repo_labels = {"decided"}
    checks = doctor(repo.root, repo.github)
    off = "app-writes: off (no [agents] app_id), so gh writes go as your own login"
    assert Check("PASS", "hooks", off) in checks  # the existing line, which the WARN refers to
    (warned,) = [c for c in checks if c.name == "decisions" and c.status == "WARN"]
    assert warned.detail == (
        "no [agents] app_id (hooks: app-writes off), so a never zone holds by the skills and pr_gate.py only:"
        f" `{cli_command()} gh` refuses its merge only as the App (D-40); connect one with shipmill-setup's"
        " step 3 (app-create)"
    )


def test_s030_19_a_missing_decided_label_warns_with_the_fix(repo: Repo) -> None:
    configure(repo, APP)
    repo.github.repo_labels = {"needs-decision"}
    found = block(repo)
    assert found[-1] == Check(
        "WARN",
        "decisions",
        "no decided label, which a notify decision adds with its decided comment: create it with"
        f" `{cli_command()} gh label create decided`, or run shipmill-setup's setup_state.py --fix",
    )
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)).replace("app_id = 7\n", ""))
    assert "`gh label create decided`" in block(repo)[-1].detail  # no App: the person's gh


class Unreadable(FakeGitHub):
    def label_names(self) -> frozenset[str]:
        raise ReleaseError("gh label list failed: HTTP 401: Bad credentials")


def test_s030_19_a_failed_label_read_warns(repo: Repo) -> None:
    configure(repo, APP)
    assert block(repo, Unreadable())[-1] == Check(
        "WARN", "decisions", "can't read the labels for decided: gh label list failed: HTTP 401: Bad credentials"
    )
    assert [c for c in doctor(repo.root, None) if c.name == "decisions"][-1] == Check(
        "WARN", "decisions", "can't read the labels for decided: gh isn't installed"
    )


def test_s030_19_decisions_without_agents_warns_that_nothing_reads_it(repo: Repo) -> None:
    configure(repo, '\n[decisions]\ntriage-verdict = "ask"\n')
    assert block(repo) == [
        Check(
            "WARN",
            "decisions",
            "[decisions] is set, but nothing reads it without [agents]: the levels apply to agent sessions only;"
            " add [agents] or delete [decisions]",
        )
    ]
    assert repo.github.label_reads == 0


def test_s030_19_no_agents_and_no_decisions_print_no_block(repo: Repo) -> None:
    # D-9: a release-only repo sees no decisions line and no decided label WARN
    assert block(repo) == []
    assert repo.github.label_reads == 0
