"""Spec 038, `doctor` checks the product's repos: in the home repo, the App on each listed repo
and each one's [product] home, read with the product token (S-038-27, S-038-28); in a
component, its home's [product] repos, read with the maintainer's gh and nothing else of the
home (S-038-30). No test reaches the network: GitHub is DoctorApi, the gh is FakeHome"""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill import cli_command
from shipmill.app import Answer, product_cache
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.doctor import Check, ProductReads, doctor, product_on_host
from shipmill.downstream import GhReader
from shipmill.errors import ReleaseError
from shipmill.gate import state_dir
from shipmill.gitrepo import Git

from .conftest import POLICY, Repo
from .test_app import APP_ID, FakeSigner, key_file
from .test_app_gh import WITH_APP
from .test_app_token import executable
from .test_gate import NOW
from .test_product_token import ASKED, ProductApi

HOME = "romamo/demo"  # the checkout's repo, the product's home
LISTED = ("romamo/api", "romamo/web", "other-org/sdk")
FILE = CONFIG_PATH.as_posix()
NAMES_HOME = f'[product]\nhome = "{HOME}"\n'


def home_config(repos: str) -> str:
    return POLICY + "\n" + WITH_APP + f"\n[product]\nrepos = {repos}\n"


LISTS = home_config("[" + ", ".join(f'"{r}"' for r in LISTED) + "]")


def encoded(text: str) -> str:
    return json.dumps({"type": "file", "encoding": "base64", "content": base64.b64encode(text.encode()).decode()})


@dataclass
class DoctorApi(ProductApi):
    """ProductApi, plus each listed repo's config file read through the contents API; a repo
    missing from files has none (404). reads records each read and the token it carried"""

    files: dict[str, str] = field(default_factory=lambda: dict.fromkeys(LISTED, NAMES_HOME))
    reads: list[tuple[str, str | None]] = field(default_factory=list)

    def get(self, path: str, token: str | None) -> Answer:
        for repo in LISTED:
            if path == f"/repos/{repo}/contents/{FILE}":
                self.reads.append((repo, token))
                if repo not in self.files:
                    return Answer(404, '{"message": "Not Found"}')
                return Answer(200, encoded(self.files[repo]))
        return super().get(path, token)


def product_block(repo: Repo, api: DoctorApi | None, key: Path | None, home: str | None = HOME) -> list[Check]:
    """doctor's product lines in the home repo, with the App's key on the host when key is given"""
    probe = None
    if api is not None:
        cache = state_dir(Git(repo.root))
        probe = product_on_host(
            key, repo.root / "home", lambda owner: cache / product_cache(owner), FakeSigner(), api, lambda: NOW
        )
    checks = doctor(repo.root, repo.github, repo=home, product=probe)
    return [c for c in checks if c.name == "product"]


def lines(checks: list[Check]) -> list[tuple[str, str]]:
    return [(c.status, c.detail) for c in checks]


# -- S-038-27 --------------------------------------------------------------------------------


def test_s038_27_a_listed_repo_without_the_app_or_a_product_permission_fails_naming_app_install(
    repo: Repo, tmp_path: Path
) -> None:
    repo.write(str(CONFIG_PATH), LISTS)
    api = DoctorApi(
        installs={"romamo/api": 55, "romamo/web": 55},  # none on other-org/sdk
        granted={"romamo/web": {"contents": "read", "issues": "read", "pull_requests": "read", "metadata": "read"}},
    )
    api_line, web, sdk, waiting = lines(product_block(repo, api, key_file(tmp_path)))
    assert api_line == (
        "PASS",
        f"romamo/api: the App {APP_ID} is installed with Contents: read, Issues: write, Pull requests: read,"
        " Metadata: read",
    )
    assert web[0] == "FAIL"
    assert web[1].startswith("romamo/web: app demo-agent on romamo/web lacks these permissions: Issues: write")
    assert web[1].endswith(f"run `{cli_command()} app-install romamo/web`")
    assert sdk == (
        "FAIL",
        "other-org/sdk: app demo-agent is not installed on other-org/sdk; the coordinator can't reach it:"
        f" run `{cli_command()} app-install other-org/sdk`",
    )
    # romamo/api's config needs the product token over every listed repo of romamo, so it waits
    assert waiting == (
        "WARN",
        "romamo/api: its [product] home is unchecked: the product token over romamo's listed repos needs"
        " the App on romamo/web too",
    )
    assert api.posts == []  # no token is minted while one of the owner's repos lacks the App
    assert api.reads == []


