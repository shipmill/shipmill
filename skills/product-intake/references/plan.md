# Goal plans and the comments around them

Write each body to a file in the repo's `tmp/` and post it with `--body-file`, as for an opportunity ([opportunity.md](opportunity.md)). Every write runs as `shipmill gh` (SKILL.md, rule 7), as `uvx shipmill==0.196.0 gh ...`, the release this plugin pins (spec 031), in every session. Every comment intake writes on a plan issue starts with `Triage:` or a `<!-- shipmill:... -->` marker, so `intake_state.py` never reads it as the maintainer's answer, even where the session writes as the maintainer's own login.

## The plan issue

Title: `Plan for G-n: <the goal's text>`, label `goal-plan`. `plans.py check` enforces the body's grammar; run it on the file before opening or rewriting the issue.

```markdown
<!-- shipmill:plan goal=G-{n} rev={k} -->
## Goal

G-{n}: {the goal's text, as `shipmill product show` prints it}

Trigger: {no-work | stalled | requested in #N}
Measure: {the goal's measure from spec 027, or "none yet"}

## Work

- W-1 existing: #{n}
- W-2 feature: {the outcome a user gets}
- W-3 fix: {what is wrong today} (after W-2)

## Order

{Why this order, and what reaching the goal looks like once the work is done.}

## Milestone

none

## Notes

{What was considered and left out, the D-n rules it runs into. Optional.}
```

- The Goal section's lines after `Trigger:` follow the goal's kind (spec 105), as `shipmill product show --json` gives it and `plans.py check` reads it from `docs/product.md`; the template above is a goal of kind none, with `Measure:` alone. Each line once, in this order, its fields copied from the goal's text:
  - a goal, `<outcome>. Check: <check>. By: <horizon>`: `Check: {check}`, then `By: {horizon}`, a date `YYYY-MM-DD` or a release `X.Y.Z` with an optional `v`, and no `Measure:` line
  - a measure, `Held: <statement>. Threshold: <threshold>. Source: <source>`: `Threshold: {threshold}`, `Source: {source}`, then `Measure: {the measure line, or "none"}`
  - a goal of kind none: `Measure: {the measure line, or "none yet"}`, as before spec 105
  - A missing line, a line of another kind, or one given twice is refused naming the line
- A measure is held for good: it gets a plan only when the maintainer asks for one (`requested in #N`), never on `no-work`
- The marker is the first line; `rev` starts at 1 and rises by one with each rewrite
- Headings Goal, Work, Order, Milestone, and Notes, in this order; Notes may be left out
- Work items are `- W-<n> <feature|fix|existing>: <text>`, numbered from W-1 in the order the work should start. `existing` names one open issue that already serves the goal (`#N` or `owner/repo#N`), never proposed a second time. `(after W-k[, W-j])` names earlier items an item depends on
- A `feature` item states an outcome, never a design: its spec comes later, through the spec gate
- Milestone is one line: `none`, or the title of the milestone the plan completes (D-38). Name one only when the goal reads as a version's worth of work; `none` is the default
- A plan for a goal that has an open plan replaces it (spec 106): it keeps the open plan's Work items it still proposes and names the ones it drops under Notes; the old plan then reads PLAN_REPLACED and is closed. A row `opportunity #<n> accepted` proposes that opportunity as a `feature` item whose text starts `#<n>`, so its accept files no issue for it: the opportunity becomes the item's head
- A plan for a row with `follows` (spec 097) adds `Follows: #{P}` to the Goal section, on its own line right after the `Measure:` line (the `By:` line for a goal of kind goal), naming the finished plan it follows. `plans.py check` accepts one such line there and refuses any other line starting `Follows:`; a goal's first plan has none. Each line of the row's `missing` is answered: a Work item that reaches it, or a line under Notes saying why this plan leaves it out; the Order says what the last plan left missing and how this one reaches it

```bash
uv run --no-project python <skill>/scripts/plans.py check tmp/plan-G-{n}.md
shipmill gh issue create -R {owner/repo} --title "Plan for G-{n}: {goal text}" --label goal-plan --body-file tmp/plan-G-{n}.md
```

## Intake's triage line on the plan

