"""Spec 026, Docs: the skills and the install docs name the delivery hooks, and the headless
allowlist points to them"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def folded(*parts: str) -> str:
    """A doc with its line wrapping folded, so a statement reads as one line"""
    return " ".join(ROOT.joinpath(*parts).read_text(encoding="utf-8").split())


def section(text: str, start: str, end: str) -> str:
    assert text.count(start) == 1, start
    return text.split(start, 1)[1].split(end, 1)[0]


def test_s026_18_pr_triage_rule_8_says_the_hook_refuses_a_plain_gh_write() -> None:
    rule = section(folded("skills", "github-pr-triage", "SKILL.md"), "8. **Write as the App", " ## ")
    assert "the plugin's delivery hook refuses a plain `gh` write while `app_id` is set" in rule
    assert "`GH_TOKEN=... gh`" in rule
    assert "(spec 026)" in rule


def test_s026_18_landing_says_the_hook_refuses_a_rebase_merge_and_an_unpinned_force_push() -> None:
    text = folded("skills", "github-pr-triage", "references", "landing.md")
    merge = section(text, "## Merge style", " ## ")
    assert "the plugin's delivery hook refuses a rebase merge" in merge
    assert "`merge_method=rebase`" in merge and "`--squash`" in merge
    fix = section(text, "## Getting a fix onto a PR", " ## ")
    assert "the plugin's delivery hook refuses a force push without a lease pinned to a commit" in fix
    assert "`:<sha>`" in fix


def test_s026_18_setup_says_the_hooks_come_with_the_plugin_asks_for_private_paths_and_reads_doctor() -> None:
    text = folded("skills", "shipmill-setup", "SKILL.md")
    for phrase in (
        "The delivery hooks come with the plugin (spec 026)",
        "Ask whether the repo has paths whose files must never leave it",
        "`[hooks] private`",
        "`[hooks] default_branch = false`",
        "Before you report the agent side connected, run `$CR doctor` and read its `hooks` block",
    ):
        assert phrase in text, phrase


def test_s026_18_release_lanes_documents_the_hooks_keys_next_to_agents() -> None:
    text = folded("docs", "release-lanes.md")
    hooks = section(text, "## Delivery hooks", " ## ")
    assert "```toml [hooks] default_branch = true" in hooks
    assert 'private = ["owner/**"]' in hooks
    assert "`default_branch` is a boolean, default true" in hooks
    assert "`private` is a list of globs, default empty" in hooks
    # next to [agents]: right after the [agents] wip section
    assert text.index("## Work in progress") < text.index("## Delivery hooks") < text.index("## Notices on fixed")


@pytest.mark.parametrize(
    "phrase",
    [
        "The delivery hooks come with the plugin (spec 026)",
        "They need `uv` on your `PATH`",
        "`$CR doctor` tests them",
        # the failure case as spec 026 (PR #465) words it: exit 1, the command runs
        "`shipmill hook: can't start hooks/delivery.py (<the reason>);"
        " this command runs unchecked, see shipmill doctor` and exits 1",
    ],
)
def test_s026_18_install_says_the_hooks_come_with_the_plugin_need_uv_and_doctor_tests_them(phrase: str) -> None:
    assert phrase in folded("docs", "install.md")


def test_s026_18_a_comment_above_headless_tools_points_to_the_hooks() -> None:
    lines = (ROOT / "src" / "shipmill" / "gate.py").read_text(encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("HEADLESS_TOOLS = ("))
    above: list[str] = []
    for line in reversed(lines[:at]):
        if not line.startswith("#"):
            break
        above.append(line)
    assert any("hooks/delivery.py" in line for line in above)
