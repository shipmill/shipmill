# Goal plans and the comments around them

Write each body to a file in the repo's `tmp/` and post it with `--body-file`, as for an opportunity ([opportunity.md](opportunity.md)). Every write runs as `shipmill gh` (SKILL.md, rule 7), as `uvx shipmill==0.183.0 gh ...`, the release this plugin pins (spec 031), in every session. Every comment intake writes on a plan issue starts with `Triage:` or a `<!-- shipmill:... -->` marker, so `intake_state.py` never reads it as the maintainer's answer, even where the session writes as the maintainer's own login.

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

- The marker is the first line; `rev` starts at 1 and rises by one with each rewrite
- Headings Goal, Work, Order, Milestone, and Notes, in this order; Notes may be left out
- Work items are `- W-<n> <feature|fix|existing>: <text>`, numbered from W-1 in the order the work should start. `existing` names one open issue that already serves the goal (`#N` or `owner/repo#N`), never proposed a second time. `(after W-k[, W-j])` names earlier items an item depends on
- A `feature` item states an outcome, never a design: its spec comes later, through the spec gate
- Milestone is one line: `none`, or the title of the milestone the plan completes (D-38). Name one only when the goal reads as a version's worth of work; `none` is the default
- A plan for a row with `follows` (spec 097) adds `Follows: #{P}` to the Goal section, on its own line right after the `Measure:` line, naming the finished plan it follows. `plans.py check` accepts one such line there and refuses any other line starting `Follows:`; a goal's first plan has none. Each line of the row's `missing` is answered: a Work item that reaches it, or a line under Notes saying why this plan leaves it out; the Order says what the last plan left missing and how this one reaches it

```bash
uv run --no-project python <skill>/scripts/plans.py check tmp/plan-G-{n}.md
shipmill gh issue create -R {owner/repo} --title "Plan for G-{n}: {goal text}" --label goal-plan --body-file tmp/plan-G-{n}.md
```

## Intake's triage line on the plan

```markdown
Triage: **plan**. Serves: G-{n}. It waits for the maintainer's answer, a reply whose first line decides: `accept` files every feature and fix item as an issue (no build starts until triage takes them up, and each feature still needs its own approved spec), `accept W-1, W-3` files only the items named and drops the rest, `accept except W-2` files all but the items named, a line starting with `decline` closes the plan as not planned with the rest as the reason, and anything else is read as an edit to make.{ The items most open to cutting: W-k, and why.}
```

Never use the word "implement" here: `triage_state.py` reads the newest triage comment's verdict from it. Name the items most open to cutting, so a cut is one reply (spec 096). A first line that starts with `accept` and is none of the three forms is an unclear accept: the session asks about it once (SKILL.md, PLAN_ANSWERED) and never guesses.

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
shipmill gh issue create -R {owner/repo} --title "{item text}" --body-file tmp/plan-{plan}-W-{n}.md {--milestone "{title}"}
```

Then make it a sub-issue of the plan with github-issue-triage's `chains.py link {owner/repo}#{plan} --child {owner/repo}#{item} --no-text`: `--no-text` writes GitHub's relation alone, with no `Depends on` line in the plan's body, which stays as accepted

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

Holds:
- {a part of the end state that holds, and what shows it}

Still missing:
- {a part of the end state that doesn't hold, and why}
```

- The marker is the first line, exactly. An outcome counts only from the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR, and a trusted person's comment carrying the agent marker counts for nothing (D-29, D-62)
- `` `@{maintainer}` `` is each login the `--role maintainer=` flag gives, in a code span: an outcome is no needs-decision question, so it names the maintainer without notifying them (D-61); without the flag the line starts at `The work`
- `Holds:` and `Still missing:` each hold list items; a list with no part is `- nothing`. An Order that names no end state is `Still missing:` with `- the Order named no end state`. The goal's next plan reads the `Still missing:` items as its row's `missing`
- The outcome is a report, never a decision: it changes no goal, adds no measure (D-34), never calls the goal met, and never reopens the plan or files new items on it; the next plan proposes what is missing, for the maintainer to accept or decline (D-10)
