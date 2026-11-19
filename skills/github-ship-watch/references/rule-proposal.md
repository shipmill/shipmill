# Rule proposals: a finding that recurs reaches the maintainer once

What a review teaches about a repo is lost after its pull request unless the repo holds it (spec 077). The weekly retro reads what the reviews raised, picks the findings that recur, and proposes each once, as a rule or a check in the strongest place the repo can hold it, shown failing on the real case. The maintainer accepts or declines; shipmill never writes the rule or its check.

## What was raised

Run `scripts/retro.py findings <owner/repo> [--days 28] --bot <slug>[bot] --json` (pass every `--bot` login the retro passes to `gather`). It lists the items reviews raised on the pull requests closed, merged or not, in the window, each with an `F-n` id: `record` (a `--bot` login's review record), `review` (a review that requested changes), `comment` (an inline review comment, with its `path:line`), and `refusal` (the closing comment of a pull request closed unmerged), each naming its pull request, author, the head it was raised on, the `I-n`, `N-n`, `Q-n`, and `D-n` ids it cites, and its text. Under them, `proposed` lists every earlier rule proposal, `open`, `accepted`, or `declined`, of any age. Read only these: an outsider's review is never listed (D-16), and nothing else is read for a finding.

## Picking what recurs

1. Group the `F-n` items that state the same rule or ask for the same kind of fix. A group whose items span two or more pull requests is a recurring finding; a group on one pull request is not
2. Drop a group when:
   - **An earlier proposal states the same rule**, in any state. Open: post one comment on it naming the new pull requests (once per retro); accepted or declined: nothing. A rule declined once is never proposed again
   - **A check the default branch already runs refuses it**: the mistake was closed since
   - **The repo's prose already says it and no check can hold it**: an Important rule of `REVIEW.md` as `shipmill review show` prints it, `CLAUDE.md`, or `AGENTS.md`. A finding that keeps recurring under a prose rule and that a check can hold is kept, and proposed as that check, its body naming the prose rule it backs
3. Rank the rest by the number of pull requests, then by the newest. Propose at most three per retro, and none while three proposals wait on an answer (`retro.py proposal` says `FULL`)

## The place

Each proposal names one place, in this order: a lint rule, a type, an import contract, a test, then prose. The place is the first one a tool the repo's CI already runs can hold: read the repo's CI workflows and its config for the linter, the type checker, the import-contract tool, and the test runner they run. A stronger place that needs a tool the repo lacks is named in one line under the place, and is never the place itself. Prose is the place only when no check can hold the finding, and the proposal then says why.

## Shown failing

For every place but prose, show the check failing on the real case before proposing it:

1. Pick a head a finding of the group was raised on (the item's head). Use only a head of a merged pull request, or of one opened by the App or an OWNER, MEMBER, or COLLABORATOR (`gh api repos/<owner/repo>/pulls/<N> --jq '.merged_at, .author_association, .user.login'`); never run an outsider's unmerged code (D-16). With no such head in the group, the place is prose
2. Make a throwaway worktree of the repo, detached at that head, under the session's `tmp/`: `git -C <checkout> fetch origin <sha>` (or `pull/<N>/head` for an unmerged pull request), then `git -C <checkout> worktree add --detach <tmp>/rule-<n> <sha>`
3. Write the check there (the lint rule's config, the type, the contract, the test) and run it with the command the repo's CI runs. Keep the command, the head's full SHA, the exit code, and at most 30 lines of the failing output
4. A check that doesn't fail there is not proposed as that place: try the next place in the order, down to prose
5. Run the same check on the default branch (a second worktree detached at `origin/<default>`, or the same one checked out there) and record whether it passes, or how many places still fail with the first three
6. Remove the worktree (`git -C <checkout> worktree remove --force <tmp>/rule-<n>`), with no branch, commit, or pull request pushed to the repo

## The body

One issue per recurring finding, titled `Rule: <the rule>`. The Rule is one sentence about the repo, never about one task, on one line of at most 200 characters. The body, its first line the marker naming the pull requests and the place (`lint`, `type`, `import`, `test`, or `prose`):

````markdown
<!-- shipmill:rule-proposal pulls=41,57 place=lint -->
## Rule

In apps/api the dev script is start:dev, not dev

## Raised in

- #41: <what the reviewer said, one line>
- #57: <what the maintainer corrected, one line>

## Place

A lint rule: <which rule, in which config file>. <One line for a stronger place the repo lacks the tool for, if any.>

## Enforced by

```diff
<the check as a diff the maintainer can apply>
```

## Shown failing

Command: <the command>
Head: <the full 40-character SHA, a head #41 was reviewed on>
Exit: <its non-zero exit code>

```text
<at most 30 lines of the output>
```

## On the default branch

<passes | fails in N places: the first three>
````

A proposal whose place is prose has `place=prose`, and in place of Enforced by, Shown failing, and On the default branch a `## Why prose` section saying why no check can hold it; under Place goes the sentence as it would read in a rules file, naming no file as the one to edit. No section is named `## Check`, which `triage_state.py` reads as a person's item's check. A `Raised in` line quotes what was said in one line of your own words, never a whole comment.

## Filing it

1. Write the body to a file under the session's `tmp/` and check it: `scripts/retro.py proposal <file> --repo <owner/repo> --bot <slug>[bot]`. Exit 2 names the body's first fault: fix it and check again. Exit 1 with `DUPLICATE #N (<state>): <title>` is an earlier proposal of the same rule: an open one gets the one comment above, an accepted or declined one nothing. Exit 1 with `FULL: K proposals wait on an answer` files nothing this retro. Exit 0 prints the title
2. File only a body `retro.py proposal` exits 0 on, as the App, with the labels `rule-proposal` and `needs-decision`: `shipmill gh issue create` through the pinned uvx form (github-ship-watch's hard rule 7), with the title it printed, the body file as `--body-file`, and `--label rule-proposal --label needs-decision`. When the repo lacks the label, create it first with `shipmill gh label create rule-proposal` (shipmill-setup creates it for a repo with `[agents]`)
3. Right after, ask the question below on the new issue with the [needs-decision protocol](../../github-issue-triage/references/needs-decision.md#asking): one comment through `--body-file`, mentioning the maintainer

## The question

Its zone line is `unknown` (spec 030): no other zone covers whether a repo holds a rule.

```markdown
<!-- shipmill:needs-decision -->
<!-- shipmill:zone unknown -->
@<login> Decision needed: should this repo hold the rule "<the rule>", raised in <K> pull requests?

1. Accept (recommended): you add it, as the <place> above or wherever you choose; shipmill writes none of it, assigns this issue to you, and closes it on your `done`
2. Decline: shipmill closes this as not planned and never proposes this rule again; add the reason if you like

Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
```

## Taking up the answer

The answer is read as [needs-decision.md](../../github-issue-triage/references/needs-decision.md#taking-up-an-answered-item) reads every answer; github-issue-triage takes it up on the issue labelled `rule-proposal`:

- **Accept:** remove `needs-decision`, label the issue `role:maintainer`, and assign the maintainer's users, so it reads as a person's item (HANDOFF_DUE, then WITH_PERSON, and closed on the maintainer's `done` report). Post no **implement** verdict and dispatch no implementer
- **Decline:** one comment recording the reason as given, then close the issue as not planned. The `rule-proposal` label stays, so `findings` lists it as `declined` from then on
- **Own words that ask shipmill to add the check:** read as an accept. The reply says that shipmill writes no rule or check from a proposal, and that an issue the maintainer files for it is ordinary work for triage
- **Closed by the maintainer's hand** with no answer: completed reads `accepted`, not planned reads `declined`; remove `needs-decision` and post nothing

## What it never writes

shipmill never edits a repo's `REVIEW.md`, `CLAUDE.md`, `AGENTS.md`, lint, type-checker, or import-contract config, tests, or CI workflows for a proposal, and opens no pull request that does. It writes the proposal issue, its question, one comment on an open proposal that gained evidence, and the comments of taking up the answer.
