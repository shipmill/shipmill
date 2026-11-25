"""#1632: doctor reads the workflows, the config and pyproject.toml from the checkout's tree, so
its checkout row says when that tree is behind origin's default branch, read with git alone"""

from shipmill.doctor import Check, doctor

from .conftest import Repo

FIX = "git switch main && git pull, or run doctor from a worktree of origin/main"


def checkout(repo: Repo) -> list[Check]:
    return [c for c in doctor(repo.root) if c.name == "checkout"]


def advance_origin(repo: Repo, commits: int) -> str:
    """Push commits to origin's main and leave the local main where it was; the old HEAD's short sha"""
    old = repo.git.sha()
    for n in range(commits):
        repo.write("src/app.py", f"VALUE = {n + 2}\n")
        repo.git.run("commit", "-q", "-am", f"Change {n}")
    repo.git.run("push", "-q", "origin", "main")
    repo.git.run("reset", "-q", "--hard", old)
    return old[:7]


def test_1632_a_checkout_at_origins_default_branch_passes(repo: Repo) -> None:
    repo.git.run("remote", "set-head", "origin", "main")
    assert checkout(repo) == [
        Check("PASS", "checkout", "HEAD contains origin/main, the default branch as last fetched")
    ]


def test_1632_a_checkout_ahead_of_origins_default_branch_passes(repo: Repo) -> None:
    repo.git.run("remote", "set-head", "origin", "main")
    repo.write("src/app.py", "VALUE = 9\n")
    repo.git.run("commit", "-q", "-am", "Local work")
    assert [c.status for c in checkout(repo)] == ["PASS"]


def test_1632_a_branch_behind_origins_default_branch_warns_with_the_count_and_the_fix(repo: Repo) -> None:
    repo.git.run("remote", "set-head", "origin", "main")
    old = advance_origin(repo, 2)
    assert checkout(repo) == [
        Check(
            "WARN",
            "checkout",
            f"branch main is 2 commits behind origin/main, so the rows read from the working tree"
            f" (workflows, .github/shipmill.toml, pyproject.toml) describe {old}, not origin/main: {FIX}",
        )
    ]


def test_1632_a_detached_head_behind_origins_default_branch_warns(repo: Repo) -> None:
    repo.git.run("remote", "set-head", "origin", "main")
    old = advance_origin(repo, 1)
    repo.git.run("checkout", "-q", "--detach", "HEAD")
    assert checkout(repo) == [
        Check(
            "WARN",
            "checkout",
            f"a detached HEAD is 1 commit behind origin/main, so the rows read from the working tree"
            f" (workflows, .github/shipmill.toml, pyproject.toml) describe {old}, not origin/main: {FIX}",
        )
    ]


def test_1632_an_unset_origin_head_warns_and_never_crashes(repo: Repo) -> None:
    assert not repo.git.ok("symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    assert checkout(repo) == [
        Check(
            "WARN",
            "checkout",
            "origin/HEAD is unset, so doctor can't tell whether this checkout is behind origin's default branch:"
            " git remote set-head origin --auto",
        )
    ]


def test_1632_an_origin_head_that_cant_be_counted_warns(repo: Repo) -> None:
    repo.git.run("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
    [found] = checkout(repo)
    assert found.status == "WARN"
    assert found.detail.startswith("can't count the commits HEAD is behind origin/gone: git rev-list")


def test_1632_no_origin_remote_gives_no_row(repo: Repo) -> None:
    repo.git.run("remote", "remove", "origin")
    assert checkout(repo) == []


def test_1632_the_row_comes_before_the_rows_read_from_the_tree(repo: Repo) -> None:
    repo.git.run("remote", "set-head", "origin", "main")
    advance_origin(repo, 1)
    names = [c.name for c in doctor(repo.root)]
    assert names[:2] == ["policy", "checkout"]
    assert {"workflow", "version", "changelog"} <= set(names[2:])


def test_1632_a_config_that_fails_to_load_still_gets_the_row(repo: Repo) -> None:
    repo.git.run("remote", "set-head", "origin", "main")
    advance_origin(repo, 1)
    repo.write(repo.policy_file, "mode = [\n")
    assert [(c.status, c.name) for c in doctor(repo.root)] == [("FAIL", "policy"), ("WARN", "checkout")]
