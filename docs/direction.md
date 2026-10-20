# The product's direction

A guide for the maintainer of a repository whose agents implement. It explains the file
you are asked to write, `docs/product.md`, what the agents do with it, and how you change
it. The rules behind it are D-34 in [decisions.md](decisions.md) and
[spec 024](specs/024-product-direction.md).

## What it is

`docs/product.md` says where your product is going, in five parts:

- **Mission**: what the product is for, in a paragraph or two
- **Users**: who it serves
- **Goals**: the outcomes it works toward now
- **Non-goals**: what it deliberately doesn't do
- **Quality bar**: what every change must hold, such as compatibility, speed, or security

Agents know what each issue asks and nothing about why the product exists. The direction
is that why, written once by you, so the loop closes tasks without walking the product
somewhere nobody chose.

## What the agents do with it

- **Triage** names the goal an issue serves (`Serves: G-n`) in its verdict on any issue
  that asks for new behaviour. An issue that hits a non-goal gets **won't fix**, citing
  `N-n`. A feature that serves no goal gets **postpone**, saying which goal it would need,
  so you add that goal or let it wait. A user's request that serves no goal still goes to
  product intake, marked as serving none. A bug fix serves the quality bar and needs no goal
- **Product intake** says in each opportunity issue which goal it serves, or that it serves
  none; an opportunity serving no goal is never proposed for acceptance on demand alone
- **Specs** carry a `serves:` line right after `status:` (`serves: G-2, G-3`, or
  `serves: quality bar`). `specs.py check` refuses a spec without it, or one naming an id
  the direction doesn't list; a built spec without the line passes
- **Implementers** put a `## Plan` in the pull request's body before the code, with four
  lines: `Serves:` (goal ids, or `quality bar` for a fix), `Files:`, `Order:`, and `Proof:`
- **The merge gate**, `pr_gate.py`, refuses an agent's pull request without a `## Plan`
  holding those four lines, or whose `Serves:` names an id the direction doesn't list. A
  person's pull request is never refused for its plan
- **Reviewers** get the Goals, Non-goals, and Quality bar in their brief, with the plan, and
  report a change that hits a non-goal, breaks a quality-bar item (citing `Q-n`), or departs
  from its plan without saying why

## Without it

A repository where shipmill only cuts releases (no `[agents]` section in
`.github/shipmill.toml`) needs no direction, and nothing above applies. Where the agents
implement, the loop runs as it did before spec 024 when the file is missing: triage judges
each issue by itself, specs and plans aren't checked against goals. `shipmill doctor`
fails such a repo (`FAIL direction`) until `docs/product.md` exists and is well formed.

## Its structure

The structure is fixed, so code reads it without a model:

- One level-one heading, the product's name, then `## Mission`, `## Users`, `## Goals`,
  `## Non-goals`, `## Quality bar`, exactly so and in this order; no other heading
- Mission is prose. Each other section holds only items of the form `- <id>: <text>`, one
  line each, with ids `U-n` for users, `G-n` for goals, `N-n` for non-goals, and `Q-n` for
  the quality bar, numbered from 1
- Users, Goals, and Quality bar each hold at least one item; Non-goals may be empty
- An id is never reused once removed, so a gap is fine and a reference to it stays valid or
  fails
- A section that outgrows a page moves to its own file under `docs/product/`, such as
  `docs/product/goals.md`, starting with the same `## Goals` heading; the section in
  `docs/product.md` keeps its heading and holds only `See [Goals](product/goals.md).`

A short example:

```markdown
# Acme

## Mission

Acme turns a folder of photos into a printed album in one command.

## Users

- U-1: A parent who wants an album without learning a layout tool

## Goals

- G-1: An album from 200 photos in under a minute
- G-2: Albums print correctly at the three largest print shops

## Non-goals

- N-1: Photo editing: Acme lays out photos, it doesn't retouch them

## Quality bar

- Q-1: A new release opens every album the last one saved
```

shipmill's own direction is [product.md](product.md).

## Who changes it

Only you. The shipmill-setup skill writes the first version from your answers when it
connects `[agents]`, and never invents a goal. Afterwards an agent may propose an edit in a
pull request, but the merge gate holds any pull request that touches `docs/product.md` or
`docs/product/` for your decision; the agents never merge one on their own judgment.

Edit the prose (the Mission) by hand. For the items, the `shipmill product` commands write
the line for you and keep the ids right; they change the working tree only, so the change
still lands through a pull request:

| Command | Does |
|---|---|
| `shipmill product check` | Exits 1 naming the file, line, and rule broken; 0 when well formed |
| `shipmill product show [--section NAME] [--json]` | Prints the direction, or some sections (`mission`, `users`, `goals`, `non-goals`, `quality`), moved ones resolved |
| `shipmill product ids` | Lists every id with its text, one per line |
| `shipmill product add <users\|goals\|non-goals\|quality> "<text>"` | Appends an item with the next id, one above any the file's history held, and prints it |
| `shipmill product edit <id> "<text>"` | Rewrites one item's text; its id stays |
| `shipmill product retire <id>` | Removes one item; its id is never handed out again |

Each takes `--repo DIR` (default: the current directory). An edit command exits 2 without
writing when the file doesn't pass `check` first. In a session with the shipmill plugin,
an edit of the direction runs `shipmill product check` right away and shows a broken line
with its number. A goal you retire that an unbuilt spec still serves makes `specs.py check`
fail for that spec, which lists the specs to revisit.

## REVIEW.md

`REVIEW.md` at the repository's root is the optional review rubric, read by shipmill's
reviewers and by Claude's Code Review alike. Its free sections are prose for people and
the model; three sections are structured, since the gate acts on them: `## Important`
(rules that block a merge, `- I-n: <rule>`), `## Nits` (with one `cap: N` line, the most
nits a review raises, 5 by default), and `## Protected areas` (``- `<glob>`: <why>``,
paths whose changes wait for you). `shipmill review check` validates it, and
`shipmill review add-rule`, `protect`, `set-cap`, and `retire` edit it as the product
commands do. A repository without one is reviewed as before.
