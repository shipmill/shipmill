"""Spec 054: `shipmill land --app-key` pushes the protected branches as the App, and without
it every push is the one land made before; a push the branch's rules refuse names the fix"""

import base64
import datetime as dt
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from shipmill.app import LAND_PERMISSIONS
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.land import AppPush, cleanup, land, mint_land, prepare
from shipmill.planner import Decision, Event, Hotfix
from shipmill.policy import Lane

from .conftest import Repo, at_day
from .test_app import APP_ID, REPO, FakeSigner, key_file
from .test_app_token import MintApi
from .test_lanes import plan, release

TOKEN = "ghs_theAppsToken"
APP = AppPush(TOKEN, APP_ID)
HEADER = "http.https://github.com/.extraheader"
AS_APP = (
    (HEADER, ""),
    (HEADER, "AUTHORIZATION: basic " + base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()),
)
Push = tuple[tuple[str, ...], tuple[tuple[str, str], ...]]  # one push's refspecs and git settings


class RecordingGit(Git):
    """A real Git that keeps each push's refspecs and settings, and every process's arguments
    and added environment"""

    def __init__(self, root: Path, env: Mapping[str, str]) -> None:
        super().__init__(root, "bot", "bot@example.com")
        self.env = dict(env)
        self.pushes: list[Push] = []
        self.argv: list[tuple[str, ...]] = []
        self.extra: list[dict[str, str]] = []

    def push(self, *refspecs: str, config: tuple[tuple[str, str], ...] = ()) -> str:
        self.pushes.append((refspecs, config))
        return super().push(*refspecs, config=config)

    def _proc(
        self, args: tuple[str, ...], stdin: bytes | None = None, extra: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        self.argv.append(args)
        self.extra.append(dict(extra or {}))
        return super()._proc(args, stdin, extra)


def _flow(repo: Repo, decision: Decision, app: AppPush | None) -> tuple[RecordingGit, str]:
    """prepare, land, and cleanup as the workflows run them, recorded; the release commit"""
    assert decision.action == "release", decision.reason
    assert decision.lane is not None and decision.version is not None
    git = RecordingGit(repo.root, repo.git.env)
    day = at_day(1).date()
    policy = repo.policy
    prepared = prepare(
        git, policy, decision.lane, decision.version, decision.base, day, decision.merges, decision.prs,
        commit=True, push=True,
    )  # fmt: skip
    land(git, policy, repo.github, decision.lane, decision.version, prepared.sha, decision.base, day, app=app)
    assert cleanup(git, decision.version)
    return git, prepared.sha


def _rc(repo: Repo) -> Decision:
    repo.merge(1, "Added", "Feature A")
    return plan(repo, at_day(1))


def _stable_unmoved(repo: Repo) -> Decision:
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    return plan(repo, at_day(4), event=Event.MANUAL, lane=Lane.STABLE)


def _stable_moved(repo: Repo) -> Decision:
    repo.merge(1, "Added", "Feature A")
    release(repo, plan(repo, at_day(1)))
    repo.at(at_day(1, 9))
    repo.merge(2, "Fixed", "Fix B, after the rc")
    return plan(repo, at_day(1, 9), event=Event.MANUAL, lane=Lane.STABLE)


def _hotfix(repo: Repo) -> Decision:
    repo.merge(1, "Added", "Feature A, not ready")
    repo.merge(2, "Fixed", "Urgent fix", "src/app.py", "VALUE = 2\n")
    return plan(repo, at_day(1), event=Event.MANUAL, lane=Lane.HOTFIX, hotfix=Hotfix((2,)))


def _expected(shape: str, tag: str, sha: str, protected: tuple[tuple[str, str], ...]) -> list[Push]:
    """The pushes land made before spec 054, in order, with the settings of the protected ones"""
    work = f"shipmill/{tag}"
    branch = {
        "rc": [],
        "stable unmoved": [((f"{sha}:refs/heads/main",), protected)],
        "stable moved": [],
        "hotfix": [((f"{sha}:refs/heads/release/1.0",), protected)],
    }[shape]
    synced = [(("HEAD:refs/heads/main",), protected)] if shape in ("stable moved", "hotfix") else []
    return [
        ((f"{sha}:refs/heads/{work}",), ()),
        *branch,
        ((f"refs/tags/{tag}",), ()),
        *synced,
        ((f":refs/heads/{work}",), ()),
    ]


SHAPES = {"rc": _rc, "stable unmoved": _stable_unmoved, "stable moved": _stable_moved, "hotfix": _hotfix}


@pytest.mark.parametrize("shape", list(SHAPES))
def test_s054_2_without_the_app_every_push_is_as_before(repo: Repo, shape: str) -> None:
    decision = SHAPES[shape](repo)
    assert decision.version is not None
    git, sha = _flow(repo, decision, None)
    assert git.pushes == _expected(shape, decision.version.tag, sha, ())
    # the same credential: no push adds a git setting or any environment of its own
    assert all(extra == {} for extra in git.extra)


@pytest.mark.parametrize("shape", list(SHAPES))
def test_s054_6_the_app_pushes_the_branches_and_the_workflow_token_the_tag_and_work_branch(
    repo: Repo, shape: str
) -> None:
    decision = SHAPES[shape](repo)
    assert decision.version is not None
    git, sha = _flow(repo, decision, APP)
    assert git.pushes == _expected(shape, decision.version.tag, sha, AS_APP)
    assert repo.git.remote_tag(decision.version.tag)


def test_s054_6_the_apps_settings_reach_git_through_its_environment(repo: Repo) -> None:
    decision = _stable_unmoved(repo)
    git, sha = _flow(repo, decision, APP)
    [pushed] = [e for a, e in zip(git.argv, git.extra, strict=True) if a[:1] == ("push",) and a[-1].endswith("main")]
    start = int(os.environ.get("GIT_CONFIG_COUNT", "0"))  # the host's own entries come first
    assert pushed == {
        "GIT_CONFIG_COUNT": str(start + 2),
        f"GIT_CONFIG_KEY_{start}": HEADER,
        f"GIT_CONFIG_VALUE_{start}": "",
        f"GIT_CONFIG_KEY_{start + 1}": HEADER,
        f"GIT_CONFIG_VALUE_{start + 1}": AS_APP[1][1],
    }
    assert repo.git.remote_branch("main") == sha


def test_s054_6_the_apps_settings_append_to_git_config_entries_already_in_the_environment(
    repo: Repo, tmp_path: Path
) -> None:
    # a job's own GIT_CONFIG_* entry (here a push URL) still applies to the App's push
    elsewhere = tmp_path / "elsewhere.git"
    subprocess.run(["git", "init", "-q", "--bare", str(elsewhere)], check=True)
    git = Git(repo.root)
    git.env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "remote.origin.pushurl",
        "GIT_CONFIG_VALUE_0": str(elsewhere),
    }
    assert git.push("HEAD:refs/heads/pushed", config=AS_APP) == ""
    assert Git(elsewhere).run("rev-parse", "refs/heads/pushed").strip() == repo.git.run("rev-parse", "HEAD").strip()
    assert repo.git.remote_branch("pushed") is None


