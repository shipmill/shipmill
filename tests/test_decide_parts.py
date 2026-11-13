"""Spec 057: [decisions.paths.<zone>], a level for part of a zone, and `decide levels` listing it"""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from shipmill.cli import main
from shipmill.decide import DecisionPolicy, Level, Part, Zone
from shipmill.errors import ReleaseError
from shipmill.policy import Policy

from .conftest import POLICY, Repo
from .test_decide_cli import commit

WHERE = "shipmill.toml [decisions]"
LEVELS = "['act', 'notify', 'ask', 'never']"
TAKES = "only direction, security, and protected are detected by path"
WORKFLOWS = '[decisions.paths.security]\n".github/workflows/**" = "notify"\n'


def decisions(text: str) -> DecisionPolicy:
    return Policy.parse(tomllib.loads(POLICY + "\n" + text), "shipmill.toml").decisions


def refused(text: str) -> str:
    with pytest.raises(ReleaseError) as caught:
        decisions(text)
    return str(caught.value)


def part(zone: str, glob: str, level: str) -> str:
    return f'[decisions.paths.{zone}]\n"{glob}" = "{level}"\n'


# -- S-057-1: the part is kept and listed -----------------------------------------------------


def test_s057_1_parse_keeps_the_part_and_leaves_every_zone_level_as_it_was() -> None:
    policy = decisions('[decisions]\nsecurity = "ask"\n\n' + WORKFLOWS + '".github/shipmill.toml" = "notify"\n')
    assert policy.parts_of(Zone.SECURITY) == (
        Part(Zone.SECURITY, ".github/workflows/**", Level.NOTIFY),
        Part(Zone.SECURITY, ".github/shipmill.toml", Level.NOTIFY),
    )  # the config's order
    assert policy.parts_of(Zone.PROTECTED) == ()
    assert policy.levels == decisions('[decisions]\nsecurity = "ask"\n').levels


def test_s057_1_a_config_without_parts_parses_as_before() -> None:
    assert decisions("") == DecisionPolicy()
    assert decisions("[decisions.paths]\n") == DecisionPolicy()


def test_s057_1_levels_json_lists_the_part_under_its_zone_and_no_paths_elsewhere(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, POLICY + "\n" + WORKFLOWS)
    assert main(["--repo", str(repo.root), "decide", "levels", "--json"]) == 0
    rows = {r["zone"]: r for r in json.loads(capsys.readouterr().out)["zones"]}
    assert rows["security"] == {
        "zone": "security",
        "level": "ask",
        "floor": "notify",
        "source": "default",
        "paths": [{"glob": ".github/workflows/**", "level": "notify", "source": "config"}],
    }
    assert all(r["paths"] == [] for zone, r in rows.items() if zone != "security")
    assert len(rows) == 21


