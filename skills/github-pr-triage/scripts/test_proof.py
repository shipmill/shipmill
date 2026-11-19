#!/usr/bin/env python3
"""Do a change's tests prove it, read from its history (spec 076)?

    test_proof.py fix|refactor --base <ref> [--head <ref>] [--plan-file <file>]
        [--test-path <glob>]... [--timeout <s>] [--json] -- <command>

The change is the commits of `git rev-list --reverse --first-parent <merge base>..<head>`, the
merge base that of --base and --head (default HEAD). Each commit is read against its first
parent.

A test file is a path with a directory named tests, test, __tests__, or spec, or a file named
test_*.py, *_test.py, conftest.py, *.test.*, *.spec.*, *_test.go, or *_test.rs. One or more
--test-path globs replace that list: ** matches any run of characters, / included, * and ?
within one path segment, anything else itself (as spec 061).

What runs: git alone (rev-parse, merge-base, rev-list, diff, and worktree add, remove, and
prune), and <command>, exactly as given after --, without a shell, in a detached worktree
added under the system temp directory for the tree it tests and removed again whatever the
outcome, so the caller's checkout is never switched. A word {tests} in <command> is replaced by
the first commit's test files (fix) or dropped (refactor). --timeout bounds each run (default
600 seconds). Nothing else runs and nothing touches the network.

fix checks, in order:
  1. the first commit changes at least one file and only test files
  2. <command> exits non-zero on the first commit's tree
  3. <command> exits 0 on the head's tree
  4. no later commit removes or changes a line of a file the first commit touched, deletes
     it, or renames it; lines added are fine
A change that touches no test file reads NO_TEST and runs no command.

refactor checks, in order:
  1. <command> exits 0 on the merge base's tree; otherwise BASELINE_RED, and nothing else
     is checked
  2. no test file that exists at the merge base is modified, deleted, or renamed by the
     change; test files it adds are fine

--plan-file is a file holding the pull request's body: its `## Plan` section's
`Tests changed:` line names files exempt from fix's check 4 and refactor's check 2, each in
backticks followed by `: ` and its reason, entries separated by `;`.

Output: `test_proof: <VERDICT> (<kind>)`, then one `ok:` or `fail:` line per check, and under
a failed or unexpectedly passing run its last 40 output lines. --json prints one object.

Exit codes: 0 PROVEN or NO_TEST; 1 UNPROVEN or BASELINE_RED; 2 bad arguments, a ref that isn't
a commit, an empty change, a missing <command>, a `Tests changed:` entry with no reason, a run
past --timeout, or a git failure.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

PROG = "test_proof"
TESTS_WORD = "{tests}"
TAIL = 40  # output lines printed under a failed or unexpectedly passing run
DEFAULT_TIMEOUT = 600
TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec"})
TEST_NAMES = ("test_*.py", "*_test.py", "conftest.py", "*.test.*", "*.spec.*", "*_test.go", "*_test.rs")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_TESTS_CHANGED = re.compile(r"^\s*(?:[-*]\s+)?Tests changed:(.*)$")
_ENTRY = re.compile(r"`([^`]+)`(?::(.*))?")


class Stop(Exception):
    """A state the script can't judge: it exits 2 with the message"""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    output: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Change:
    """One commit's change against its first parent: status (A, M, D, R, C, T), old and new path"""

    status: str
    old: str
    new: str


# git


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed: {proc.stderr.strip()}; run it in the repository the change is in")
    return proc.stdout


