"""Spec 030: `shipmill gh`, as the App, refuses to merge a pull request with a `never` zone
(S-030-13). No test reaches the network: the pull request is FakeReads, GitHub MintApi"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shipmill.app_gh import Merge, merge_of
from shipmill.cli import main
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.github import FileChange, PullChange

from .conftest import POLICY, Repo
from .test_app import APP_ID, REPO, FakeSigner, key_file
from .test_app_token import FAKE_GH, MintApi, executable

CONFIG = CONFIG_PATH.as_posix()
WITH_APP = f'\n[agents]\nprompt = "/t"\napp_id = {APP_ID}\n'
URL = f"https://github.com/{REPO}/pull/7"
DIRECTION = FileChange("docs/product.md", "modified", "@@ -1,1 +1,1 @@\n-a\n+b", None)
CODE = FileChange("src/app.py", "modified", "@@ -1,1 +1,1 @@\n-VALUE = 1\n+VALUE = 2", None)


@dataclass
class FakeReads:
    """The pull request a merge names, as GhCli reads it"""

    files: tuple[FileChange, ...]
    url: str = URL
    numbers: list[int] = field(default_factory=list)
    selectors: list[str | None] = field(default_factory=list)

    def pull_change(self, number: int) -> PullChange:
        self.numbers.append(number)
        return PullChange(number, "b" * 40, "h" * 40, self.files)

    def text_at(self, sha: str, path: str) -> str:
        raise AssertionError(f"no file is read for these paths, got {path} at {sha}")

    def pull_of(self, selector: str | None) -> str:
        self.selectors.append(selector)
        return self.url + "\n"


@dataclass
class Reader:
    """The factory `shipmill gh` builds its reads with; records the env it is given"""

    reads: FakeReads
    envs: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, top: Path, binary: Path, env: Mapping[str, str]) -> FakeReads:
        self.envs.append(dict(env))
        return self.reads


@dataclass
class Runner:
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        self.calls.append(list(argv))
        return 0


def connected(repo: Repo, tmp_path: Path, config: str = POLICY + WITH_APP) -> Path:
    """The config on origin/HEAD, origin named on GitHub, and the App's key"""
    repo.write(CONFIG, config)
    repo.git.run("add", "-A")
    repo.git.run("commit", "-q", "-m", "connect")
    repo.git.run("push", "-q", "origin", "main")
    repo.git.run("remote", "set-head", "origin", "main")
    repo.git.run("remote", "set-url", "origin", f"https://github.com/{REPO}.git")
    return key_file(tmp_path)


def gh(
    repo: Repo,
    tmp_path: Path,
    key: Path,
    args: list[str],
    reader: Reader,
    runner: Runner,
    environ: Mapping[str, str] | None = None,
) -> int:
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    executable(fakes / "gh", FAKE_GH)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return main(
        ["--repo", str(repo.root), "gh", "--app-key", str(key), *args],
        api=MintApi(),
        signer=FakeSigner(),
        environ={"PATH": f"{fakes}:/usr/bin:/bin", **(environ or {})},
        home=home,
        gh_runner=runner,
        merge_reader=reader,
    )


MERGES = [
    ["pr", "merge", "7"],
    ["pr", "merge", "--squash", "--delete-branch", "7"],
    ["pr", "merge", "7", "-d", "--subject", "pr 9", "-b", "8"],
    ["pr", "-R", REPO, "merge", "#7", "--auto"],
    ["pr", "merge", f"--repo={REPO}", "-s", "7"],
    ["pr", "merge", URL],
    ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/merge"],
    ["api", "--method", "PUT", f"/repos/{REPO}/pulls/7/merge", "-f", "merge_method=squash"],
    ["api", "-XPUT", "repos/{owner}/{repo}/pulls/7/merge"],
    ["api", "--method=put", f"https://api.github.com/repos/{REPO}/pulls/7/merge"],
    ["api", "-X", "PUT", f"repos/{REPO}/pulls/007/merge"],  # GitHub reads 007 as 7
    ["api", "-X", "PUT", f"repos/{REPO}/pulls/%37/merge"],  # and %37 too
]


