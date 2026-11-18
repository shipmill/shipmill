# S-076: A change's tests prove it, read from the pull request's history

status: approved
serves: G-2

## Problem

Nothing shows that a change's tests prove what it claims (#1226, which groups #383 and
#1144 and which the maintainer accepted on 2026-11-18).

- **A bug fix.** github-issue-resolve's test gate
  (`skills/github-issue-resolve/references/test-gate.md`) asks for a test that fails on the
  old code and passes on the new, and the pull request's Test plan says it did. Nothing
  checks it: the implementer commits the test and the fix together, so the history can't
  tell a test that failed first from one written after the fix to pass (#383)
- **A refactor.** It has no rule of its own. The design gate lets "an internal refactor with
  no visible change" through and the test gate is about fixes, so a refactor's pull request
  can edit the tests that are meant to prove nothing changed, and the reviewer
  (`skills/github-pr-triage/references/reviewer-brief.md`) has no check that says so (#1144)

It hits maintainers who let agents land fixes and refactors without reading every diff: a
test written after the fix, or edited along with the refactor, passes review and proves
nothing.

## Behaviour

**The plan says what kind of change it is.** The `## Plan` section of spec 024 gains two
optional lines, written by github-issue-resolve in Phase 4 (`skills/github-issue-resolve/SKILL.md`)
and carried by `skills/github-issue-triage/references/implementer-brief.md`:

- `Kind: fix` for a bug fix whose proof is a new or changed test, `Kind: refactor` for a
  change meant to leave behaviour as it is. Any other change has no `Kind:` line
- `Tests changed:` names each existing test file the change had to edit against the rules
  below, in backticks, each followed by `: ` and its reason, entries separated by `;`
  (``Tests changed: `tests/test_a.py`: the helper it imported was renamed``)

`pr_gate.py` reads neither line: a plan with only the four lines of spec 024 still passes.

**A fix commits its failing test first.** For a `Kind: fix` change, github-issue-resolve
makes the test its own first commit, touching test files only, and the fix in the commits
after it; later commits don't remove or change a line of the files that first commit
touched. A fix proven by an unchanged existing test, the type checker, or a boundary model
(test gate, questions 1 to 3) touches no test file, writes no `Kind:` line, and is judged by
the test gate as today.

**The check.** A new script beside `landed.py`,
`skills/github-pr-triage/scripts/test_proof.py` (Python 3.10, no dependencies), reads the
commits and the diff with git alone and runs the test command it is given:

```text
test_proof.py fix      --base <ref> [--head <ref>] [--plan-file <file>] [--test-path <glob>]... [--timeout <s>] [--json] -- <command>
test_proof.py refactor --base <ref> [--head <ref>] [--plan-file <file>] [--test-path <glob>]... [--timeout <s>] [--json] -- <command>
```

The change is the commits of `git rev-list --reverse --first-parent $(git merge-base <base>
<head>)..<head>`; `--head` defaults to `HEAD`. A **test file** is a path with a directory
named `tests`, `test`, `__tests__`, or `spec`, or a file named `test_*.py`, `*_test.py`,
`conftest.py`, `*.test.*`, `*.spec.*`, `*_test.go`, or `*_test.rs`; one or more `--test-path`
globs (`**`, `*`, `?` as in spec 061) replace that list. `<command>` is run as given, without
a shell, in a detached worktree the script adds under the system temp directory for the tree
it tests and removes again whatever the outcome, so the caller's checkout is never switched;
a word `{tests}` in it is replaced by the first commit's test files (`fix`) or dropped
(`refactor`). `--plan-file` is a file holding the pull request's body, read for the plan's
`Tests changed:` line. `--timeout` bounds each run (default 600 seconds).

`fix` checks, in order:

1. The first commit changes at least one file and only test files
2. `<command>` exits non-zero on the first commit's tree
3. `<command>` exits 0 on the head's tree
4. No file the first commit touched has a line removed or changed between the first commit
   and the head (`git diff --numstat` counts no deleted line, and the file isn't deleted or
   renamed); lines added are fine. A file named on `Tests changed:` with a reason is exempt

A change that touches no test file at all reads `NO_TEST`: there is nothing to prove from
history.

`refactor` checks, in order:

1. `<command>` exits 0 on the merge base's tree; when it doesn't, the verdict is
   `BASELINE_RED` and nothing else is checked, so a red base is not blamed on the refactor
2. No test file that exists at the merge base is modified, deleted, or renamed in the
   change; test files it adds are fine. A file named on `Tests changed:` with a reason is
   exempt

The first output line is `test_proof: <VERDICT> (<kind>)`, the verdict one of `PROVEN`,
`UNPROVEN`, `NO_TEST`, `BASELINE_RED`; then one `ok:` or `fail:` line per check, each `fail:`
naming the commit as a 7-character SHA and the files, and under a failed or unexpectedly
passing run of `<command>` its last 40 output lines, so the reader can tell a test that
fails for the issue's reason from one that fails to import. `--json` prints one object with
`verdict`, `kind`, `first_commit`, `test_files`, and a `checks` list. Exit codes, as
`landed.py`'s: 0 for `PROVEN` and `NO_TEST`, 1 for `UNPROVEN` and `BASELINE_RED`, 2 for bad
arguments, a ref that isn't a commit, an empty change, a missing `<command>`, a
`Tests changed:` entry with no reason, a run past `--timeout`, or a git failure, each with a
message naming the fix.

**A headless session.** The script starts a program of the caller's choosing, so in a
headless gate session `hooks/delivery.py` reads the words after `--` in a call to
`test_proof.py` as a command of their own and refuses the call when that command alone
would be refused (D-82: `uv run pytest` passes, `uv run sh` doesn't).

**The reviewer runs it.** The Open PR brief of
`skills/github-pr-triage/references/reviewer-brief.md` gains a step-2 line, held only when
the brief's `{plan}` has a `Kind:` line: after the rebase and before any fix of its own, the
reviewer writes the pull request's body to `tmp/` and runs `test_proof.py <kind> --base
origin/{default} --plan-file <file> -- <the touched files' test command>`. `UNPROVEN` is a
finding quoting the `fail:` lines; `BASELINE_RED` is reported as the base's failure, not a
finding against the pull request (D-75 already holds landing on a red default branch);
`NO_TEST` on a `Kind: fix` plan is a finding, since the plan claimed a test. The reviewer
still judges what the script can't: that the first commit's test fails for the issue's
reason, and that each `Tests changed:` reason holds. Step 3 adds one check: a pull request
whose linked issue or title calls it a bug fix with a new test, or a refactor, and whose
plan has no `Kind:` line is a finding. The final report gains a "Test proof" line with the
verdict, which goes into the review record. The Post-merge review brief is unchanged.
`skills/github-pr-triage/SKILL.md` lists the script in its scripts table.

Touched areas: `skills/github-pr-triage/scripts/test_proof.py`,
`skills/github-pr-triage/references/reviewer-brief.md`, `skills/github-pr-triage/SKILL.md`,
`skills/github-issue-resolve/SKILL.md`, `skills/github-issue-resolve/references/test-gate.md`,
`skills/github-issue-triage/references/implementer-brief.md`, `hooks/delivery.py`, the
`## Plan` section (`Kind:`, `Tests changed:`), and `tests/test_test_proof.py`.

## Acceptance criteria

- S-076-1: `test_proof.py fix` prints `test_proof: PROVEN (fix)` and exits 0 for a change whose first commit touches only test files, whose command exits non-zero on the first commit's tree and 0 on the head's tree, and whose later commits leave those files as they were
- S-076-2: `test_proof.py fix` prints `UNPROVEN` and exits 1, with a `fail:` line naming the commit and the files, when the first commit changes a file that isn't a test file, when the command exits 0 on the first commit's tree, or when it exits non-zero on the head's tree; a failed or unexpectedly passing run prints its last 40 output lines
- S-076-3: `test_proof.py fix` reads a later commit that only adds lines to a file of the first commit as `ok:`, and one that removes or changes a line of it, deletes it, or renames it as `fail:`, unless `--plan-file`'s `Tests changed:` line names that file with a reason
- S-076-4: `test_proof.py fix` prints `test_proof: NO_TEST (fix)` and exits 0, running no command, for a change that touches no test file
- S-076-5: `test_proof.py refactor` prints `PROVEN` and exits 0 when the command exits 0 on the merge base's tree and the change modifies, deletes, or renames no test file that exists there, a change that adds a test file included; it prints `UNPROVEN` and exits 1 naming each such file otherwise, unless `Tests changed:` names it with a reason
- S-076-6: `test_proof.py refactor` prints `test_proof: BASELINE_RED (refactor)` and exits 1, checking nothing else, when the command exits non-zero on the merge base's tree
- S-076-7: the default test files are a path with a directory named `tests`, `test`, `__tests__`, or `spec`, and a file named `test_*.py`, `*_test.py`, `conftest.py`, `*.test.*`, `*.spec.*`, `*_test.go`, or `*_test.rs`; given `--test-path`, only paths matching one of its globs are test files
- S-076-8: the command runs without a shell in a detached worktree outside the caller's checkout, with `{tests}` replaced by the first commit's test files for `fix` and dropped for `refactor`; after the script exits, on any verdict or error, `git worktree list` shows no worktree it added and the caller's checkout is on the branch and commit it was on
- S-076-9: `test_proof.py` exits 2 with a message naming the fix, running no command, for a `--base` or `--head` that isn't a commit, a change with no commit, no command after `--`, or a `Tests changed:` entry with no reason; a run past `--timeout` exits 2 and leaves no worktree
- S-076-10: `--json` prints one object with `verdict`, `kind`, `first_commit` (null for `refactor`), `test_files`, and `checks`, each check with its `name`, `ok`, and `detail`
- S-076-11: in a headless gate session `hooks/delivery.py` refuses a call to `test_proof.py` whose command after `--` it would refuse as a call of its own (`uv run sh`), and passes one it would pass (`uv run pytest tests/test_a.py`)
- S-076-12: `skills/github-issue-resolve/SKILL.md` Phase 4 has the implementer write `Kind: fix` or `Kind: refactor` and `Tests changed:` in the plan, commit a `Kind: fix` change's test first and alone, and leave existing test files alone in a `Kind: refactor` change; `implementer-brief.md` carries the same commit order, and `test-gate.md` says a new or changed test is committed before the fix
- S-076-13: `reviewer-brief.md`'s Open PR brief runs `test_proof.py <kind>` when the plan has a `Kind:` line, after the rebase and before the reviewer's own fixes, reports `UNPROVEN` and a `NO_TEST` on `Kind: fix` as findings and `BASELINE_RED` as the base's failure, asks for a finding on a fix-with-test or refactor whose plan has no `Kind:` line, and holds a "Test proof" line in the final report; the Post-merge review brief has none of them
- S-076-14: `pr_gate.py` passes a plan with `Kind:` and `Tests changed:` lines as it passes one with the four lines of spec 024, and its verdict is the same with and without them

## Out of scope

- `pr_gate.py` refusing a pull request on the script's verdict: the reviewer runs the check and reports it; holding it at the merge is a later step once the verdicts have been read on real pull requests
- Proof that isn't a test: a fix proven by an unchanged existing test, the type checker, or a boundary model stays with the test gate's Test plan
- Judging why a test fails: the script prints the run's output and the reviewer reads it
- A config key for the test paths: `--test-path` covers a repo the defaults don't fit, and a key in `.github/shipmill.toml` waits for one that needs it
- Tests that live inside source files (Rust's inline `#[cfg(test)]` modules, doctests): the check reads files, not parts of them
- Changes that are neither a fix nor a refactor: a feature's tests are held by its spec's criteria (`specs.py coverage`)
- Running the check on pull requests that merged before it existed, and the Post-merge review brief

## Decisions relied on

- D-34
- D-75
- D-82

## Issues

- shipmill/shipmill#1283: S-076-1, S-076-2, S-076-3, S-076-4, S-076-5, S-076-6, S-076-7, S-076-8, S-076-9, S-076-10
- shipmill/shipmill#1285: S-076-11
- shipmill/shipmill#1286: S-076-12, S-076-13, S-076-14

## Verification
