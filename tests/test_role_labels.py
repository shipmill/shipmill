"""Spec 036: shipmill-setup wants a label for each role, role:maintainer wherever it wants
needs-decision and role:<name> for each role [agents.roles] defines"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
AGENTS = '[agents]\nprompt = "x"\n'
ROLES = (
    '[agents.roles]\nmaintainer = ["octocat"]\ninfra = [\n  "octocat",\n  "hubot",\n]\n'
    "legal = [\"@example-org/legal\"]  # a team\n'accounting' = []\n"
)


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ss() -> ModuleType:
    return load("setup_state", SKILLS / "shipmill-setup" / "scripts" / "setup_state.py")


@pytest.fixture(scope="module")
def ws(ss: ModuleType) -> ModuleType:
    module: ModuleType = ss.watch_module()
    return module


def config(root: Path, text: str) -> None:
    (root / ".github").mkdir(exist_ok=True)
    (root / ".github" / "shipmill.toml").write_text(text, encoding="utf-8")


def py310(ws: ModuleType) -> SimpleNamespace:
    """watch_state.py as Python 3.10 has it: no tomllib, the plain table reader"""
    return SimpleNamespace(tomllib=None, toml_tables=ws.toml_tables)


def roles(wanted: dict[str, tuple[str, str]]) -> list[str]:
    return [name for name in wanted if name.startswith("role:")]


@pytest.mark.parametrize(
    "text", [AGENTS, '[agents]\nprompt = "x"\nmode = "headless"\n', '[agents]\nprompt = "x"\napp_id = 1\n']
)
def test_s036_15_role_maintainer_is_wanted_wherever_needs_decision_is(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, text: str
) -> None:
    config(tmp_path, text)
    wanted = ss.wanted_labels(tmp_path, ws)
    assert "needs-decision" in wanted and "human" in wanted  # human is still wanted
    assert roles(wanted) == ["role:maintainer"]
    assert wanted["role:maintainer"] == ("0e8a16", "A step for the maintainer role: its people do it")
    row = ss.labels_row(["needs-decision", "role:maintainer", "human"], wanted)
    assert (row.state, row.detail) == ("LABELS_MISSING", "needs-decision, role:maintainer, human")


@pytest.mark.parametrize("text", [None, "", 'mode = "release"\n', '[lanes.dev]\nmode = "headless"\n'])
def test_s036_15_no_role_label_without_agents(ss: ModuleType, ws: ModuleType, tmp_path: Path, text: str | None) -> None:
    if text is not None:
        config(tmp_path, text)
    wanted = ss.wanted_labels(tmp_path, ws)
    assert "needs-decision" not in wanted and roles(wanted) == []


@pytest.mark.parametrize("on_310", [False, True], ids=["tomllib", "py310"])
def test_s036_15_each_role_of_agents_roles_is_wanted_once(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, on_310: bool
) -> None:
    config(tmp_path, AGENTS + ROLES)
    reader = py310(ws) if on_310 else ws
    wanted = ss.wanted_labels(tmp_path, reader)
    # maintainer first and once, though the table names it too; an empty role still gets its label
    assert roles(wanted) == ["role:maintainer", "role:infra", "role:legal", "role:accounting"]
    assert "human" in wanted
    assert wanted["role:infra"] == ("0e8a16", "A step for the infra role: its people do it")
    missing = [name for name in wanted if name in ("needs-decision", "role:maintainer", "role:infra")]
    assert ss.labels_row(missing, wanted).detail == "needs-decision, role:maintainer, role:infra"


@pytest.mark.parametrize("on_310", [False, True], ids=["tomllib", "py310"])
def test_s036_15_a_table_without_maintainer_still_wants_it_first(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, on_310: bool
) -> None:
    config(tmp_path, AGENTS + '[agents.roles]\ninfra = ["octocat"]\n')
    wanted = ss.wanted_labels(tmp_path, py310(ws) if on_310 else ws)
    assert roles(wanted) == ["role:maintainer", "role:infra"]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (AGENTS + 'roles = "infra"\n', "[agents.roles] must be a table of role names, got str"),
        (AGENTS + "roles = [1]\n", "[agents.roles] must be a table of role names, got list"),
        (AGENTS + '[agents.roles]\nInfra = ["a"]\n', "[agents.roles] 'Infra' isn't a role name"),
        (AGENTS + '[agents.roles]\n"-x" = ["a"]\n', "[agents.roles] '-x' isn't a role name"),
        (AGENTS + f'[agents.roles]\n{"a" * 46} = ["a"]\n', f"[agents.roles] '{'a' * 46}' isn't a role name"),
    ],
)
def test_s036_15_malformed_roles_exit_2_naming_them(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, error: str
) -> None:
    config(tmp_path, text)
    with pytest.raises(SystemExit) as exc:
        ss.wanted_labels(tmp_path, ws)
    assert exc.value.code == 2
    assert error in capsys.readouterr().err


@pytest.mark.parametrize(
    "text",
    [
        AGENTS + 'roles = { infra = ["a"] }\n',  # inline
        AGENTS + 'roles.infra = ["a"]\n',  # dotted
        AGENTS + '[agents.roles.infra]\nagent = "x"\n',  # a role as a table
    ],
)
def test_s036_15_on_310_roles_set_another_way_is_refused(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    config(tmp_path, text)
    with pytest.raises(SystemExit) as exc:
        ss.wanted_labels(tmp_path, py310(ws))
    assert exc.value.code == 2
    assert "can't read [agents.roles] on Python 3.10" in capsys.readouterr().err


def test_s036_15_a_role_name_on_310_is_checked_too(
    ss: ModuleType, ws: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config(tmp_path, AGENTS + '[agents.roles]\nInfra = ["a"]\n')
    with pytest.raises(SystemExit) as exc:
        ss.wanted_labels(tmp_path, py310(ws))
    assert exc.value.code == 2
    assert "[agents.roles] 'Infra' isn't a role name" in capsys.readouterr().err
