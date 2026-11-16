#!/usr/bin/env python3
"""Did these commits land on a ref? Matches by patch id, so a rebased or cherry-picked copy
counts; falls back to the patch id without CHANGELOG.md, whose conflicts are often resolved
by hand. A patch id keeps whitespace (`git patch-id --verbatim`), as a re-indented line can
change what code means; on a git without it (older than 2.40) no commit matches by patch id,
so only ancestry proves a commit landed. Run before deleting a worktree or branch.

Exit codes: 0 every commit landed; 1 at least one did not; 2 bad arguments or a git failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

EXCLUDE = "CHANGELOG.md"


def git(*args: str, stdin: str | None = None) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, input=stdin)
    if proc.returncode != 0:
        sys.exit(f"landed: git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def verbatim_patch_ids() -> bool:
    """Whether this git hashes a patch with its whitespace kept: `git patch-id --verbatim`, git
    2.40 or later, run on an empty patch (D-92)"""
    proc = subprocess.run(["git", "patch-id", "--verbatim"], capture_output=True, text=True, input="")
    return proc.returncode == 0


def patch_ids(log_patch: str) -> dict[str, str]:
    """patch id -> commit, from `git log -p` output"""
    out = git("patch-id", "--verbatim", stdin=log_patch)
    ids: dict[str, str] = {}
    for line in out.splitlines():
        pid, commit = line.split()
        ids.setdefault(pid, commit)
    return ids


def show(commit: str, *paths: str) -> str:
    return git("show", commit, "--", *paths) if paths else git("show", commit)


def own_id(commit: str, *paths: str) -> str | None:
    out = git("patch-id", "--verbatim", stdin=show(commit, *paths))
    return out.split()[0] if out.strip() else None


def main(argv: list[str] | None = None, verbatim: bool | None = None) -> int:
    """verbatim says whether git can hash a patch with its whitespace kept; None asks this git"""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("commits", nargs="+", help="commits to look for")
    parser.add_argument("--onto", required=True, help="ref they should be on, e.g. origin/main")
    parser.add_argument("--depth", type=int, default=500, help="non-merge commits of --onto to search (default 500)")
    args = parser.parse_args(argv)
    if args.depth < 1:
        parser.error("--depth must be positive")
    if verbatim is None:
        verbatim = verbatim_patch_ids()
    commits = [git("rev-parse", "--verify", f"{c}^{{commit}}").strip() for c in args.commits]
    exact: dict[str, str] = {}
    loose: dict[str, str] = {}
    if verbatim:
        window = ["log", "-p", "--no-merges", f"-n{args.depth}", args.onto]
        exact = patch_ids(git(*window))
        loose = patch_ids(git(*window, "--", ".", f":!{EXCLUDE}"))
    else:
        print("landed: git has no `patch-id --verbatim` (older than 2.40); matching by ancestry only", file=sys.stderr)
    missing = 0
    for commit in commits:
        short = commit[:7]
        subject = git("log", "-1", "--format=%s", commit).strip()
        if subprocess.run(["git", "merge-base", "--is-ancestor", commit, args.onto]).returncode == 0:
            print(f"{short} on {args.onto} itself: {subject}")
            continue
        if not verbatim:
            changes_more = git("show", "--format=", commit, "--", ".", f":!{EXCLUDE}").strip()
            if changes_more:
                print(f"{short} NOT LANDED: {subject}")
            else:
                print(f"{short} changes only {EXCLUDE}; compare by hand: {subject}")
            missing += 1
            continue
        pid = own_id(commit)
        if pid and pid in exact:
            print(f"{short} landed as {exact[pid][:7]}: {subject}")
            continue
        loose_id = own_id(commit, ".", f":!{EXCLUDE}")
        if loose_id and loose_id in loose:
            print(f"{short} landed as {loose[loose_id][:7]} ({EXCLUDE} differs): {subject}")
            continue
        if loose_id is None:
            print(f"{short} changes only {EXCLUDE}; compare by hand: {subject}")
        else:
            print(f"{short} NOT LANDED: {subject}")
        missing += 1
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
