"""Spec 031: `[agents] plugin_update`, deprecated and ignored in 0.60.0 (S-031-21), is refused
since (S-031-22, D-32, D-44), and the docs describe the pinned release without a gate paused
on a stale plugin"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from shipmill.agents import PLUGIN_UPDATE_REMOVED, AgentsConfig, app_id_of
from shipmill.cli import main
from shipmill.doctor import Check, doctor
from shipmill.errors import ReleaseError

from .conftest import POLICY, Repo

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/shipmill:github-issue-triage {repo} triage the new issues"\n'
REMOVED = "[agents] plugin_update was removed (spec 031); delete it"
VALUES = ["true", "false", '"yes"', "1"]  # either bool, and a value of the wrong type too


def test_s031_22_the_message_names_the_key_and_spec_031() -> None:
    assert PLUGIN_UPDATE_REMOVED == REMOVED  # the spec's text


@pytest.mark.parametrize("value", VALUES)
def test_s031_22_every_reader_of_agents_refuses_the_key(repo: Repo, value: str) -> None:
    # the policy (plan, doctor, status, watch), the gate's and launchd's [agents] alone, and app_id_of
    repo.write(repo.policy_file, POLICY + AGENTS + f"plugin_update = {value}\n")
    for read in (lambda: AgentsConfig.load(repo.root), lambda: app_id_of(repo.root)):
        with pytest.raises(ReleaseError) as caught:
            read()
        assert str(caught.value) == REMOVED
    with pytest.raises(ReleaseError) as caught:
        main(["--repo", str(repo.root), "plan"], github=repo.github)
    assert str(caught.value) == REMOVED


@pytest.mark.parametrize("value", ["true", "false"])
def test_s031_22_the_cli_exits_2_naming_the_key(repo: Repo, value: str) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + f"plugin_update = {value}\n")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(repo.root), "plan"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stderr) == (2, f"shipmill: {REMOVED}\n")


@pytest.mark.parametrize("value", ["true", "false"])
def test_s031_22_doctor_fails_the_policy_with_the_refusal_and_warns_no_deprecation(repo: Repo, value: str) -> None:
    # as doctor reports any config the policy refuses: one FAIL, the checks that need it skipped
    repo.write(repo.policy_file, POLICY + AGENTS + f"plugin_update = {value}\n")
    assert doctor(repo.root) == [Check("FAIL", "policy", REMOVED)]


def test_s031_22_a_config_without_the_key_reads_as_before(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS)
    assert AgentsConfig.load(repo.root).prompt.startswith("/shipmill:github-issue-triage")
    assert "plugin_update" not in {c.name for c in doctor(repo.root)}


def test_s031_22_shipmills_own_config_sets_no_plugin_update() -> None:
    AgentsConfig.load(ROOT)  # refused if it did


# -- S-031-23: the docs ----------------------------------------------------------------------

INSTALL = ROOT / "docs" / "install.md"
LANES = ROOT / "docs" / "release-lanes.md"
SETUP = ROOT / "skills" / "shipmill-setup" / "SKILL.md"
WATCH = ROOT / "skills" / "github-ship-watch" / "SKILL.md"
DOCS = (INSTALL, LANES, SETUP, WATCH)

# What each topic reads as, and the docs that carry it (spec 031's Docs section)
TOPICS = {
    "the pinned CLI": (r"uvx shipmill==(?:\d+\.\d+\.\d+|<version>)", (INSTALL, SETUP, WATCH)),
    "the marketplace serving releases": (r"marketplace[^.]*release tag", (INSTALL,)),
    "gate sessions loading the installed plugin": (r"load the installed plugin", (INSTALL, SETUP, WATCH)),
    "requires": (r'requires = ">=', (INSTALL, LANES)),
    # the deprecation's end: the docs say the key was removed and is refused (S-031-22)
    "the plugin_update deprecation": (r"plugin_update`? was removed", (INSTALL, LANES, SETUP, WATCH)),
}
# what a gate paused on a stale plugin reads as (D-35, superseded by D-44)
PAUSED = re.compile(r"PLUGIN_STALE|\bD-35\b|starts no session (?:while|until)|no session stops or starts until")


@pytest.mark.parametrize("topic", sorted(TOPICS))
def test_s031_23_the_docs_describe_the_pinned_release(topic: str) -> None:
    pattern, docs = TOPICS[topic]
    for doc in docs:
        text = " ".join(doc.read_text(encoding="utf-8").split())  # a phrase may wrap
        assert re.search(pattern, text), f"{doc.relative_to(ROOT)} doesn't describe {topic}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_s031_23_no_doc_describes_a_gate_paused_on_a_stale_plugin(doc: Path) -> None:
    text = " ".join(doc.read_text(encoding="utf-8").split())
    assert PAUSED.search(text) is None, PAUSED.search(text)
