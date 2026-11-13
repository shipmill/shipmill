"""Spec 055, S-055-17: `shipmill gh pr create` as the App reads the body it would send with
pr_gate.py's plan_problems, by the ids of docs/product.md on the default branch, and gh never
runs for a body whose plan doesn't hold. No test reaches the network: GitHub is MintApi, openssl
FakeSigner, and gh Runner"""

import io
import subprocess
from pathlib import Path

import pytest

from shipmill.agent_marker import MARKER
from shipmill.app_gh import other_body
from shipmill.cli import main
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git

from .test_app import REPO, FakeSigner, key_file
from .test_app_gh import WITH_APP, Host, Runner, checkout, default_branch
from .test_app_token import FAKE_GH, MintApi, executable
from .test_pr_gate import DIRECTION, PLAN

PRODUCT = {"docs/product.md": DIRECTION}
NO_PLAN = "Fixes #7\n\nIt works.\n"


@pytest.fixture
def host(tmp_path: Path) -> Host:
    fakes, record, home = tmp_path / "fakes", tmp_path / "record", tmp_path / "home"
    for folder in (fakes, record, home):
        folder.mkdir()
    executable(fakes / "gh", FAKE_GH)
    return Host(fakes, record, home)


def connected(tmp_path: Path, files: dict[str, str] = PRODUCT) -> Path:
    """A checkout with the App, origin/HEAD at a commit holding files"""
    root = checkout(tmp_path, WITH_APP)
    default_branch(root, files)
    key_file(tmp_path)
    return root


def create(root: Path, host: Host, runner: Runner, args: list[str], stdin: str = "") -> int:
    return main(
        ["--repo", str(root), "gh", "--app-key", str(root.parent / "app.pem"), "pr", "create", "--title", "t", *args],
        api=MintApi(),
        signer=FakeSigner(),
        stdin=io.StringIO(stdin),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
    )


def refused(root: Path, host: Host, args: list[str], stdin: str = "") -> str:
    runner = Runner()
    with pytest.raises(ReleaseError) as raised:  # cli.run prints it and exits 2
        create(root, host, runner, args, stdin)
    assert runner.calls == []  # gh never runs
    return str(raised.value)


def sent(root: Path, host: Host, args: list[str], stdin: str = "") -> str:
    """The --body gh ran with"""
    runner = Runner()
    assert create(root, host, runner, args, stdin) == 7
    [(argv, _)] = runner.calls
    return argv[argv.index("--body") + 1]


def test_s055_17_a_body_with_no_plan_is_refused_and_gh_never_runs(tmp_path: Path, host: Host) -> None:
    said = refused(connected(tmp_path), host, ["--body", NO_PLAN])
    assert "gh pr create is refused: the body's plan doesn't hold" in said
    assert "\n  no `## Plan` section; an agent's pull request carries its plan" in said


def test_s055_17_each_problem_of_the_plan_is_printed(tmp_path: Path, host: Host) -> None:
    body = PLAN.replace("- Serves: G-3", "- Serves: G-9, G-1").replace("- Proof: tests/test_app.py\n", "")
    said = refused(connected(tmp_path), host, ["--body", body])
    assert said.splitlines()[1:] == [
        "  the plan has no `Proof:` line",
        "  `Serves:` names G-9, which docs/product.md doesn't list",
    ]


@pytest.mark.parametrize("flag", ["--body-file", "-F"])
def test_s055_17_a_body_file_is_checked_as_gh_would_send_it(tmp_path: Path, host: Host, flag: str) -> None:
    root = connected(tmp_path)
    bad, good = tmp_path / "bad.md", tmp_path / "good.md"
    bad.write_text(NO_PLAN, encoding="utf-8")
    good.write_text(PLAN, encoding="utf-8")
    assert "no `## Plan` section" in refused(root, host, [flag, str(bad)])
    assert sent(root, host, [flag, str(good)]) == f"{PLAN}\n{MARKER}"


