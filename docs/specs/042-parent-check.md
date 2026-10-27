# S-042: A parent closes once its check holds

status: built
serves: G-2

## Problem

A parent closes when its last child closes, and a feature issue first runs "Verify the
whole spec" (spec 017, A parent and its progress; `skills/github-issue-triage/references/spec-gate.md`).
Both happen at merge time. Where a merge is a deploy (a gate that merges green pull requests
in a repo with continuous deployment), nothing in the chain checks that the change works in
production, so a parent reads done when its code is merged, not when its result is seen
(#678).

On main today:

- `skills/github-issue-triage/scripts/triage_state.py`'s `classify_open` reads a parent
  that isn't a person's item as UNBLOCKED, `children K/N closed` in its note, once every
  child closed, whatever its body says; the session then closes it. Only a person's item
  (`human` or `role:<name>`) reads its `## Check`, as VERIFY_DUE after a done report and
  VERIFY_CLOSED after a close (specs 017 and 036)
- The last build issue's pull request says `Fixes #<feature>` (spec-gate.md, Dispatch the
  build), so the feature issue closes with the merge and never reads UNBLOCKED at all
- `skills/github-issue-triage/scripts/upstream_state.py` reads an `upstream` report whose
  children all closed as CLOSE_DUE, and the coordinator closes it with a summary (spec 038),
  however the fault looks in production

The case that surfaced it: a product of seven repos, where a new key in a scraped payload
needed reader fixes in three repos, a storage change, a manual index-mapping step, a
classifier, a backfill, an API field, and docs. Every part closed green while the outcome
that mattered (the warning gone, the field served, the export still working) was never
looked at. The workaround that works today, a person's item with a `## Check` as the last
child, is a convention each maintainer has to discover and repeat.

## Behaviour

### A parent's check

A **parent** is an open issue with at least one sub-issue (spec 017) that is not a person's
item. Its **check** is a `## Check` section of its body, read with the regex that reads a
person's item's (`CHECK` in `triage_state.py`): a command or a URL and what it must
return, saying what must hold in production and how to see it. A parent without a `## Check`
section reads exactly as today.

`triage_state.py` reads a parent with a check where it would read UNBLOCKED (every hold
closed, after UNTRUSTED, UPSTREAM, NEEDS_DECISION, DECIDED, VETOED, OFF_MILESTONE, and
UNFILLED), as:

| State | Means | The session |
|---|---|---|
| VERIFY_DUE | Every hold closed, and no check-failed comment came after the newest close | Runs the check (below) |
| CHECK_FAILED | Every hold closed, and a check-failed comment came after the newest close | Files the fix as a new child of the parent |

VERIFY_DUE is the state a person's item reads after a done report, so `watch_state.py`'s
`TRIAGE_ACTION` already counts it; its note starts with the parent's progress, `children
K/N closed`, then each child, and ends `run its ## Check`. CHECK_FAILED's note reads
`check failed <date>`, then the progress and the children. Both are in `ACTION`, so
`triage_state.py` exits 1 on either. While a child is open, the parent reads BLOCKED as
today, with or without a check.

A **check-failed comment** is a comment whose first line is `<!--
shipmill:check-failed -->`, by the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR
(D-16); one by anyone else never counts. The **newest close** is the latest `closedAt` among
the parent's closed holds, children and `Depends on` lines alike, so a fix child that closes
after the check-failed comment makes the parent read VERIFY_DUE again.

A person's item with sub-issues stays a person's item: it reads as specs 017 and 036 say.
An issue labelled `upstream` still reads UPSTREAM in `triage_state.py`; its check is the
coordinator's (below).

### The session runs the check

github-issue-triage's session, on VERIFY_DUE (`skills/github-issue-triage/references/triage-rubric.md`,
A parent's check, and `references/comments.md`, A parent's check):

- **It holds:** close the parent as completed (`gh issue close <n> --reason completed`),
  then post the verified comment: `<!-- shipmill:verified -->` as its first line, the check
  that ran, what came back, and each child and how it closed. It is the parent's closing
  comment, posted after the close so `triage_state.py` can date it there. A feature issue
  has its spec verified first, as today
- **It fails:** post the check-failed comment: the marker, the check, what came back, and
  what it must return. The parent then reads CHECK_FAILED
- **The change hasn't reached production yet** (the deploy run for the merge is still
  going, or the version served predates the merge): no comment and no close; the parent
  stays VERIFY_DUE for the next read. It isn't a failure