@pytest.mark.parametrize("args", MERGES)
def test_s030_13_a_merge_of_a_never_zone_pr_exits_2_without_running_gh(
    repo: Repo, tmp_path: Path, args: list[str]
) -> None:
    key = connected(repo, tmp_path)
    reader, runner = Reader(FakeReads((DIRECTION,))), Runner()
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        gh(repo, tmp_path, key, args, reader, runner)
    message = str(raised.value)
    assert "#7 in romamo/demo has a never zone (direction: docs/product.md edits the product's direction" in message
    assert "only the maintainer merges it, by hand" in message
    assert runner.calls == []
    assert reader.reads.numbers == [7]
    [env] = reader.envs
    assert (env["GH_TOKEN"], env["GH_REPO"]) == ("token-1", REPO)  # read as the App, in the checkout's repo


@pytest.mark.parametrize("args", MERGES)
def test_s030_13_a_merge_of_a_pr_without_a_never_zone_runs_gh_as_before(
    repo: Repo, tmp_path: Path, args: list[str]
) -> None:
    key = connected(repo, tmp_path)
    reader, runner = Reader(FakeReads((CODE,))), Runner()
    assert gh(repo, tmp_path, key, args, reader, runner) == 0
    [argv] = runner.calls
    assert argv[1:] == args
    assert reader.reads.numbers == [7]


@pytest.mark.parametrize(("args", "selector"), [(["pr", "merge", "feat/x", "-m"], "feat/x"), (["pr", "merge"], None)])
def test_s030_13_a_branch_or_the_current_branch_is_resolved_by_gh(
    repo: Repo, tmp_path: Path, args: list[str], selector: str | None
) -> None:
    key = connected(repo, tmp_path)
    reader, runner = Reader(FakeReads((DIRECTION,))), Runner()
    with pytest.raises(ReleaseError, match="has a never zone"):
        gh(repo, tmp_path, key, args, reader, runner)
    assert (reader.reads.selectors, reader.reads.numbers, runner.calls) == ([selector], [7], [])


def test_s030_13_the_levels_come_from_origin_head_not_the_working_tree(repo: Repo, tmp_path: Path) -> None:
    key = connected(repo, tmp_path, POLICY + WITH_APP + '\n[decisions]\ndirection = "ask"\n')
    reader, runner = Reader(FakeReads((DIRECTION,))), Runner()
    assert gh(repo, tmp_path, key, ["pr", "merge", "7"], reader, runner) == 0  # direction at ask: no hold here
    repo.write(CONFIG, POLICY + WITH_APP)  # the working tree's own levels don't count
    assert gh(repo, tmp_path, key, ["pr", "merge", "7"], reader, runner) == 0
    assert len(runner.calls) == 2


def test_s030_13_without_origin_head_a_merge_exits_2_naming_the_fix(repo: Repo, tmp_path: Path) -> None:
    key = connected(repo, tmp_path)
    repo.git.run("remote", "set-head", "origin", "--delete")
    reader, runner = Reader(FakeReads((CODE,))), Runner()
    with pytest.raises(ReleaseError) as raised:
        gh(repo, tmp_path, key, ["pr", "merge", "7"], reader, runner)
    assert "origin/HEAD is not set" in str(raised.value)
    assert f"`git -C {repo.root} remote set-head origin --auto`" in str(raised.value)
    assert runner.calls == []


def test_s030_13_a_base_without_the_config_exits_2_naming_the_fix(repo: Repo, tmp_path: Path) -> None:
    key = connected(repo, tmp_path)
    repo.git.run("rm", "-q", CONFIG)
    repo.git.run("commit", "-q", "-m", "drop the config")
    repo.git.run("update-ref", "refs/remotes/origin/main", "HEAD")  # as a fetch would; origin is on GitHub now
    repo.write(CONFIG, POLICY + WITH_APP)  # app_id is read from the working tree, the levels from the base
    reader, runner = Reader(FakeReads((CODE,))), Runner()
    with pytest.raises(ReleaseError) as raised:
        gh(repo, tmp_path, key, ["pr", "merge", "7"], reader, runner)
    message = str(raised.value)
    assert f"origin/HEAD has no {CONFIG}" in message
    assert "land the config on the default branch" in message
    assert f"`git -C {repo.root} fetch origin`" in message
    assert runner.calls == []


