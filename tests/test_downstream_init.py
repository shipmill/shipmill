"""Spec 032: `shipmill init --downstream` writes the library's downstream caller"""

import subprocess
import sys

import pytest

from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.doctor import DOWNSTREAM_CALLER
from shipmill.errors import ReleaseError
from shipmill.init import downstream_caller_text, init_downstream

from .conftest import POLICY, Repo

SECTION = (
    "\n[downstream]\napp_id = 123456\n\n[downstream.consumer-app]\n"
    'repo = "example-org/consumer-app"\nworkflow = "library-tests.yml"\n'
)
CALLER_BODY = """on:
  pull_request_target:
    types: [opened, synchronize, reopened]
  workflow_dispatch:
    inputs:
      pr: {description: "pull request to test", required: true, type: number}
      collect: {description: "set by shipmill: the head SHA to collect results for", type: string, default: ""}
permissions:
  actions: write          # start this workflow's collect run
  checks: write           # write one check per downstream on the pull request's head
  contents: read
  pull-requests: read
jobs:
  downstream:
    uses: shipmill/shipmill/.github/workflows/downstream.yml@v0
    with:
      pr: ${{ github.event.pull_request.number || inputs.pr }}
      collect: ${{ inputs.collect }}
    secrets:
      downstream-key: ${{ secrets.SHIPMILL_DOWNSTREAM_KEY }}
"""


def _with_downstream(repo: Repo) -> None:
    repo.write(str(CONFIG_PATH), POLICY + SECTION)
    repo.git.run("commit", "-q", "-am", "Add [downstream]")


def _changed(repo: Repo) -> list[str]:
    return repo.git.run("status", "--porcelain", "--untracked-files=all").splitlines()


def test_s032_3_init_downstream_writes_only_the_caller_the_spec_names(repo: Repo) -> None:
    _with_downstream(repo)
    assert main(["--repo", str(repo.root), "init", "--downstream"]) == 0
    text = repo.read(str(DOWNSTREAM_CALLER))
    assert text == downstream_caller_text()
    assert text.startswith("name: Downstream tests\n")
    assert text.endswith(CALLER_BODY)
    assert _changed(repo) == [f"?? {DOWNSTREAM_CALLER}"]


def test_s032_3_init_downstream_refuses_an_existing_caller_without_force(repo: Repo) -> None:
    _with_downstream(repo)
    repo.write(str(DOWNSTREAM_CALLER), "name: mine\n")
    with pytest.raises(ReleaseError, match="downstream.yml exists; pass --force to overwrite"):
        init_downstream(repo.root, force=False)
    assert repo.read(str(DOWNSTREAM_CALLER)) == "name: mine\n"
    init_downstream(repo.root, force=True)
    assert repo.read(str(DOWNSTREAM_CALLER)) == downstream_caller_text()


def test_s032_3_init_downstream_exits_2_when_the_policy_has_no_downstream(repo: Repo) -> None:
    argv = [sys.executable, "-m", "shipmill", "--repo", str(repo.root), "init", "--downstream"]
    out = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert out.returncode == 2
    assert "has no [downstream] section" in out.stderr
    assert _changed(repo) == []


@pytest.mark.parametrize("flags", [["--caller"], ["--operate"], ["--no-fragments"], ["--runs-on", "self-hosted"]])
def test_s032_3_init_downstream_refuses_the_flags_of_other_files(repo: Repo, flags: list[str]) -> None:
    _with_downstream(repo)
    with pytest.raises(ReleaseError, match=f"--downstream writes only .*; drop {flags[0]}"):
        main(["--repo", str(repo.root), "init", "--downstream", *flags])
    assert _changed(repo) == []
