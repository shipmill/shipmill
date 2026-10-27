"""Spec 043, S-043-1: watch_state.py's [product] reader, which chains.py, triage_state.py's
--home, and upstream_state.py read through, takes `standalone = true` alone as no table, on
tomllib and on the Python 3.10 fallback alike, and refuses any other standalone naming the key"""

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "skills" / "github-ship-watch" / "scripts" / "watch_state.py"
AGENTS = '[agents]\nprompt = "/t"\napp_id = 42\n\n'


@pytest.fixture(scope="module")
def ws() -> ModuleType:
    spec = importlib.util.spec_from_file_location("watch_state_standalone", WATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def readers(ws: ModuleType) -> list[Callable[[str, Path], object]]:
    """Each [product] reader: tomllib's and the 3.10 fallback's, for home and for repos"""
    return [ws.product_home, ws.product_home_310, ws.product_repos, ws.product_repos_310]


@pytest.mark.parametrize(
    "text",
    [
        "[product]\nstandalone = true\n",
        AGENTS + "[product]\nstandalone = true  # it stands alone\n",
        "[product]\n# setup's answer\n\nstandalone = true\n\n[hooks]\ndefault_branch = true\n",
    ],
)
def test_s043_1_standalone_reads_as_no_product_table_on_311_and_310(ws: ModuleType, tmp_path: Path, text: str) -> None:
    policy = tmp_path / "shipmill.toml"
    assert [read(text, policy) for read in readers(ws)] == [None, None, None, None]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[product]\nstandalone = false\n", "standalone takes only true; got"),
        ('[product]\nstandalone = "true"\n', "standalone takes only true; got"),
        ("[product]\nstandalone = 1\n", "standalone takes only true; got"),
        ('[product]\nstandalone = true\nhome = "acme/product"\n', "standalone can't be set beside home"),
        ('[product]\nhome = "acme/product"\nstandalone = true\n', "standalone can't be set beside home"),
        ('[product]\nstandalone = true\nrepos = ["acme/api"]\n', "standalone can't be set beside repos"),
        ('[product]\nrepos = ["acme/api"]\nstandalone = false\n', "standalone can't be set beside repos"),
    ],
)
def test_s043_1_a_bad_standalone_is_refused_naming_the_key_on_311_and_310(
    ws: ModuleType, tmp_path: Path, text: str, message: str
) -> None:
    for read in readers(ws):
        with pytest.raises(ws.Refused, match=message) as refused:
            read(text, tmp_path / "shipmill.toml")
        assert refused.value.code == 2, read


def test_s043_1_the_310_reader_refuses_a_second_standalone_or_a_key_beside_it(ws: ModuleType, tmp_path: Path) -> None:
    policy = tmp_path / "shipmill.toml"
    with pytest.raises(ws.Refused, match="standalone is set twice"):
        ws.product_home_310("[product]\nstandalone = true\nstandalone = true\n", policy)
    with pytest.raises(ws.Refused, match="standalone can't be set beside owner"):
        ws.product_repos_310("[product]\nstandalone = true\nowner = 1\n", policy)
    with pytest.raises(ws.Refused, match="unknown key 'owner'"):
        ws.product_repos("[product]\nstandalone = true\nowner = 1\n", policy)