@pytest.mark.parametrize(
    ("entries", "named"),
    [
        ('["romamo/api", "romamo"]', "repos holds 'romamo'; each repo is owner/name"),
        ('["romamo/api", "ROMAMO/API"]', "repos lists ROMAMO/API twice"),
        ("[]", "repos must list at least one repo"),
    ],
)
def test_s038_27_a_malformed_or_repeated_repos_entry_is_a_fail_row_and_doctor_runs_its_other_checks(
    repo: Repo, tmp_path: Path, entries: str, named: str
) -> None:
    repo.write(str(CONFIG_PATH), home_config(entries))
    api = DoctorApi()
    cache = state_dir(Git(repo.root))
    probe = product_on_host(
        key_file(tmp_path), tmp_path, lambda owner: cache / product_cache(owner), FakeSigner(), api, lambda: NOW
    )
    checks = doctor(repo.root, repo.github, repo=HOME, product=probe)
    [row] = [c for c in checks if c.name == "product"]
    assert row.status == "FAIL"
    assert f"[product]: {named}" in row.detail
    assert row.detail.endswith(f"fix [product] in {FILE}, which shipmill gate, gh, and app-token refuse until then")
    names = {c.name for c in checks}
    assert {"policy", "hooks", "decisions", "changelog", "workflow"} <= names  # the rest of doctor ran
    assert next(c for c in checks if c.name == "policy").status == "PASS"
    assert api.calls == []  # a refused table is never checked against GitHub


def test_s038_27_through_the_cli_a_malformed_entry_exits_1_not_2(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.write(str(CONFIG_PATH), home_config('["romamo/api", "romamo/api"]'))
    argv = ["--repo", str(repo.root), "doctor", "--app-key", str(key_file(tmp_path))]
    code = main(argv, github=repo.github, api=DoctorApi(), signer=FakeSigner(), environ={"PATH": ""}, home=tmp_path)
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL product: shipmill.toml [product]: repos lists romamo/api twice" in out
    assert "PASS policy:" in out


def test_s038_27_without_the_key_on_the_host_one_warn_says_the_repos_are_unchecked(repo: Repo, tmp_path: Path) -> None:
    repo.write(str(CONFIG_PATH), LISTS)
    api = DoctorApi()
    unchecked = (
        "WARN",
        f"the App {APP_ID}'s installation on each repo [product] repos lists, and their [product] home, are"
        f" unchecked: its private key isn't on this host; pass --app-key, or save it at"
        f" ~/.config/shipmill/app-{APP_ID}.pem",
    )
    assert lines(product_block(repo, api, None)) == [unchecked]
    assert lines(product_block(repo, None, None)) == [unchecked]
    assert api.calls == []


def test_s038_27_a_config_without_product_gets_no_product_line(repo: Repo, tmp_path: Path) -> None:
    repo.write(str(CONFIG_PATH), POLICY + "\n" + WITH_APP)
    api = DoctorApi()
    assert product_block(repo, api, key_file(tmp_path)) == []
    assert api.calls == []


# -- S-038-28 --------------------------------------------------------------------------------


def test_s038_28_a_component_with_no_or_another_home_warns_naming_the_fix_read_with_the_product_token(
    repo: Repo, tmp_path: Path
) -> None:
    repo.write(str(CONFIG_PATH), LISTS)
    api = DoctorApi(
        files={
            "romamo/api": f'[product]\nhome = "{HOME.upper()}"\n',  # case ignored
            "romamo/web": '[product]\nhome = "romamo/elsewhere"\n',
            # other-org/sdk has no config at all
        }
    )
    checks = product_block(repo, api, key_file(tmp_path))
    back = lines(checks)[len(LISTED) :]
    fix = f'set [product] home = "{HOME}" in'
    assert back == [
        ("PASS", f"romamo/api's [product] home names {HOME}"),
        (
            "WARN",
            f"romamo/web's [product] home names romamo/elsewhere, not this home {HOME}: {fix} romamo/web's {FILE}",
        ),
        (
            "WARN",
            f"other-org/sdk has no {FILE}, so it names no product home and its sessions see no coordinator:"
            f" {fix} other-org/sdk's {FILE}",
        ),
    ]
    # each read carried the product token over its owner's listed repos, minted once per owner
    minted = {path: body["repositories"] for path, body in api.posts}
    assert sorted(map(sorted, minted.values())) == [["api", "web"], ["sdk"]]  # type: ignore[arg-type]
    assert {token for _, token in api.reads} <= {"token-1", "token-2"}
    assert [read for read, _ in api.reads] == list(LISTED)
    for _, body in api.posts:
        assert body["permissions"] == ASKED
    assert not any("token-" in c.detail for c in checks)  # a token never reaches a line
    assert (state_dir(Git(repo.root)) / product_cache("romamo")).is_file()  # the app-token --product cache


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ('name = "api"\n', "has no [product] home"),
        (WITH_APP + '\n[product]\nrepos = ["romamo/x"]\n', "has no [product] home"),  # a home itself
        ('[product]\nrepos = ["romamo/x"]\n', "repos needs [agents] app_id"),
        ("[product\n", "can't read its"),
        ('[product]\nhome = "nope"\n', "can't read its"),
    ],
)
def test_s038_28_a_component_config_without_a_home_or_that_cant_be_read_warns(
    repo: Repo, tmp_path: Path, text: str, named: str
) -> None:
    repo.write(str(CONFIG_PATH), home_config('["romamo/api"]'))
    api = DoctorApi(files={"romamo/api": text})
    _, back = lines(product_block(repo, api, key_file(tmp_path)))
    assert back[0] == "WARN"
    assert back[1].startswith("romamo/api")
    assert named in back[1]


