"""Spec 031: `[agents] plugin_update`, deprecated and ignored in 0.60.0 (S-031-21), is refused
since: dropped on load, it turns nothing off (spec 052, D-64); and the docs describe the pinned
release without a gate paused on a stale plugin"""

import re
from pathlib import Path

import pytest

from shipmill.agents import PLUGIN_UPDATE_REMOVED, AgentsConfig, app_id_of
from shipmill.cli import main
from shipmill.doctor import doctor
from shipmill.refused import PLUGIN_UPDATE

from .conftest import POLICY, Repo

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/shipmill:github-issue-triage {repo} triage the new issues"\n'
REMOVED = "[agents] plugin_update was removed (spec 031); delete it"
VALUES = ["true", "false", '"yes"', "1"]  # either bool, and a value of the wrong type too


# S-031-22's exit 2 was dropped in #859: a config that sets the key loads, reads as without it,
# and says the refusal once on stderr (spec 052, tests/test_refused.py)


def test_the_refusal_keeps_spec_031s_words() -> None:
    assert PLUGIN_UPDATE_REMOVED == REMOVED  # the line the docs quote


@pytest.mark.parametrize("value", VALUES)
def test_every_reader_of_agents_drops_the_key(repo: Repo, value: str) -> None:
    # the policy (plan, doctor, status, watch), the gate's and launchd's [agents] alone, and app_id_of
    repo.write(repo.policy_file, POLICY + AGENTS + f"plugin_update = {value}\n")
    assert AgentsConfig.load(repo.root).refused == (PLUGIN_UPDATE,)
    assert app_id_of(repo.root) is None
    # environ={}: plan reads $GITHUB_EVENT_NAME, which CI sets to pull_request, not a plan event
    assert main(["--repo", str(repo.root), "plan"], github=repo.github, environ={}) == 0


def test_a_config_without_the_key_reads_as_before(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS)
    agents = AgentsConfig.load(repo.root)
    assert agents.prompt.startswith("/shipmill:github-issue-triage")
    assert agents.refused == ()
    assert "plugin_update" not in {c.name for c in doctor(repo.root)}


def test_shipmills_own_config_sets_no_plugin_update() -> None:
    assert AgentsConfig.load(ROOT).refused == ()


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