```markdown
Triage: **plan**. Serves: G-{n}. It waits for the maintainer's answer, a reply whose first line decides: `accept` files every feature and fix item as an issue (no build starts until triage takes them up, and each feature still needs its own approved spec), `accept W-1, W-3` files only the items named and drops the rest, `accept except W-2` files all but the items named, a line starting with `decline` closes the plan as not planned with the rest as the reason, `hold until <a date, #N, or release>` holds the plan untouched until then and re-checks it when the condition is met, `answer by YYYY-MM-DD` moves the date the answer is due (seven days after the plan's newest revision otherwise, spec 106) and answers nothing, and anything else is read as an edit to make.{ The items most open to cutting: W-k, and why.}
```

Never use the word "implement" here: `triage_state.py` reads the newest triage comment's verdict from it. Name the items most open to cutting, so a cut is one reply (spec 096). A first line that starts with `accept` and is none of the three forms is an unclear accept: the session asks about it once (SKILL.md, PLAN_ANSWERED) and never guesses. An answer the maintainer gives in a session is recorded with `shipmill goal-plan answer <plan> accept [--only W-1,W-3 | --except W-2]`, `decline --reason`, `hold --until`, or `send-back --reason`, with `--by <login>` (spec 107), which writes it in the form the plan's reader counts.

## A revision

Rewrite the body as the edit asks, raising `rev` by one in the marker, check it, then post:

```markdown
<!-- shipmill:plan-revised rev={k} -->
Revised as asked: {what changed, one line}. It waits for your answer again.
```

The revision counts only from the `--bot-login`: without the App's login, the answer it handled stays the newest and the plan reads PLAN_ANSWERED again.

## On the request issue (a requested plan)

```markdown
Triage: **plan**: the plan for G-{n} is #{plan}. Answer there; this request closes as completed.
```

Then `shipmill gh issue close {N} -R {owner/repo} --reason completed`.

## A filed item

Title: the item's text. One issue per `feature` and `fix` item, in Work order:

```markdown
<!-- shipmill:plan-item #{plan} W-{n} -->
{The item's text, stated as a request: for a feature, the outcome a user gets; for a fix, what is wrong today and what is right.}

Serves: G-{n}

From the accepted plan #{plan}.

Depends on {owner/repo}#{the issue of W-k}
```

- The marker is the first line, exactly, so `plans.py items` and `intake_state.py` find it
- One `Depends on` line per `(after W-k)`, naming W-k's issue: the one filed for it, or the `existing` item's own number. Leave the lines out for an item with no `(after ...)`
- Never write a hold phrase before the plan's number ("waits on #{plan}"): `triage_state.py` would read the item as held by its own plan

```bash
shipmill gh issue create -R {owner/repo} --title "{item text}" --label project --body-file tmp/plan-{plan}-W-{n}.md {--milestone "{title}"}
```

The `project` label makes the filed item a project's head (spec 106): `intake_state.py --projects` reads its state from its `Check: ` sub-issue and its parts. An item filed before spec 106 has no label and reads no project row; an `existing` item is never labelled by the filing. When the repo lacks the label, create it first with `shipmill gh label create project --description "A project's head issue (spec 106)"`: `issue create` refuses a label the repo doesn't have

Then make it a sub-issue of the plan with github-issue-triage's `chains.py link {owner/repo}#{plan} --child {owner/repo}#{item} --no-text`: `--no-text` writes GitHub's relation alone, with no `Depends on` line in the plan's body, which stays as accepted

## Spec 106's states, labels, and markers

A goal reads proposed, written, planned, met, or dropped; a plan PLAN_OPEN with its answer date, PLAN_OVERDUE past it, or PLAN_REPLACED once a newer plan of its goal is open; a project held, active, in focus, closing, closed, or stopped (docs/flow.md's "Goals, plans, and projects" has the tables). The labels and markers they are read from:

| Label | On | Means |
|---|---|---|
| `project` | an issue, by a trusted author or the App | a project's head; a filed `feature` or `fix` item carries it; `shipmill project add <n> --by <login>` adds it for the maintainer (spec 108) |
| `held` | a project's head | held, until its turn starts it (PROJECT_START_DUE removes it once the check issue exists); `shipmill project hold` adds it, `project resume` takes it off while a slot is free (spec 108) |
| `focus` | an active head, by the maintainer | in focus: the maintainer's steps on it come first; `shipmill project focus` and `unfocus` move it (spec 108) |
| `goal-proposal` | an issue | a goal not yet in the direction; GOAL_PROPOSAL_DUE opens one with the opportunity as its sub-issue |
| `goal-review` | the App's issue | GOAL_OVERDUE's question: extend, rewrite, or drop the goal |

A head's check issue is filed and linked with `shipmill project check <head> --title "<what will be true>" --check-file <file>`, and an opportunity the maintainer turns down is closed with `shipmill opportunity decline <n> --by <login> --reason "<why>"`, the relay first (spec 108, D-115).

The check issue's `## Check` is one a person other than its builder can run, and it runs by reading alone (spec 042, D-116):

- **Read what already shows it:** existing issues and pull requests that show the behaviour, or the result of the released package's test that reproduces the project's repro, read where it ran
- **Never a write:** a check never opens an issue, adds a label, opens a pull request, or deploys to see the behaviour happen, so a `## Cleanup` never has to undo the check itself
- **A check whose only form is a write** says so in its `## Check`, and the session asks the maintainer on the check issue at once through the [needs-decision protocol](../../github-issue-triage/references/needs-decision.md): "leave it open: I check it and close it by hand" or "close it unchecked"
- **Never closed at `decided`:** a check that didn't run is closed only on the maintainer's "close it unchecked" answer, whatever the zone's level, never at a `decided` comment

| Marker | Where | Written on |
|---|---|---|
| `<!-- shipmill:goal-overdue G-<n> by=<horizon> -->` | the first line of the `goal-review` issue, by the App | GOAL_OVERDUE |
| `<!-- shipmill:plan-replaced #<new> -->` | the first line of the comment closing the older plan as not planned | PLAN_REPLACED |
| `<!-- shipmill:project-stopped -->` | the first line of the comment closing the head as not planned, the reason in its body | PROJECT_STOP_DUE |

A marker counts only from the App (D-29): the same line by anyone else records nothing.

## Intake's line on the plan once filed

```markdown
Triage: **plan**: accepted and filed: W-2 #{a}, W-3 #{b}{; linked: W-1 #{n}}{; not linked: W-4 {owner/repo}#{m}, W-5 #{k} (another parent)}{; dropped: W-4, W-5}{; W-3 filed without its after W-4}{; milestone {title}}. Triage takes them up within `[agents] wip`.
```

- With no `feature` or `fix` item to file, the filed part is `nothing new` (`accepted and filed: nothing new; linked: W-1 #{n}`)
- `linked:` names each `existing` item of this repository made a sub-issue of the plan (D-114), kept ones alone after a partial accept; `not linked:` names each kept `existing` item of another repository, and each one with another parent, marked `(another parent)`: neither is linked
- `dropped:` names each item a partial accept dropped (`accept W-1, W-3` or `accept except W-2`, spec 096), in Work order; a full accept leaves the part out. A dropped item is never filed, linked, or put in the milestone
- `W-k filed without its after W-j` names each kept item whose `(after W-j)` was on a dropped item: it got no `Depends on` line and no relation for W-j
- Each `{...}` part is there only when it applies; the ids are placeholders, so an item is named in one part at most

## A finished plan's outcome

On PLAN_DONE (spec 097), check the end state the Order names against trusted text only (D-16): the plan's body, the App's and trusted authors' comments, and the code and specs on the default branch, with how each item closed. For an open plan, close it as completed first, then post the outcome, so `intake_state.py` reads it as posted after the last close; on a plan closed already, post the outcome alone:

```bash
shipmill gh issue close {P} -R {owner/repo} --reason completed
shipmill gh issue comment {P} -R {owner/repo} --body-file tmp/plan-{P}-outcome.md
```

```text
<!-- shipmill:plan-outcome -->
`@{maintainer}` The work of this plan has closed: W-1 #{a} completed, W-2 #{b} not planned.

The Order said reaching the goal looks like: {the end state, quoted from the Order}

Goal check: {holds, fails, or can't be run by an agent}: {what the goal's Check: showed, or why it can't be run}

Holds:
- {a part of the end state that holds, and what shows it}

Still missing:
- {a part of the end state that doesn't hold, and why}
```

- The marker is the first line, exactly. An outcome counts only from the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR, and a trusted person's comment carrying the agent marker counts for nothing (D-29, D-62)
- `` `@{maintainer}` `` is each login the `--role maintainer=` flag gives, in a code span: an outcome is no needs-decision question, so it names the maintainer without notifying them (D-61); without the flag the line starts at `The work`
- `Holds:` and `Still missing:` each hold list items; a list with no part is `- nothing`. An Order that names no end state is `Still missing:` with `- the Order named no end state`. The goal's next plan reads the `Still missing:` items as its row's `missing`
- `Goal check:` (spec 106) runs the goal's own `Check:` from the direction, as spec 042 reads a parent's check: it only reads, never writes to production. It says `holds`, `fails`, or `can't be run by an agent`, with what showed it. A goal of no kind, or a measure, has no check: leave the line out
- The outcome is a report, never a decision: it changes no goal, adds no measure (D-34), never calls the goal met, and never reopens the plan or files new items on it; the next plan proposes what is missing, for the maintainer to accept or decline (D-10). When the goal check holds, the session proposes the goal met in a separate pull request (SKILL.md, PLAN_DONE), which only the maintainer merges
