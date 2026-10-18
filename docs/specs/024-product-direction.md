# S-024: Agents work toward the product's direction

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

- **The product's direction** changes over months: mission, users, current goals,
  non-goals, and the quality bar
- **A change's plan** lives for one pull request: what it touches, in which order, which
  test proves it, and which goal it serves
- **The review rubric** changes over months: what counts as Important in this repo, what a
  nit is, and the passes every review makes

## Behaviour

### `docs/product.md`

A repo's direction is the file `docs/product.md` on the default branch. Its structure is
fixed, so code reads it without a model, and every item an agent may cite has an id:

    # <product name>

    ## Mission

    <one or more paragraphs: what the product is for>

    ## Users

    - U-1: <who it serves>

    ## Goals

    - G-1: <an outcome the product works toward now>

    ## Non-goals

    - N-1: <what the product deliberately doesn't do>

    ## Quality bar

    - Q-1: <what every change must hold: compatibility, speed, security, accessibility>

The grammar, which `src/shipmill/product.py` parses:

- One level-one heading, the product's name, then the five level-two headings exactly as
  above and in this order; any other heading is an error
- Mission is prose. The other four sections hold only list items of the form
  `- <prefix>-<n>: <text>`, one line each, with prefixes `U`, `G`, `N`, and `Q`
- Ids are numbered from 1 within their prefix, unique, and never reused once removed, so a
  gap is allowed and a reference stays valid or fails
- Users, Goals, and Quality bar each hold at least one item; Non-goals may be empty
- A section that outgrows a page moves to its own file in `docs/product/` (for example
  `docs/product/goals.md`): the section in `docs/product.md` keeps its heading and holds
  one line, `See [<section>](product/<file>.md).`, and that file starts with the same
  level-two heading and follows the same rules. The parser follows the link; nothing else
  may sit in the section beside it

`shipmill product check [--repo DIR]` exits 0 on a well-formed direction and 1 naming the
file, line, and rule broken. `shipmill product show [--repo DIR] [--section NAME] [--json]`
prints the direction, or one section, as text or JSON (`{"name", "mission", "users":
[{"id", "text"}], "goals", "non_goals", "quality"}`), resolving moved sections, so a skill
gives an agent exactly the part it needs. `shipmill product ids` lists every id with its
text, one per line, for a check that a reference exists.

Only the maintainer changes the direction: github-pr-triage never merges a pull request
that edits `docs/product.md` or `docs/product/` on its own judgment, and asks through the
needs-decision protocol unless the maintainer asked for that merge in this session.

`shipmill-setup` writes it when it connects the agent side (`[agents]`): it asks the
maintainer for the mission, users, goals, non-goals, and quality bar, and commits the file
through the setup's pull request. It never invents a goal. `shipmill doctor` fails a repo
that has an `[agents]` section and no `docs/product.md`, or one `shipmill product check`
refuses, and names the fix. A repo without `[agents]` (shipmill only cuts its releases)
needs none.

### Who reads which part

Each skill takes only its part, through `shipmill product show --section`:

| Reader | Sections |
|---|---|
| github-issue-triage (verdicts) | Goals, Non-goals |
| product-intake (opportunities) | Mission, Users, Goals, Non-goals |
| github-issue-triage (spec gate) | Users, Goals |
| github-issue-resolve (plan) | Goals, Quality bar |
| github-pr-triage (reviewer brief) | Goals, Non-goals, Quality bar |

### Triage reads it

`skills/github-issue-triage/SKILL.md` and `references/triage-rubric.md`: every verdict on
an issue that asks for new behaviour names the goal it serves (`Serves: G-n`) or the
non-goal it hits, in the comment's verdict line:

- An issue that hits a non-goal gets **won't fix**, citing `N-n`
- A feature or opportunity that serves no goal gets **postpone**, saying which goal it
  would need; the maintainer adds the goal or lets it wait
- A bug fix or a contract tweak serves the quality bar and needs no goal

### Specs and opportunities name their goal

A spec carries a `serves:` line right after its `status:` line, naming one or more goal
ids (`serves: G-2, G-3`) or `quality bar`. `specs.py check` refuses a spec without it when
the repo has `docs/product.md`, and one naming an id `shipmill product ids` doesn't list.
A spec built before this rule, with no `serves:` line, is accepted.

`skills/product-intake/SKILL.md`: an opportunity issue's body names the goal it serves, or
says it serves none; the maintainer's accept or decline reads it. Demand still counts, but
an opportunity that serves no goal is never accepted on demand alone.

### A pull request carries its plan

An implementer (`skills/github-issue-resolve/SKILL.md`, Phase 4) writes the plan before
the code and puts it in the pull request's body as a `## Plan` section:

- `Serves:` a goal id, or `quality bar` for a fix
- `Files:` the files it expects to change
- `Order:` the steps, the failing test first for a bug fix
- `Proof:` the tests or checks that show it works

A spec's build issue may point to its spec's Behaviour instead of repeating it. A plan
that turns out wrong is updated in the body before the push that departs from it.
`skills/github-pr-triage/scripts/pr_gate.py` refuses an agent's pull request without a
`## Plan` section, or whose `Serves:` names an id the direction doesn't list.

### Review reads the rubric, the plan, and the direction

`REVIEW.md` is the repo's review rubric, at the repository's root, where Claude's managed
Code Review reads it too, so one file serves both reviewers. It is free Markdown, and the
reviewer brief reads these level-two sections when present:

- `## Passes`: the reviews every pull request gets (for example bugs, security,
  compliance with the spec)
- `## Important`: what blocks a merge in this repo
- `## Nits`: what doesn't, and the most a review raises (a line `cap: N`, 5 by default)
- `## Protected areas`: paths a change to which needs the maintainer, one glob per list
  item

A `REVIEW.md` in a subdirectory adds rules for changes under it, on top of the root's, as
in Code Review. Both are read from the default branch, never from the pull request.

`skills/github-pr-triage/references/reviewer-brief.md` adds to every brief: the root
`REVIEW.md` and those of the directories the diff touches, the direction's Goals,
Non-goals, and Quality bar, and the pull request's plan. A reviewer reports as findings: a
diff that departs from its plan without the plan saying why, a change that hits a
non-goal, a change that breaks a quality-bar item (citing `Q-n`). Nits beyond the cap are
dropped. `pr_gate.py` matches the diff's files against Protected areas and asks the
maintainer through needs-decision for a match. Without a `REVIEW.md` the brief is as today.
`shipmill-setup` offers a starter rubric; it is optional.

## Acceptance criteria

- S-024-1: `shipmill product check` exits 0 on a well-formed `docs/product.md` and 1 naming the file, line, and rule for each of: a missing, extra, or out-of-order heading, a list item not of the form `- <prefix>-<n>: <text>`, a wrong prefix for its section, a duplicate id, an empty Users, Goals, or Quality bar
- S-024-2: `shipmill product show --json` prints the name, mission, and each section's items with id and text, and `--section NAME` prints only that section
- S-024-3: A section moved to `docs/product/<file>.md` by a `See [...]` line is read from that file by `check`, `show`, and `ids`, and `check` fails when the linked file is missing or holds a different heading
- S-024-4: `shipmill product ids` lists every id with its text, including ids from moved sections
- S-024-5: `shipmill doctor` fails a repo whose config has `[agents]` and no `docs/product.md`, or a direction `shipmill product check` refuses, naming the fix; a repo without `[agents]` gets no direction line
- S-024-6: `specs.py check` refuses a spec without a `serves:` line, or naming an id the direction doesn't list, when `docs/product.md` exists; it accepts a built spec without the line, and any spec when the repo has no direction
- S-024-7: `pr_gate.py` refuses an agent's pull request whose body has no `## Plan` section or whose `Serves:` names an unknown id, accepts one with a valid plan, and asks through needs-decision for a diff matching a `REVIEW.md` Protected areas glob
- S-024-8: github-issue-triage's comment templates and rubric name the goal served or the non-goal hit for new behaviour, give won't fix for a non-goal, postpone for a feature serving no goal, and exempt bug fixes, reading the sections the table names
- S-024-9: github-issue-resolve writes the `## Plan` section (Serves, Files, Order, Proof) before the code, and updates it before a push that departs from it
- S-024-10: The reviewer brief includes the root `REVIEW.md` and those of the touched directories, the direction's Goals, Non-goals, and Quality bar, and the plan, and asks for findings on a departure from the plan, a non-goal, and a quality-bar item, with nits capped
- S-024-11: github-pr-triage never merges a pull request that edits `docs/product.md` or `docs/product/` on its own judgment, and asks through needs-decision instead
- S-024-12: shipmill-setup asks the maintainer for the direction's content when it connects `[agents]` and commits it through its pull request, without inventing goals

## Out of scope

- Planning versions from goals: milestones stay the maintainer's list (D-32); a later spec
  can plan from goals now that they exist
- Strategy, discovery, and metrics per goal: the full lifecycle is deferred
- A plan file per change in the repo: the pull request's body holds it, next to the change
- Grading whether a change really advances a goal: the reviewer judges, and evals (#380)
  can measure the judging
- A fixed grammar for `REVIEW.md`: it is shared with Code Review, which reads free Markdown

## Decisions relied on

- D-5: issue bodies link specs, they don't hold them
- D-10: only the maintainer accepts or declines an opportunity
- D-32: the roadmap plan is gone until a goals layer exists
- D-34: agents work toward the product's written direction

## Issues

## Verification