def test_s055_17_a_body_on_stdin_is_read_once_and_checked(tmp_path: Path, host: Host) -> None:
    root = connected(tmp_path)
    assert "no `## Plan` section" in refused(root, host, ["--body-file", "-"], stdin=NO_PLAN)
    # gh gets the body read from stdin as --body, so it never reads stdin again
    assert sent(root, host, ["-F", "-"], stdin=PLAN) == f"{PLAN}\n{MARKER}"


@pytest.mark.parametrize("flag", ["--body", "-b"])
def test_s055_17_a_valid_plan_runs_gh(tmp_path: Path, host: Host, flag: str) -> None:
    assert sent(connected(tmp_path), host, [flag, PLAN]) == f"{PLAN}\n{MARKER}"


def test_s055_17_a_plan_read_from_a_moved_goals_section_runs_gh(tmp_path: Path, host: Host) -> None:
    moved = DIRECTION.replace("- G-1: Ship\n- G-3: Ship faster\n", "See [Goals](product/goals.md).\n")
    files = {"docs/product.md": moved, "docs/product/goals.md": "## Goals\n\n- G-3: Ship faster\n"}
    assert sent(connected(tmp_path, files), host, ["--body", PLAN]) == f"{PLAN}\n{MARKER}"


@pytest.mark.parametrize("line", ["Spec for #12", "- Spec for #12", f"Spec for {REPO}#12"])
def test_s055_17_a_spec_body_needs_no_plan(tmp_path: Path, host: Host, line: str) -> None:
    body = f"{line}\n\nThe spec.\n"
    assert sent(connected(tmp_path), host, ["--body", body]) == f"{body}\n{MARKER}"


def test_s055_17_a_spec_line_of_another_repo_is_no_spec_body(tmp_path: Path, host: Host) -> None:
    assert "no `## Plan` section" in refused(connected(tmp_path), host, ["--body", "Spec for other/repo#12\n"])


def test_s055_17_a_repo_without_a_direction_on_its_default_branch_is_not_checked(tmp_path: Path, host: Host) -> None:
    root = connected(tmp_path, {})
    (root / "docs").mkdir()
    (root / "docs" / "product.md").write_text(DIRECTION, encoding="utf-8")  # the work tree's, not the branch's
    assert sent(root, host, ["--body", NO_PLAN]) == f"{NO_PLAN}\n{MARKER}"


def test_s055_17_the_direction_is_read_from_the_default_branch_not_the_work_tree(tmp_path: Path, host: Host) -> None:
    root = connected(tmp_path)
    (root / "docs" / "product.md").unlink()
    assert "no `## Plan` section" in refused(root, host, ["--body", NO_PLAN])


def bare_origin(tmp_path: Path, files: dict[str, str], branch: str = "trunk") -> Path:
    """A local bare origin whose default branch, branch, holds files"""
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    git_run(tmp_path, "init", "-q", "--bare", "-b", branch, str(origin))
    git_run(tmp_path, "init", "-q", "-b", branch, str(seed))
    for name, text in files.items():
        (seed / name).parent.mkdir(parents=True, exist_ok=True)
        (seed / name).write_text(text, encoding="utf-8")
    git_run(seed, "add", "-A")
    git_run(seed, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "b")
    git_run(seed, "push", "-q", str(origin), f"HEAD:refs/heads/{branch}")
    return origin


