"""Spec 032: `shipmill doctor`'s downstream block (S-032-15), and the docs that cover
downstream tests (S-032-16)"""

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import cli_command
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.doctor import DOWNSTREAM_CALLER, doctor, downstream_lacks
from shipmill.downstream import SECRET, Downstream, Found, Unreadable, app_on_host
from shipmill.errors import ReleaseError
from shipmill.init import downstream_caller_text

from .conftest import POLICY, Repo
from .test_app import FakeSigner, key_file
from .test_downstream_start import APP, REPORT_ONLY, REQUIRED, SECTION, DownstreamApi

ROOT = Path(__file__).parent.parent
FIX = f"`{cli_command()} init --downstream --force`"
GOOD = """\
name: Tests against the library
run-name: library ${{ inputs.library-ref }} (${{ inputs.shipmill-id }})
on:
  workflow_dispatch:
    inputs:
      library-repo: {required: true, type: string}
      library-ref: {required: true, type: string}
      shipmill-id: {required: true, type: string}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo testing
"""


@dataclass
class FakeReader:
    """The maintainer's gh: the library's secrets, and each downstream repo's workflow files by
    repo; a repo missing from files is one the login can't read"""

    names: frozenset[str] | None = frozenset({SECRET, "PYPI_TOKEN"})  # None: the read fails
    files: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            REQUIRED.repo: {REQUIRED.workflow: GOOD},
            REPORT_ONLY.repo: {REPORT_ONLY.workflow: GOOD},
        }
    )
    reads: list[str] = field(default_factory=list)

    def secrets(self) -> frozenset[str]:
        self.reads.append("secrets")
        if self.names is None:
            raise ReleaseError("gh secret list --app actions failed: HTTP 403: Resource not accessible")
        return self.names

    def workflow(self, downstream: Downstream) -> Found:
        self.reads.append(downstream.repo)
        if downstream.repo not in self.files:
            raise Unreadable(f"your gh login can't read {downstream.repo}")
        ref = downstream.ref if downstream.ref is not None else "trunk"
        return Found(ref, self.files[downstream.repo].get(downstream.workflow))


def clock() -> dt.datetime:
    return dt.datetime(2026, 10, 20, 9, 30, tzinfo=dt.UTC)


def library(repo: Repo, caller: str | None = None) -> None:
    """conftest's repo with [downstream] (two downstreams) and the caller init writes"""
    repo.write(str(CONFIG_PATH), POLICY + SECTION)
    if caller is not None:
        repo.write(str(DOWNSTREAM_CALLER), caller)


def block(
    repo: Repo,
    reader: FakeReader | None = None,
    api: DownstreamApi | None = None,
    key: Path | None = None,
    home: Path | None = None,
) -> list[tuple[str, str]]:
    """doctor's downstream lines, with the App's key on the host when key or api is given"""
    app = None
    if api is not None:
        app = app_on_host(key, home or repo.root / "home", FakeSigner(), api, clock)
    checks = doctor(repo.root, repo.github, downstream=reader, app=app)
    return [(c.status, c.detail) for c in checks if c.name == "downstream"]


def test_s032_15_a_policy_without_downstream_gets_no_downstream_block(repo: Repo, tmp_path: Path) -> None:
    reader = FakeReader()
    api = DownstreamApi()
    assert block(repo, reader, api, key_file(tmp_path)) == []
    assert reader.reads == []
    assert api.minted == []


def test_s032_15_the_caller_init_writes_passes_and_the_whole_block_is_green(repo: Repo, tmp_path: Path) -> None:
    library(repo, downstream_caller_text())
    lines = block(repo, FakeReader(), DownstreamApi(), key_file(tmp_path))
    assert [status for status, _ in lines] == ["PASS"] * 6
    assert lines[0][1] == (
        f"{DOWNSTREAM_CALLER} calls shipmill's downstream.yml on pull_request_target and workflow_dispatch"
        " with actions: write and checks: write"
    )
    assert lines[1][1] == f"the repository secret {SECRET} is set"
    assert lines[2][1] == (
        "consumer-app: library-tests.yml on release in example-org/consumer-app runs on workflow_dispatch"
        " with library-repo, library-ref, shipmill-id, and its run-name carries inputs.shipmill-id"
    )
    assert lines[3][1].startswith("private-app: tests.yaml on trunk in example-org/private-app runs on")
    assert (
        lines[4][1]
        == f"consumer-app: the App {APP} is installed on example-org/consumer-app with Actions: read and write"
    )


def test_s032_15_a_missing_caller_fails_naming_init_downstream_force(repo: Repo) -> None:
    library(repo)
    [caller, *_] = block(repo, FakeReader())
    assert caller == ("FAIL", f"[downstream] is set, but there is no {DOWNSTREAM_CALLER}: {FIX} writes it")


