"""Spec 024: doctor fails a repo whose agents implement ([agents]) without a well-formed
docs/product.md, naming the fix; a repo that only cuts releases gets no direction line"""

import os
from pathlib import Path

import pytest

from shipmill import cli_command
from shipmill.cli import main
from shipmill.config import CONFIG_PATH, config_path
from shipmill.doctor import Check, direction_check, doctor
from shipmill.policy import Policy

from .conftest import Repo
from .test_product import GOALS, MOVED, WELL_FORMED

ROOT = Path(__file__).resolve().parents[1]


def add_agents(repo: Repo) -> None:
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + '\n[agents]\nprompt = "/t"\n')


def direction(repo: Repo) -> list[Check]:
    return [c for c in doctor(repo.root) if c.name == "direction"]


def test_s024_5_agents_without_a_direction_fail_naming_the_file_and_the_check(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    add_agents(repo)
    (found,) = direction(repo)
    assert found.status == "FAIL"
    assert "there is no docs/product.md" in found.detail
    assert "ask the maintainer for the mission, users, goals, non-goals, and quality bar" in found.detail
    assert found.detail.endswith(f"then run `{cli_command()} product check`")
    assert main(["--repo", str(repo.root), "doctor"], environ={"PATH": ""}) == 1  # no claude: no hook self-test
    assert "FAIL direction: [agents] is set" in capsys.readouterr().out


def test_s024_5_agents_with_a_direction_product_check_refuses_fail_with_its_first_problem(repo: Repo) -> None:
    add_agents(repo)
    repo.write("docs/product.md", WELL_FORMED.replace("- U-1: A widget buyer\n", "- G-1: A widget buyer\n"))
    (found,) = direction(repo)
    assert found.status == "FAIL"
    assert found.detail.startswith("docs/product.md is not well formed: docs/product.md:11: `## Users` holds U-n")
    assert found.detail.endswith(f"run `{cli_command()} product check` for each line, fix them")


def test_s024_5_agents_with_a_well_formed_direction_pass(repo: Repo) -> None:
    add_agents(repo)
    repo.write("docs/product.md", WELL_FORMED)
    assert direction(repo) == [Check("PASS", "direction", "docs/product.md is well formed")]


def test_s024_5_a_repo_without_agents_gets_no_direction_line(repo: Repo) -> None:
    assert direction(repo) == []
    repo.write("docs/product.md", "not a direction\n")
    assert direction(repo) == []


def test_s024_5_this_repo_has_agents_and_its_direction_passes() -> None:
    """shipmill's own config has [agents], so its doctor reads its docs/product.md"""
    assert Policy.load(config_path(ROOT)).agents is not None
    assert direction_check(ROOT).status == "PASS"


def test_s024_5_a_moved_section_is_followed(repo: Repo) -> None:
    add_agents(repo)
    repo.write("docs/product.md", MOVED)
    (found,) = direction(repo)
    assert found.status == "FAIL"
    assert "docs/product/goals.md, which doesn't exist" in found.detail
    repo.write("docs/product/goals.md", GOALS)
    assert direction(repo) == [Check("PASS", "direction", "docs/product.md is well formed")]


def test_s024_5_a_direction_that_isnt_utf8_fails_naming_the_fix(repo: Repo) -> None:
    add_agents(repo)
    (repo.root / "docs").mkdir(exist_ok=True)
    (repo.root / "docs/product.md").write_bytes(b"# Acme\n\xff\n")
    (found,) = direction(repo)
    assert found.status == "FAIL"
    assert "is not UTF-8 text" in found.detail
    assert found.detail.endswith(f"then run `{cli_command()} product check`")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_s024_5_an_unreadable_direction_fails_naming_the_fix(repo: Repo) -> None:
    add_agents(repo)
    repo.write("docs/product.md", WELL_FORMED)
    path = repo.root / "docs/product.md"
    path.chmod(0)
    try:
        (found,) = direction(repo)
    finally:
        path.chmod(0o644)
    assert found.status == "FAIL"
    assert "Permission denied" in found.detail
    assert found.detail.endswith(f"then run `{cli_command()} product check`")