def test_s057_1_levels_text_prints_a_part_line_under_its_zone(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    commit(repo, POLICY + "\n" + WORKFLOWS)
    assert main(["--repo", str(repo.root), "decide", "levels"]) == 0
    out = capsys.readouterr().out.splitlines()
    at = next(i for i, line in enumerate(out) if line.startswith("security "))
    assert out[at + 1].split() == ["part", '".github/workflows/**"', "notify", "config", "[decisions.paths.security]"]
    assert out[at + 2].startswith("protected ")
    assert len(out) == 1 + 21 + 1


# -- S-057-2: what may stand under paths, and the four levels ---------------------------------


def test_s057_2_paths_that_is_not_a_table_is_refused_naming_the_key() -> None:
    assert refused('[decisions]\npaths = "security"\n') == f"{WHERE}: paths must be a table, got 'security'"


def test_s057_2_a_zone_under_paths_that_is_not_a_table_is_refused_naming_the_key() -> None:
    assert refused('[decisions.paths]\nsecurity = "notify"\n') == (
        f"{WHERE}: [decisions.paths] security must be a table of globs and levels, [decisions.paths.security],"
        " got 'notify'"
    )


@pytest.mark.parametrize("zone", ["scope", "contract-change", "interpretation"])
def test_s057_2_a_zone_code_doesnt_detect_by_path_is_refused(zone: str) -> None:
    assert refused(part(zone, "src/**", "ask")) == f"{WHERE}: [decisions.paths] {zone} takes no paths: {TAKES}"


def test_s057_2_decision_policy_under_paths_is_refused_as_fixed() -> None:
    assert refused(part("decision-policy", ".github/**", "never")) == (
        f"{WHERE}: [decisions.paths] decision-policy is fixed at never: only the maintainer changes [decisions]"
        " (D-48); remove the key"
    )


def test_s057_2_a_release_side_zone_under_paths_is_refused_naming_autonomy() -> None:
    assert refused(part("release", "src/**", "ask")) == (
        f"{WHERE}: [decisions.paths] release is set in [autonomy] release and takes no paths: {TAKES}"
    )


def test_s057_2_no_zone_id_under_paths_is_refused_listing_the_three_zones() -> None:
    assert refused(part("colour", "src/**", "ask")) == f"{WHERE}: [decisions.paths] unknown zone 'colour'; {TAKES}"


@pytest.mark.parametrize("value", ['"maybe"', '"ACT"', "1", "true", '["ask"]'])
def test_s057_2_a_value_that_is_no_level_is_refused_naming_the_four_levels(value: str) -> None:
    got = repr(tomllib.loads(f"v = {value}")["v"])
    assert refused(f'[decisions.paths.protected]\n"src/**" = {value}\n') == (
        f'{WHERE}: [decisions.paths.protected] "src/**" must be one of {LEVELS}, got {got}'
    )


# -- S-057-3: the floors hold for parts -------------------------------------------------------


def test_s057_3_a_security_part_at_act_is_refused_naming_the_floor() -> None:
    assert refused(part("security", ".github/workflows/**", "act")) == (
        f'{WHERE}: [decisions.paths.security] ".github/workflows/**" = "act" is below its floor notify:'
        " a change to workflows, secrets, or permissions is always told (D-48)"
    )


def test_s057_3_a_direction_part_at_act_is_refused_naming_the_floor() -> None:
    assert refused(part("direction", "docs/product/**", "act")) == (
        f'{WHERE}: [decisions.paths.direction] "docs/product/**" = "act" is below its floor ask:'
        " only the maintainer changes the direction (D-34)"
    )


def test_s057_3_parts_at_or_above_the_floor_are_accepted_above_or_below_the_zone() -> None:
    policy = decisions(
        part("security", ".github/workflows/**", "notify")
        + "\n"
        + '[decisions.paths.protected]\n"deploy/migrations/**" = "never"\n"docs/**" = "act"\n'
    )
    assert [p.level for p in policy.parts_of(Zone.SECURITY)] == [Level.NOTIFY]
    assert [(p.glob, p.level) for p in policy.parts_of(Zone.PROTECTED)] == [
        ("deploy/migrations/**", Level.NEVER),
        ("docs/**", Level.ACT),
    ]


# -- S-057-4: a glob is relative, in the repo, and inside its zone's paths --------------------

GLOBS = {
    "empty": ("protected", "", "is an empty glob; name a path relative to the repository root"),
    "absolute": ("protected", "/etc/passwd", "is absolute; a glob is relative to the repository root"),
    "dot-dot": ("protected", "src/../../etc/**", "holds ..; a glob stays inside the repository"),
    "security outside .github/": (
        "security",
        "src/auth/**",
        "lies outside security's paths: a security glob starts .github/",
    ),
    "direction outside docs/product": (
        "direction",
        "docs/flow.md",
        "lies outside direction's paths: a direction glob is docs/product.md or starts docs/product/",
    ),
}


@pytest.mark.parametrize("name", GLOBS)
def test_s057_4_a_glob_outside_the_repo_or_its_zones_paths_is_refused(name: str) -> None:
    zone, glob, why = GLOBS[name]
    assert refused(part(zone, glob, "never")) == f'{WHERE}: [decisions.paths.{zone}] "{glob}" {why}'


def test_s057_4_globs_inside_their_zones_paths_are_accepted() -> None:
    policy = decisions(
        '[decisions.paths.direction]\n"docs/product.md" = "never"\n"docs/product/**" = "ask"\n'
        + "\n"
        + part("protected", "deploy/migrations/**", "never")
    )
    assert [p.glob for p in policy.parts_of(Zone.DIRECTION)] == ["docs/product.md", "docs/product/**"]


def test_s057_4_a_part_built_in_code_holds_the_same_rules() -> None:
    with pytest.raises(ReleaseError, match="is below its floor notify"):
        Part(Zone.SECURITY, ".github/workflows/**", Level.ACT)
    with pytest.raises(ReleaseError, match="a security glob starts .github/"):
        Part(Zone.SECURITY, "src/**", Level.ASK)
    with pytest.raises(ReleaseError, match=f"scope takes no paths: {TAKES}"):
        Part(Zone.SCOPE, "src/**", Level.ASK)


# -- exit 2 from the CLI ----------------------------------------------------------------------

EXITS = {
    "S-057-2 paths not a table": ("[decisions]\npaths = 1\n", "paths must be a table"),
    "S-057-2 scope": (part("scope", "src/**", "ask"), "scope takes no paths"),
    "S-057-2 contract-change": (part("contract-change", "src/**", "ask"), "contract-change takes no paths"),
    "S-057-2 decision-policy": (part("decision-policy", ".github/**", "never"), "decision-policy is fixed at never"),
    "S-057-2 release": (part("release", "src/**", "ask"), "release is set in [autonomy]"),
    "S-057-2 no zone id": (part("colour", "src/**", "ask"), "direction, security, and protected"),
    "S-057-2 no level": (part("protected", "src/**", "maybe"), f"must be one of {LEVELS}"),
    "S-057-3 security at act": (part("security", ".github/**", "act"), "is below its floor notify"),
    "S-057-3 direction at act": (part("direction", "docs/product.md", "act"), "is below its floor ask"),
    "S-057-4 empty": (part("protected", "", "ask"), "is an empty glob"),
    "S-057-4 absolute": (part("protected", "/src/**", "ask"), "is absolute"),
    "S-057-4 dot-dot": (part("protected", "../src/**", "ask"), "holds .."),
    "S-057-4 security": (part("security", "src/**", "ask"), "a security glob starts .github/"),
    "S-057-4 direction": (part("direction", "docs/x.md", "ask"), "a direction glob is docs/product.md"),
}


# proves: S-057-2, S-057-3, S-057-4
@pytest.mark.parametrize("name", EXITS)
def test_s057_2_a_bad_part_exits_2_naming_the_key(name: str, tmp_path: Path) -> None:
    text, message = EXITS[name]
    path = tmp_path / ".github" / "shipmill.toml"
    path.parent.mkdir()
    path.write_text(POLICY + "\n" + text, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-c", "from shipmill.cli import run; run()", "--repo", str(tmp_path), "decide", "levels"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert done.stderr.startswith(f"shipmill: {WHERE}: ")
    assert message in done.stderr
