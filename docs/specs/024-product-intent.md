# S-024: Agents work toward the product's intent

status: approved

## Problem

Agents know what each task asks (an issue, a spec) and nothing about why the product
exists or where it is going. Triage judges an issue by itself, product intake ranks
requests by how loudly they are asked for, and a reviewer checks a diff against the issue
and the repo's rules, never against the product's direction. So the loop closes tasks
correctly and can still walk the product somewhere nobody chose. D-32 removed the roadmap
plan for this reason and said planning comes back with a goals layer; this spec is that
layer, as text the agents read. Asked for by the maintainer in chat (D-34).

Three texts carry it, each with a different lifetime:

- **The product's intent** changes over months: mission, users, current goals, non-goals,
  and the quality bar
- **A change's plan** lives for one pull request: what it touches, in which order, which
  test proves it, and which goal it serves
- **The review rubric** changes over months: what counts as Important in this repo, what a
  nit is, and the passes every review makes

## Behaviour

### `docs/intent.md`

A repo's intent is the file `docs/intent.md` on the default branch, with these sections
in this order, each a level-two heading:

- `## Mission`: one paragraph on what the product is for
- `## Users`: who it serves, as a list
- `## Goals`: the current goals, one per line as `- G-n: <outcome>`, numbered from 1 and
  never reused once removed
- `## Non-goals`: what the product deliberately doesn't do, one per line as
  `- N-n: <statement>`
- `## Quality bar`: what every change must hold in this product (compatibility, speed,
  security, accessibility), as a list

`skills/github-issue-triage/scripts/intent.py check [path]` exits 1 naming the first
problem: a missing or out-of-order section, a goal or non-goal line without its id, a
duplicate id, or no goals at all. `intent.py goals [path] [--json]` lists the ids with
their text. Only the maintainer changes it: a pull request that edits `docs/intent.md` is
never merged by an agent on its own judgment; github-pr-triage asks through the
needs-decision protocol unless the maintainer asked for that merge in this session.

`shipmill-setup` writes it when it connects the agent side (`[agents]`): it asks the
maintainer for the mission, users, goals, and non-goals, and commits the file through the
setup's pull request. It never invents a goal. `shipmill doctor` fails a repo that has an
`[agents]` section and no `docs/intent.md`, or one that `intent.py check` refuses, and
names the fix. A repo without `[agents]` (shipmill only cuts its releases) needs no
intent.

### Triage reads it

`skills/github-issue-triage/SKILL.md` and `references/triage-rubric.md`: every verdict on
an issue that asks for new behaviour names the goal it serves (`Serves: G-n`) or the
non-goal it hits, in the comment's verdict line:

- An issue that hits a non-goal gets **won't fix**, citing `N-n`
- A feature or opportunity that serves no goal gets **postpone**, saying which goal it
  would need; the maintainer adds the goal or lets it wait
- A bug fix or a contract tweak serves the quality bar and needs no goal

### Specs and opportunities name their goal

A spec carries a `serves:` line right after its `status:` line, naming one or more goals
(`serves: G-2, G-3`) or `quality bar`. `specs.py check` refuses a spec without it when the
repo has `docs/intent.md`, and one naming a goal the intent doesn't list. A spec that was
built before this rule, with no `serves:` line, is accepted.

`skills/product-intake/SKILL.md`: an opportunity issue's body names the goal it serves, or
says it serves none; the maintainer's accept or decline reads it. Demand still counts, but
an opportunity that serves no goal is never accepted on demand alone.

### A pull request carries its plan

An implementer (`skills/github-issue-resolve/SKILL.md`, Phase 4) writes the plan before
the code and puts it in the pull request's body as a `## Plan` section:

- `Serves:` the goal, or `quality bar` for a fix
- `Files:` the files it expects to change
- `Order:` the steps, the failing test first for a bug fix
- `Proof:` the tests or checks that show it works

A spec's build issue may point to its spec's Behaviour instead of repeating it. A plan
that turns out wrong is updated in the body before the push that departs from it.
`skills/github-pr-triage/scripts/pr_gate.py` refuses an agent's pull request without a
`## Plan` section.

### Review reads the rubric, the plan, and the intent

`docs/review.md` is the repo's review rubric, with these sections:

- `## Passes`: the reviews every pull request gets (for example bugs, security,
  compliance with the spec)
- `## Important`: what blocks a merge in this repo
- `## Nits`: what doesn't, and the most a review raises (`cap: N`, 5 by default)
- `## Protected areas`: paths a change to which needs the maintainer, as a list

`skills/github-pr-triage/references/reviewer-brief.md` adds to every brief, when the files
exist: the rubric's passes and Important list, the intent's goals, non-goals, and quality
bar, and the pull request's plan. A reviewer reports as findings: a diff that departs from
its plan without the plan saying why, a change that hits a non-goal, a change to a
protected area. Nits beyond the cap are dropped. Without `docs/review.md` the brief is as
today. `shipmill-setup` offers a starter rubric; it is optional.

## Acceptance criteria

- S-024-1: `intent.py check` exits 0 on a well-formed `docs/intent.md` and 1 naming the problem for a missing section, sections out of order, a goal line without an id, a duplicate id, or no goals
- S-024-2: `intent.py goals --json` lists each goal and non-goal with its id and text
- S-024-3: `shipmill doctor` fails a repo whose config has `[agents]` and no `docs/intent.md`, or an intent `intent.py check` refuses, naming the fix; a repo without `[agents]` gets no intent line
- S-024-4: `specs.py check` refuses a spec without a `serves:` line, or naming a goal the intent doesn't list, when `docs/intent.md` exists; it accepts a built spec without the line, and any spec when the repo has no intent
- S-024-5: `pr_gate.py` refuses an agent's pull request whose body has no `## Plan` section, and accepts one with it
- S-024-6: github-issue-triage's comment templates and rubric name the goal served or the non-goal hit for new behaviour, give won't fix for a non-goal, postpone for a feature serving no goal, and exempt bug fixes
- S-024-7: github-issue-resolve writes the `## Plan` section (Serves, Files, Order, Proof) before the code, and updates it before a push that departs from it
- S-024-8: The reviewer brief includes the rubric, the intent, and the plan when the files exist, and asks for findings on a departure from the plan, a non-goal, and a protected area, with nits capped
- S-024-9: github-pr-triage never merges a pull request that edits `docs/intent.md` on its own judgment, and asks through needs-decision instead
- S-024-10: shipmill-setup asks the maintainer for the intent's content when it connects `[agents]` and commits it through its pull request, without inventing goals

## Out of scope

- Planning versions from goals: milestones stay the maintainer's list (D-32); a later spec
  can plan from goals now that they exist
- Strategy, discovery, and metrics per goal: the full lifecycle is deferred
- A plan file per change in the repo: the pull request's body holds it, next to the change
- Grading whether a change really advances a goal: the reviewer judges, and evals (#380)
  can measure the judging

## Decisions relied on

- D-5: issue bodies link specs, they don't hold them
- D-10: only the maintainer accepts or declines an opportunity
- D-32: the roadmap plan is gone until a goals layer exists
- D-34: agents work toward the product's written intent

## Issues

## Verification
