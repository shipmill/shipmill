"""Spec 063: doctor warns of a plain actions/checkout on the runner a deploy job deploys from (#1165)"""

import pytest

from shipmill.cli import main
from shipmill.doctor import Check, doctor

from .conftest import Repo

DEPLOY = """\
name: Deploy
on: push
jobs:
  deploy:
    runs-on: [self-hosted, linux, prod]
    environment: production
    steps:
      - run: ./deploy.sh
"""
RELEASE = """\
on:
  push:
  schedule:
    - cron: "0 * * * *"
jobs:
  prepare:
    uses: shipmill/shipmill/.github/workflows/prepare.yml@v0
  land:
    uses: shipmill/shipmill/.github/workflows/land.yml@v0
"""
PUBLISH = """\
on:
  workflow_dispatch:
    inputs:
      tag:
        required: true
jobs:
  publish:
    runs-on: ubuntu-latest
"""
DEPLOY_JOB = ".github/workflows/deploy.yml job deploy"


def notify(runs_on: str, checkout: str = "      - uses: actions/checkout@v4\n") -> str:
    return f"name: Notify\non: push\njobs:\n  notify:\n    runs-on: {runs_on}\n    steps:\n{checkout}      - run: ./n\n"


def rows(repo: Repo) -> list[Check]:
    return [c for c in doctor(repo.root, repo.github) if c.name == "deploy runner"]


def warning(labels: str, file: str = ".github/workflows/notify.yml", job: str = "notify") -> Check:
    detail = (
        f"{file} job {job} runs actions/checkout without path: on [{labels}], a runner {DEPLOY_JOB} deploys from;"
        " its checkout cleans the workspace the deploy left: set with: path: to a folder of its own, or run it"
        " on another runner"
    )
    return Check("WARN", "deploy runner", detail)


PASS = Check(
    "PASS",
    "deploy runner",
    f"no plain actions/checkout shares a self-hosted runner with a deploy job; checked {DEPLOY_JOB}",
)


@pytest.mark.parametrize(
    ("runs_on", "labels"),
    [
        ("self-hosted", "self-hosted"),  # a scalar
        ("[self-hosted, linux]", "self-hosted, linux"),  # a flow list
        ("\n      - self-hosted\n      - Linux", "self-hosted, Linux"),  # a block list; labels match without case
        ("\n      group: prod-runners\n      labels: [self-hosted, prod]", "self-hosted, prod"),  # a mapping
        ("\n      labels:\n        - prod", "prod"),  # a mapping's block list
    ],
)
def test_s063_9_a_plain_checkout_on_a_subset_of_a_deploy_jobs_labels_warns_naming_file_and_job(
    repo: Repo, runs_on: str, labels: str
) -> None:
    repo.write(".github/workflows/deploy.yml", DEPLOY)
    repo.write(".github/workflows/notify.yml", notify(runs_on))
    assert rows(repo) == [warning(labels)]


def test_s063_9_a_job_of_a_workflow_environments_names_is_a_deploy_job(repo: Repo) -> None:
    environment = '\n[environments.production]\nlane = "stable"\nworkflow = "deploy.yml"\n'
    repo.write(repo.policy_file, repo.read(repo.policy_file) + environment)
    assert any(c.name == "environment" for c in doctor(repo.root, repo.github))  # the config loaded
    repo.write(".github/workflows/deploy.yml", DEPLOY.replace("    environment: production\n", ""))
    repo.write(".github/workflows/notify.yaml", notify("[self-hosted]"))
    assert rows(repo) == [warning("self-hosted", ".github/workflows/notify.yaml")]


def test_s063_9_the_row_is_never_a_fail_and_leaves_the_exit_code(
    repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.write(".github/workflows/deploy.yml", DEPLOY)
    repo.write(".github/workflows/release.yml", RELEASE)  # the fixture's own FAIL rows, fixed
    repo.write(".github/workflows/publish.yml", PUBLISH)
    no_claude = {"PATH": ""}  # no hook self-test against this host's install
    before = main(["--repo", str(repo.root), "doctor"], github=repo.github, environ=no_claude)
    repo.write(".github/workflows/notify.yml", notify("[self-hosted, prod]"))
    others = {c.name for c in doctor(repo.root, repo.github) if c.status == "FAIL"}
    assert others == set()  # no other FAIL, so doctor exits 0
    assert main(["--repo", str(repo.root), "doctor"], github=repo.github, environ=no_claude) == before == 0
    assert "WARN deploy runner: .github/workflows/notify.yml job notify" in capsys.readouterr().out


@pytest.mark.parametrize(
    "notify_text",
    [
        notify("self-hosted", "      - uses: actions/checkout@v4\n        with:\n          path: notify\n"),
        notify("self-hosted", "      - uses: actions/checkout@v4\n        with: {path: notify}\n"),
        notify("[self-hosted, windows]"),  # not a subset of the deploy job's labels
        notify("${{ inputs.runner }}"),
        notify("self-hosted", "      - uses: actions/setup-python@v5\n"),
    ],
)
def test_s063_10_no_warning_when_the_checkout_sets_path_or_the_labels_differ(repo: Repo, notify_text: str) -> None:
    repo.write(".github/workflows/deploy.yml", DEPLOY)
    repo.write(".github/workflows/notify.yml", notify_text)
    assert rows(repo) == [PASS]


def test_s063_10_a_deploy_job_with_an_expression_runs_on_is_not_compared(repo: Repo) -> None:
    repo.write(".github/workflows/deploy.yml", DEPLOY.replace("[self-hosted, linux, prod]", "${{ vars.RUNNER }}"))
    repo.write(".github/workflows/notify.yml", notify("self-hosted"))
    assert rows(repo) == []


def test_s063_10_a_deploy_job_on_a_github_hosted_label_prints_no_row(repo: Repo) -> None:
    repo.write(".github/workflows/deploy.yml", DEPLOY.replace("[self-hosted, linux, prod]", "ubuntu-latest"))
    repo.write(".github/workflows/notify.yml", notify("ubuntu-latest"))
    assert rows(repo) == []


def test_s063_10_no_deploy_job_prints_no_row(repo: Repo) -> None:
    repo.write(".github/workflows/notify.yml", notify("self-hosted"))
    assert rows(repo) == []


def test_s063_10_the_deploy_jobs_own_checkout_and_a_group_only_runs_on_are_not_compared(repo: Repo) -> None:
    repo.write(
        ".github/workflows/deploy.yml",
        DEPLOY.replace("      - run: ./deploy.sh\n", "    - uses: actions/checkout@v4\n"),
    )
    repo.write(".github/workflows/notify.yml", notify("\n      group: prod-runners"))
    assert rows(repo) == [PASS]
