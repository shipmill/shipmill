# Issue comments

Write each body to a file and post it with `gh issue comment <n> --body-file <file>`. Keep the files in the repo's `tmp/` folder. Start every triage comment with `Triage:` followed by the bolded verdict, because `triage_state.py` finds triage comments by that prefix. Follow the user's writing rules: no trailing periods on list items, and em dashes only rarely.

**The goal, in the verdict line.** When the repo has `docs/product.md`, a verdict on new behaviour names the goal it serves right after the bolded verdict, `Serves: G-n.` (several as `Serves: G-2, G-3.`), from the direction's Goals; a non-goal it hits gets the Won't fix (non-goal) template, and a feature that serves no goal the Postpone (no goal) template; a user's request that serves no goal keeps the Opportunity template with `Serves no goal.` in its slot ([triage-rubric.md](triage-rubric.md), The direction). A bug fix or a contract tweak serves the quality bar and names no goal, and a repo without `docs/product.md` leaves the `{ Serves: G-n.}` slots out.

**Who decides a verdict.** In a repo whose config has `[agents]`, won't fix, duplicate, postpone, and close as done are the `triage-verdict` zone, and its level says whether the verdict also gets a decided comment and the `decided` label (`notify`, the default) or waits on a question (`ask`), as [Who decides](needs-decision.md#who-decides) says.

**A login in a code span** (D-61). A bare `@login` is an email to that person, so a template here leads with one only in a needs-decision question, a person's hand-off, and a decided comment. Every other comment names the login in a code span, `` `@{login}` ``, as the templates below do, and so does a verdict that names whose answer it follows (``Triage: implement, on `@{login}`'s answer``). An older comment with the bare form reads the same to every reader.

## Status comment

