"""Spec 031: `[agents] plugin_update` is deprecated for one minor release (D-32, D-44), and the
docs describe the pinned release without a gate paused on a stale plugin"""

import re
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.doctor import PLUGIN_UPDATE_DEPRECATED, Check, doctor

from .conftest import POLICY, Repo

ROOT = Path(__file__).resolve().parents[1]
AGENTS = '\n[agents]\nprompt = "/shipmill:github-issue-triage {repo} triage the new issues"\n'


@pytest.mark.parametrize("value", ["true", "false"])
def test_s031_21_doctor_warns_naming_the_key_the_spec_and_the_next_minor_refusing_it(repo: Repo, value: str) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS + f"plugin_update = {value}\n")
    found = [c for c in doctor(repo.root) if c.name == "plugin_update"]
    assert found == [Check("WARN", "plugin_update", PLUGIN_UPDATE_DEPRECATED)]
    assert "[agents] plugin_update is deprecated (spec 031)" in found[0].detail
    assert "the next minor release refuses" in found[0].detail


def test_s031_21_doctor_says_nothing_without_the_key(repo: Repo) -> None:
    repo.write(repo.policy_file, POLICY + AGENTS)
    assert "plugin_update" not in {c.name for c in doctor(repo.root)}


def test_s031_21_the_warning_alone_never_fails_doctor(repo: Repo) -> None:
    no_claude = {"PATH": ""}  # no hook self-test against this host's real install
    repo.write(repo.policy_file, POLICY + AGENTS)
    without = main(["--repo", str(repo.root), "doctor"], github=repo.github, environ=no_claude)
    repo.write(repo.policy_file, POLICY + AGENTS + "plugin_update = true\n")
    assert main(["--repo", str(repo.root), "doctor"], github=repo.github, environ=no_claude) == without


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
    "the plugin_update deprecation": (r"plugin_update`? is deprecated", (INSTALL, LANES, SETUP, WATCH)),
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
