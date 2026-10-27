# Issue comments

Write each body to a file and post it with `gh issue comment <n> --body-file <file>`. Keep the files in the repo's `tmp/` folder. Start every triage comment with `Triage:` followed by the bolded verdict, because `triage_state.py` finds triage comments by that prefix. Follow the user's writing rules: no trailing periods on list items, and em dashes only rarely.

**The goal, in the verdict line.** When the repo has `docs/product.md`, a verdict on new behaviour names the goal it serves right after the bolded verdict, `Serves: G-n.` (several as `Serves: G-2, G-3.`), from the direction's Goals; a non-goal it hits gets the Won't fix (non-goal) template, and a feature that serves no goal the Postpone (no goal) template; a user's request that serves no goal keeps the Opportunity template with `Serves no goal.` in its slot ([triage-rubric.md](triage-rubric.md), The direction). A bug fix or a contract tweak serves the quality bar and names no goal, and a repo without `docs/product.md` leaves the `{ Serves: G-n.}` slots out.

**Who decides a verdict.** In a repo whose config has `[agents]`, won't fix, duplicate, postpone, and close as done are the `triage-verdict` zone, and its level says whether the verdict also gets a decided comment and the `decided` label (`notify`, the default) or waits on a question (`ask`), as [Who decides](needs-decision.md#who-decides) says.

## Implement

```markdown
Triage: **implement**{, for the next release candidate | after rcN}.{ Serves: G-n.}{ Waits on your decision below.}

{Only while a design question is open (design-gate.md, step 3), and only in a session the user started by hand; the block goes first, before the plan. A gate session posts the block as its own needs-decision comment instead, right after this one:}
**Decision needed:** {the question in one sentence, in words a user of the tool knows}

1. {option} (recommended): {what it means for users}
2. {option}: {what it means for users, what it costs}

Reply here with a number or your own answer{, or in the gate session}; nothing is built until you do.

The plan:

- {change 1}
- {change 2}

{Only for a contract change (design-gate.md):}
**Design.** {The contract change exactly: flag, field and type, default.} {Why this over the alternative.} {Compatibility: who breaks, and the migration.} {Relies on D-n.} {How it's tested.}

{What is deliberately left out, and where it went (a postponed issue, 1.1).} I'll link the PR here.
```

Write the decision block for the person who owes the answer, not for the implementer: no file, function, or permission names in the question or the options unless the answer turns on them, and then say what each one means. Name the effect instead ("repos without ship-watch stay stuck until someone notices"). Keep the options to the ones you'd accept, two or three, the recommended one first. The same block, under the same heading, asks a PR's "decisions for you" on the pull request (design-gate.md, step 3).