@pytest.mark.parametrize(
    ("cut", "named"),
    [
        ("  pull_request_target:\n    types: [opened, synchronize, reopened]\n", "the pull_request_target trigger"),
        ("    uses: shipmill/shipmill/.github/workflows/downstream.yml@v0\n", "the call to shipmill/shipmill"),
        ("  actions: write          # start this workflow's collect run\n", "actions: write"),
        ("  checks: write           # write one check per downstream on the pull request's head\n", "checks: write"),
    ],
)
def test_s032_15_a_caller_missing_a_part_fails_naming_it_and_the_fix(repo: Repo, cut: str, named: str) -> None:
    text = downstream_caller_text()
    assert cut in text
    library(repo, text.replace(cut, ""))
    status, detail = block(repo, FakeReader())[0]
    assert status == "FAIL"
    assert detail.startswith(f"{DOWNSTREAM_CALLER} lacks {named}")
    assert detail.endswith(f": rewrite it with {FIX}")


def test_s032_15_a_caller_without_the_workflow_dispatch_trigger_fails(repo: Repo) -> None:
    text = downstream_caller_text()
    start, end = text.index("  workflow_dispatch:\n"), text.index("permissions:\n")
    library(repo, text[:start] + text[end:])
    assert block(repo, FakeReader())[0] == (
        "FAIL",
        f"{DOWNSTREAM_CALLER} lacks the workflow_dispatch trigger: rewrite it with {FIX}",
    )


def test_s032_15_a_permission_named_only_in_a_comment_still_fails(repo: Repo) -> None:
    text = downstream_caller_text().replace("  checks: write  ", "  # checks: write")
    library(repo, text)
    assert block(repo, FakeReader())[0][1].startswith(f"{DOWNSTREAM_CALLER} lacks checks: write")


def test_s032_15_a_missing_secret_fails_and_an_unreadable_list_warns(repo: Repo) -> None:
    library(repo, downstream_caller_text())
    assert block(repo, FakeReader(names=frozenset({"PYPI_TOKEN"})))[1] == (
        "FAIL",
        f"no repository secret {SECRET}, so the workflow can't start a downstream run:"
        f" add App {APP}'s private key with `gh secret set {SECRET} < <the key file>`",
    )
    status, detail = block(repo, FakeReader(names=None))[1]
    assert status == "WARN"
    assert detail.startswith(f"can't read the repository secrets for {SECRET}: gh secret list")


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        (
            GOOD.replace("      library-ref: {required: true, type: string}\n", ""),
            "the workflow_dispatch input library-ref",
        ),
        (
            GOOD.replace("      library-repo: {required: true, type: string}\n", "").replace(
                "      shipmill-id: {required: true, type: string}\n", ""
            ),
            "the workflow_dispatch inputs library-repo, shipmill-id",
        ),
        (
            GOOD.replace(" (${{ inputs.shipmill-id }})", ""),
            "a run-name containing inputs.shipmill-id (run-name must contain inputs.shipmill-id)",
        ),
        (
            GOOD.replace("run-name:", "# run-name:"),
            "a run-name containing inputs.shipmill-id (run-name must contain inputs.shipmill-id)",
        ),
    ],
)
def test_s032_15_a_downstream_workflow_missing_a_part_fails_naming_it(repo: Repo, text: str, missing: str) -> None:
    library(repo, downstream_caller_text())
    reader = FakeReader()
    reader.files[REQUIRED.repo][REQUIRED.workflow] = text
    assert block(repo, reader)[2] == (
        "FAIL",
        f"consumer-app: library-tests.yml on release in example-org/consumer-app lacks {missing}",
    )


def test_s032_15_a_workflow_without_workflow_dispatch_lacks_the_trigger_and_its_inputs() -> None:
    text = GOOD.split("on:\n")[0] + "on:\n  push:\n"
    assert downstream_lacks(text) == [
        "the workflow_dispatch trigger",
        "the workflow_dispatch inputs library-repo, library-ref, shipmill-id",
    ]


def test_s032_15_a_workflow_not_on_the_ref_fails(repo: Repo) -> None:
    library(repo, downstream_caller_text())
    reader = FakeReader()
    del reader.files[REPORT_ONLY.repo][REPORT_ONLY.workflow]
    assert block(repo, reader)[3] == (
        "FAIL",
        "private-app: tests.yaml doesn't exist on trunk in example-org/private-app",
    )


def test_s032_15_a_downstream_the_login_cant_read_warns_naming_the_repo(repo: Repo) -> None:
    library(repo, downstream_caller_text())
    reader = FakeReader()
    del reader.files[REPORT_ONLY.repo]
    assert block(repo, reader)[3] == (
        "WARN",
        "private-app: your gh login can't read example-org/private-app, so tests.yaml there is unchecked;"
        " the first pull request's check `downstream: private-app` will show whether it starts",
    )


def test_s032_15_without_gh_the_reads_warn(repo: Repo) -> None:
    library(repo, downstream_caller_text())
    lines = block(repo, None)
    assert lines[1] == ("WARN", "can't read the repository secrets or the downstream workflows: gh isn't installed")


