# S-077: A finding that recurs in a repo reaches the maintainer once, as a proposed rule or check

status: built
serves: G-2

## Problem

What a review teaches about a connected repo is lost after the pull request: "When reviewers
keep raising the same finding there, or the maintainer keeps correcting the same thing, the
next implementer starts without it and makes the same mistake" (#1145, grouped into #1227,
which the maintainer accepted on 2026-11-18). shipmill's own lessons go into its skills; a
connected repo has no such place that shipmill may write, since its `REVIEW.md`, `CLAUDE.md`,
`AGENTS.md` and checks are the maintainer's.

It hits the maintainer of every connected repo who corrects the same mistake in pull request
after pull request. The weekly retro already reads the week's review comments for findings
that recurred (`skills/github-ship-watch/SKILL.md`, Weekly retro, step 2), but it proposes a
skill edit, a check, or a decision as an ordinary issue, which fits shipmill's own repo and
not a client's: nothing says where the rule would live, nothing shows it would have caught
the real case, and a proposal the maintainer turned down can come back the next week.

The second comment on #1145 adds the ranking. A rule in `REVIEW.md`, `CLAUDE.md` or
`AGENTS.md` is advice: the next implementer can miss it, and a reviewer has to catch it again
in every pull request. A lint rule, a type, an import boundary or a test refuses the mistake
before review. That is the reasoning of spec 026 for shipmill's own failures (a hook under
the skill's text for the mistakes that cost most), and it holds for a connected repo too.

## Behaviour

**What was raised.** A new subcommand, `retro.py findings <owner/repo> [--days D] [--bot
<login>]... [--json]` (`skills/github-ship-watch/scripts/retro.py`), lists what reviews
raised on the pull requests closed, merged or not, in the last D days (default 28, at least
1), read from GitHub only (D-6). Per pull request it lists items, each with an id `F-1`,
`F-2`, and so on, newest pull request first:

1. **Review records** (`record`): a review by a `--bot` login whose body's first line is
   `<!-- shipmill:review merge -->` or `<!-- shipmill:review refuse -->` (spec 055)
2. **A person's reviews** (`review`) and **inline review comments** (`comment`): a review that
   requested changes, and a review comment on a line, by an OWNER, MEMBER, or COLLABORATOR who
   is no `--bot` login, its body without the agent marker (D-62)
3. **Refusals** (`refusal`): for a pull request closed without a merge, the newest comment at
   or before the close by a `--bot` login or an OWNER, MEMBER, or COLLABORATOR

Each item names its pull request, kind, author, the head it was raised on (the review's
`commit_id`, a comment's `original_commit_id`, or the pull request's head for a refusal), a
comment's `path:line`, the rule ids its text cites (`I-n`, `N-n`, `Q-n`, `D-n`), and its text
cut at 600 characters, then `…`. Anything by another author is left out whole (D-16), and a
pull request with no item is not listed. Under the items it lists **Proposed**: every issue
of the repo labelled `rule-proposal`, in any state and of any age, whose body's first line
is the proposal marker (below) and whose author is a `--bot` login or an OWNER, MEMBER, or
COLLABORATOR, with its number, title, the marker's pull requests, and its state: `open`,
`accepted` (closed as completed), or `declined` (closed as not planned). `--json` prints one
object with the keys `window`, `findings`, and `proposed`. A `--days` below 1, a window with
more closed pull requests than `gather` reads, or a failed GitHub read exits 2 and prints no
partial list.

**Picking what recurs.** The Weekly retro of `skills/github-ship-watch/SKILL.md` gains a step
after Gather, described in a new `skills/github-ship-watch/references/rule-proposal.md`. The
session groups the `F-n` items that state the same rule or the same kind of fix; a group that
spans two or more pull requests is a recurring finding. It drops a group when:

- An earlier proposal in the Proposed list, in any state, states the same rule: open, it
  gets one comment naming the new pull requests; accepted or declined, it gets nothing
- A check the repo runs already refuses it on the default branch (the mistake was closed
  since)