def git_run(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def unset_head(tmp_path: Path, origin: Path, fetched: bool = False) -> Path:
    """A checkout with the App whose origin is origin and that has no origin/HEAD, as one made
    by `git fetch` or actions/checkout; fetched leaves origin's branches fetched"""
    root = checkout(tmp_path, WITH_APP, origin=str(origin))
    if fetched:
        git_run(root, "fetch", "-q", "origin")
        git_run(root, "remote", "set-head", "origin", "--delete")  # a newer git's fetch sets it
    assert not Git(root).ok("rev-parse", "--verify", "--quiet", "origin/HEAD")
    key_file(tmp_path)
    return root


R = ["-R", REPO]  # the origin is a local path, so -R names the GitHub repo


@pytest.mark.parametrize("fetched", [False, True])
def test_s055_17_without_origin_head_the_default_branch_is_read_from_origin(
    tmp_path: Path, host: Host, fetched: bool
) -> None:
    root = unset_head(tmp_path, bare_origin(tmp_path, PRODUCT), fetched)
    assert "no `## Plan` section" in refused(root, host, [*R, "--body", NO_PLAN])
    assert sent(root, host, [*R, "--body", PLAN]) == f"{PLAN}\n{MARKER}"
    assert Git(root).ok("rev-parse", "--verify", "--quiet", "origin/trunk")  # fetched once it was missing


def test_s055_17_without_origin_head_a_default_branch_without_a_direction_is_not_checked(
    tmp_path: Path, host: Host
) -> None:
    root = unset_head(tmp_path, bare_origin(tmp_path, {"README.md": "demo\n"}))
    assert sent(root, host, [*R, "--body", NO_PLAN]) == f"{NO_PLAN}\n{MARKER}"


def test_s055_17_a_default_branch_that_cant_be_resolved_is_refused_naming_why(tmp_path: Path, host: Host) -> None:
    root = unset_head(tmp_path, tmp_path / "gone.git")
    said = refused(root, host, [*R, "--body", PLAN])
    assert "origin/HEAD is not set" in said and "origin's default branch can't be read: git ls-remote" in said


def test_s055_17_an_unresolved_default_branch_still_lets_a_spec_body_through(tmp_path: Path, host: Host) -> None:
    root = unset_head(tmp_path, tmp_path / "gone.git")
    assert sent(root, host, [*R, "--body", "Spec for #12\n"]) == f"Spec for #12\n\n{MARKER}"


def test_s055_17_a_direction_the_gate_cant_read_is_refused(tmp_path: Path, host: Host) -> None:
    root = connected(tmp_path, {"docs/product.md": DIRECTION.replace("- G-1: Ship", "- G1 Ship")})
    assert "the plan can't be checked: docs/product.md:" in refused(root, host, ["--body", PLAN])


@pytest.mark.parametrize(
    "flags",
    [["--fill"], ["-f"], ["--fill-first"], ["--fill-verbose"], ["--template", "t.md"], ["-T", "t.md"]]
    + [["--recover", "r.json"]],
)
def test_s055_17_a_flag_that_may_send_another_body_is_refused(tmp_path: Path, host: Host, flags: list[str]) -> None:
    said = refused(connected(tmp_path), host, [*flags, "--body", PLAN])
    assert f"gh pr create {flags[0]} is refused: gh may send a body from it" in said


def test_s055_17_a_switch_turned_off_sends_the_checked_body() -> None:
    assert other_body(["pr", "create", "--fill=false", "--body", "b"]) is None
    assert other_body(["pr", "create", "--title", "--fill", "--body", "b"]) is None  # a value is never a flag


@pytest.mark.parametrize("args", [["--web"], ["-e"], []])
def test_s055_17_a_body_gh_would_ask_for_stays_refused(tmp_path: Path, host: Host, args: list[str]) -> None:
    assert "is refused" in refused(connected(tmp_path), host, args)


def api(root: Path, host: Host, runner: Runner, args: list[str], stdin: str = "") -> int:
    return main(
        ["--repo", str(root), "gh", "--app-key", str(root.parent / "app.pem"), "api", *args],
        api=MintApi(),
        signer=FakeSigner(),
        stdin=io.StringIO(stdin),
        environ=host.env(),
        home=host.home,
        gh_runner=runner,
    )


def api_refused(root: Path, host: Host, args: list[str], stdin: str = "") -> str:
    runner = Runner()
    with pytest.raises(ReleaseError) as raised:
        api(root, host, runner, args, stdin)
    assert runner.calls == []  # gh never runs
    return str(raised.value)


def api_sent(root: Path, host: Host, args: list[str], stdin: str = "") -> list[str]:
    """gh's args past `api`, as it ran"""
    runner = Runner()
    assert api(root, host, runner, args, stdin) == 7
    [(argv, _)] = runner.calls
    return argv[argv.index("api") + 1 :]


PULLS = f"repos/{REPO}/pulls"


@pytest.mark.parametrize(
    "args",
    [
        [PULLS, "-f", "title=t", "-f", f"body={NO_PLAN}"],
        ["-X", "POST", PULLS, "-F", f"body={NO_PLAN}"],
        ["--method=post", f"{PULLS}/", "--field", f"body={NO_PLAN}"],
        [PULLS, "--raw-field", f"body={NO_PLAN}"],
        [f"https://api.github.com/{PULLS}?x=1", "-f", f"body={NO_PLAN}"],
        [f"{PULLS}#x", "-f", f"body={NO_PLAN}"],  # gh's URL parser drops the fragment: a POST on pulls
        [f"repos/{REPO}/pull%73", "-f", f"body={NO_PLAN}"],  # percent-decoded as GitHub decodes it
        ["repos/{owner}/{repo}/pulls", "-f", f"body={NO_PLAN}"],
        ["-X", "POST", PULLS, "-f", "title=t"],  # no body: the marker alone, which has no plan
    ],
)
def test_s055_17_a_rest_pull_request_create_with_no_plan_is_refused(
    tmp_path: Path, host: Host, args: list[str]
) -> None:
    said = api_refused(connected(tmp_path), host, ["-f", "head=b", *args])
    assert "is refused: the body's plan doesn't hold" in said and "no `## Plan` section" in said


def test_s055_17_a_rest_pull_request_body_from_a_file_or_stdin_is_checked(tmp_path: Path, host: Host) -> None:
    root = connected(tmp_path)
    bad, good = tmp_path / "bad.md", tmp_path / "good.md"
    bad.write_text(NO_PLAN, encoding="utf-8")
    good.write_text(PLAN, encoding="utf-8")
    assert "no `## Plan` section" in api_refused(root, host, [PULLS, "-F", f"body=@{bad}"])
    assert "no `## Plan` section" in api_refused(root, host, [PULLS, "-F", "body=@-"], stdin=NO_PLAN)
    assert api_sent(root, host, [PULLS, "-F", f"body=@{good}"]) == [PULLS, "-f", f"body={PLAN}\n{MARKER}"]
    assert api_sent(root, host, [PULLS, "-F", "body=@-"], stdin=PLAN) == [PULLS, "-f", f"body={PLAN}\n{MARKER}"]


def test_s055_17_a_rest_pull_request_with_a_valid_plan_runs_gh(tmp_path: Path, host: Host) -> None:
    sent_args = api_sent(connected(tmp_path), host, ["-X", "POST", PULLS, "-f", f"body={PLAN}"])
    assert sent_args == ["-X", "POST", PULLS, "-f", f"body={PLAN}\n{MARKER}"]


def test_s055_17_a_rest_pull_request_with_input_stays_refused(tmp_path: Path, host: Host) -> None:
    said = api_refused(connected(tmp_path), host, [PULLS, "--input", "-"], stdin='{"body": "b"}')
    assert "with --input is refused" in said


@pytest.mark.parametrize(
    "args",
    [
        [PULLS],  # lists them
        ["-X", "GET", PULLS, "-f", "state=open"],  # a field with GET named stays a GET
        [f"repos/{REPO}/pulls/7"],
        ["-X", "PATCH", f"repos/{REPO}/pulls/7", "-f", "title=t"],
        [f"repos/{REPO}/pulls/7/comments", "-f", f"body={NO_PLAN}"],
        [f"repos/{REPO}/issues", "-f", f"body={NO_PLAN}"],
    ],
)
def test_s055_17_other_api_calls_are_not_checked(tmp_path: Path, host: Host, args: list[str]) -> None:
    api_sent(connected(tmp_path), host, args)


def test_s055_17_other_commands_are_not_checked(tmp_path: Path, host: Host) -> None:
    root = connected(tmp_path)
    runner = Runner()
    args = ["--repo", str(root), "gh", "--app-key", str(tmp_path / "app.pem"), "pr", "comment", "7", "--body", NO_PLAN]
    assert main(args, api=MintApi(), signer=FakeSigner(), environ=host.env(), home=host.home, gh_runner=runner) == 7
    assert len(runner.calls) == 1