def test_s032_15_the_app_not_installed_or_lacking_actions_write_fails(repo: Repo, tmp_path: Path) -> None:
    library(repo, downstream_caller_text())
    api = DownstreamApi(installed={REPORT_ONLY.repo: {"actions": "read", "metadata": "read"}})
    *_, required, report_only = block(repo, FakeReader(), api, key_file(tmp_path))
    assert required == (
        "FAIL",
        f"consumer-app: the App {APP} is not installed on example-org/consumer-app, or lacks Actions: read and"
        " write: app library-downstream is not installed on example-org/consumer-app",
    )
    status, detail = report_only
    assert status == "FAIL"
    assert detail.startswith(f"private-app: the App {APP} is not installed on example-org/private-app")
    assert "lacks these permissions: Actions: write" in detail
    assert api.minted == []  # doctor reads the installation; it mints no token


def test_s032_15_a_key_at_the_default_path_is_used(repo: Repo, tmp_path: Path) -> None:
    library(repo, downstream_caller_text())
    home = tmp_path / "home"
    default = home / ".config" / "shipmill" / f"app-{APP}.pem"
    default.parent.mkdir(parents=True)
    key_file(default.parent).rename(default)
    lines = block(repo, FakeReader(), DownstreamApi(), home=home)
    assert [s for s, d in lines if "the App" in d] == ["PASS", "PASS"]


def test_s032_15_without_the_key_on_the_host_one_warn_says_the_installation_is_unchecked(
    repo: Repo, tmp_path: Path
) -> None:
    library(repo, downstream_caller_text())
    api = DownstreamApi()
    lines = block(repo, FakeReader(), api, home=tmp_path / "empty-home")
    unchecked = [line for line in lines if "installation" in line[1]]
    assert unchecked == [
        (
            "WARN",
            f"the App {APP}'s installation on each downstream is unchecked: its private key isn't on this host;"
            f" pass --app-key, or save it at ~/.config/shipmill/app-{APP}.pem",
        )
    ]
    assert block(repo, FakeReader())[-1] == unchecked[0]  # no probe at all says the same, once


def test_s032_15_a_key_that_github_refuses_warns_per_downstream(repo: Repo, tmp_path: Path) -> None:
    library(repo, downstream_caller_text())
    api = DownstreamApi(app_status=401)
    *_, required, _ = block(repo, FakeReader(), api, key_file(tmp_path))
    assert required[0] == "WARN"
    assert required[1].startswith(f"consumer-app: can't check the App {APP}'s installation on example-org/consumer-app")


def test_s032_15_through_the_cli_doctor_exits_1_and_prints_no_secret(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library(repo)
    key = key_file(tmp_path)
    argv = ["--repo", str(repo.root), "doctor", "--app-key", str(key)]
    code = main(
        argv,
        github=repo.github,
        api=DownstreamApi(),
        signer=FakeSigner(),
        environ={"PATH": ""},
        home=tmp_path / "home",
        downstream_reader=FakeReader(),
    )
    out = capsys.readouterr().out
    assert code == 1
    assert f"FAIL downstream: [downstream] is set, but there is no {DOWNSTREAM_CALLER}" in out
    assert f"PASS downstream: consumer-app: the App {APP} is installed on example-org/consumer-app" in out
    assert "not a real key" not in out
    assert "token-for-" not in out


# S-032-16


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_s032_16_release_lanes_has_a_downstream_tests_section() -> None:
    text = _text("docs/release-lanes.md")
    section = text.split("## Downstream tests\n", 1)[1].split("\n## ", 1)[0]
    for needle in (
        "[downstream]",
        "app_id",
        "timeout_minutes",
        "report_only",
        "workflow_dispatch",
        "library-repo",
        "library-ref",
        "shipmill-id",
        "run-name",
        "| Report-only |",
        "action_required",
        "gh workflow run downstream.yml -f pr=<N>",
        SECRET,
        "Actions: read and write",
        "shipmill init --downstream",
        "doctor",
    ):
        assert needle in section, needle
    assert "init --downstream" in text.split("## CLI\n", 1)[1]


def test_s032_16_setup_asks_about_dependents_and_reads_the_doctor_block() -> None:
    text = _text("skills/shipmill-setup/SKILL.md")
    section = text.split("### Downstream tests\n", 1)[1].split("\n## ", 1)[0]
    for needle in ("depend on", "[downstream]", "install the App", SECRET, "init --downstream", "doctor"):
        assert needle in section, needle


def test_s032_16_landing_treats_a_downstream_check_as_any_check() -> None:
    text = _text("skills/github-pr-triage/references/landing.md")
    section = text.split("## Downstream checks\n", 1)[1].split("\n## ", 1)[0]
    for needle in ("downstream: <name>", "red job", "gh workflow run downstream.yml -f pr=<N>", "shipmill gh"):
        assert needle in section, needle
    assert "action_required" in section and "maintainer" in section


def test_s032_16_pr_gate_says_a_downstream_check_is_read_like_any_check() -> None:
    doc = _text("skills/github-pr-triage/scripts/pr_gate.py").split('"""', 2)[1]
    assert "downstream: <name>" in doc
    assert "like any" in doc