def test_s038_28_without_a_github_origin_the_home_cant_be_told_and_no_token_is_minted(
    repo: Repo, tmp_path: Path
) -> None:
    repo.write(str(CONFIG_PATH), LISTS)
    api = DoctorApi()
    *passed, warn = lines(product_block(repo, api, key_file(tmp_path), home=None))
    assert [s for s, _ in passed] == ["PASS"] * len(LISTED)
    assert warn[0] == "WARN"
    assert "this checkout's origin isn't a GitHub repo" in warn[1]
    assert api.posts == []


def test_s038_28_a_home_that_lists_itself_fails_and_checks_nothing_more(repo: Repo, tmp_path: Path) -> None:
    repo.write(str(CONFIG_PATH), home_config(f'["romamo/api", "{HOME}"]'))
    api = DoctorApi()
    [(status, detail)] = lines(product_block(repo, api, key_file(tmp_path)))
    assert status == "FAIL"
    assert detail.startswith(f"[product] repos lists {HOME}, this checkout's own repo")
    assert api.calls == []


# -- S-038-30 --------------------------------------------------------------------------------


@dataclass
class FakeHome:
    """The maintainer's gh: each repo's files by path; a missing one answers 404 (None)"""

    files: dict[str, dict[str, str]] = field(default_factory=dict)
    error: str | None = None
    reads: list[tuple[str, str]] = field(default_factory=list)

    def file(self, repo: str, path: str) -> str | None:
        self.reads.append((repo, path))
        if self.error is not None:
            raise ReleaseError(self.error)
        return self.files.get(repo, {}).get(path)


class NoProbe:
    """A product probe that fails the test when called: a component mints no App token"""

    calls: list[int]

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, app_id: int) -> ProductReads | None:
        self.calls.append(app_id)
        raise AssertionError("a component's doctor asks nothing of the App")


COMPONENT = "romamo/api"  # the checkout's repo, a component of HOME


def component_block(repo: Repo, home: FakeHome | None, slug: str | None = COMPONENT) -> list[tuple[str, str]]:
    repo.write(str(CONFIG_PATH), POLICY + "\n" + WITH_APP + "\n" + NAMES_HOME)
    probe = NoProbe()
    checks = doctor(repo.root, repo.github, repo=slug, product=probe, home_reader=home)
    assert probe.calls == []
    return lines([c for c in checks if c.name == "product"])


def home_files(text: str) -> FakeHome:
    return FakeHome(files={HOME: {FILE: text}})


def test_s038_30_no_warn_when_the_homes_repos_lists_this_repo_case_ignored(repo: Repo) -> None:
    home = home_files(POLICY + "\n" + WITH_APP + '\n[product]\nrepos = ["ROMAMO/Api", "romamo/web"]\n')
    assert component_block(repo, home) == [("PASS", f"{HOME}'s [product] repos lists {COMPONENT}")]
    assert home.reads == [(HOME, FILE)]  # the home's config, and nothing else of the home repo