def commit_of(ref: str, flag: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise Stop(f"{flag} {ref} is not a commit; pass a ref that names one, such as origin/main, after a git fetch")
    return proc.stdout.strip()


def first_parent(commit: str) -> str:
    proc = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{commit}^1"], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else EMPTY_TREE


def changes(old: str, new: str) -> list[Change]:
    """The files changed from old to new, renames detected"""
    out = git("diff", "--name-status", "-z", "-M", old, new, "--")
    words = out.split("\0")
    found: list[Change] = []
    i = 0
    while i < len(words) and words[i]:
        status = words[i][0]
        if status in "RC":
            found.append(Change(status, words[i + 1], words[i + 2]))
            i += 3
        else:
            found.append(Change(status, words[i + 1], words[i + 1]))
            i += 2
    return found


def deleted_lines(old: str, new: str, path: str) -> int | None:
    """Lines of path removed or changed from old to new, renames not followed; None for a binary file"""
    out = git("diff", "--numstat", "--no-renames", old, new, "--", path).strip()
    if not out:
        return 0
    removed = out.splitlines()[0].split("\t")[1]
    return None if removed == "-" else int(removed)


# test files


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A --test-path glob as spec 061 reads a path: ** any run of characters, / included, * any
    run without /, ? one character other than /, anything else itself"""
    parts = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(parts), re.DOTALL)


class TestFiles:
    """Which paths are test files: the defaults, or only the --test-path globs when given"""

    def __init__(self, globs: list[str]) -> None:
        self.globs = [glob_regex(glob) for glob in globs]

    def __call__(self, path: str) -> bool:
        if self.globs:
            return any(glob.fullmatch(path) for glob in self.globs)
        *dirs, name = path.split("/")
        return any(d in TEST_DIRS for d in dirs) or any(fnmatch.fnmatchcase(name, p) for p in TEST_NAMES)


# the plan


def plan_lines(body: str) -> list[str]:
    """The `## Plan` section's lines outside fenced code; none when there is no such section"""
    found: list[str] = []
    in_plan = False
    fence: str | None = None
    for line in body.splitlines():
        opened = _FENCE.match(line)
        if fence is not None:
            if opened is not None and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
            continue
        if opened is not None:
            fence = opened.group(1)
            continue
        heading = _HEADING.match(line)
        if heading is not None and len(heading.group(1)) <= 2:
            in_plan = len(heading.group(1)) == 2 and (heading.group(2) or "").strip() == "Plan"
            continue
        if in_plan:
            found.append(line)
    return found


def tests_changed(body: str) -> dict[str, str]:
    """The files the plan's `Tests changed:` line names, each with its reason"""
    lines = [m.group(1) for m in (_TESTS_CHANGED.match(line) for line in plan_lines(body)) if m]
    if len(lines) > 1:
        raise Stop(f"the plan has {len(lines)} `Tests changed:` lines; join their entries on one, separated by `;`")
    exempt: dict[str, str] = {}
    if not lines or not lines[0].strip():
        return exempt
    for entry in (part.strip() for part in lines[0].split(";")):
        found = _ENTRY.fullmatch(entry)
        if found is None:
            raise Stop(
                f"`Tests changed:` entry {entry!r} is not a backticked path and its reason; "
                "write it as `path`: reason, entries separated by `;`"
            )
        reason = (found.group(2) or "").strip()
        if not reason:
            raise Stop(
                f"`Tests changed:` names `{found.group(1)}` with no reason; follow it with `: ` and why the change "
                "had to edit it"
            )
        exempt[found.group(1)] = reason
    return exempt


# runs


@dataclass(frozen=True)
class Run:
    code: int
    tail: list[str]


def run_on(commit: str, command: list[str], timeout: int) -> Run:
    """<command> run without a shell in a detached worktree of commit under the system temp
    directory, removed again whatever the outcome"""
    holder = tempfile.mkdtemp(prefix="test_proof-")
    tree = os.path.join(holder, "tree")
    try:
        git("worktree", "add", "--quiet", "--detach", tree, commit)
        try:
            proc = subprocess.Popen(
                command,
                cwd=tree,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            raise Stop(f"{command[0]} could not start: {error}; pass a command on PATH after --") from None
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.communicate()
            raise Stop(
                f"{' '.join(command)} ran past --timeout {timeout}s on {commit[:7]}; raise --timeout or narrow the "
                "command to the touched tests"
            ) from None
        text = out.decode("utf-8", errors="replace")
        return Run(proc.returncode, text.splitlines()[-TAIL:])
    finally:
        removed = subprocess.run(["git", "worktree", "remove", "--force", tree], capture_output=True)
        shutil.rmtree(holder, ignore_errors=True)
        if removed.returncode != 0:  # a tree the command broke: its record goes once the folder has
            subprocess.run(["git", "worktree", "prune"], capture_output=True)


def command_for(command: list[str], tests: list[str]) -> list[str]:
    words: list[str] = []
    for word in command:
        words.extend(tests if word == TESTS_WORD else [word])
    if not words:
        raise Stop("the command after -- is only {tests} and there is no test file to put there; name the test runner")
    return words


# the checks


def touched(change: list[Change]) -> set[str]:
    return {path for c in change for path in (c.old, c.new)}


def fix(
    commits: list[str], is_test: TestFiles, exempt: dict[str, str], command: list[str], timeout: int
) -> tuple[str, str, list[str], list[Check]]:
    per_commit = [(commit, changes(first_parent(commit), commit)) for commit in commits]
    first, first_change = per_commit[0]
    short = first[:7]
    if not any(is_test(path) for _, change in per_commit for path in touched(change)):
        return "NO_TEST", first, [], []
    tests = sorted({c.new for c in first_change if c.status != "D" and is_test(c.new)})
    checks: list[Check] = []

    others = sorted(path for path in touched(first_change) if not is_test(path))
    if not first_change:
        checks.append(
            Check("first-commit-tests-only", False, f"{short} changes no file; commit the failing test first")
        )
    elif others:
        checks.append(
            Check(
                "first-commit-tests-only", False, f"{short} changes files that aren't test files: {', '.join(others)}"
            )
        )
    else:
        checks.append(Check("first-commit-tests-only", True, f"{short} changes only test files: {', '.join(tests)}"))

    words = command_for(command, tests)
    named = ", ".join(tests) if tests else "no test file"
    before = run_on(first, words, timeout)
    if before.code != 0:
        detail = f"{short} ({named}): the command exits {before.code} on the first commit's tree"
        checks.append(Check("fails-before", True, detail, before.tail))
    else:
        detail = f"{short} ({named}): the command exits 0 on the first commit's tree; the test doesn't fail first"
        checks.append(Check("fails-before", False, detail, before.tail))

    head = commits[-1]
    after = run_on(head, words, timeout)
    if after.code == 0:
        checks.append(Check("passes-after", True, f"{head[:7]} ({named}): the command exits 0 on the head's tree"))
    else:
        detail = f"{head[:7]} ({named}): the command exits {after.code} on the head's tree"
        checks.append(Check("passes-after", False, detail, after.tail))

    first_files = touched(first_change)
    broken: list[str] = []
    exempted: set[str] = set()
    for commit, change in per_commit[1:]:
        parent = first_parent(commit)
        for c in change:
            if c.old not in first_files:
                continue
            if c.status == "D":
                what = f"{commit[:7]} deletes {c.old}"
            elif c.status == "R":
                what = f"{commit[:7]} renames {c.old} to {c.new}"
            elif c.status in "MT":
                removed = deleted_lines(parent, commit, c.old)
                if removed == 0:
                    continue
                what = f"{commit[:7]} removes or changes {'lines' if removed is None else removed} of {c.old}"
            else:
                continue
            if c.old in exempt:
                exempted.add(c.old)
            else:
                broken.append(what)
    if broken:
        checks.append(Check("tests-kept", False, "; ".join(broken)))
    else:
        detail = "later commits only add lines to the first commit's files"
        if exempted:
            detail += "; exempt on Tests changed: " + ", ".join(f"{p} ({exempt[p]})" for p in sorted(exempted))
        checks.append(Check("tests-kept", True, detail))
    verdict = "PROVEN" if all(check.ok for check in checks) else "UNPROVEN"
    return verdict, first, tests, checks


def refactor(
    base: str, commits: list[str], is_test: TestFiles, exempt: dict[str, str], command: list[str], timeout: int
) -> tuple[str, str | None, list[str], list[Check]]:
    head = commits[-1]
    whole = changes(base, head)
    tests = sorted({c.new for c in whole if c.status != "D" and is_test(c.new)})
    baseline = run_on(base, command_for(command, []), timeout)
    if baseline.code != 0:
        detail = f"{base[:7]}: the command exits {baseline.code} on the merge base's tree"
        return "BASELINE_RED", None, tests, [Check("baseline-green", False, detail, baseline.tail)]
    checks = [Check("baseline-green", True, f"{base[:7]}: the command exits 0 on the merge base's tree")]

    per_commit = [(commit, touched(changes(first_parent(commit), commit))) for commit in commits]
    broken: list[str] = []
    exempted: list[str] = []
    for c in whole:
        if c.status not in "MDRT" or not is_test(c.old):
            continue
        if c.old in exempt:
            exempted.append(c.old)
            continue
        verb = {"M": "modifies", "T": "modifies", "D": "deletes", "R": "renames"}[c.status]
        by = ", ".join(commit[:7] for commit, paths in per_commit if c.old in paths) or head[:7]
        broken.append(f"{by} {verb} {c.old}")
    if broken:
        checks.append(Check("tests-unchanged", False, "; ".join(broken)))
    else:
        detail = "the change modifies, deletes, or renames no test file of the merge base"
        if exempted:
            detail += "; exempt on Tests changed: " + ", ".join(f"{p} ({exempt[p]})" for p in sorted(exempted))
        checks.append(Check("tests-unchanged", True, detail))
    return ("PROVEN" if all(check.ok for check in checks) else "UNPROVEN"), None, tests, checks


# the entry point


def parse(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    own, command = (argv[: argv.index("--")], argv[argv.index("--") + 1 :]) if "--" in argv else (argv, [])
    parser = argparse.ArgumentParser(
        prog="test_proof.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("kind", choices=("fix", "refactor"))
    parser.add_argument("--base", required=True, help="the ref the change is read against, e.g. origin/main")
    parser.add_argument("--head", default="HEAD", help="the change's last commit (default HEAD)")
    parser.add_argument("--plan-file", help="a file holding the pull request's body, read for `Tests changed:`")
    parser.add_argument("--test-path", action="append", default=[], help="a glob of test files; replaces the defaults")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per run (default 600)")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(own)
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    return args, command


def main(argv: list[str] | None = None) -> int:
    args, command = parse(sys.argv[1:] if argv is None else argv)
    try:
        if not command:
            raise Stop("no command after --; give the test command, e.g. -- uv run pytest {tests}")
        exempt: dict[str, str] = {}
        if args.plan_file is not None:
            try:
                with open(args.plan_file, encoding="utf-8") as handle:
                    exempt = tests_changed(handle.read())
            except OSError as error:
                raise Stop(f"--plan-file {args.plan_file} can't be read: {error}; write the body to a file") from None
        base, head = commit_of(args.base, "--base"), commit_of(args.head, "--head")
        merge_base = git("merge-base", base, head).strip()
        commits = git("rev-list", "--reverse", "--first-parent", f"{merge_base}..{head}").split()
        if not commits:
            raise Stop(
                f"no commit between the merge base {merge_base[:7]} and {args.head}; pass the change's head as --head"
            )
        is_test = TestFiles(args.test_path)
        if args.kind == "fix":
            verdict, first, tests, checks = fix(commits, is_test, exempt, command, args.timeout)
            first_commit: str | None = first
        else:
            verdict, first_commit, tests, checks = refactor(merge_base, commits, is_test, exempt, command, args.timeout)
    except Stop as stop:
        print(f"{PROG}: {stop}", file=sys.stderr)
        return 2
    if args.json:
        record = {
            "verdict": verdict,
            "kind": args.kind,
            "first_commit": first_commit,
            "test_files": tests,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail, "output": c.output} for c in checks],
        }
        print(json.dumps(record, indent=2))
    else:
        print(f"{PROG}: {verdict} ({args.kind})")
        if verdict == "NO_TEST":
            print("note: the change touches no test file; nothing to prove from its history")
        for check in checks:
            print(f"{'ok' if check.ok else 'fail'}: {check.name}: {check.detail}")
            for line in check.output:
                print(f"    {line}")
    return 0 if verdict in ("PROVEN", "NO_TEST") else 1


if __name__ == "__main__":
    sys.exit(main())
