"""Spec 057: decisions.py's policy() reads [decisions.paths.<zone>] as the package does"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "github-issue-triage" / "scripts" / "decisions.py"
TAKES = "only direction, security, and protected are detected by path"
VALID = (
    '[decisions]\nsecurity = "ask"\n\n'
    '[decisions.paths.security]\n".github/workflows/**" = "notify"\n".github/shipmill.toml" = "notify"\n\n'
    '[decisions.paths.protected]\n"deploy/migrations/**" = "never"\n"docs/**" = "act"\n\n'
    '[decisions.paths.direction]\n"docs/product.md" = "never"\n"docs/product/**" = "ask"\n'
)


@pytest.fixture(scope="module")
def dm() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decisions_parts_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "shipmill.toml"
    path.write_text(text, encoding="utf-8")
    return path


def refused(dm: ModuleType, tmp_path: Path, text: str) -> str:
    path = config(tmp_path, text)
    with pytest.raises(dm.LogError) as caught:
        dm.policy(path)
    return str(caught.value).removeprefix(f"{path}: ")


def part(zone: str, glob: str, level: str) -> str:
    return f'[decisions.paths.{zone}]\n"{glob}" = "{level}"\n'


def test_s057_10_valid_parts_leave_every_zone_level_as_it_was(dm: ModuleType, tmp_path: Path) -> None:
    found = dm.policy(config(tmp_path, VALID))
    assert found.levels == dm.policy(config(tmp_path, '[decisions]\nsecurity = "ask"\n')).levels
    assert found.levels == {zone: default for zone, (default, _) in dm.ZONES.items()}
    assert found.parts == {
        "security": ((".github/workflows/**", "notify"), (".github/shipmill.toml", "notify")),
        "protected": (("deploy/migrations/**", "never"), ("docs/**", "act")),
        "direction": (("docs/product.md", "never"), ("docs/product/**", "ask")),
    }
    assert dm.policy(config(tmp_path, "[decisions]\nveto_hours = 12\n")).parts == {}


REFUSED = {
    # S-057-2
    "paths not a table": ("[decisions]\npaths = 1\n", "[decisions] paths must be a table"),
    "zone not a table": ('[decisions.paths]\nsecurity = "notify"\n', "[decisions.paths] security must be a table"),
    "scope": (part("scope", "src/**", "ask"), f"[decisions.paths] scope takes no paths: {TAKES}"),
    "contract-change": (
        part("contract-change", "src/**", "ask"),
        f"[decisions.paths] contract-change takes no paths: {TAKES}",
    ),
    "decision-policy": (
        part("decision-policy", ".github/**", "never"),
        "[decisions.paths] decision-policy is fixed at never; remove the key",
    ),
    "release": (part("release", "src/**", "ask"), "[decisions.paths] release: release is set in [autonomy] release"),
    "no zone id": (part("colour", "src/**", "ask"), f"[decisions.paths] colour is no zone id; {TAKES}"),
    "no level": (part("protected", "src/**", "maybe"), "a level is one of act, notify, ask, never"),
    # S-057-3
    "security at act": (
        part("security", ".github/workflows/**", "act"),
        "[decisions.paths.security] \".github/workflows/**\" = 'act' is below its floor notify",
    ),
    "direction at act": (part("direction", "docs/product.md", "act"), "is below its floor ask"),
    # S-057-4
    "empty": (part("protected", "", "ask"), '"" is an empty glob'),
    "absolute": (part("protected", "/src/**", "ask"), "is absolute"),
    "dot-dot": (part("protected", "src/../../etc/**", "ask"), "holds .."),
    "security outside .github/": (part("security", "src/auth/**", "ask"), "a security glob starts .github/"),
    "direction outside docs/product": (
        part("direction", "docs/flow.md", "ask"),
        "a direction glob is docs/product.md or starts docs/product/",
    ),
}


# proves: S-057-10
@pytest.mark.parametrize("name", REFUSED)
def test_s057_10_a_malformed_part_raises_log_error(dm: ModuleType, tmp_path: Path, name: str) -> None:
    text, message = REFUSED[name]
    assert message in refused(dm, tmp_path, text)


def test_s057_10_a_part_at_or_above_the_floor_is_accepted(dm: ModuleType, tmp_path: Path) -> None:
    text = part("security", ".github/**", "notify") + "\n" + part("protected", "src/**", "act")
    assert dm.policy(config(tmp_path, text)).parts == {
        "security": ((".github/**", "notify"),),
        "protected": (("src/**", "act"),),
    }


def test_s057_10_the_310_reader_refuses_a_paths_table(dm: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "shipmill.toml"
    for text in (part("security", ".github/**", "notify"), "[decisions]\npaths = { security = 1 }\n"):
        with pytest.raises(dm.LogError, match=r"can't read \[decisions\] on Python 3.10: use 3.11\+"):
            dm.decisions_table_310(text, path)


def test_s057_10_policy_under_python_310_raises_use_311(tmp_path: Path) -> None:
    path = config(tmp_path, VALID)
    uv = shutil.which("uv")
    assert uv is not None, "uv runs the skill scripts"
    code = (
        "import importlib.util, sys\nfrom pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('decisions_script', sys.argv[1])\n"
        "dm = importlib.util.module_from_spec(spec); sys.modules['decisions_script'] = dm\n"
        "spec.loader.exec_module(dm)\n"
        "assert dm.tomllib is None, 'tomllib on 3.10'\n"
        "try:\n    dm.policy(Path(sys.argv[2]))\nexcept dm.LogError as exc:\n    print(exc)\n"
    )
    command = [uv, "run", "--no-project", "--python", "3.10", "python", "-c", code, str(SCRIPT), str(path)]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == (
        f"{path}: can't read [decisions] on Python 3.10: use 3.11+, or plain key = value lines in it"
    )