Once a question mentions the maintainer on an item, GitHub emails them every later comment there; an edit emails nobody (spec 090). So a session keeps one status comment per issue or pull request and writes its progress by editing it: `shipmill gh issue comment <n> --status --body-file <file>`, or `shipmill gh pr comment <n> --status --body-file <file>`, each run as `uvx shipmill==0.184.0 gh ...`, the release the plugin pins. The first call creates it and every later one edits it; shipmill gh writes `<!-- shipmill:status -->` as its first line, `Updated <YYYY-MM-DD HH:MM> UTC` under it, then your text, which says where the item stands now (each write replaces the whole text; GitHub's edit history keeps the earlier ones). Write a login in it in a code span: `--status` refuses a bare `@login`. No reader reads the status comment, so a line in it holds, answers, or decides nothing.

These stay new comments, since they reach someone or a reader dates them by their place in the thread:

- A `Triage:` verdict with its hold sentences ("On hold: ..."), and a hold line on a pull request
- A needs-decision question, a decided comment, a relayed decision (`Decision by`), and a veto's take-up
- A hand-off, a still-waits, check-waiting, check-failed, or verified comment, and a close-confirmed comment
- The final result: the item is done (a fix merged, a check holds, a parent or report closes as done), closed (as not planned, won't fix, duplicate, or stale), or a pull request is refused

Everything else is progress and goes in the status comment, never in a new comment: "The fix is in #{PR}" below, the Follow-ups' replaced pull request and plan changed after review, and a session's steps on a pull request it reviews or lands (rebased, fixes committed, CI pending). A person's draft gets no status comment, as it gets no review (D-67).

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
- Files: `{path}`, `{glob}`, `{folder/}`

{Only for a contract change (design-gate.md):}
**Design.** {The contract change exactly: flag, field and type, default.} {Why this over the alternative.} {Compatibility: who breaks, and the migration.} {Relies on D-n.} {How it's tested.}

{What is deliberately left out, and where it went (a postponed issue, 1.1).} I'll link the PR here.
```

**The allowed files** (spec 085). The plan's `- Files:` line names every file the work may touch, each in backticks, relative to the repo's root: a path, a glob in spec 061's grammar (`**` any run of characters, `/` included; `*` any run without `/`; `?` one character other than `/`), or a folder ending in `/` for everything under it. A spec's build issue lists its spec file, `docs/specs/NNN-<slug>.md`, since the build issue that ends the spec fills in its Issues and Verification. The changelog fragment needn't be listed. `pr_gate.py` holds an agent's pull request that changes a file outside this line, NEEDS_DECISION, until the maintainer accepts the wider change; it reads only a verdict written before the pull request opened, so list what the work needs now rather than widening it later. A verdict with no `Files:` line declares no allowance, and the gate checks none.

Write the decision block for the person who owes the answer, not for the implementer: no file, function, or permission names in the question or the options unless the answer turns on them, and then say what each one means. Name the effect instead ("repos without ship-watch stay stuck until someone notices"). Keep the options to the ones you'd accept, two or three, the recommended one first. The same block, under the same heading, asks a PR's "decisions for you" on the pull request (design-gate.md, step 3).

In a gate session (its prompt carries the gate's `Gate session:` or `Headless:` paragraph), the block never sits in the verdict: the verdict keeps "Waits on your decision below" and the question follows as its own comment, the [needs-decision protocol](needs-decision.md)'s, with the marker as its first line and the `needs-decision` label on the issue (D-21). Without the marker and the label, the scripts read the issue as work and the gate keeps starting sessions for it.

An answer the user gives in the session (to this block, to a PR's "decisions for you", or to a needs-decision question) goes on the item before you act on it. Posted as the App (`shipmill gh` with `[agents] app_id` set), its first line is ``Decision by `@<login>`, relayed by <agent>``, so the thread tells the person's decision from agent text; `<login>` is the person who answered and `<agent>` names the tool (`Claude Code`). The login sits in a code span so the record doesn't email the person (D-61); a reader still takes an older line with the login bare, `Decision by @<login>`, as the same answer:

```markdown
Decision by `@{login}`, relayed by {agent}

{The option chosen, or the user's own words}
```

Once the PR is up, in the issue's [status comment](#status-comment), `shipmill gh issue comment <n> --status --body-file <file>`:

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

On hold: the build waits on {owner/repo}#{spec PR}, the spec PR.
```

The hold sentence names the spec PR alone: `triage_state.py` holds the issue on every reference in a sentence that says "On hold", "blocked" or "waits on". Context such as the issue the spec is for goes in a sentence of its own, with no hold phrase, or the issue also holds on that issue, which can be its own parent. This hold stays a sentence alone: GitHub has no blocked-by relation on a pull request.

A request an accepted opportunity covers is built under that opportunity: its spec is the opportunity's, so the request holds on the opportunity issue, which closes when the build does. Add the request to the opportunity's Evidence section too.

```markdown
Triage: **feature**.{ Serves: G-n.} This asks for the outcome of #{opportunity}, which the maintainer accepted; it's built under that issue{, whose spec is in #{spec PR}}, and this one closes with it.

On hold: built under {owner/repo}#{opportunity}, the accepted opportunity.
```

This hold sentence names the opportunity alone, the same way. Before posting it, hold the request on the opportunity with `chains.py link <owner/repo#request> --blocked-by <owner/repo#opportunity>` ([Chains](../SKILL.md#chains)): it writes the blocked-by relation and the body's `Depends on` line, so GitHub's dependency view and tools outside the gate see the hold too, and the sentence stays as its reason.

In a gate session, the spec PR asks for its approval with the [needs-decision protocol](needs-decision.md), on the spec PR itself, with these options (D-49). Option 1 never asks the maintainer to merge by hand: a trusted answer taking it is the approval, and github-pr-triage lands the spec PR once it is green ([spec-gate.md](spec-gate.md), Approved by an answer). A spec PR that edits `docs/product.md` says instead that the maintainer merges it, since only they change the direction (D-34). The `CI on {sha7}` line shows the PR's head when asked, and the hidden `<!-- shipmill:head {sha} -->` line under it names that head's full SHA: the answer approves that exact head, and a question without the hidden line is asked again (S-055-5).

```markdown
<!-- shipmill:needs-decision -->
@{login} Decision needed: does spec {NNN}, {what it specifies} (#{feature issue}), set the behaviour the way you want, with the choices under "Decisions for you" in this PR's body?
CI on {sha7}: {N checks green}
<!-- shipmill:head {sha} -->

1. Take every recommendation (recommended): your answer is the approval; shipmill rebases this PR if it needs it and merges it once it is mergeable and green, then files its build issues under #{feature issue}. You may still merge it by hand
2. Change some of them: reply with the numbers and what you want instead; the spec is revised in this PR and you're asked again, and nothing merges until then

Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
```

A spec PR in `accepted-spec` at `notify`, in no stricter zone and with no item under "Decisions for you" in a stricter one, asks nothing: the session takes every recommendation and posts the [decided comment](needs-decision.md#a-decided-comment) on the spec PR instead, its zone `accepted-spec`, with the `decided` label and the head it decided on in the hidden `<!-- shipmill:head {sha} -->` line under its first sentence, `@{login} Decided without waiting: spec {NNN}, {what it specifies}, is approved for #{feature issue}, which you accepted, taking every recommendation under "Decisions for you".` Its `Why:` names D-88, and its `Not taken:` says the build waits for the window (spec 067, [spec-gate.md](spec-gate.md#approved-at-notify)). github-pr-triage lands it on that comment once it is green; a change to the spec since that isn't format only needs a new one.

Once the spec merges, edit the issue body to link it and split the spec into build issues ([spec-gate.md](spec-gate.md), Split it into build issues). Comment the Implement template on each build issue, naming the spec and the criteria it delivers.

## Postpone

```markdown
Triage: **postponed to {1.1 | after 1.0}**. {Why not now: the release phase, a new wire contract, or a shared design with #A and #B.}

The plan:

- {design point}
- {design point}

{Answers to the issue's open questions, "unless someone objects".}

Revisit on: `{path}`, `{path/**}`
```

Then add the label: `gh issue edit <n> --add-label postponed`.

The `Revisit on:` line names the paths the decision depends on, each in backticks, separated by commas, relative to the repo's root: `**` matches any run of characters, `/` included, `*` any run without `/`, and `?` one character other than `/` (spec 061). `triage_state.py` then reads REVISIT only when a stable release changed a file one of them matches, and POSTPONED, `waits on <paths>`, otherwise; without the line, REVISIT comes on every stable release. Leave the line out when no path decides it. When the issue waits on another issue rather than on files, link the two instead with `chains.py link <owner/repo#held> --blocked-by <owner/repo#N>` ([Chains](../SKILL.md#chains)), which writes the blocked-by relation and the body's `Depends on` line; when it waits on a pull request, which takes no blocked-by relation, put the `Depends on #N` line in the issue's body by hand. Either way it reads BLOCKED until that one closes and UNBLOCKED then, so the line adds nothing. Revisiting a postponed issue whose comment has no `Revisit on:` line, add one when you postpone it again.

### Postpone (no goal)

A feature, new behaviour the maintainer already wants, that serves no goal of `docs/product.md`; a user's request that serves none goes to product intake instead (Opportunity). Add the `postponed` label as above. Don't use the word "implement" in this comment, and name no issue right after a hold phrase: `triage_state.py` would read NEEDS_PR or BLOCKED.

```markdown
Triage: **postponed**: it serves no goal of the direction. {What it asks for, in one sentence}: new behaviour, and none of the goals in `docs/product.md` ({G-n: its words, for the nearest one}) covers it.

It would need a goal such as "{the outcome it would serve}". The maintainer adds that goal to the direction, and this is decided again, or lets it wait.

Revisit on: `docs/product.md`, `docs/product/**`
```

A goal added to the direction is what it waits on, so the `Revisit on:` line names the direction's files: it reads REVISIT once a stable release changed one of them.

## Won't fix (non-goal)

New behaviour that hits a non-goal of `docs/product.md`. Close the issue as not planned (`gh issue close <n> --reason "not planned"`) after posting.

```markdown
Triage: **won't fix**: it hits {N-n}, "{the non-goal's words}". {Why the request falls under it, in one or two sentences.}

The direction is the maintainer's to change; if it changes, this can be reopened.
```

In a component (`[product] home`), a request that hits a non-goal of the product, one `shipmill product show` prints under `## Product non-goals (<owner/home>)`, is **won't fix** too, citing it as `<owner/home> N-n` (spec 071): `Triage: **won't fix**: it hits <owner/home> N-n, "{the non-goal's words}".` The direction it names is the home's, the maintainer's to change. While `shipmill product show` exits 2 on the home's direction, post no verdict on new behaviour (triage-rubric.md, The direction).

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

## Check

{Optional, for a fault that shows in production: a command or a URL, and what it must return once the fix is in, such as the Reproduce above no longer reproducing in production}
```

The `## Check` section is optional: add it when the fault shows in production, and leave it out otherwise (spec 042). With it, the coordinator closes the report only once the check holds there (SKILL.md, Reports from other repos); a check only reads, never writes to production.

A stand-in for a dependency on another repo's work has the same label: an issue in the waiting repo saying what work it needs, with a `Stands in for owner/repo#N` line when the other repo's issue already exists ([triage-rubric.md](triage-rubric.md), Links between issues).

Hold the waiting issue on it with `shipmill link <owner/repo#N> --blocked-by <owner/repo#R>` (it runs `chains.py link <owner/repo#N> --blocked-by <owner/repo#R>`), both in this repo, and post the hold line on the waiting issue:

```markdown
On hold: waits on {owner/repo}#{R}, the upstream report of {what fails}
```

Then the report's triage comment, the first variant when the config sets `[product] home`, the second without:

```markdown
Triage: **upstream**. Routed by {owner/home}, the product's coordinator: it files the work in the repos that own it and closes this with what changed.
```

```markdown
Triage: **upstream**. No coordinator routes it: it waits for `@{maintainer}`, who reports it to the owning repo and closes this with what changed.
```

The coordinator's close, once every child closed (SKILL.md, Reports from other repos), written with the product token; then it closes the report as completed, or as not planned when a child closed as not planned:

```markdown
Every issue this was routed to is closed:

- {owner/repo#C}: {completed | not planned}, {by owner/repo#PR | with no pull request}
- {owner/repo#D}: {completed | not planned}, {by owner/repo#PR | with no pull request}

{What changed, in one or two sentences, for the agent that waits on this.}{ Closing as not planned: {owner/repo#D} won't be done, so the issue waiting on this is decided again.}
{For a report with a ## Check:} Checked: `{the check}` returned {what came back}, as the ## Check asks.
```

A report with a `## Check` reads VERIFY_DUE in place of CLOSE_DUE `completed`: the summary above carries its last line, and the close as completed comes once the check holds. When it fails, the coordinator posts the check-failed comment on the report ([A parent's check](#a-parents-check), the same marker and body) and files the fix in the owning repo as the report's child; when the change hasn't reached production yet, nothing; when it can't run the check, the needs-decision question below on the report.

## Hold (blocked on something outside the repo)

Keep "On hold" and the upstream link in one sentence of one line, because `triage_state.py` reads that sentence to report BLOCKED and later UNBLOCKED. A sentence ends at ".", "!", or "?" before a capital letter (not after "e.g.", "i.e.", "cf.", or "vs."), so a hold word elsewhere in a paragraph doesn't hold on the links it names:

```markdown
On hold: {why, e.g. #PR goes below the spec's default of 5 rotated files}, decided in {owner/repo#N}. {What stays ready meanwhile, e.g. "#59 stays open, rebased onto main".}
```

Put the same line on the held PR.

**Name the item it waits on for the gate** (spec 089). When a session leaves an issue or a pull request it was handed unchanged because it waits on another item (an answer on another issue, a pull request to land, an upstream report), its hold comment on that subject starts with a marker line naming the item, then the hold sentence:

```markdown
<!-- shipmill:waits-on {owner/repo}#{N} -->
On hold: waits on {owner/repo}#{N}, {what it waits for there}.
```

The marker is the comment's first line, the item written as `owner/repo#N` even in the same repo, its owner as GitHub spells it (`gh repo view <owner/repo> --json nameWithOwner`), and the comment is posted through `shipmill gh` as the App, since the gate reads only its `--bot-login`'s marker. The gate otherwise marks a subject nobody wrote on idle and leaves it until the subject itself changes; with the marker, it hands the subject again once the named item is updated. A later hold on the same subject posts a new marker: the newest one counts.

When the line holds an issue on an issue, link the two first with `shipmill link <owner/repo#held> --blocked-by <owner/repo#N>` ([Chains](../SKILL.md#chains)), as the Upstream report does: it writes the blocked-by relation and the body's `Depends on` line (`text only:` where the forge refuses the relation), so the hold shows in GitHub's dependency view and to tools outside the gate, and the line stays as its reason. When it exits 2 with `closes a cycle:`, the issue would wait on itself, as a part held on its own parent does (#772): post no hold line either, which would deadlock it the same way, and name that issue as context in a sentence with no hold phrase. A hold that names a pull request, or a hold on a pull request, stays the line alone: GitHub has no blocked-by relation on a pull request. In a component, `chains.py link` refuses another repo's item (S-038-11): wait on a local stand-in instead ([Upstream report](#upstream-report)).

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

Only holds gate the hand-off: `triage_state.py` reads a `Depends on` line, a blocked-by relation, a sub-issue, and a hold comment's sentence naming an issue, never a precondition the body states in prose. So each precondition of the step is linked as a hold, `chains.py link <item> --blocked-by <precondition>`; one with no issue of its own gets one filed first, as the App. Never leave a precondition as prose alone, in the item or a comment on it: the item reads HANDOFF_DUE as soon as its holds close, whatever the prose says (#1487).

**HANDOFF_DUE**, the hand-off: a mention of every assignee and of every team its roles resolve to (the note's `for @a @example-org/legal`, or the `assignees` and `teams` lists of its `--json` line), which holds closed, the issue's steps quoted (never rewritten), its `## Check` when it has one, and how to report. A team can't be assigned, so the mention is how its members hear of the step; a team-only role's item mentions the team alone. Post it once per unblock; nothing mentions the person or the team again while the item reads WITH_PERSON. A done report counts from an assignee or a trusted author (D-16): a team member who is a member of the repo's organization counts, an outside one doesn't.

A `role:maintainer` item (or a `human` one) is never handed to a headless session to work it, which is why an item that needs full access (spec 087: ssh with a key, Docker, the host's keys) carries the label: a person runs it, approving each command. So its hand-off also names the command that opens an interactive session on it in the repo's checkout, `claude "/shipmill:github-issue-resolve <owner>/<repo>#<n>"`, with the item's own repo and number. Another role's hand-off doesn't name it.

```markdown
<!-- shipmill:handoff -->
@{assignee} @{assignee} @{org/team}, it's your turn: {owner/repo#N} closed{, and owner/repo#M}.

What to do, from this issue:

> {the issue's steps, quoted line by line}

{When the issue has one:} When it's done, this must hold:

> {its ## Check, quoted}

{When it is labelled role:maintainer or human:} To work it in an interactive session, run this in the repo's checkout:

`claude "/shipmill:github-issue-resolve {owner/repo}#{N}"`

Reply `done` here when it's finished, or close the issue.
```

**VERIFY_DUE**, the check holds: say what was checked and what came back, then close the issue as completed (`gh issue close <n> --reason completed`), which unblocks whatever it held. With no `## Check`, say "Closed on `@{login}`'s report: this issue has no ## Check" instead.

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
Checked after `@{login}` closed this: `{the check}` returned {what came back}.
```

**VERIFY_CLOSED**, the check fails: reopen it (`gh issue reopen <n>`), then post a hand-off through `--body-file`; the open issue holds everything it blocks again.

```markdown
<!-- shipmill:handoff -->
@{assignee}, I reopened this: `{the check}` returned {what came back}, and it must return {what the ## Check asks}. What waits on this issue waits again.

Reply `done` here when it's fixed, or close the issue.
```

**STALE_HANDOFF**, the parent closed and the step is done or no longer needed: close the item (`gh issue close <n> --reason completed`, or `--reason "not planned"` for a step that went away) with a comment saying why, the parent named and the login in a code span (D-61):

```markdown
Closing: its parent {owner/repo#N} closed, and {the step was done in ... / the step is no longer needed because ...}.
```

**STALE_HANDOFF**, the step still waits on its person: the still-waits comment, which ends the state until the parent reopens and closes again. It counts from the `--bot-login`, or from an OWNER, MEMBER, or COLLABORATOR without the agent marker (D-62); post it once, never as a reminder, and mention nobody:

```markdown
<!-- shipmill:still-waits -->
Its parent {owner/repo#N} closed, and this step still waits on `@{assignee}`: {why it is still needed}.
```

**NO_ASSIGNEE** gets no comment and no question: it means the state was read without the `--role` flags, so read it again with them ([triage-rubric.md](triage-rubric.md), A person's item). The roles say who does a step, so a session never asks. Only an ASSIGN_DUE assignment GitHub refuses goes to the maintainer, through the [needs-decision protocol](needs-decision.md): name the users it couldn't assign and GitHub's message, and recommend assigning the maintainer.

A check the session can't run: a question through the [needs-decision protocol](needs-decision.md), in its format, with its marker and the `needs-decision` label. Say what the report claims and why the check can't run here, and give two options, the recommended one first, as the protocol asks: close it on the report when other evidence backs the report (a log line, a page that changed), it isn't done when nothing but the report does (then it comes first, with the `(recommended)` mark and why):

```markdown
<!-- shipmill:needs-decision -->
@{maintainer} Decision needed: `@{login}` reported this done, and I can't run its check here (`{the check}`: {why, such as "the host isn't reachable from this machine"}).

1. Close it on the report (recommended): {the evidence beyond the report}; what waits on it starts now, unchecked
2. It isn't done: I hand it back to `@{assignee}`, and what waits on it keeps waiting

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

A child closed as not planned doesn't stop the close; say so in its line. A feature issue first gets its spec verified ([spec-gate.md](spec-gate.md), Verify the whole spec). A parent with a `## Check` never takes this comment: it closes on its check, below.

A goal plan (labelled `goal-plan`, its newest trusted triage comment product intake's `Triage: **plan**`) whose work has closed reads TRIAGED, `work closed; product intake reports the outcome`, never UNBLOCKED (spec 097): it is product intake's to close with its outcome, and triage never closes it with the parent's close comment. Leave it open: product intake closes it and posts whether the goal moved.

## A parent's check

A parent with a `## Check` section reads VERIFY_DUE once its holds all close (an issue with one and no sub-issue, once its own pull request merged, #1671), CHECK_FAILED after a check-failed comment, and VERIFY_CLOSED when it closed before its check ran ([triage-rubric.md](triage-rubric.md), A parent's check). Each comment below starts with its marker as the first line, posted through `--body-file`, since `triage_state.py` reads the marker only there and only from the `--bot-login` or a trusted author. A check only reads: it runs a command or opens a URL and compares what comes back, and never writes to production.

**VERIFY_DUE**, the check holds: close the parent as completed (`gh issue close <n> --reason completed`), then post the verified comment, after the close so `triage_state.py` dates it there. Never post it with `gh issue close --comment`, which posts the comment before the close. On VERIFY_CLOSED the parent is closed already: the comment alone.

```markdown
<!-- shipmill:verified -->
Checked: `{the check}` returned {what came back}, as the ## Check asks. Closed as done.

- {owner/repo#N}: {completed | not planned}
- {owner/repo#M}: {completed | not planned}
```

**VERIFY_DUE**, the check fails: the check-failed comment, so the parent reads CHECK_FAILED. On VERIFY_CLOSED, reopen it first (`gh issue reopen <n>`).

```markdown
<!-- shipmill:check-failed -->
The check didn't pass: `{the check}` returned {what came back}, and it must return {what the ## Check asks}. The fix is filed as a child of this issue; this closes once it lands and the check holds.
```

**CHECK_FAILED**, the fix: a new issue in the parent's repo, through `--body-file`, triaged **implement**, then made a child with `chains.py link <owner/repo#parent> --child <owner/repo#fix>`, so the parent reads BLOCKED on it and VERIFY_DUE again once it closes. The children that closed stay closed:

```markdown
The ## Check of #{parent} fails in production: `{the check}` returned {what came back}, and it must return {what the ## Check asks}.

{What the fix is, as far as the session could tell, with the place in the code}
```

**The change hasn't reached production yet** (the deploy run for the merge is still going, or the version served predates the merge): no comment and no close. The parent reads the same on the next read.

A check the session can't run (a production log, a dashboard, a host it can't reach, a command outside a headless session's allowlist, or one that would write to production): a question through the [needs-decision protocol](needs-decision.md), in its format, with its marker, its zone line under the marker when the config has `[agents]` (`triage-verdict`, the zone of closing an issue as done), and the `needs-decision` label. Say what the check is and why it can't run here, and give the two options, the recommended one first: leave it open when nothing else shows the result, close it unchecked when other evidence does (then it comes first, with the `(recommended)` mark and why):

```markdown
<!-- shipmill:needs-decision -->
@{maintainer} Decision needed: every child of this issue closed, and I can't run its check here (`{the check}`: {why, such as "it reads a production log this session can't reach"}).

1. Leave it open: I check it and close it by hand (recommended): nothing else shows the result in production; it stays open until you close it
2. Close it unchecked: {the evidence beyond the merged children, or "nothing beyond the merged children"}; it closes now and nobody saw the result in production

Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
```

On "close it unchecked", close the parent as completed, then post the verified comment with `` Closed unchecked on `@{login}`'s answer: no check ran. `` in place of its `Checked:` line. On a report, the coordinator posts the summary comment ([Upstream report](#upstream-report)) with that line in place of its `Checked:` line, then closes the report as completed, since the waiting agent reads the summary.

On "leave it open", post the check-waiting comment, through `--body-file`, on the parent or the report, naming who answered with the login in a code span, `` `@{login}` ``, right after the marker line (an older comment's bare `@{login}` reads the same); `triage_state.py` reads the parent as WITH_PERSON on it, and `upstream_state.py` the report as ASKED, so no session starts for it again. A child that closes after it, or a check-failed or verified comment after it, ends the wait:

```markdown
<!-- shipmill:check-waiting -->
`@{login}` answered "leave it open": they run the ## Check (`{the check}`) and close this by hand.
```

## Follow-ups

- A PR was replaced, in the issue's status comment (`shipmill gh issue comment <n> --status --body-file <file>`): "Update: #{old} was replaced by #{new}, {rebased with review fixes}. This issue closes when #{new} merges."
- The plan changed after review, e.g. main already had part of the fix, in the issue's status comment (`--status`): "Update after rebasing: {what main already does}; #{PR} now only {what remains}." Also update the PR's title and body.
- A wrong auto-close: `gh issue reopen <n> --comment "Reopening: commit {sha} closed this because its message quotes {text}. The fix is in #{PR}, which hasn't merged yet."`
- A right close that reads SUSPECT_CLOSE: post the close-confirmed comment through `--body-file`, with `issue comment` once the issue is closed. Its first line is the marker exactly, and only one by an OWNER, MEMBER, or COLLABORATOR or the App, posted after the last close, counts (D-29). `gh issue close --comment` posts its comment before the close, so a marker posted that way never counts; after a reopen and a new close, post it again:

  ```markdown
  <!-- shipmill:close-confirmed -->
  The close is right: {why, such as "done by hand: the drill ran on 2026-10-08, see the run log" or "the fix is on main in {sha}"}.
  ```
- A manual close after a merge: `gh issue close <n> --comment "Fixed by #{PR}{, merged with every CI job green}. {What's still unconfirmed, and how to reopen with evidence.}"`