In a gate session (its prompt carries the gate's `Gate session:` or `Headless:` paragraph), the block never sits in the verdict: the verdict keeps "Waits on your decision below" and the question follows as its own comment, the [needs-decision protocol](needs-decision.md)'s, with the marker as its first line and the `needs-decision` label on the issue (D-21). Without the marker and the label, the scripts read the issue as work and the gate keeps starting sessions for it.

An answer the user gives in the session (to this block, to a PR's "decisions for you", or to a needs-decision question) goes on the item before you act on it. Posted as the App (`shipmill gh` with `[agents] app_id` set), its first line is `Decision by @<login>, relayed by <agent>`, so the thread tells the person's decision from agent text; `<login>` is the person who answered and `<agent>` names the tool (`Claude Code`):

```markdown
Decision by @{login}, relayed by {agent}

{The option chosen, or the user's own words}
```

Once the PR is up:

```markdown
The fix is in #{PR}: {what it does, in one or two sentences}. {Any trade-off or behaviour change, e.g. "a real permission error takes up to 2 s to surface on Windows".} {The answer to the issue's open question, if it had one.} This issue closes when #{PR} merges.
```

## Opportunity

A request for a new capability that no accepted opportunity covers goes to product intake (triage-rubric.md, A new capability). The verdict is the marker intake uses itself, so `triage_state.py` reads the issue TRIAGED and `intake_state.py` reads it NEW_FEEDBACK until an opportunity's Evidence section lists it. Don't use the word "implement" in this comment, and don't put an issue number right after a hold phrase ("waits on #40"): `triage_state.py` would read NEEDS_PR or BLOCKED.

```markdown
Triage: **opportunity**.{ Serves: G-n.} {What the request asks for, in one sentence}: a new capability, not a bug fix or a contract tweak. It goes to product intake, which groups it with the requests for the same outcome into one opportunity issue{, likely #{open opportunity}}; the maintainer accepts or declines that opportunity, and an accepted one gets a spec before anything is built. Follow this issue for the link to the opportunity.
```

## Feature

A feature waits for its spec ([spec-gate.md](spec-gate.md)). Keep "On hold" and the spec PR's `owner/repo#N` in one sentence of one line, so `triage_state.py` reports BLOCKED until the spec merges and UNBLOCKED after. Don't use the word "implement" in this comment: the script reads the latest triage comment's verdict from it.

```markdown
Triage: **feature**.{ Serves: G-n.} {What the new behaviour is, in one or two sentences, and why it isn't a bug fix or a contract tweak.}

The spec is in #{spec PR} (`docs/specs/{NNN}-{slug}.md`), with its acceptance criteria. Merging it is the approval, as is an answer on it that takes every recommendation, after which shipmill merges it once it is green; the build starts once it merges.

On hold: the build waits on {owner/repo}#{spec PR}, the spec
```

A request an accepted opportunity covers is built under that opportunity: its spec is the opportunity's, so the request holds on the opportunity issue, which closes when the build does. Add the request to the opportunity's Evidence section too.

```markdown
Triage: **feature**.{ Serves: G-n.} This asks for the outcome of #{opportunity}, which the maintainer accepted; it's built under that issue{, whose spec is in #{spec PR}}, and this one closes with it.

On hold: built under {owner/repo}#{opportunity}, the accepted opportunity
```

In a gate session, the spec PR asks for its approval with the [needs-decision protocol](needs-decision.md), on the spec PR itself, with these options (D-49). Option 1 never asks the maintainer to merge by hand: a trusted answer taking it is the approval, and github-pr-triage lands the spec PR once it is green ([spec-gate.md](spec-gate.md), Approved by an answer). A spec PR that edits `docs/product.md` says instead that the maintainer merges it, since only they change the direction (D-34).

```markdown
<!-- shipmill:needs-decision -->
@{login} Decision needed: does spec {NNN}, {what it specifies} (#{feature issue}), set the behaviour the way you want, with the choices under "Decisions for you" in this PR's body?

1. Take every recommendation (recommended): your answer is the approval; shipmill rebases this PR if it needs it and merges it once it is mergeable and green, then files its build issues under #{feature issue}. You may still merge it by hand
2. Change some of them: reply with the numbers and what you want instead; the spec is revised in this PR and you're asked again, and nothing merges until then

Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
```

Once the spec merges, edit the issue body to link it and split the spec into build issues ([spec-gate.md](spec-gate.md), Split it into build issues). Comment the Implement template on each build issue, naming the spec and the criteria it delivers.

## Postpone

```markdown
Triage: **postponed to {1.1 | after 1.0}**. {Why not now: the release phase, a new wire contract, or a shared design with #A and #B.}

The plan:

- {design point}
- {design point}

{Answers to the issue's open questions, "unless someone objects".}
```

Then add the label: `gh issue edit <n> --add-label postponed`.

### Postpone (no goal)

A feature, new behaviour the maintainer already wants, that serves no goal of `docs/product.md`; a user's request that serves none goes to product intake instead (Opportunity). Add the `postponed` label as above. Don't use the word "implement" in this comment, and name no issue right after a hold phrase: `triage_state.py` would read NEEDS_PR or BLOCKED.

```markdown
Triage: **postponed**: it serves no goal of the direction. {What it asks for, in one sentence}: new behaviour, and none of the goals in `docs/product.md` ({G-n: its words, for the nearest one}) covers it.

It would need a goal such as "{the outcome it would serve}". The maintainer adds that goal to the direction, and this is decided again, or lets it wait.
```

## Won't fix (non-goal)

New behaviour that hits a non-goal of `docs/product.md`. Close the issue as not planned (`gh issue close <n> --reason "not planned"`) after posting.

```markdown
Triage: **won't fix**: it hits {N-n}, "{the non-goal's words}". {Why the request falls under it, in one or two sentences.}

The direction is the maintainer's to change; if it changes, this can be reopened.
```

## Clarify

```markdown
Triage: **needs a decision**. {What conflicts, with exact values and the requirement or doc IDs.}

Options:

1. {option}: {consequence}
2. {option}: {consequence}

I'd go with {n} because {reason}.{ The other repo's part is reported in #{R}, an upstream report in this repo.}
```

What only another repo can settle (a spec the project implements, a module another repo owns) goes in an upstream report in this repo, below, never in an issue filed in the other repo.

## Upstream report

A fault traced to a module another repo owns is reported in this repo, never in the other one (spec 038, D-47): an issue labelled `upstream`, filed with `issue create --label upstream --body-file <file>` through `shipmill gh` (as the App with `[agents] app_id` set). Its body:

```markdown
{What fails, in one sentence}. It holds #{N}.

## Reproduce

{How to reproduce it: the steps or the command, and what came back}

## Touches

{The object it touches: an endpoint, a table, an index, a package and its version}

## Suspected code

{The place in the module's source, as owner/repo path:line, when you traced the cause there; a guess you couldn't trace starts with `Guess:`, such as "Guess: the index the nightly job rebuilds"}
```

A stand-in for a dependency on another repo's work has the same label: an issue in the waiting repo saying what work it needs, with a `Stands in for owner/repo#N` line when the other repo's issue already exists ([triage-rubric.md](triage-rubric.md), Links between issues).

Hold the waiting issue on it with `chains.py link <owner/repo#N> --blocked-by <owner/repo#R>`, both in this repo, and post the hold line on the waiting issue:

```markdown
On hold: waits on {owner/repo}#{R}, the upstream report of {what fails}
```

Then the report's triage comment, the first variant when the config sets `[product] home`, the second without:

```markdown
Triage: **upstream**. Routed by {owner/home}, the product's coordinator: it files the work in the repos that own it and closes this with what changed.
```

```markdown
Triage: **upstream**. No coordinator routes it: it waits for @{maintainer}, who reports it to the owning repo and closes this with what changed.
```

The coordinator's close, once every child closed (SKILL.md, Reports from other repos), written with the product token; then it closes the report as completed, or as not planned when a child closed as not planned:

```markdown
Every issue this was routed to is closed:

- {owner/repo#C}: {completed | not planned}, {by owner/repo#PR | with no pull request}
- {owner/repo#D}: {completed | not planned}, {by owner/repo#PR | with no pull request}

{What changed, in one or two sentences, for the agent that waits on this.}{ Closing as not planned: {owner/repo#D} won't be done, so the issue waiting on this is decided again.}
```

## Hold (blocked on something outside the repo)

Keep "On hold" and the upstream link in one sentence of one line, because `triage_state.py` reads that sentence to report BLOCKED and later UNBLOCKED. A sentence ends at ".", "!", or "?" before a capital letter (not after "e.g.", "i.e.", "cf.", or "vs."), so a hold word elsewhere in a paragraph doesn't hold on the links it names:

```markdown
On hold: {why, e.g. #PR goes below the spec's default of 5 rotated files}, decided in {owner/repo#N}. {What stays ready meanwhile, e.g. "#59 stays open, rebased onto main".}
```

Put the same line on the held PR.

## A cycle

An issue that reads CYCLE is on a loop of open issues each holding the next, so none can start (spec 041). Ask on the loop's first item, the one its `cycle <loop>` note starts with, through the [needs-decision protocol](needs-decision.md) (D-21), with its marker and the `needs-decision` label: which link is wrong, one option per link of the loop, each naming its form (a `Depends on` line, a native blocked-by relation, or a sub-issue), your recommendation first with the `(recommended)` mark and why. A link that is both a line and a relation is one option. The other items on the loop read BLOCKED, waiting on this question, so ask once:

```markdown
<!-- shipmill:needs-decision -->
@{maintainer} Decision needed: these issues wait on each other, so none can start: {owner/repo#A} -> {owner/repo#B} -> {owner/repo#A}. Which link is wrong?

1. {owner/repo#A} waits on {owner/repo#B} ({a Depends on line | a blocked-by relation | a sub-issue | a Depends on line and a blocked-by relation}) (recommended): {why this link is the wrong one, such as "#B only names #A for the decision recorded there"}
2. {owner/repo#B} waits on {owner/repo#A} ({its form})

Reply here with a number or your own answer; shipmill takes this up on the tick after your reply. I remove both forms of the link you pick, the `Depends on` line and the relation.
```

## A person's item

An issue labelled `role:<name>` (or `human`, which counts as `role:maintainer`) gets no triage verdict: its assignees do it ([triage-rubric.md](triage-rubric.md), A person's item). Each comment below starts with its marker as the first line where it has one, since `triage_state.py` reads the marker only there and only from the `--bot-login` or a trusted author.

**ASSIGN_DUE** gets no comment: assigning the users its note names is the whole step, and GitHub's assignment is the notification. The hand-off comes once the item's holds close.

**HANDOFF_DUE**, the hand-off: a mention of every assignee and of every team its roles resolve to (the note's `for @a @example-org/legal`, or the `assignees` and `teams` lists of its `--json` line), which holds closed, the issue's steps quoted (never rewritten), its `## Check` when it has one, and how to report. A team can't be assigned, so the mention is how its members hear of the step; a team-only role's item mentions the team alone. Post it once per unblock; nothing mentions the person or the team again while the item reads WITH_PERSON. A done report counts from an assignee or a trusted author (D-16): a team member who is a member of the repo's organization counts, an outside one doesn't.

```markdown
<!-- shipmill:handoff -->
@{assignee} @{assignee} @{org/team}, it's your turn: {owner/repo#N} closed{, and owner/repo#M}.

What to do, from this issue:

> {the issue's steps, quoted line by line}

{When the issue has one:} When it's done, this must hold:

> {its ## Check, quoted}

Reply `done` here when it's finished, or close the issue.
```

**VERIFY_DUE**, the check holds: say what was checked and what came back, then close the issue as completed (`gh issue close <n> --reason completed`), which unblocks whatever it held. With no `## Check`, say "Closed on @{login}'s report: this issue has no ## Check" instead.

```markdown
Checked: `{the check}` returned {what came back}, as the ## Check asks. Closing as done.
```

**VERIFY_DUE**, the check fails: a new hand-off, so the item reads WITH_PERSON again.

```markdown
<!-- shipmill:handoff -->
@{assignee}, the check didn't pass yet: `{the check}` returned {what came back}, and it must return {what the ## Check asks}.

Reply `done` here when it's fixed, or close the issue.
```

**VERIFY_CLOSED**, the check holds: the verified comment, which ends the state.

```markdown
<!-- shipmill:verified -->
Checked after @{login} closed this: `{the check}` returned {what came back}.
```

**VERIFY_CLOSED**, the check fails: reopen it (`gh issue reopen <n>`), then post a hand-off through `--body-file`; the open issue holds everything it blocks again.

```markdown
<!-- shipmill:handoff -->
@{assignee}, I reopened this: `{the check}` returned {what came back}, and it must return {what the ## Check asks}. What waits on this issue waits again.

Reply `done` here when it's fixed, or close the issue.
```

**NO_ASSIGNEE** gets no comment and no question: it means the state was read without the `--role` flags, so read it again with them ([triage-rubric.md](triage-rubric.md), A person's item). The roles say who does a step, so a session never asks. Only an ASSIGN_DUE assignment GitHub refuses goes to the maintainer, through the [needs-decision protocol](needs-decision.md): name the users it couldn't assign and GitHub's message, and recommend assigning the maintainer.

A check the session can't run: a question through the [needs-decision protocol](needs-decision.md), in its format, with its marker and the `needs-decision` label. Say what the report claims and why the check can't run here, and give two options, the recommended one first, as the protocol asks: close it on the report when other evidence backs the report (a log line, a page that changed), it isn't done when nothing but the report does (then it comes first, with the `(recommended)` mark and why):

```markdown
<!-- shipmill:needs-decision -->
@{maintainer} Decision needed: @{login} reported this done, and I can't run its check here (`{the check}`: {why, such as "the host isn't reachable from this machine"}).

1. Close it on the report (recommended): {the evidence beyond the report}; what waits on it starts now, unchecked
2. It isn't done: I hand it back to @{assignee}, and what waits on it keeps waiting

Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
```

## A parent's close

A parent held only by its children reads UNBLOCKED once the last closes. Close it with:

```markdown
Every sub-issue is closed:

- {owner/repo#N}: {completed | not planned}
- {owner/repo#M}: {completed | not planned}

Closing this as done.
```

A child closed as not planned doesn't stop the close; say so in its line. A feature issue first gets its spec verified ([spec-gate.md](spec-gate.md), Verify the whole spec).

## Follow-ups

- A PR was replaced: "Update: #{old} was replaced by #{new}, {rebased with review fixes}. This issue closes when #{new} merges."
- The plan changed after review, e.g. main already had part of the fix: "Update after rebasing: {what main already does}; #{PR} now only {what remains}." Also update the PR's title and body.
- A wrong auto-close: `gh issue reopen <n> --comment "Reopening: commit {sha} closed this because its message quotes {text}. The fix is in #{PR}, which hasn't merged yet."`
- A right close that reads SUSPECT_CLOSE: post the close-confirmed comment through `--body-file`, with `issue comment` once the issue is closed. Its first line is the marker exactly, and only one by an OWNER, MEMBER, or COLLABORATOR or the App, posted after the last close, counts (D-29). `gh issue close --comment` posts its comment before the close, so a marker posted that way never counts; after a reopen and a new close, post it again:

  ```markdown
  <!-- shipmill:close-confirmed -->
  The close is right: {why, such as "done by hand: the drill ran on 2026-10-08, see the run log" or "the fix is on main in {sha}"}.
  ```
- A manual close after a merge: `gh issue close <n> --comment "Fixed by #{PR}{, merged with every CI job green}. {What's still unconfirmed, and how to reopen with evidence.}"`