@pytest.mark.parametrize(
    "text",
    [
        WITH_APP + '\n[product]\nrepos = ["romamo/web"]\n',
        WITH_APP,  # no [product] at all
        '[product]\nhome = "romamo/other"\n',  # the home is itself a component
    ],
)
def test_s038_30_a_home_whose_repos_doesnt_list_this_repo_warns_naming_the_fix(repo: Repo, text: str) -> None:
    home = home_files(text)
    assert component_block(repo, home) == [
        (
            "WARN",
            f"{HOME}'s [product] repos doesn't list {COMPONENT}, so its coordinator never routes this repo's"
            f' upstream reports: add "{COMPONENT}" to [product] repos in {HOME}\'s {FILE}',
        )
    ]
    assert home.reads == [(HOME, FILE)]


@pytest.mark.parametrize(
    ("home", "why"),
    [
        (FakeHome(), f"GitHub has no such file, or your gh login can't read {HOME}"),
        (home_files("[product\n"), f"{HOME}:{FILE}"),
        (home_files('[product]\nrepos = ["romamo/api"]\n'), "repos needs [agents] app_id"),
        (FakeHome(error="gh api repos/romamo/demo/contents failed: HTTP 403"), "HTTP 403"),
        (None, "gh isn't installed"),
    ],
)
def test_s038_30_a_home_config_that_cant_be_read_warns_naming_the_home(
    repo: Repo, home: FakeHome | None, why: str
) -> None:
    [(status, detail)] = component_block(repo, home)
    assert status == "WARN"
    assert detail.startswith(f"can't read {HOME}'s {FILE}, so whether its [product] repos lists {COMPONENT}")
    assert why in detail


def test_s038_30_writes_nothing_in_the_home_and_needs_the_checkouts_repo(repo: Repo) -> None:
    home = home_files(WITH_APP + f'\n[product]\nrepos = ["{COMPONENT}"]\n')
    [(status, detail)] = component_block(repo, home, slug=None)
    assert status == "WARN"
    assert "this checkout's origin isn't a GitHub repo" in detail
    assert home.reads == []  # nothing is read when the back-link can't be compared
    status, _ = component_block(repo, home)[0]
    assert status == "PASS"
    assert home.reads == [(HOME, FILE)]  # FakeHome has only reads: there is no write to make


FAKE_GH = """#!/bin/sh
printf '%s\\n' "$@" > "$(dirname "$0")/args"
case "$4" in
  repos/romamo/demo/*) printf '[product]\\nrepos = ["romamo/api"]\\n' ;;
  repos/romamo/gone/*) echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;
  *) echo 'gh: Resource not accessible (HTTP 403)' >&2; exit 1 ;;
esac
"""


def test_s038_30_the_gh_reader_reads_one_file_of_the_home_and_a_404_is_none(tmp_path: Path) -> None:
    gh = executable(tmp_path / "gh", FAKE_GH)
    reader = GhReader(tmp_path, str(gh))
    assert reader.file(HOME, FILE) == '[product]\nrepos = ["romamo/api"]\n'
    args = (tmp_path / "args").read_text(encoding="utf-8").splitlines()
    assert args == ["api", "-H", "Accept: application/vnd.github.raw", f"repos/{HOME}/contents/{FILE}"]
    assert reader.file("romamo/gone", FILE) is None
    with pytest.raises(ReleaseError, match="HTTP 403"):
        reader.file("romamo/private", FILE)


def test_s038_30_the_cli_reads_the_home_through_gh_never_with_the_apps_token(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.write(str(CONFIG_PATH), POLICY + "\n" + WITH_APP + "\n" + NAMES_HOME)
    api = DoctorApi()
    argv = ["--repo", str(repo.root), "doctor", "--app-key", str(key_file(tmp_path))]
    main(argv, github=repo.github, api=api, signer=FakeSigner(), environ={"PATH": ""}, home=tmp_path)
    out = capsys.readouterr().out
    assert "product: can't check that romamo/demo's [product] repos lists this repo" in out
    assert api.calls == []  # a component's doctor asks nothing of the App about its home
    assert api.posts == []