- The repo's prose already says it (an Important rule of `REVIEW.md` as `shipmill review show`
  prints it, `CLAUDE.md`, or `AGENTS.md`) and no deterministic check can hold it. A finding
  that keeps recurring under a prose rule and that a check can hold is kept: it is proposed
  as that check, its body naming the prose rule it backs

The rest are ranked by the number of pull requests, then by the newest. At most three are
proposed per retro, and none while three proposals wait on an answer. Findings from reviews
no longer feed step 3's change proposals, in any repo, shipmill's own included: step 3 keeps
the stuck states and the metrics.

**The strongest place.** Each proposal names one place, the first in this order that can
refuse the mistake with a tool the repo's CI already runs: a lint rule, a type, an import
contract, a test, then prose. A stronger place that needs a tool the repo lacks is named in
one line under the place and is never the place itself. Prose is the place only when no
check can hold the finding, and the proposal then says why.

**Shown failing.** For every place but prose the session writes the check (the lint rule's
config, the type, the contract, the test) in a throwaway worktree of the repo, detached at a
head one of the group's items was raised on, runs it there, and keeps the command, the head,
the exit code, and at most 30 lines of the failing output. It runs only at a head of a merged
pull request, or of one opened by the App or by an OWNER, MEMBER, or COLLABORATOR, never an
outsider's unmerged code (D-16). A check that doesn't fail there is not that place: the
session tries the next place in the order. It then runs the same check at `origin/<default>`
and records whether it passes or how many places still fail. The worktree is removed; no
branch, commit, or pull request reaches the repo.

**The proposal.** One issue per recurring finding, filed as the App (`shipmill gh issue
create`, D-14) with the labels `rule-proposal` and `needs-decision`, its title `Rule: <the
rule>`. Its body:

    <!-- shipmill:rule-proposal pulls=41,57 place=lint -->
    ## Rule

    In apps/api the dev script is start:dev, not dev

    ## Raised in

    - #41: <what the reviewer said, one line>
    - #57: <what the maintainer corrected, one line>

    ## Place

    A lint rule: <which rule, in which config file>. <One line for a stronger place the repo
    lacks the tool for, if any.>

    ## Enforced by

    <the check as a diff the maintainer can apply, in a fenced block>

    ## Shown failing

    Command: <the command>
    Head: <the full SHA, a head #41 was reviewed on>
    Exit: <its non-zero exit code>

    <at most 30 lines of the output, in a fenced block>

    ## On the default branch

    <passes | fails in N places: the first three>

The Rule is one sentence about the repo, never about one task, on one line of at most 200
characters. A proposal whose place is prose has `place=prose`, a `## Why prose` section in
place of Enforced by, Shown failing, and On the default branch, and under Place the sentence
as it would read in a rules file, naming no file as the one to edit. No section is named
`## Check`, which `triage_state.py` reads as a person's item's check.

`retro.py proposal <body-file> --repo <owner/repo> [--bot <login>]... [--max-open 3]` checks
a body before it is filed. It exits 2, naming the first fault, when the marker isn't the
first line, names fewer than two distinct pull requests, or names a place outside `lint`,
`type`, `import`, `test`, `prose`; when a section is missing or empty; when Rule isn't one
line of at most 200 characters; when Raised in lacks a `- #N` line for a pull request of the
marker; when, for a place other than prose, Shown failing lacks a `Command:` line, a `Head:`
line with a full 40-character SHA, an `Exit:` line with a non-zero number, or a fenced
output of 1 to 30 lines; or when a prose proposal lacks Why prose. It exits 1 and prints
`DUPLICATE #N (<state>): <title>` when the title matches a Proposed issue's in any state
(compared as `dedupe` compares titles), or `FULL: K proposals wait on an answer` when
`--max-open` or more Proposed issues are open with the `needs-decision` label. It exits 0
and prints the title otherwise. The session files only a body that exits 0.

**The question.** Right after filing, the session asks with the needs-decision protocol on
the proposal issue, its zone line `unknown` (spec 030), mentioning the maintainer:

```markdown
<!-- shipmill:needs-decision -->
<!-- shipmill:zone unknown -->
@{login} Decision needed: should this repo hold the rule "{the rule}", raised in {K} pull requests?

1. Accept (recommended): you add it, as the {place} above or wherever you choose; shipmill writes none of it, assigns this issue to you, and closes it on your `done`
2. Decline: shipmill closes this as not planned and never proposes this rule again; add the reason if you like

Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
```

**Taking up the answer.** `skills/github-issue-triage/references/needs-decision.md` (Taking
up an answered item) points a `rule-proposal` issue at `rule-proposal.md`:

- **Accept:** remove `needs-decision`, label the issue `role:maintainer` and assign the
  maintainer's users, so it reads as a person's item (HANDOFF_DUE, then WITH_PERSON, and
  closed on the maintainer's `done` report). No **implement** verdict is posted and no
  implementer is dispatched
- **Decline:** one comment recording the reason as given, then close as not planned. The
  label stays, so `findings` lists it as `declined` from then on
- **Own words that ask shipmill to add the check:** read as an accept. The reply says that
  shipmill writes no rule or check from a proposal, and that an issue the maintainer files
  for it is ordinary work for triage
- **Closed by the maintainer's hand** with no answer: completed reads `accepted`, not planned
  reads `declined`; the session removes `needs-decision` and posts nothing

Under this spec shipmill never edits a repo's `REVIEW.md`, `CLAUDE.md`, `AGENTS.md`, lint,
type-checker, or import-contract config, tests, or CI workflows, and opens no pull request
that does: it writes the proposal issue, its question, one comment on an open proposal that
gained evidence, and the comments of taking up the answer. The retro's tracking comment lists
the week's rule proposals with their links beside what recurred.

**Setup.** `skills/shipmill-setup/SKILL.md` adds `rule-proposal` to the labels it creates for
a repo with `[agents]`; the retro creates it when it is missing (`shipmill gh label create
rule-proposal`).

Touched areas: `skills/github-ship-watch/scripts/retro.py` (`findings`, `proposal`),
`skills/github-ship-watch/SKILL.md` (Weekly retro),
`skills/github-ship-watch/references/rule-proposal.md` (new),
`skills/github-issue-triage/references/needs-decision.md`, `skills/shipmill-setup/SKILL.md`
(labels), the `rule-proposal` label, the `<!-- shipmill:rule-proposal -->` marker, and
`tests/test_retro.py`.

## Acceptance criteria

- S-077-1: `retro.py findings <owner/repo>` lists, for a pull request closed within `--days`, a `--bot` login's review whose first line is `<!-- shipmill:review refuse -->` as a `record` item, a COLLABORATOR's review that requested changes as a `review` item, and their inline review comment as a `comment` item with its `path:line`, each with an `F-n` id, the pull request's number, the author, the head it was raised on, and the `I-n`, `N-n`, `Q-n`, and `D-n` ids its text cites; a pull request closed before the window is not listed
- S-077-2: a pull request closed without a merge lists its newest comment at or before the close by a `--bot` login or an OWNER, MEMBER, or COLLABORATOR as a `refusal` item; a merged pull request has no `refusal` item
- S-077-3: a review, review comment, or closing comment by an author who is not an OWNER, MEMBER, COLLABORATOR, or a `--bot` login, and a person's review or review comment carrying the agent marker, is not listed, in the text and the `--json` output; a pull request left with no item is not listed; an item's text is cut at 600 characters followed by `…`
- S-077-4: `findings` lists under Proposed every issue labelled `rule-proposal` whose body's first line is the `<!-- shipmill:rule-proposal ... -->` marker and whose author is a `--bot` login or an OWNER, MEMBER, or COLLABORATOR, whatever its age, with its number, title, the marker's pull requests, and the state `open`, `accepted` for one closed as completed, or `declined` for one closed as not planned; an issue with the label by another author, or without the marker, is not listed
- S-077-5: `findings --json` prints one object with the keys `window`, `findings`, and `proposed`; a `--days` below 1, a window that reaches the closed pull request limit, or a failed GitHub read exits 2 with a message naming the fix and prints no list
- S-077-6: `retro.py proposal <file> --repo <owner/repo>` exits 2 naming the fault when the marker is not the body's first line, names fewer than two distinct pull requests, or names a place other than `lint`, `type`, `import`, `test`, or `prose`; when the Rule, Raised in, or Place section is missing or empty; when Rule is more than one line or over 200 characters; or when Raised in has no `- #N` line for a pull request the marker names
- S-077-7: for a body whose place is not `prose`, `proposal` exits 2 when Enforced by has no fenced block, when Shown failing lacks a `Command:` line, a `Head:` line holding a 40-character SHA, or an `Exit:` line holding a non-zero number, when its fenced output is empty or longer than 30 lines, or when On the default branch is missing; a `prose` body needs none of them and exits 2 without a non-empty Why prose section
- S-077-8: `proposal` exits 1 and prints `DUPLICATE #N (<state>): <title>` when the body's title `Rule: <the rule>` matches, case, punctuation, and spacing aside, the title of a Proposed issue that is open, accepted, or declined; in particular a rule declined once is refused however long ago it was declined
- S-077-9: `proposal` exits 1 and prints `FULL: K proposals wait on an answer` when at least `--max-open` (default 3) Proposed issues are open with the `needs-decision` label; an open proposal without that label doesn't count; a body that passes every check exits 0 and prints its title
- S-077-10: `skills/github-ship-watch/references/rule-proposal.md` holds the body template with the sections Rule, Raised in, Place, Enforced by, Shown failing, and On the default branch and none named `## Check`, the order of places (a lint rule, a type, an import contract, a test, then prose) with the rule that the place is the first one a tool the repo's CI already runs can hold, and the instruction to file only a body `retro.py proposal` exits 0 on, as the App, with the labels `rule-proposal` and `needs-decision`
- S-077-11: `rule-proposal.md` says the check is run in a throwaway worktree at a head a finding of the group was raised on, only a head of a merged pull request or of one opened by the App or an OWNER, MEMBER, or COLLABORATOR, that a check which doesn't fail there is not proposed as that place, and that the worktree is removed with no branch, commit, or pull request pushed to the repo
- S-077-12: the Weekly retro of `skills/github-ship-watch/SKILL.md` runs `retro.py findings`, takes a group of `F-n` items spanning two or more pull requests as a recurring finding, names the three reasons to drop one (an earlier proposal in any state, a check the default branch already runs, prose that says it where no check can hold it), proposes at most three per retro, and says step 3's change proposals no longer come from review findings; its closing paragraph lists `REVIEW.md`, `CLAUDE.md`, `AGENTS.md`, the repo's checks, and its CI workflows among what the retro never edits
- S-077-13: `rule-proposal.md` holds the needs-decision question with the zone line `unknown` and the options Accept and Decline as above, and `needs-decision.md` (Taking up an answered item) names it for an issue labelled `rule-proposal`: an accept removes `needs-decision`, adds `role:maintainer`, assigns the maintainer's users, and posts no **implement** verdict; a decline comments the reason and closes the issue as not planned with the `rule-proposal` label kept
- S-077-14: `skills/shipmill-setup/SKILL.md` lists `rule-proposal` among the labels created for a repo with `[agents]`

## Out of scope

- A pull request by shipmill that adds the accepted rule or check, in any file: where a rule lives and who writes it stay the maintainer's (N-3, the Notes of #1227). An issue the maintainer files for it is ordinary work under the existing gates
- Matching findings by code: which items state the same rule is the session's reading of the `F-n` list; `retro.py` gathers them and holds the title, the format, and the cap
- Findings from outside reviews (CI failures, incidents, reverts): incidents have postmortems, and reverts reach the reviewer through spec 073
- Passing accepted rules to implementers or reviewers by shipmill: they read the repo's own rules files and checks, where the maintainer put the rule
- A proposal across the repos of a product: each repo's retro proposes for its own repo
- A new zone for the question: it is asked in `unknown`; see "Decisions for you" in the spec PR
- Proposing again when a declined rule's finding keeps recurring: reopening the declined issue is the maintainer's way to ask for it

## Decisions relied on

- D-6
- D-10
- D-14
- D-16
- D-34
- D-48
- D-62

## Issues

- shipmill/shipmill#1277: S-077-1, S-077-2, S-077-3, S-077-4, S-077-5
- shipmill/shipmill#1280: S-077-6, S-077-7, S-077-8, S-077-9
- shipmill/shipmill#1284: S-077-10, S-077-11, S-077-12, S-077-13, S-077-14

## Verification

Checked on the default branch plus #1284's pull request: `retro.py findings shipmill/shipmill --days 1` and `retro.py proposal` run against this repo, the documents read, and the tests `specs.py coverage --spec 077` lists, all passing.

- S-077-1: `findings shipmill/shipmill --days 1 --bot shipmill-romamo[bot]` lists the day's closed pull requests newest first, each review record as an `F-n` `record` item with its author, head SHA, and cited `D-n` and `Q-n` ids; `test_s077_1_*` covers the `review` and `comment` items with `path:line` and a pull request closed before the window
- S-077-2: `test_s077_2_*` lists an unmerged pull request's newest trusted comment at or before the close as a `refusal`, and none for a merged one
- S-077-3: `test_s077_3_*` leaves out an outsider's review, comment, and closing comment and a person's marked review in the text and `--json`, drops a pull request left empty, and cuts a long text at 600 characters with `…`
- S-077-4: `test_s077_4_*` lists the trusted, marked `rule-proposal` issues as `open`, `accepted`, and `declined` whatever their age, and leaves out an outsider's and an unmarked one
- S-077-5: `test_s077_5_*` reads `--json`'s `window`, `findings`, and `proposed`, and exits 2 with no list on `--days 0`, a window at the closed pull request limit, and a failed read
- S-077-6: `test_s077_6_*` exits 2 naming each fault of the marker, the sections, the Rule's length and lines, and a missing `- #N`, reading nothing; a 200-character Rule passes
- S-077-7: `test_s077_7_*` exits 2 for each missing piece of a check place's Enforced by, Shown failing (`Command:`, a 40-character `Head:`, a non-zero `Exit:`, 1 to 30 output lines), and On the default branch, and for a prose body without Why prose
- S-077-8: `test_s077_8_*` prints `DUPLICATE #N (<state>): <title>` with exit 1 for an open, an accepted, and a long-declined proposal of the same rule, case, punctuation, and spacing aside
- S-077-9: `proposal tmp/rule-check.md --repo shipmill/shipmill`, a body filled from rule-proposal.md's template, exits 0 printing `Rule: In apps/api the dev script is start:dev, not dev`; `test_s077_9_*` prints `FULL: 3 proposals wait on an answer` with exit 1, an open proposal without `needs-decision` not counted
- S-077-10: rule-proposal.md's template has the six sections in order and no `## Check`, and filled in it passes `proposal_fault`; The place gives the order and the first place the repo's CI can hold; Filing it files only a body `retro.py proposal` exits 0 on, as the App, with `rule-proposal` and `needs-decision` (`test_s077_10_*`)
- S-077-11: rule-proposal.md's Shown failing runs the check in a throwaway worktree at a head a finding was raised on, a merged pull request's or a trusted author's only, drops a place whose check doesn't fail there, and removes the worktree with nothing pushed (`test_s077_11_*`)
- S-077-12: the Weekly retro's step 2 runs `retro.py findings`, takes a group across two or more pull requests as recurring, names the three reasons to drop one, and proposes at most three; step 3 says its change proposals no longer come from review findings; the closing paragraph names `REVIEW.md`, `CLAUDE.md`, `AGENTS.md`, the repo's checks, and its CI workflows (`test_s077_12_*`)
- S-077-13: rule-proposal.md's question has the zone line `unknown` and the options Accept and Decline; needs-decision.md's Taking up an answered item sends a `rule-proposal` issue there, an accept removing `needs-decision`, adding `role:maintainer`, assigning the maintainer's users, with no **implement** verdict, a decline commenting the reason and closing as not planned with the label kept (`test_s077_13_*`)
- S-077-14: shipmill-setup's SKILL.md lists `rule-proposal` among the `[agents]` labels in both of its lists, and `setup_state.py`'s `wanted_labels` wants it with `[agents]` and not without (`test_s077_14_*`)