def test_s054_6_a_malformed_git_config_count_in_the_environment_fails_naming_it(repo: Repo) -> None:
    git = Git(repo.root)
    git.env = {"GIT_CONFIG_COUNT": "two"}
    with pytest.raises(ReleaseError, match="GIT_CONFIG_COUNT is 'two', not a count"):
        git.push("HEAD:refs/heads/pushed", config=AS_APP)


def test_s054_7_no_process_argument_holds_the_token(repo: Repo) -> None:
    git, _ = _flow(repo, _stable_moved(repo), APP)
    secret = AS_APP[1][1].removeprefix("AUTHORIZATION: basic ")
    assert not [args for args in git.argv if any(TOKEN in a or secret in a for a in args)]
    assert TOKEN not in repr(APP)


# The CLI: `shipmill land --app-key`

AGENTS = f'\n[agents]\nprompt = "/t"\napp_id = {APP_ID}\n'


def _with_app_id(repo: Repo) -> None:
    repo.git.run("checkout", "-q", "main")
    repo.write(str(CONFIG_PATH), repo.read(str(CONFIG_PATH)) + AGENTS)
    repo.git.run("commit", "-qam", "Set [agents] app_id")
    repo.git.run("push", "-q", "origin", "main")


def _prepared(repo: Repo, decision: Decision) -> list[str]:
    """prepare as the workflow runs it; land's arguments"""
    assert decision.lane is not None and decision.version is not None
    day = at_day(1).date()
    prepared = prepare(
        repo.git, repo.policy, decision.lane, decision.version, decision.base, day, decision.merges, decision.prs,
        commit=True, push=True,
    )  # fmt: skip
    return [
        "--repo", str(repo.root), "land", "--lane", decision.lane.value, "--version", str(decision.version),
        "--sha", prepared.sha, "--base", decision.base, "--date", str(day),
    ]  # fmt: skip


