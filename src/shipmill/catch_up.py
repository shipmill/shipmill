"""The local default branch against origin's, and the gate's catch-up of it (#886, D-66).

`shipmill status` reads where the branch releases land on stands against GitHub's (read_main,
S-011-16) and only reports it (D-55). Each `shipmill gate` tick, unless [agents] catch_up =
false, catches that branch up by fast-forward only, where that can't lose work: with
`git fetch origin <b>:<b>` when no worktree has it checked out, and with `git pull --ff-only`
in the repo's main checkout when that checkout has it checked out, has a clean tree, and the
branch is only behind. Anything else changes nothing and stays reported by `shipmill status`.
It never switches, stashes, resets, or rebases a checkout, and never forces a ref.
"""

import enum
from dataclasses import dataclass

from shipmill.gitrepo import REMOTE, Git
from shipmill.worktrees import parse_worktrees


@dataclass(frozen=True, slots=True)
class Main:
    """The branch releases land on (the config's `branch`, else GitHub's default branch, #694)
    here and on GitHub; local is None without a local branch, and checked_out says whether the
    checkout is on it"""

    branch: str
    local: str | None
    remote: str
    ahead: int
    behind: int
    checked_out: bool


def read_main(git: Git, branch: str) -> Main:
    """After watch_state.py's fetch, so origin's branch is GitHub's"""
    remote = git.run("rev-parse", "--verify", "-q", f"refs/remotes/{REMOTE}/{branch}^{{commit}}").strip()
    if not git.ok("rev-parse", "--verify", "-q", f"refs/heads/{branch}"):
        return Main(branch, None, remote, 0, 0, False)
    local = git.sha(f"refs/heads/{branch}")
    ahead, behind = git.run("rev-list", "--left-right", "--count", f"{local}...{remote}").split()
    on = (
        git.ok("symbolic-ref", "-q", "HEAD") and git.run("symbolic-ref", "-q", "HEAD").strip() == f"refs/heads/{branch}"
    )
    return Main(branch, local, remote, int(ahead), int(behind), on)


class How(enum.StrEnum):
    """How a catch-up moves the branch"""

    FETCH = "fetch"  # checked out nowhere: `git fetch origin <b>:<b>` moves the ref alone
    PULL = "pull"  # checked out in the main checkout, clean: `git -C <checkout> pull --ff-only`


@dataclass(frozen=True, slots=True)
class CatchUp:
    """What a tick's catch-up did: the branch, how many commits it was behind origin's, and how
    it moved (None: it moved nothing, being up to date, ahead, diverged, dirty, or checked out
    elsewhere); error, a git failure's first line, which changes nothing else in the tick. On a
    dry run, how is what a real tick would do, and nothing moved"""

    branch: str | None
    behind: int = 0
    how: How | None = None
    error: str | None = None

    def line(self, dry_run: bool) -> str | None:
        if self.error is not None:
            return f"catch-up failed: {self.error}"
        if self.how is None or self.branch is None:
            return None
        commits = f"{self.behind} commit{'' if self.behind == 1 else 's'}"
        verb = "would catch up" if dry_run else "catch-up"
        return f"{verb}: {self.branch} {commits} → {REMOTE}/{self.branch}"

    def record(self) -> dict[str, object]:
        how = None if self.how is None else self.how.value
        return {"branch": self.branch, "behind": self.behind, "how": how, "error": self.error}


def catch_up(git: Git, dry_run: bool) -> CatchUp:
    """D-66 from the gate's checkout git, a worktree of the repo, so it shares the branch refs
    with the main checkout. Fetches origin's landing branch first, so a tick that refreshed
    nothing (held, busy) compares against GitHub's; a dry run fetches that remote-tracking ref
    too, as the prune's judge does, and moves no branch. A git failure raises ReleaseError"""
    branch = git.landing_branch()
    git.run("fetch", "-q", REMOTE, branch)
    main = read_main(git, branch)
    if main.local is None or main.ahead or not main.behind:
        return CatchUp(branch, main.behind)
    trees = parse_worktrees(git.run("worktree", "list", "--porcelain", "-z"))
    holders = [t for t in trees if t.branch == branch]
    checkout = Git(trees[0].path)  # git lists the main working tree first
    if not holders:
        how = How.FETCH
    elif holders == [trees[0]] and not trees[0].bare and not checkout.run("status", "--porcelain").strip():
        how = How.PULL
    else:  # dirty, or checked out in a linked worktree: shipmill status keeps reporting it
        return CatchUp(branch, main.behind)
    if not dry_run:
        if how is How.FETCH:  # no leading +: git refuses a non-fast-forward
            git.run("fetch", "-q", REMOTE, f"{branch}:{branch}")
        else:  # --no-rebase: a pull.rebase setting never turns it into a rebase
            checkout.run("pull", "-q", "--ff-only", "--no-rebase", REMOTE, branch)
    return CatchUp(branch, main.behind, how)