@pytest.mark.parametrize("args", [["pr", "merge", "7"], ["api", "-X", "PUT", "repos/{owner}/{repo}/pulls/7/merge"]])
def test_s030_13_gh_repo_in_host_form_names_the_checkouts_repo(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    key = connected(repo, tmp_path)
    reader, runner = Reader(FakeReads((CODE,))), Runner()
    assert gh(repo, tmp_path, key, args, reader, runner, {"GH_REPO": f"github.com/{REPO}"}) == 0
    assert [env["GH_REPO"] for env in reader.envs] == [REPO]
    assert len(runner.calls) == 1


def test_s030_13_a_merge_in_another_repo_is_refused(repo: Repo, tmp_path: Path) -> None:
    key = connected(repo, tmp_path)
    reader, runner = Reader(FakeReads((CODE,))), Runner()
    with pytest.raises(ReleaseError, match="merge it from a checkout of other/repo"):
        gh(repo, tmp_path, key, ["pr", "merge", "https://github.com/other/repo/pull/7"], reader, runner)
    assert (runner.calls, reader.reads.numbers) == ([], [])


@pytest.mark.parametrize(
    "args",
    [
        ["pr", "view", "7"],
        ["pr", "comment", "7", "--body", "pr merge 7"],
        ["pr", "create", "--title", "merge", "--body", "x"],
        ["api", f"repos/{REPO}/pulls/7/merge"],
        ["api", "-X", "GET", f"repos/{REPO}/pulls/7/merge"],
        ["api", "-X", "PUT", f"repos/{REPO}/pulls/7/requested_reviewers"],
        ["issue", "comment", "7", "--body", "merge"],
    ],
)
def test_s030_13_other_gh_calls_read_nothing(repo: Repo, tmp_path: Path, args: list[str]) -> None:
    key = connected(repo, tmp_path)
    reader, runner = Reader(FakeReads((DIRECTION,))), Runner()
    assert gh(repo, tmp_path, key, args, reader, runner) == 0
    assert reader.envs == []
    assert [argv[1:] for argv in runner.calls] == [args]


@pytest.mark.parametrize(
    ("args", "merge"),
    [
        (["pr", "merge", "-t", "merge", "12"], Merge("gh pr merge", 12, None, None)),
        (["pr", "merge", "-tmerge", "12"], Merge("gh pr merge", 12, None, None)),
        (["pr", "merge", "--", "12"], Merge("gh pr merge", 12, None, None)),
        (["pr", "merge", "--body-file", "b.md", "x"], Merge("gh pr merge", None, "x", None)),
        (["pr", "merge", "-R", "a/b"], Merge("gh pr merge", None, None, "a/b")),
        (["api", "-X", "PUT", "repos/{owner}/b/pulls/3/merge"], Merge("gh api -X PUT .../merge", 3, None, "{owner}/b")),
        (["api", "-X", "PUT", "-X", "GET", "repos/a/b/pulls/3/merge"], None),  # the last method counts
        (["api", "-H", "-X", "PUT", "repos/a/b/pulls/3/merge"], None),  # -X is -H's value; the method is PUT's
        (["pr", "-R", "merge", "view", "3"], None),  # -R's value is `merge`
        ([], None),
    ],
)
def test_s030_13_merge_of_reads_the_arguments_as_gh_does(args: list[str], merge: Merge | None) -> None:
    assert merge_of(args) == merge


def test_s030_13_a_placeholder_is_filled_from_the_default_repo() -> None:
    merge = merge_of(["api", "-X", "PUT", "repos/{owner}/{repo}/pulls/3/merge"])
    assert merge is not None and merge.target("a/b") == "a/b"
    assert Merge("x", 3, None, "{owner}/c").target("a/b") == "a/c"
    assert Merge("x", 3, None, None).target("a/b") == "a/b"