def _origin(repo: Repo) -> str:
    return repo.git.run("ls-remote", "origin")


ENV = {"GITHUB_REPOSITORY": REPO}


def test_s054_4_an_app_key_without_app_id_exits_2_naming_the_key(repo: Repo, tmp_path: Path) -> None:
    argv = _prepared(repo, _stable_unmoved(repo))
    before = _origin(repo)
    api = MintApi()
    with pytest.raises(ReleaseError, match=r"--app-key names an App's key, but \[agents\] in .* sets no app_id"):
        main([*argv, "--app-key", str(key_file(tmp_path))], repo.github, api=api, signer=FakeSigner(), environ=ENV)
    assert _origin(repo) == before
    assert api.calls == [] and api.posts == []


def test_s054_5_land_mints_one_token_for_the_repo_with_contents_and_workflows_write(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _with_app_id(repo)
    argv = _prepared(repo, _stable_unmoved(repo))
    api = MintApi()
    key = key_file(tmp_path)
    assert main([*argv, "--app-key", str(key)], repo.github, api=api, signer=FakeSigner(), environ=ENV) == 0
    [(_, _, body)] = api.posts
    assert body == {"repositories": ["demo"], "permissions": {"contents": "write", "workflows": "write"}}
    assert {p.key: str(p.access) for p in LAND_PERMISSIONS} == {"contents": "write", "workflows": "write"}
    out = capsys.readouterr()
    assert '"placed": "main"' in out.out
    # S-054-7: no line of land's output holds the token or the key
    for said in (out.out, out.err):
        assert "token-1" not in said and "not a real key" not in said


@pytest.mark.parametrize(
    ("api", "problem", "fix"),
    [
        (MintApi(installed=False), f"app demo-agent is not installed on {REPO}", f"app-install {REPO}"),
        (
            MintApi(permissions={"contents": "write", "metadata": "read"}),
            f"app demo-agent on {REPO} lacks these permissions: Workflows: write",
            "grant them in the App's settings",
        ),
    ],
)
def test_s054_5_an_app_that_cant_push_exits_2_naming_the_fix_with_no_push(
    repo: Repo, tmp_path: Path, api: MintApi, problem: str, fix: str
) -> None:
    _with_app_id(repo)
    argv = _prepared(repo, _stable_unmoved(repo))
    before = _origin(repo)
    with pytest.raises(ReleaseError) as caught:
        main([*argv, "--app-key", str(key_file(tmp_path))], repo.github, api=api, signer=FakeSigner(), environ=ENV)
    said = str(caught.value)
    assert said.startswith(f"land can't push as the App {APP_ID}, so it pushed nothing: {problem}")
    assert "; fix: " in said and fix in said
    assert _origin(repo) == before
    assert api.posts == []


def test_s054_5_a_missing_key_exits_2_naming_it_with_no_push(repo: Repo, tmp_path: Path) -> None:
    _with_app_id(repo)
    argv = _prepared(repo, _stable_unmoved(repo))
    before = _origin(repo)
    missing = tmp_path / "absent.pem"
    with pytest.raises(ReleaseError, match=f"no App private key at {missing}; fix: download the App's private key"):
        main([*argv, "--app-key", str(missing)], repo.github, api=MintApi(), signer=FakeSigner(), environ=ENV)
    assert _origin(repo) == before


def test_s054_5_mint_land_never_falls_back(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="readable by group or others; fix: chmod 600"):
        mint_land(APP_ID, REPO, key_file(tmp_path, 0o644), dt.datetime.now(dt.UTC), FakeSigner(), MintApi())


# S-054-9: a push the branch's rules refuse


def _refuse_branch(repo: Repo, branch: str, message: str) -> None:
    """Make origin refuse pushes to branch with message, as GitHub's rules do"""
    origin = Path(repo.git.run("remote", "get-url", "origin").strip())
    hook = origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "while read old new ref; do\n"
        f'  if [ "$ref" = "refs/heads/{branch}" ]; then echo "{message}" >&2; exit 1; fi\n'
        "done\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)


FIX = "run shipmill doctor, and see Protected default branch in docs/release-lanes.md"
GH013 = "error: GH013: Repository rule violations found for refs/heads/{branch}."
GH006 = "error: GH006: Protected branch update failed for refs/heads/{branch}."


def _land(repo: Repo, decision: Decision, app: AppPush | None) -> None:
    assert decision.lane is not None and decision.version is not None
    day = at_day(1).date()
    policy = repo.policy
    prepared = prepare(
        repo.git, policy, decision.lane, decision.version, decision.base, day, decision.merges, decision.prs,
        commit=True, push=True,
    )  # fmt: skip
    land(repo.git, policy, repo.github, decision.lane, decision.version, prepared.sha, decision.base, day, app=app)


@pytest.mark.parametrize(
    ("shape", "branch", "refusal", "app", "identity"),
    [
        ("stable unmoved", "main", GH013, None, "github-actions[bot]"),
        ("stable unmoved", "main", GH006, APP, f"the App {APP_ID}"),
        ("hotfix", "release/1.0", GH013, APP, f"the App {APP_ID}"),
    ],
)
def test_s054_9_a_push_the_rules_refuse_names_doctor_and_the_docs(
    repo: Repo, shape: str, branch: str, refusal: str, app: AppPush | None, identity: str
) -> None:
    decision = SHAPES[shape](repo)
    _refuse_branch(repo, branch, refusal.format(branch=branch))
    with pytest.raises(ReleaseError) as caught:
        _land(repo, decision, app)
    said = str(caught.value)
    assert said.startswith("pushing ") and f" to {branch} was rejected: " in said
    assert said.endswith(f"; {branch}'s rules refuse {identity}: {FIX}")
    assert TOKEN not in said


def test_s054_9_a_sync_the_rules_refuse_fails_at_once_naming_the_fix(repo: Repo) -> None:
    decision = _stable_moved(repo)
    _refuse_branch(repo, "main", GH013.format(branch="main"))
    with pytest.raises(ReleaseError) as caught:
        _land(repo, decision, APP)
    said = str(caught.value)
    assert said.startswith("pushing the sync of 1.1.0 to main was rejected: ")
    assert said.endswith(f"; main's rules refuse the App {APP_ID}: {FIX}")


def test_s054_9_any_other_refusal_keeps_todays_message(repo: Repo) -> None:
    decision = _stable_unmoved(repo)
    _refuse_branch(repo, "main", "refused for another reason")
    with pytest.raises(ReleaseError) as caught:
        _land(repo, decision, None)
    said = str(caught.value)
    assert said.startswith("pushing ") and " to main was rejected: " in said
    assert "refused for another reason" in said and "shipmill doctor" not in said
    assert said.endswith("origin.git'")  # git's own last line, "failed to push some refs to '<origin>'"


def test_s054_9_a_sync_refused_otherwise_still_retries(repo: Repo) -> None:
    decision = _stable_moved(repo)
    _refuse_branch(repo, "main", "refused for another reason")
    with pytest.raises(ReleaseError, match="main kept moving: the sync of 1.1.0 failed 5 times"):
        _land(repo, decision, None)
