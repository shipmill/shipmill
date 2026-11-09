"""#1001: every setup-uv step in the reusable workflows pins one exact uv (D-80)"""

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
USES = re.compile(r"^(?P<indent> *)- uses: astral-sh/setup-uv@\S+\s*$")
VERSION = re.compile(r"^ +version: \"?(?P<version>[^\"\s]+)\"?\s*$")
EXACT = re.compile(r"\d+\.\d+\.\d+")


def _setup_uv_versions(text: str) -> list[str | None]:
    """The `version:` each setup-uv step in a workflow sets, None for a step that sets none"""
    lines = text.splitlines()
    found: list[str | None] = []
    for i, line in enumerate(lines):
        if not (step := USES.match(line)):
            continue
        indent = len(step["indent"])
        version = None
        for following in lines[i + 1 :]:
            if following.strip() and len(following) - len(following.lstrip(" ")) <= indent:
                break
            if pinned := VERSION.match(following):
                version = pinned["version"]
        found.append(version)
    return found


def _all_versions() -> dict[str, list[str | None]]:
    return {path.name: _setup_uv_versions(path.read_text(encoding="utf-8")) for path in sorted(WORKFLOWS.glob("*.yml"))}


def test_every_setup_uv_step_pins_one_exact_uv() -> None:
    found = _all_versions()
    steps = [(name, version) for name, versions in found.items() for version in versions]
    assert len(steps) >= 13, steps  # prepare, land, operate, downstream, publish, ci, evals
    for name in ("prepare.yml", "land.yml", "operate.yml", "downstream.yml", "publish.yml", "ci.yml", "evals.yml"):
        assert found[name], name
    unpinned = [name for name, version in steps if version is None]
    assert not unpinned, f"setup-uv steps with no version: {unpinned}"
    versions = {version for _, version in steps}
    assert len(versions) == 1, f"setup-uv steps pin different uv versions: {sorted(map(str, versions))}"
    assert all(version is not None and EXACT.fullmatch(version) for version in versions), versions


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ("      - uses: astral-sh/setup-uv@v10.2.0\n\n      - name: Next\n", [None]),
        ('      - uses: astral-sh/setup-uv@v10.2.0\n        with:\n          version: "0.13.7"\n', ["0.13.7"]),
        (
            '      - uses: astral-sh/setup-uv@v10.2.0\n        with:\n          python-version: "3.14"\n'
            "      - uses: astral-sh/setup-uv@v10.2.0\n        with:\n          version: 0.13.6\n",
            [None, "0.13.6"],
        ),
    ],
)
def test_the_reader_finds_each_steps_version(step: str, expected: list[str | None]) -> None:
    assert _setup_uv_versions(f"jobs:\n  a:\n    steps:\n{step}") == expected
