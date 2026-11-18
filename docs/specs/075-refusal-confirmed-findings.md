# S-075: A pull request is refused only on findings a second reviewer confirmed

status: approved
serves: G-2

## Problem

A reviewer agent's REFUSE stands on its own findings. Step 4 of the reviewer brief
(`skills/github-pr-triage/references/reviewer-brief.md`) has it reproduce a bug only before
it fixes one; a larger problem it leaves as a finding, and which refuses the pull request, is
checked by nobody. The landing session verifies the reviewer's fix commits
(`skills/github-pr-triage/SKILL.md`, step 3), not the findings it left, and `shipmill review
record --verdict refuse` records the refusal as reported (#1142, grouped into #1225, which
the maintainer accepted on 2026-11-18).

It hits maintainers whose pull requests are written and reviewed by agents. With an agent
author a false finding is not ignored: it costs a round of fixes and another review, and the
maintainer can't tell a real refusal from a mistaken one without reading the diff. Nothing
counts how often the first reviewer was wrong, so the retro can't show it. Prior art: a
verify pass over every blocking finding in another open-source delivery flow, and code
review tools that post only the findings a separate group of agents votes for.

## Behaviour

**Findings carry ids.** The Open PR brief in
`skills/github-pr-triage/references/reviewer-brief.md` has the reviewer list, in its final
report, each finding it did not fix as `F-1`, `F-2`, and so on: its file and line, the claim
in one sentence, and whether the verdict stands on it (`blocking`) or it is a nit. A REFUSE
names at least one blocking finding; a report whose REFUSE names none is sent back to its
reviewer. Findings the reviewer fixed stay as they are, checked by the landing session in
step 3 of `skills/github-pr-triage/SKILL.md`.

**The second look.** `reviewer-brief.md` gains a third brief, "Verify a refusal". For each
pull request whose reviewer reports REFUSE, the landing session launches one more agent
before it records anything: a fresh one (`subagent_type: general-purpose`, `isolation:
"worktree"`), never the first reviewer and never the landing session itself, all such agents
in one message, and in the foreground in a headless session as reviewers are. Its brief
holds the pull request, the reviewed head, and each blocking finding's id, file and line,
and claim; it holds neither the first reviewer's verdict nor the rest of its report. It
checks out the reviewed head, pushes nothing, comments nowhere, fixes nothing, and marks
every finding with exactly one of:

- `confirmed`, with the failure scenario: the input or steps, what happens, and what should, run where it can be run (a failing test or command and its output), otherwise traced through the code with file and line
- `rejected`, with the file and line of the code that already handles it, or of the rule or test that shows the claim is wrong
- `minor`, with one line saying why it is real and doesn't block: a note

It is told to agree or reject by the code, never by default: a finding it can neither show
failing nor show handled is not confirmed, and is marked `minor` with the note starting
`unproven:`. A security finding (a secret reaching output, a missing check on an entry path)
it can't settle either way is marked `confirmed` with what it could not rule out, so doubt
there refuses.

**The verdict is taken from what remains.** `skills/github-pr-triage/SKILL.md`'s step 3
takes the verifier's marks: rejected findings are dropped, minor ones become notes, and the
verdict is REFUSE only when at least one finding is confirmed; with none confirmed it is the
reviewer's verdict without the refusal, MERGE or MERGE AFTER SMALL FIX. The report the
session records is the reviewer's, followed by a "Second look" part: one line per `F-n` with
its mark and the scenario, the handling code, or the note. The handback list names only
confirmed findings, each with its failure scenario, as the reason of a REFUSE; notes travel
in the review record and the pull request's report, never as work the author owes. The
verifier's notes don't count against the rubric's nit cap. The Post-merge review brief is
unchanged.

**The record keeps the counts.** `shipmill review record` (`src/shipmill/review_record.py`,
`src/shipmill/cli.py`) gains `--findings confirmed=N,rejected=N,minor=N`, all three keys,
each a whole number of 0 or more, in any order. Given, the record's body holds, as the line
right after the verdict's marker, `<!-- shipmill:findings confirmed=N rejected=N minor=N -->`,
then the report as before. It exits 2 and writes nothing, naming the fix, when the value is
malformed (a missing or repeated key, an unknown key, a negative or non-numeric count), when
`--verdict refuse` comes with `confirmed=0` (nothing confirmed: record `merge`), and when
`--verdict merge` comes with a `confirmed` above 0 (a confirmed finding refuses). Without
`--findings` the command behaves as before, so a record made by an earlier release or by a
session that ran no second look is still written and read. A merge that follows a second
look carries the counts too, which is how an overturned refusal is recorded. `landing.md`'s
"Recording the review" shows the flag and says a refusal is recorded only after the second
look.

**The gate says which refusal it reads.** `skills/github-pr-triage/scripts/pr_gate.py` keeps
its verdict and exit code for a head whose newest record refuses it: UNREVIEWED, exit 9
(S-055-14). Its `unreviewed:` line now tells the two cases apart: for a refuse record with a
findings line, `the newest review of <sha7> on record refuses it on N confirmed
finding(s); fix them, review it again, then record it with shipmill review record`; for one
without, `the newest review of <sha7> on record refuses it on findings no second reviewer
checked; verify them (reviewer-brief.md, Verify a refusal), then record it again`. A
findings line that can't be read (not the three keys, or not right after the marker) reads
as none.

