"""`shipmill ruleset` (S-054-17): the create-ruleset body that protects the default branch and
lets the App land"""

import json

import pytest

from shipmill.cli import main
from shipmill.errors import ReleaseError

from .conftest import POLICY, Repo

APP = 42
WITH_APP = POLICY + f'\n[agents]\nprompt = "/t"\napp_id = {APP}\n'
CALLER = """\
jobs:
  prepare:
    uses: ./.github/workflows/prepare.yml
  ci:
    needs: prepare
    uses: ./.github/workflows/ci.yml # the release commit's CI
    with:
      ref: v1
  land:
    uses: ./.github/workflows/land.yml
"""
CI = """\
name: CI
on:
  pull_request:
  workflow_call:
    inputs:
      ref:
        type: string

jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - name: not a job name
        run: true
  lint:
    name: "Lint"  # a plain name
    runs-on: ubuntu-latest
    steps:
      - run: true
"""


def printed(repo: Repo, capsys: pytest.CaptureFixture[str], config: str = WITH_APP, ci: str = CI) -> dict[str, object]:
    repo.write(repo.policy_file, config)
    repo.write(".github/workflows/release.yml", CALLER)
    repo.write(".github/workflows/ci.yml", ci)
    assert main(["--repo", str(repo.root), "ruleset"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert isinstance(body, dict)
    return body


def test_s054_17_the_body_protects_the_default_branch_and_lets_the_app_land(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert printed(repo, capsys) == {
        "name": "shipmill: protected default branch",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH", "refs/heads/release/*"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [{"context": "checks"}, {"context": "Lint"}],
                },
            },
        ],
        "bypass_actors": [{"actor_id": APP, "actor_type": "Integration", "bypass_mode": "always"}],
    }


def test_s054_17_without_a_hotfix_lane_only_the_default_branch(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    config = WITH_APP.replace("[lanes.hotfix]\ngithub_release = true\n", "")
    body = printed(repo, capsys, config)
    assert body["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}


def test_s054_17_without_app_id_it_exits_2_naming_the_key(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.write(".github/workflows/release.yml", CALLER)
    repo.write(".github/workflows/ci.yml", CI)
    with pytest.raises(ReleaseError, match=r"\[agents\] app_id"):  # run() turns it into exit 2
        main(["--repo", str(repo.root), "ruleset"])
    assert capsys.readouterr().out == ""


# proves: S-054-17
@pytest.mark.parametrize(
    ("ci", "needle"),
    [
        (
            CI.replace(
                "    runs-on: ubuntu-latest\n    steps:\n      - name",
                "    strategy:\n      matrix: {}\n    steps:\n      - name",
            ),
            "job checks",
        ),
        (CI.replace('name: "Lint"', "name: ${{ matrix.os }}"), "job lint"),
        ("name: CI\non: pull_request\n", "has no jobs"),
    ],
)
def test_a_ci_whose_check_names_its_text_doesnt_tell_is_refused(
    repo: Repo, capsys: pytest.CaptureFixture[str], ci: str, needle: str
) -> None:
    repo.write(repo.policy_file, WITH_APP)
    repo.write(".github/workflows/release.yml", CALLER)
    repo.write(".github/workflows/ci.yml", ci)
    with pytest.raises(ReleaseError, match=needle):
        main(["--repo", str(repo.root), "ruleset"])
    assert capsys.readouterr().out == ""


def test_a_quoted_name_keeps_its_hash(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    body = printed(repo, capsys, ci=CI.replace('name: "Lint"  # a plain name', 'name: "Lint #1"  # a comment'))
    rules = body["rules"]
    assert isinstance(rules, list)
    assert rules[3]["parameters"]["required_status_checks"] == [{"context": "checks"}, {"context": "Lint #1"}]


def test_a_release_workflow_without_one_ci_call_is_refused(repo: Repo) -> None:
    repo.write(repo.policy_file, WITH_APP)
    repo.write(
        ".github/workflows/release.yml", CALLER.replace("./.github/workflows/ci.yml", "o/r/.github/workflows/ci.yml@v1")
    )
    with pytest.raises(ReleaseError, match="must call one local CI workflow .*; it calls none"):
        main(["--repo", str(repo.root), "ruleset"])
