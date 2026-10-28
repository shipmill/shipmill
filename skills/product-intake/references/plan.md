# Goal plans and the comments around them

Write each body to a file in the repo's `tmp/` and post it with `--body-file`, as for an opportunity ([opportunity.md](opportunity.md)). Every write runs as `shipmill gh` (SKILL.md, rule 7), as `uvx shipmill==0.89.0 gh ...`, the release this plugin pins (spec 031), in every session. Every comment intake writes on a plan issue starts with `Triage:` or a `<!-- shipmill:... -->` marker, so `intake_state.py` never reads it as the maintainer's answer, even where the session writes as the maintainer's own login.

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

```bash
uv run --no-project python <skill>/scripts/plans.py check tmp/plan-G-{n}.md
shipmill gh issue create -R {owner/repo} --title "Plan for G-{n}: {goal text}" --label goal-plan --body-file tmp/plan-G-{n}.md
```

## Intake's triage line on the plan

```markdown
Triage: **plan**. Serves: G-{n}. It waits for the maintainer's answer, a reply whose first line decides: `accept` files the feature and fix items as issues (no build starts until triage takes them up, and each feature still needs its own approved spec), a line starting with `decline` closes the plan as not planned with the rest as the reason, and anything else is read as an edit to make.
```

Never use the word "implement" here: `triage_state.py` reads the newest triage comment's verdict from it.

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
Triage: **plan**: accepted and filed: W-2 #{a}, W-3 #{b}{; milestone {title}}. Triage takes them up within `[agents] wip`.
```
