"""S-054-19: the docs say how to land as the App on a protected default branch (spec 054)"""

import re
from pathlib import Path

from shipmill.landing import ENVIRONMENT, SECRET
from shipmill.ruleset import RELEASE_BRANCHES

ROOT = Path(__file__).parent.parent
LANES = ROOT / "docs" / "release-lanes.md"
HEADING = "Protected default branch"


def folded(path: Path) -> str:
    """A file with its line wrapping folded, so a statement reads as one line"""
    return " ".join(path.read_text(encoding="utf-8").split())


def section(text: str, heading: str) -> str:
    """The text under a `## ` heading, up to the next `## ` heading or the end"""
    found = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert found is not None, f"docs/release-lanes.md has no {heading} section"
    return " ".join(found.group(1).split())


def test_s054_19_land_points_at_the_section_by_its_heading() -> None:
    land = (ROOT / "src" / "shipmill" / "land.py").read_text(encoding="utf-8")
    assert f"see {HEADING}" in land
    assert re.search(rf"^## {HEADING}$", LANES.read_text(encoding="utf-8"), re.MULTILINE)


def test_s054_19_the_section_covers_the_opt_in_the_environment_and_its_secret() -> None:
    text = section(LANES.read_text(encoding="utf-8"), HEADING)
    assert "`[agents] app_id`" in text
    assert f"`land-environment: {ENVIRONMENT}`" in text
    assert "`shipmill init --caller --land-as-app --force`" in text
    assert f"`{ENVIRONMENT}`, whose deployment branches are limited to the default branch" in text
    assert f"secret `{SECRET}`" in text
    assert "never falls back to the workflow token" in text


def test_s054_19_the_section_covers_shipmill_ruleset() -> None:
    text = section(LANES.read_text(encoding="utf-8"), HEADING)
    assert "### `shipmill ruleset`" in text
    assert "`uvx shipmill ruleset | gh api -X POST repos/<owner>/<repo>/rulesets --input -`" in text
    assert f"`{RELEASE_BRANCHES}` when the policy has a hotfix lane" in text
    assert "an `Integration` with `bypass_mode` `always`" in text


def test_s054_19_the_section_says_which_workflows_an_app_push_starts() -> None:
    text = section(LANES.read_text(encoding="utf-8"), HEADING)
    assert "### What an App push starts" in text
    assert "start the repository's `on: push` workflows on the default branch" in text
    assert "plans no release when nothing was merged since" in text
    assert "it starts no `on: push: tags` workflow" in text
    assert "### Limits" in text


def test_s054_19_limits_install_and_setup_name_the_opt_in() -> None:
    limits = section(LANES.read_text(encoding="utf-8"), "Limits")
    assert "land as the App ([Protected default branch](#protected-default-branch))" in limits
    assert "Until landing changes" not in limits
    install = folded(ROOT / "docs" / "install.md")
    assert "opt in to landing as the App" in install
    assert "(release-lanes.md#protected-default-branch)" in install
    assert "until #1038" not in install
    setup = folded(ROOT / "skills" / "shipmill-setup" / "SKILL.md")
    row = setup.split("| Branch protection |")[1].split("| Python package basics |")[0]
    assert "`shipmill doctor`'s `landing` row" in row
    assert "offer the opt-in to land as the App" in row
    assert "docs/release-lanes.md#protected-default-branch" in row
