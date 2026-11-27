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
- In a component repo, one whose `.github/shipmill.toml` sets `[product] home`, a goal may
  name the goals of the product's home direction it serves on one line right under its item
  line, or under its measure line: `  serves: G-2, G-4` (spec 071). `product check` refuses
  the line in any other repo, the home included
- A goal of kind goal (`<outcome>. Check: <check>. By: <horizon>`, spec 105) ends with one
  more sentence once it is over, the maintainer's record (spec 106): `. Met: <YYYY-MM-DD>`, or
  `. Dropped: <YYYY-MM-DD>: <reason>`. `product check` refuses either on a standing measure or
  a goal of no kind, a date that is no calendar date, an empty reason, or both at once. A met
  or dropped goal keeps its id, so references to it still resolve; it reads no plan trigger,
  and `specs.py check` refuses a draft or approved spec that serves it. `product show --json`
  gives every goal `state` (`met`, `dropped`, or null) and `ended` (that date, or null)

In a component, `product check` also reads the home's direction, as committed on its default
branch, and refuses a serves line naming a goal the home's Goals don't list; `product show`
adds the product's goals and non-goals after the component's own, under `## Product goals
(<owner/home>)` and `## Product non-goals (<owner/home>)`, and in `--json` as one `product`
key. Both read the home with the App's read-only token (spec 065), so they need the App's key
on the host and the home's `[product] repos` listing the component; when the home can't be
read they exit 2 naming the home and the fix, and `--local` reads only the checkout, as on a
laptop or in CI. A component whose goals carry no serves line reads nothing of the home in
`check`.

A short example:

```markdown
# Acme

## Mission

Acme turns a folder of photos into a printed album in one command.

## Users

- U-1: A parent who wants an album without learning a layout tool

## Goals

- G-1: Albums print correctly at the three largest print shops. Check: a test album prints without a layout error at each of the three. By: 2027-03-31
- G-2: Held: An album from 200 photos in under a minute. Threshold: 60 seconds on the reference laptop. Source: the album benchmark in CI

## Non-goals

- N-1: Photo editing: Acme lays out photos, it doesn't retouch them

## Quality bar

- Q-1: A new release opens every album the last one saved
```

G-1 is a goal: it ends once its check passes. G-2 is a standing measure: it is held for
good. shipmill's own direction is [product.md](product.md), and [goals.md](goals.md) walks
one goal from written to met: the plan product intake proposes for it, your answers, the
projects it files, and how you record it met or dropped.

## Who changes it

Only you. The shipmill-setup skill writes the first version from your answers when it
connects `[agents]`, asks whether each goal ends on a check or is held at a threshold, and
never invents a goal or picks its check, horizon, threshold, or source. Afterwards an agent may propose an edit in a
pull request, but the merge gate holds any pull request that touches `docs/product.md` or
`docs/product/` for your decision; the agents never merge one on their own judgment.

Edit the prose (the Mission) by hand. For the items, the `shipmill product` commands write
the line for you and keep the ids right; they change the working tree only, so the change
still lands through a pull request:

| Command | Does |
|---|---|
| `shipmill product check [--ref REF] [--local]` | Exits 1 naming the file, line, and rule broken; 0 when well formed. `--ref` reads the files as committed at a git ref, such as `origin/main`, instead of the working tree; exits 1 with `no docs/product.md at <ref>` when the file is absent there, and 2 for a ref git can't resolve. `--local` reads only this checkout's direction, never the product home's (spec 071) |
| `shipmill product show [--section NAME] [--json] [--local]` | Prints the direction, or some sections (`mission`, `users`, `goals`, `non-goals`, `quality`), moved ones resolved |
| `shipmill product ids` | Lists every id with its text, one per line |
| `shipmill product add <users\|goals\|non-goals\|quality> "<text>"` | Appends an item with the next id, one above any the file's history held, and prints it |
| `shipmill product edit <id> "<text>"` | Rewrites one item's text; its id stays |
| `shipmill product retire <id>` | Removes one item; its id is never handed out again |
| `shipmill product measure <G-n> "<metric> <comparison> <target>"` | Writes the goal's measure line, or replaces the one it has (spec 027); `--clear` removes it |
| `shipmill product goal <G-n> --check "<check>" --by <horizon>` | Rewrites the goal as a goal, `<outcome>. Check: <check>. By: <horizon>`, keeping its outcome, and prints the line (spec 105); the horizon is a date, `YYYY-MM-DD`, or a release, `X.Y.Z`. Exits 2 on a measure, a malformed horizon, or a goal with a measure line |
| `shipmill product held <G-n> --threshold "<threshold>" --source "<source>"` | Rewrites the goal as a standing measure, `Held: <statement>. Threshold: <threshold>. Source: <source>`, keeping its statement and its measure line, and prints the line (spec 105). Exits 2 on a goal |
| `shipmill product met <G-n> [--on YYYY-MM-DD]` | Records a goal of kind goal as met: appends `. Met: <date>` to its text, the date today in UTC unless given (spec 106); refuses a measure, a goal of no kind, and one already met or dropped |
| `shipmill product drop <G-n>` | Records a goal of kind goal as dropped, with `--reason "<reason>"`: appends `. Dropped: <today>: <reason>` (spec 106); refuses as `met` does |
| `shipmill product serves <G-n> <G-n> ...` | In a component (`[product] home`), writes the goal's serves line naming the goals of the product's home direction it serves, or replaces the one it has (spec 071); `--clear` removes it |

Without `uv tool install shipmill`, run each as `uvx shipmill product ...`.

Each takes `--repo DIR` (default: the current directory). An edit command exits 2 without
writing when the file doesn't pass `check` first. In a session with the shipmill plugin,
an edit of the direction runs `shipmill product check --local` right away and shows a broken line
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