- **The session can't run it** (a production log, a dashboard, a host it can't reach, a
  command outside a headless session's allowlist): a question through the needs-decision
  protocol (D-21) on the parent, saying what the check is and why it can't run here, with
  the options "leave it open: I check it and close it by hand" (recommended when nothing
  else shows the result) and "close it unchecked". The parent reads NEEDS_DECISION until
  the answer
- **Never a write to production.** A check only reads: it runs a command or opens a URL and
  compares what comes back. A check that needs a deploy, a rollback, a data change, or any
  other write is one the session can't run, so it goes to the maintainer. shipmill decides
  and verifies; the platform executes (D-31, `docs/product.md` N-1)

On CHECK_FAILED, the session files the fix as a new issue in the parent's repo, naming the
parent, the check, and what came back, triages it **implement**, and makes it a child with
`chains.py link <owner/repo#parent> --child <owner/repo#fix>`. The parent then reads BLOCKED
on the new child, and VERIFY_DUE again once it closes. When the session can't tell what the
fix is, it asks on the parent through the needs-decision protocol instead. A failure reopens
nothing: the children stay closed, and the fix is new work.

### A parent closed before its check

For the `--closed N` most recently closed issues, `triage_state.py` reads a closed parent
(an issue with a sub-issue, not a person's item, not labelled `upstream`) closed as completed,
with a check, and with no trusted verified comment after its last close, as VERIFY_CLOSED
when the close came from a pull request or a commit (a closer), or from the `--bot-login`.
That catches a feature issue closed by the last build pull request's `Fixes #<feature>`, and
a session that closed the parent and stopped before its verified comment. Such a parent
never reads SUSPECT_CLOSE; with a trusted verified comment after its last close it reads
nothing. A parent closed by hand by a trusted person other than the `--bot-login` is that
person's call and reads as it does today.

On VERIFY_CLOSED the session runs the check: it holds, the verified comment; it fails,
reopen the parent (`gh issue reopen <n>`), post the check-failed comment, and it reads
CHECK_FAILED. It can't run, the needs-decision question as above, on the closed parent.

### The spec gate asks for the check

`skills/github-issue-triage/references/spec-gate.md` (Split it into build issues) gains a
step before the split: when the feature's build deploys (a merge reaches production with no
step by a person, through continuous deployment or a deploy shipmill's `land` starts), the
session adds a `## Check` section to the feature issue's body: one line, what must hold in
production and how to see it. A feature issue whose build doesn't deploy gets none.

Dispatch the build's last-build rule changes for a feature issue with a check: the pull
request that closes the last build issue doesn't say `Fixes #<feature>`, so the feature
issue stays open, reads VERIFY_DUE once that pull request merges, and closes on its check.
Without a check the rule stays as today.

### An `upstream` report's check

An `upstream` report's body may carry a `## Check` too: what must hold once the fix is in,
such as its `## Reproduce` no longer reproducing in production. The agent that files a
report adds one when the fault shows in production
(`skills/github-issue-resolve/SKILL.md`, Phase 2, and comments.md, Upstream report).

`upstream_state.py` reads a trusted report with a check whose children all closed, as:

- **VERIFY_DUE**, in place of CLOSE_DUE `completed`, when no check-failed comment came after
  the newest child close; its note is `children K/N closed` and the children, then `run its
  ## Check`
- **CHECK_FAILED** when a check-failed comment (the same marker and trust rule) came after
  the newest child close
- **CLOSE_DUE** `not_planned` as today when any child closed as not planned or is a pull
  request closed unmerged: the work didn't land, so there is nothing to check, and the
  waiting agent decides again

Both new states are in its `ACTION`, so it exits 1 on either, and `watch_state.py`'s
UPSTREAM_DUE row names them with ROUTE_DUE, ANSWERED, and CLOSE_DUE. A report without a check
reads as spec 038 says.

The coordinator's session (github-issue-triage's SKILL.md, Reports from other repos) runs the
check as above: it holds, the summary comment of spec 038 with the check and what came back,
then the close as completed; it fails, the check-failed comment on the report, then a fix
issue in the owning repo through `shipmill gh --product`, linked as the report's child with
`chains.py link --product`; it can't run, the needs-decision question on the report. It
never changes files, pushes, or opens a pull request outside the home repo (D-47).

### The watch and status

