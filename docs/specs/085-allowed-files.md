# S-085: An agent's pull request lands only with the files its issue allows

status: built
serves: G-2

## Problem

An agent working on an issue may change any file its session can write (#1308). A fix for a
typo can also edit CI, the decision log, or another agent's files, and only the reviewer's
reading stops it. Spec 055 (#1048) moved the landing rules into code; what a change may touch
is still a matter of the agent's instructions. The plan's `Files:` line (spec 024) is the
implementer's own forecast: the agent that writes the change writes it too, nothing compares
it with the change, and ship-watch's "Plan match" measure only counts how often they agree.

Who is affected: maintainers who let agents land without reading every diff (G-2).

Evidence: no requests yet. The prior art is a hackathon entry where each agent writes only
its own files, checked by code, with the task's specification locked at intake.

This spec makes the issue's verdict, written before the implementer starts, say which files
the work may touch, and makes `pr_gate.py`, which every merge runs (spec 055), hold an
agent's pull request whose changed files fall outside it, naming the files, until the
maintainer accepts the wider change.

## Behaviour

### The allowance is written on the issue, before the work starts

The triage verdict that sends an issue to an implementer, the Implement template of
`skills/github-issue-triage/references/comments.md` (`Triage: **implement**...`), carries a
line in its plan:

```markdown
- Files: `src/shipmill/gate.py`, `tests/test_gate*.py`, `docs/flow.md`
```

So does a `Proposed plan:` comment under `[autonomy] fix = "propose"`
(`skills/github-issue-triage/references/autonomy.md`), whose `Files:` line becomes its
allowance once the maintainer replies `apply`. The paths on it are the issue's **allowed
files**: each one in backticks, relative to the repo's root, read with spec 061's grammar
(`**` any run of characters, `/` included; `*` any run without `/`; `?` one character other
than `/`), and a path ending in `/` covers everything under it. This is the grammar
`skills/github-ship-watch/scripts/metrics.py`'s `covered` reads a plan's `Files:` line with.
A spec's build issue lists its spec file among them, since the build issue that ends the
spec fills in its Issues and Verification.

### Which comment counts

`skills/github-pr-triage/scripts/pr_gate.py` reads the allowance of each issue an agent's
pull request closes or names as `Part of #N` (its `named_issues`), from the issue threads the
veto and the answer already read (`threads_of`, one GraphQL read, no new call). For each
issue the allowance comes from one comment: the newest whose first line starts
`Triage: **implement**` or `Proposed plan:`, written by the `--bot-login` or by an OWNER,
MEMBER, or COLLABORATOR, and created before the pull request was opened (the comment's and
the pull request's `createdAt`, which GitHub sets). Its lines outside a fence that start
`Files:` (after an optional list bullet) give the paths; several such lines add up.

- A comment by anyone else (a CONTRIBUTOR, another bot) never counts, so a stranger can't
  widen what an agent may touch
- A comment created after the pull request opened never counts: what the work may touch is
  fixed when the work starts, and the agent that does it can't widen it by commenting
- A counting comment edited after the pull request opened (its `lastEditedAt`, which GitHub
  sets, at or after the pull request's `createdAt`) holds it, whatever the edit says:
  `files: the allowance on #812 changed after this pull request opened`. The maintainer's
  answer lifts it as it lifts any `files:` line; a comment edited before the pull request
  opened, or never, counts as above (D-106, #1570)
- An issue whose counting comment has no `Files:` line **declares no allowance**

### What the gate holds

An agent's pull request (spec 055's reading: the `--bot-login`'s, one named with `--agent`,
or one whose body carries the agent marker on a line of its own, D-62) where at least one
named issue declares an allowance is checked against the union of the declared allowances.
Each changed path the files API lists, and the old path of a renamed file, is **covered**
when it equals an allowed path, sits under one ending in `/`, or matches one as a glob. A
file directly inside the `[changelog] fragments` folder that the base's
`.github/shipmill.toml` names is always covered, since every pull request adds its fragment
(spec 013).

A pull request with a changed path no allowance covers reads NEEDS_DECISION, exit 5, with
one line per such path:

```text
  files: src/shipmill/release.py is outside what #812 allows
  files: .github/workflows/ci.yml is outside what #812, #815 allow
```

After 20 such lines, one more says `  files: and <k> more outside the allowed files`. The
lines join the gate's other asks: the maintainer's answer that lifts the `ask` zones and the
Protected areas asks (spec 055, D-89, D-93) lifts them too, under the same rules for the
head it covers. An answer on a named issue given before the pull request opened, which
spec 055 reads as covering every head for the other asks, lifts a `files:` line only when
its question's `<!-- shipmill:head <sha> -->` line names the judged head or one whose own
change is the same (D-109, #1604): it was given before anyone saw the files. No other
record widens a pull request's allowance once it is open.

The gate also reads NEEDS_DECISION, fail closed, when:

- a counting comment's `Files:` line names no path in backticks, or a path that is empty,
  absolute, or holds `..`:
  `` files: #812's allowed files can't be read: `Files:` names no path in backticks ``
- a named issue's thread is cut off at its newest 100 comments and none of those is a
  counting comment: `files: the thread of #812 is cut off at 100 comments: its allowed files
  can't be read, so a person looks`

Not checked, and judged as before: a person's pull request, a draft (D-67), and an agent's
pull request none of whose named issues declares an allowance, or that names no issue (a
spec pull request's `Spec for #N` names none, nor does a revert's `Reverts #N`).

### The merge

`src/shipmill/app_gh.py`'s merge path runs `pr_gate.py` before gh (spec 055), so
`shipmill gh pr merge <n>` on such a pull request exits 2 without running gh, printing the
gate's NEEDS_DECISION line and its `files:` lines. No flag of `shipmill gh` or of
`pr_gate.py` turns the check off.

### The skills

- `comments.md`'s Implement template carries the `- Files:` line in its plan, with the
  build issue's spec file named for a spec's build issue; `autonomy.md`'s `Proposed plan:`
  writes its `Files:` paths in backticks
- `skills/github-issue-triage/references/implementer-brief.md` passes the issue's allowed
  files to the implementer and says a file outside them is a "decision for you": stop and
  report it, don't push it. `skills/github-issue-resolve/SKILL.md`'s Phase 4 says the plan's
  `Files:` line stays within the issue's allowed files
- `skills/github-pr-triage/references/landing.md` says a `files:` hold is asked with the
  needs-decision question on the pull request, naming each file outside and why the change
  needs it, and lands on the maintainer's answer, never on a new verdict on the issue
- `pr_gate.py`'s docstring states the rule and its lines

## Acceptance criteria

- S-085-1: `pr_gate.py` reads an issue's allowed files from the newest comment whose first line starts `Triage: **implement**` or `Proposed plan:`, by the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR, created before the pull request; the backticked paths of every `Files:` line outside a fence in it (after an optional list bullet) add up, and a counting comment without a `Files:` line declares no allowance
- S-085-2: A `Triage: **implement**` comment with a `Files:` line by a CONTRIBUTOR or another bot, or one created after the pull request's `createdAt` by the `--bot-login` or the maintainer, doesn't count: the allowance stays the older counting comment's, or none
- S-085-3: A changed path is covered when it equals an allowed path, sits under one ending in `/`, or matches one by spec 061's grammar (`src/*.py` covers `src/a.py` and not `src/x/a.py`; `src/**` covers both); a renamed file's old path must be covered too; a file directly inside the base config's `[changelog] fragments` folder is covered without being listed
- S-085-4: An agent's ready, green pull request whose named issue allows `src/a.py` and that changes `src/a.py` and `.github/workflows/ci.yml` reads NEEDS_DECISION, exits 5, and prints `  files: .github/workflows/ci.yml is outside what #<n> allows`; the same pull request changing only `src/a.py` and its changelog fragment reads READY with no `files:` line
- S-085-5: With two named issues, a path is covered when either declared allowance covers it, an issue declaring none adds nothing, and an uncovered path's line names every issue that declares an allowance (`is outside what #A, #B allow`)
- S-085-6: More than 20 uncovered paths print 20 `files:` lines and then `  files: and <k> more outside the allowed files`
- S-085-7: A person's pull request, a draft, an agent's pull request whose named issues declare no allowance, and an agent's pull request that names no issue are judged as before, with no `files:` line
- S-085-8: A counting `Files:` line with no backticked path, or with an empty, absolute, or `..` path, reads NEEDS_DECISION with `files: #<n>'s allowed files can't be read: <why>`; a named issue whose thread has older comments unread and no counting comment among its newest 100 reads NEEDS_DECISION with `files: the thread of #<n> is cut off at 100 comments: its allowed files can't be read, so a person looks`
- S-085-9: The maintainer's accepting answer to a needs-decision question naming the judged head, read by spec 055's rules, lifts the `files:` lines and CI decides; a head whose own change differs from the answered head's keeps them with `needs-decision: answered at <sha7>, and the change differs since`, and a new `Triage: **implement**` comment by the `--bot-login` after the pull request opened, listing the file, doesn't lift them
- S-085-10: `shipmill gh pr merge <n>`, as the App, on a pull request S-085-4 holds exits 2 without running gh, printing `is refused: pr_gate.py reads #<n> NEEDS_DECISION` and the `files:` line
- S-085-11: `comments.md`'s Implement template has a `- Files:` line with paths in backticks and says a spec's build issue lists its spec file; `autonomy.md`'s `Proposed plan:` writes its `Files:` paths in backticks
- S-085-12: `implementer-brief.md` passes the issue's allowed files and calls a file outside them a decision for you; `github-issue-resolve`'s Phase 4 keeps the plan's `Files:` line within them; `landing.md` asks a `files:` hold with the needs-decision question naming each file outside; `pr_gate.py`'s docstring names the `files:` lines and their exit code 5
- S-085-13: A counting comment whose `lastEditedAt` is at or after the pull request's `createdAt` holds an agent's pull request, NEEDS_DECISION, with `  files: the allowance on #<n> changed after this pull request opened`, whatever the edit says, and the maintainer's answer lifts it as S-085-9 lifts any `files:` line; a counting comment edited before the pull request opened, or never edited (`lastEditedAt` null), counts as S-085-1 says, and an edited comment that doesn't count (S-085-2) holds nothing (D-106, #1570)
- S-085-14: The maintainer's accepting answer on a named issue, given before the pull request opened, to a question naming no head (or a head whose own change differs from the judged head's) keeps the `files:` lines: an agent's pull request whose issue allows `src/a.py` and that changes `src/b.py` reads NEEDS_DECISION with `  files: src/b.py is outside what #<n> allows`, while that answer still lifts the pull request's other asks as spec 055 says; an accepting answer to a question naming the judged head lifts the `files:` lines (D-109, #1604)

## Out of scope

- Holding an agent's pull request whose issue declares no allowance, or that names no issue: this build checks declared allowances only, so connected repos with open work don't stop at upgrade; a strict mode, a setting in `.github/shipmill.toml` (D-4), is a follow-up once triage writes the line everywhere (see the decisions)
- Refusing the write before it happens: a delivery hook or `shipmill gh pr create` check that stops a commit or a push touching a file outside the allowance. The landing gate is the barrier here; an earlier refusal is a follow-up
- Telling the triage session from the implementer's session when both write as the App: an implementer that posts a new verdict before opening its pull request widens its own allowance. The brief forbids it, and the verdict's author and time are on the issue for the reviewer; proving which session wrote it needs an identity per role
- A `[decisions]` zone or level of its own for widening the files, and its retro counts: the hold is a fixed ask, as the approved-spec hold of D-81 is
- A per-agent ownership of files across concurrent work (one agent's files closed to another's): the allowance is per issue, not per agent
- Locking the spec's text or the numbers in a pull request's description, which the prior art also does

## Decisions relied on

- D-48: the hold asks, and is read from GitHub, never from a setting in the pull request
- D-62: an agent's pull request is told by its marker; a person's comment counts only without one
- D-65: comments stay the App's in every author mode, so the `--bot-login` names the verdict's writer
- D-67: a draft is judged for nothing else
- D-79: the issues a pull request names are the ones its closing keywords close, read as GitHub reads them, and the ones it names as `Part of #N`
- D-81: an ask held by the gate with no zone of its own, lifted by the maintainer's answer, has precedent in the approved-spec hold
- D-89: the newest trusted answer is the one read
- D-93: a relayed answer is read by the relay grammar
- D-106: a counting comment edited after the pull request opened holds it
- D-109: an answer given before an agent's pull request opened never widens its files

## Issues

- shipmill/shipmill#1523: S-085-1, S-085-2, S-085-3, S-085-4, S-085-5, S-085-6, S-085-7, S-085-8
- shipmill/shipmill#1525: S-085-9, S-085-10
- shipmill/shipmill#1527: S-085-11, S-085-12
- shipmill/shipmill#1570: S-085-13
- shipmill/shipmill#1604: S-085-14

## Verification

Checked against main plus #1600 (which reads a `Proposed plan:` under its `<!-- shipmill:... -->` lines, #1594): `uv run pytest -v tests/test_allowed_files.py tests/test_allowed_files_edited.py tests/test_allowed_files_skills.py -k s085` ran 75 tests, all passed, besides reading the code and prose each criterion names.

- S-085-1: `allowance` in `pr_gate.py` read; a `Triage: **implement**` and a `Proposed plan:` comment, the latter as `autonomy.md` writes it under the needs-decision and zone lines and answered `apply`, give the allowance, `Files:` lines add up, one in a fence adds nothing, the newest counting comment wins, and one without a `Files:` line declares none, in `tests/test_allowed_files.py`; holds
- S-085-2: a CONTRIBUTOR's, a stranger's, another bot's, and the App's or the maintainer's comment after the PR opened leave the older allowance or none, in `tests/test_allowed_files.py`; holds
- S-085-3: spec 061's grammar (`src/*.py`, `src/**`, `?`, a trailing `/`), a renamed file's old path, and only a file directly inside the base config's fragments folder covered, in `tests/test_allowed_files.py`; holds
- S-085-4: the App's ready, green PR changing `src/a.py` and `.github/workflows/ci.yml` exits 5 with `  files: .github/workflows/ci.yml is outside what #12 allows`, and with `src/a.py` and its fragment reads READY, in `tests/test_allowed_files.py`; holds
- S-085-5: two issues' allowances add up, one declaring none adds nothing, and the line names `#A, #B allow`, in `tests/test_allowed_files.py`; holds
- S-085-6: more than 20 uncovered paths print 20 lines and `  files: and <k> more outside the allowed files`, in `tests/test_allowed_files.py`; holds
- S-085-7: a person's PR, a draft, an agent's PR whose issues declare none, and one naming no issue read as before with no `files:` line, in `tests/test_allowed_files.py`, and `files_hold` runs only for an agent's open, non-draft PR in `pr_gate.py`'s main loop; holds
- S-085-8: a `Files:` line with no backticked, an empty, an absolute, or a `..` path, and a thread cut off at 100 comments with no counting one, read NEEDS_DECISION with their lines, in `tests/test_allowed_files.py`; holds
- S-085-9: the maintainer's accepting answer lifts the `files:` lines, one not taking the recommended option or a head whose own change differs keeps them, and the App's new verdict after the PR opened lifts nothing, in `tests/test_allowed_files.py`; holds
- S-085-10: `shipmill gh pr merge 7 --squash` on S-085-4's PR runs no gh and prints `is refused: pr_gate.py reads #7 NEEDS_DECISION` with the `files:` line (`src/shipmill/merge_gate.py`), in `tests/test_allowed_files.py`; holds
- S-085-11: `comments.md`'s Implement template has `- Files:` with backticked paths and names a build issue's spec file, and `autonomy.md`'s `Proposed plan:` writes backticked paths, read and in `tests/test_allowed_files_skills.py`; holds
- S-085-12: `implementer-brief.md`, `github-issue-resolve`'s Phase 4, `landing.md`, and `pr_gate.py`'s docstring (the `files:` lines and exit 5) read and in `tests/test_allowed_files_skills.py`; holds
- S-085-13: a counting comment edited at or after the PR opened holds it with `  files: the allowance on #<n> changed after this pull request opened`, a `Proposed plan:` under its markers included, the answer lifts it, one edited before or never counts, an edited comment that doesn't count holds nothing, and a malformed `lastEditedAt` stops the gate, in `tests/test_allowed_files_edited.py` and `tests/test_allowed_files.py`; holds
- S-085-14: `acceptance` and its caller in `pr_gate.py` read; #1604's repro (an issue answer before the PR opened to a question naming no head, the PR changing `src/b.py`) holds with its `files:` line, the same answer still lifts a protected area's ask, and an issue answer to a question naming the judged head lifts the `files:` line, in `tests/test_allowed_files.py`; holds