**The retro counts them.** `skills/github-ship-watch/scripts/retro.py gather` gains
`--reviews`: over the window, the review records the `--bot` logins posted (reviews whose
first line is a `shipmill:review` marker), read from GitHub alone. It prints, and `--json`
holds under `reviews`: the refuse records and how many of them carry a findings line
(`verified`) or none (`unverified`, with their pull requests); the merge records carrying a
findings line (`overturned`: the first reviewer refused, and nothing was confirmed); the
totals of confirmed, rejected, and minor findings over every record with a findings line;
and `first_reviewer_wrong`, the percent of those findings marked rejected, rounded down, or
`no data` when there are none. `skills/github-ship-watch/SKILL.md`'s weekly retro passes
`--reviews` and reports the line; it proposes nothing from it on its own.

Touched areas: `skills/github-pr-triage/references/reviewer-brief.md`,
`skills/github-pr-triage/SKILL.md`, `skills/github-pr-triage/references/landing.md`,
`skills/github-pr-triage/scripts/pr_gate.py`, `src/shipmill/review_record.py`,
`src/shipmill/cli.py` (`review record`), `skills/github-ship-watch/scripts/retro.py`,
`skills/github-ship-watch/SKILL.md`, `tests/test_review_record.py`, `tests/test_pr_gate.py`,
and `tests/test_retro.py`.

## Acceptance criteria

- S-075-1: `reviewer-brief.md`'s Open PR brief has the reviewer list each unfixed finding in its final report as `F-n` with file and line, a one-sentence claim, and `blocking` or nit, and says a REFUSE names at least one blocking finding
- S-075-2: `reviewer-brief.md` holds a "Verify a refusal" brief that gives a fresh agent the pull request, the reviewed head, and each blocking finding's id, file and line, and claim, without the first reviewer's verdict; it tells the agent to push, comment, and fix nothing, and to mark each finding `confirmed` with a failure scenario, `rejected` with the file and line that handles it, or `minor` with a note; a finding it can neither show failing nor handled is `minor` with a note starting `unproven:`, save a security finding, which is `confirmed`
- S-075-3: `skills/github-pr-triage/SKILL.md` says a reviewer's REFUSE is verified by that brief before it is recorded or handed back, by an agent that is neither the first reviewer nor the landing session, in the foreground in a headless session; that the verdict is REFUSE only with at least one confirmed finding; that the recorded report gains a "Second look" part with one line per `F-n`; and that the handback names only confirmed findings with their scenarios
- S-075-4: `shipmill review record <n> --head <sha> --verdict refuse --findings confirmed=2,rejected=1,minor=0 --body-file <f>` posts a review whose body's first line is `<!-- shipmill:review refuse -->`, whose next line is `<!-- shipmill:findings confirmed=2 rejected=1 minor=0 -->`, followed by the report; the keys are accepted in any order and written in that one
- S-075-5: `review record` exits 2 and writes nothing, with a message naming the fix, for a `--findings` value with a missing, repeated, or unknown key or a negative or non-numeric count, for `--verdict refuse` with `confirmed=0`, and for `--verdict merge` with `confirmed` above 0
- S-075-6: `review record` without `--findings` writes the same body as before for either verdict, and `--verdict merge --findings confirmed=0,rejected=2,minor=1` writes the merge marker followed by the findings line
- S-075-7: `pr_gate.py` reads a head whose newest covering record is a refuse UNREVIEWED, exit 9, with the `unreviewed:` line naming the confirmed count when the record's second line is a readable findings line, and the line `refuses it on findings no second reviewer checked` when it has none or one that can't be read; a merge record reads READY with or without a findings line
- S-075-8: `retro.py gather --reviews` counts, over the window, the `--bot` logins' refuse records as `verified` (with a findings line) or `unverified` (without, listing their pull requests), the merge records with a findings line as `overturned`, and the totals of confirmed, rejected, and minor findings; `first_reviewer_wrong` is the percent rejected of all three, rounded down, and `no data` with none; `--json` holds them under `reviews`; a review by anyone else, or one outside the window, counts for nothing
- S-075-9: `landing.md`'s "Recording the review" shows `--findings` and says a refusal is recorded only after the second look, and `skills/github-ship-watch/SKILL.md`'s weekly retro passes `--reviews` to `retro.py gather`

## Out of scope

- A second look at a MERGE: a missed bug is another problem than a false finding, and the measure it would move is the change failure rate the retro already reports
- Refusing a refuse record without `--findings` in `review record` or the gate: it would change S-055-16, so it is listed under "Decisions for you" in the spec PR as the alternative
- A vote of several verifiers per finding: one independent look per refused pull request is the cost this spec takes on; the retro's counts say whether more is needed
- The landing session's inline review of a docs-only pull request, which checks each claim against the source itself and needs no review record (S-055-15)
- A person's review: a trusted person's APPROVED review stays a record as it is, and a person's request for changes is theirs
- The Post-merge review brief, whose reviewer fixes each bug with proof instead of refusing
- Proposing a change from the counts (a stricter brief, another model for the first reviewer): the retro reports the rate and the maintainer decides

## Decisions relied on

- D-29
- D-54
- D-62

## Issues

- shipmill/shipmill#1272: S-075-4, S-075-5, S-075-6
- shipmill/shipmill#1274: S-075-7
- shipmill/shipmill#1275: S-075-8
- shipmill/shipmill#1279: S-075-1, S-075-2, S-075-3, S-075-9

## Verification