`skills/github-ship-watch/scripts/watch_state.py`'s `TRIAGE_ACTION` gains CHECK_FAILED, so the
gate starts a session for it, and `src/shipmill/status.py` lists CHECK_FAILED to triage.

### Docs

`skills/github-issue-triage/SKILL.md` (Chains, Reports from other repos),
`references/triage-rubric.md` (a new A parent's check section, and the UNBLOCKED row naming
it), `references/comments.md` (A parent's check: the verified comment, the check-failed
comment, and the needs-decision question; the Upstream report's `## Check`), and
`references/spec-gate.md` describe the check, its states, and the session's actions;
`docs/flow.md` shows a parent's check after its last child.

## Acceptance criteria

- S-042-1: an open, triaged issue that isn't a person's item, whose sub-issues are all closed and whose body has a `## Check` section, reads VERIFY_DUE in `triage_state.py`, its note starting `children K/N closed` and ending `run its ## Check`, and the script exits 1
- S-042-2: the same parent without a `## Check` section reads UNBLOCKED with the same note it read before this spec, and a parent with an open sub-issue reads BLOCKED with or without one
- S-042-3: a parent with a check whose comments hold a `<!-- shipmill:check-failed -->` first-line comment by the `--bot-login` or a trusted author after the newest close among its holds reads CHECK_FAILED and the script exits 1; the same comment by any other author changes nothing
- S-042-4: a parent that reads CHECK_FAILED reads BLOCKED once a new open sub-issue is added, and VERIFY_DUE once that sub-issue closes after the check-failed comment
- S-042-5: an issue labelled `human` or `role:<name>` with sub-issues and a `## Check` reads as specs 017 and 036 say, never VERIFY_DUE on its children alone or CHECK_FAILED, and an `upstream` parent with a check still reads UPSTREAM in `triage_state.py`
- S-042-6: a closed parent with a `## Check`, closed as completed by a pull request, a commit, or the `--bot-login`, with no trusted `<!-- shipmill:verified -->` comment after its last close, reads VERIFY_CLOSED and never SUSPECT_CLOSE; with such a comment after the close it reads nothing; closed by hand by a trusted author other than the `--bot-login` it reads as before this spec
- S-042-7: `upstream_state.py` reads a trusted report with a `## Check` whose children all closed and none as not planned as VERIFY_DUE, as CHECK_FAILED with a trusted check-failed comment after the newest child close, and as CLOSE_DUE `not_planned` when a child closed as not planned; a report without a check reads CLOSE_DUE as before; it exits 1 on VERIFY_DUE and CHECK_FAILED
- S-042-8: `watch_state.py` counts CHECK_FAILED as a triage action and names VERIFY_DUE and CHECK_FAILED reports in its UPSTREAM_DUE row, and `shipmill status` lists a CHECK_FAILED issue to triage
- S-042-9: triage-rubric.md and comments.md describe a parent's check: VERIFY_DUE's close then verified comment with the check and what came back, the check-failed comment and the fix filed as a child with `chains.py link --child`, no comment while the change hasn't reached production, the needs-decision question with its two options for a check the session can't run, and that a check never writes to production; github-issue-triage's SKILL.md says the same in Chains and, for an `upstream` report, in Reports from other repos
- S-042-10: spec-gate.md asks for a `## Check` on the feature issue before the split when its build deploys, and says the pull request that closes the last build issue of a feature issue with a check doesn't say `Fixes #<feature>`
- S-042-11: comments.md's Upstream report and github-issue-resolve's Phase 2 give the report an optional `## Check` for a fault that shows in production
- S-042-12: over one scripted forge, a parent with a check and two children reads BLOCKED, then VERIFY_DUE when both close; a check-failed comment makes it CHECK_FAILED, a linked fix child BLOCKED, the fix's close VERIFY_DUE again; the session's close and verified comment leave it reading nothing among the closed issues

## Out of scope

- Executing or rolling back a deploy to make a check pass: the platform's (D-31, N-1); the session only reads
- A limit on how many times a check may fail before the maintainer is asked: each failure files one fix child, and a repeat shows in the note's children; a cap can follow once a parent loops
- Waiting a set time after a deploy before checking (a bake): `shipmill operate` bakes an environment; a parent's check runs on the next read once the change is served
- Checks on items other than parents and `upstream` reports: a build issue's own result is its pull request's tests, and a person's item keeps its spec 017 check
- Writing `## Check` sections into existing parents: a parent without one reads as today, and a maintainer adds one by editing the body
- A check the forge runs itself (a required status on the issue): GitHub has none for issues

## Decisions relied on

- D-5
- D-16
- D-21
- D-29
- D-31
- D-47

## Issues

The feature issue is shipmill/shipmill#678. Its build issues landed through #728 (#717),
#733 (#718), and #737 (#719).

- shipmill/shipmill#717: S-042-1, S-042-2, S-042-3, S-042-4, S-042-5, S-042-6, S-042-12
- shipmill/shipmill#718: S-042-7, S-042-8
- shipmill/shipmill#719: S-042-9, S-042-10, S-042-11

## Verification

- S-042-1: tests/test_parent_check.py (test_s042_1_*) reads a triaged parent with a `## Check` and both children closed as VERIFY_DUE with the note `children 2/2 closed ...: run its ## Check`, and the real `triage_state.py` run over that forge exits 1; passes
- S-042-2: tests/test_parent_check.py (test_s042_2_*): the same parent without a check reads UNBLOCKED with the note it read before, and one open child makes it BLOCKED with or without a check; passes
- S-042-3: tests/test_parent_check.py (test_s042_3_*): a `<!-- shipmill:check-failed -->` first line by the `--bot-login` or a MEMBER after the newest close reads CHECK_FAILED (`check failed <date> children 2/2 closed ...`) and the script exits 1; by a CONTRIBUTOR, before the newest close, or mid-comment it stays VERIFY_DUE; passes
- S-042-4: tests/test_parent_check.py (test_s042_4_*): an open fix child after the check-failed comment reads BLOCKED, and its close after the comment reads VERIFY_DUE with `children 3/3 closed`; passes
- S-042-5: tests/test_parent_check.py (test_s042_5_*): a `human` or `role:infra` item with closed children and a check-failed comment reads HANDOFF_DUE, then VERIFY_DUE on a done report, never CHECK_FAILED; an `upstream` parent reads UPSTREAM in `gated`; passes
- S-042-6: tests/test_parent_check.py (test_s042_6_*): a closed parent with a check reads VERIFY_CLOSED when closed by a pull request, a commit, or the `--bot-login`, never SUSPECT_CLOSE; nothing with a trusted verified comment after the close; SUSPECT_CLOSE as before when closed by hand by a trusted person; and fetch reads its comments back to the close; passes
- S-042-7: tests/test_upstream_state.py (test_s042_7_*): a trusted report with a check whose children landed reads VERIFY_DUE, CHECK_FAILED after a trusted check-failed comment (an outsider's changes nothing), CLOSE_DUE `not_planned` when a child closed not planned, VERIFY_DUE again after a fix child closes, and exits 1 on both; passes
- S-042-8: tests/test_upstream_state.py (test_s042_8_*) puts VERIFY_DUE and CHECK_FAILED reports in the UPSTREAM_DUE row and CHECK_FAILED in `TRIAGE_ACTION`; tests/test_status_picture.py (test_s042_8_*) lists a CHECK_FAILED issue under `to triage`; `src/shipmill/status.py` and `watch_state.py` name CHECK_FAILED on main; passes
- S-042-9: tests/test_parent_check_docs.py (test_s042_9_*) reads triage-rubric.md's and comments.md's A parent's check (the close then the verified comment with the check and what came back, the check-failed comment, the fix linked with `chains.py link <owner/repo#parent> --child <owner/repo#fix>`, no comment before production, the needs-decision question with its two options, never a write to production) and SKILL.md's Chains and Reports from other repos saying the same; the markers it asserts are read from `triage_state.py`'s constants; passes
- S-042-10: tests/test_parent_check_docs.py (test_s042_10_*): spec-gate.md asks for the feature issue's `## Check` before the split's first step when the build deploys, and its last-build rule leaves out `Fixes #<feature>` for a feature issue with a check; passes
- S-042-11: tests/test_parent_check_docs.py (test_s042_11_*): comments.md's Upstream report template has an optional `## Check` after Suspected code, and github-issue-resolve's Phase 2 upstream row names it; passes
- S-042-12: tests/test_parent_check.py (test_s042_12_*) drives `chains.py` and the real `triage_state.py` over one scripted forge: BLOCKED, VERIFY_DUE once both children close, CHECK_FAILED, BLOCKED on the linked fix, VERIFY_DUE on its close, and nothing among the closed issues after the close and the verified comment; passes
