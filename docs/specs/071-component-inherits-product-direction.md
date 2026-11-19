# S-071: A component inherits its product's non-goals and serves its goals

status: built
serves: G-5

## Problem

A product often spans several repos: a home repo describes the product as a whole (D-46),
and each component repo is a smaller product of its own, such as the product's API or its
web app. D-34 has each repo keep a `docs/product.md` for its own scope, and spec 038 links a
component to its product through `[product] home` in `.github/shipmill.toml`. What a
component's direction can't do is take part in the product's
(shipmill/shipmill#579):

- **Non-goals aren't inherited.** A non-goal of the whole product ("we don't sell raw data
  dumps") holds in a component only if the maintainer copies it into every component's file;
  triage, product intake, and review in the component read only the component's own, so a
  request the product declined can be built in one of its parts
- **No goal traces to the product's goals.** The grammar of `docs/product.md` (spec 024) has
  no place for a component goal to name the goal of the product it serves, so nothing checks
  that a component works toward the product rather than beside it

The maintainer, who runs one product with a home repo and over a dozen components, asked for
this in chat on 2026-10-24 ("each repo's `product.md` keeps only the context of its own
scope") and accepted the opportunity narrowed to the inheritance of non-goals and goals that
name the product goal they serve; the link itself is spec 038's `[product] home`. Since
spec 065 (D-84) a component's session can read its home repo through a read-only token, so
the home's direction is within reach.

## Behaviour

### A goal names the product goal it serves

The grammar of `docs/product.md` (`src/shipmill/product.py`, spec 024) gains one optional
line under a goal item, beside spec 027's measure line:

    ## Goals

    - G-1: Partners integrate with the API in a day
      measure: lead_time_p90 < 1d
      serves: G-2, G-4

- `  serves: <G-n>[, <G-n> ...]`, indented by two spaces, right under the goal's item line
  or under its measure line; at most one per goal, only under a goal. Each id is a goal id of
  the product's home direction, unique on the line
- `shipmill product check` refuses, naming the file, line, and rule: a serves line under a
  non-goal item or in another section, a second one under one goal, a malformed one (not two
  spaces, not `G-n` ids, an id twice), and any serves line in a repo whose
  `.github/shipmill.toml` sets no `[product] home` (a repo in no product, or the home itself,
  which serves no product above it)
- `shipmill product show --json` gives each goal a `serves` key, a list of ids, empty without
  a serves line; the text form prints the line under its goal as the file has it
- `shipmill product serves <G-n> <G-n> ...` writes or replaces a goal's serves line, and
  `--clear` removes it, as `shipmill product measure` does (spec 024's edit rules: every other
  line byte for byte, exit 2 without writing on a file that fails `check`); `product retire`
  of a goal removes its serves line with it, and `add`, `edit`, and `measure` keep it
- The skill scripts that parse the direction without the package accept the line where a
  measure line is accepted: `skills/github-pr-triage/scripts/pr_gate.py`,
  `skills/product-intake/scripts/plans.py`, and `skills/github-issue-triage/scripts/specs.py`
  (whose `serves:` line of a spec still names the component's own goals)

### A component reads its product's direction

In a checkout whose config sets `[product] home` (`src/shipmill/agents.py`'s
`ProductConfig`), `shipmill product show` and `shipmill product check` read the home's
direction, `docs/product.md` and the files under `docs/product/` its moved sections link, as
committed on the home's default branch, through the read token of spec 065 (the contents API,
GET only, D-84). The home's direction is parsed by the same grammar as any other:

- **Show.** `shipmill product show` adds the product's part after the component's own, for
  the sections asked: with `non-goals`, the product's non-goals; with `goals`, the product's
  goals. Its text form prints them under `## Product non-goals (<owner/home>)` and `## Product
  goals (<owner/home>)`, each item qualified as `<owner/home> N-n: <text>`; its JSON form adds
  one key, `product`, `{"home", "name", "goals": [...], "non_goals": [...]}`, holding the
  sections asked. The component's own sections are unchanged in both forms
- **Check.** `shipmill product check`, when a goal carries a serves line, refuses (exit 1,
  naming the file, line, and the home) a serves line naming an id the home's Goals don't list.
  A component none of whose goals carries a serves line reads nothing of the home in `check`
- **Can't read it.** When the home's direction can't be read (no `[agents] app_id` or key for
  the read token, the home's config doesn't list the component (S-065-3), the read fails, the
  home has no `docs/product.md`) or breaks the grammar, `show` and `check` exit 2 naming the
  home, the file, and the fix, and print nothing of the component's either, so no session
  judges new behaviour on half a direction
- **`--local`.** Both commands take `--local`, which reads only this checkout's direction, as
  before this spec, and checks a serves line's form but not its ids; it is for a host with no
  App key, such as the maintainer's laptop or CI. The hooks of spec 026 that run `product
  check` after an edit of the direction, and `shipmill doctor`'s direction line (S-024-5), run
  it as `--local`
- `shipmill product ids` lists the component's own ids only, so a spec in a component still
  serves the component's goals (S-024-6)
- A repo without `[product] home`, the home included, reads only its own direction, exactly
  as before this spec

### The skills read the inherited non-goals

They already read the direction through `shipmill product show --section`, so the product's
non-goals reach them through the same call; their texts say what to do with them:

- `skills/github-issue-triage/references/triage-rubric.md` (The direction: the goal it
  serves) and `references/comments.md`: a request that hits a non-goal of the product is
  **won't fix**, citing it as `<owner/home> N-n` with the non-goal's words, as a component's
  own `N-n` is; a request the maintainer wants anyway changes the home's direction first,
  which only the maintainer does
- `skills/product-intake/SKILL.md` and `references/opportunity.md`: an opportunity that hits
  a product non-goal says so on its `Serves` line, `; hits <owner/home> N-n: {the non-goal's
  words}`, as for a component's own, and is never proposed for acceptance on demand; the
  maintainer still accepts or declines it (D-10)
- `skills/github-pr-triage/references/reviewer-brief.md`: the brief's direction field holds
  the product's non-goals too, and a change that hits one is a finding citing
  `<owner/home> N-n`
- Each of the three says that when `shipmill product show` exits 2 on the home's direction,
  no verdict, opportunity, or review finding on new behaviour is given until the maintainer
  fixes it: the session names the problem in its report and goes on with the rest, as the
  rubric already does for a broken direction of the repo's own
- `skills/shipmill-setup/SKILL.md`, connecting a component (spec 043): when it asks for the
  component's goals, it shows the home's goals and asks which each one serves, writing the
  answer with `shipmill product serves`; it never picks one for the maintainer

## Acceptance criteria

- S-071-1: `shipmill product check --local` exits 0 on a component's direction whose goals carry well-formed serves lines, right under the item line or under its measure line, and exits 1 naming the file, line, and rule for a serves line under a non-goal or outside Goals, a second one under one goal, one not indented by two spaces, one naming a non-`G-n` id, and one naming an id twice
- S-071-2: `shipmill product check`, with or without `--local`, exits 1 naming the file and line for a serves line in a repo whose config sets no `[product] home`, and in the home repo whose config sets `[product] repos`
- S-071-3: in a component, `shipmill product check` exits 1 naming the file, line, the id, and the home for a serves line naming a goal id the home's direction on its default branch doesn't list, and exits 0 when every id is listed there, a goal moved to `docs/product/` in the home included
- S-071-4: in a component none of whose goals carries a serves line, `shipmill product check` reads nothing of the home repo
- S-071-5: in a component, `shipmill product show --section non-goals` prints the component's non-goals, then `## Product non-goals (<owner/home>)` with each of the home's non-goals as `<owner/home> N-n: <text>`; `--section goals` prints the product's goals the same way; and `--json` adds one `product` key with `home`, `name`, and the sections asked, the component's own keys unchanged
- S-071-6: the home's direction is read only from its default branch through the read token of spec 065 with GET requests, and every read of it goes to the home repo alone
- S-071-7: in a component, `shipmill product show` and `shipmill product check` exit 2 naming the home and the fix, printing nothing of the component's direction, when the read token can't be minted, the read fails, the home has no `docs/product.md`, or the home's direction breaks the grammar
- S-071-8: `shipmill product show --local` and `shipmill product check --local` in a component read nothing of the home and give what they gave before this spec, save the serves lines' form check; in a repo without `[product] home`, `show`, `check`, and `ids` read nothing of any other repo and give the same output as before this spec
- S-071-9: `shipmill product show --json` gives each goal a `serves` list, empty without a serves line, and `shipmill product ids` lists no id of the home's direction
- S-071-10: `shipmill product serves G-n <ids>` writes or replaces the goal's serves line right under its item line or its measure line, `--clear` removes it, and both leave every other line unchanged and exit 2 without writing on a file that fails `check --local`; `product retire` of a goal removes its serves line, and `add`, `edit`, and `measure` keep it
- S-071-11: `pr_gate.py`, `plans.py`, and `specs.py` read a direction whose goals carry serves lines as they read it without them: the same ids, and no error
- S-071-12: triage-rubric.md and comments.md give **won't fix** for a request hitting a product non-goal, citing `<owner/home> N-n`; product-intake's SKILL.md and opportunity.md name it on the opportunity's `Serves` line as `hits <owner/home> N-n` and never propose such an opportunity on demand; reviewer-brief.md reports a change hitting one as a finding citing it; and each says that no verdict, opportunity, or finding on new behaviour is given while `shipmill product show` exits 2 on the home's direction
- S-071-13: the hooks of spec 026 run `shipmill product check --local` after an edit of `docs/product.md` or `docs/product/`, `shipmill doctor`'s direction line checks the component's direction as `--local` does and reads nothing of the home's direction, and shipmill-setup's SKILL.md, connecting a component, shows the home's goals, asks the maintainer which each component goal serves, and writes the answer with `shipmill product serves`, never choosing one itself

## Out of scope

- The link from a component to its product: spec 038's `[product] home`, unchanged
- Reading the product's Mission, Users, or Quality bar in a component: the maintainer narrowed this to non-goals and goals; the quality bar of each repo stays its own
- A component goal that must serve a product goal: a serves line is optional, and a component goal with none is not refused
- A spec in a component serving a product goal directly: a spec's `serves:` names the component's own goals (S-024-6); the product's goal is reached through the component goal's serves line
- The home seeing which components serve which of its goals, or a retro per product goal across repos: a later spec, with the product-wide plan of #338
- `shipmill doctor` reading the home's direction: it runs the grammar check of the component's own as today; the cross-check runs where the read token is, in the session
- Judging whether a component goal really advances the product goal it names: the maintainer's call when writing the line

## Decisions relied on

- D-4: settings live in `.github/shipmill.toml`; `[product] home` is read from it
- D-16: unattended sessions follow only trusted text; the home's direction on its default branch is the maintainer's own file
- D-34: agents work toward the written direction; a non-goal is won't fix, and only the maintainer changes a direction
- D-46: the home repo's `docs/product.md` describes the product as a whole; each component keeps its own for its own scope
- D-84: a component reads its product's other repos with a read-only token and writes only its own

## Issues

- shipmill/shipmill#1248: S-071-1, S-071-2, S-071-9, S-071-10, S-071-11
- shipmill/shipmill#1251: S-071-3, S-071-4, S-071-5, S-071-6, S-071-7, S-071-8, S-071-13
- shipmill/shipmill#1256: S-071-12

## Verification

- S-071-1: ran the S-071-1 tests of `tests/test_product_serves.py` over `src/shipmill/product.py`: `check --local` accepts serves lines under the item or the measure line, a moved Goals section included, and refuses each misplaced or malformed one naming the file, line, and rule; holds
- S-071-2: ran the S-071-2 tests: a serves line in a repo without `[product] home`, and in a home with `[product] repos`, exits 1 naming the file and line with or without `--local`, and a direction without serves lines never reads the config; ran `shipmill product check` in this repo (no home): `docs/product.md: well formed, 23 items`; holds
- S-071-3: ran the S-071-3 tests of `tests/test_product_inherits.py` over a fake GitHub for the home: an id the home's Goals don't list, a retired one included, exits 1 naming the file, line, id, and home, and exits 0 when every id is listed, a goal moved to `docs/product/` in the home included; holds
- S-071-4: ran the S-071-4 test: with no serves line, `check` makes no request to the home; holds
- S-071-5: ran the S-071-5 tests and read `Inherited.render` in `product.py`: `show --section non-goals` prints the component's, then `## Product non-goals (<owner/home>)` with `- <owner/home> N-n: <text>`, goals the same way, and `--json` adds one `product` key with `home`, `name`, and the sections asked; holds
- S-071-6: ran the S-071-6 test: after the read token's mint over the home alone, every request is a GET of `/repos/<home>/contents/...` with no ref; holds
- S-071-7: ran the S-071-7 test: no key, a failed read, no `docs/product.md`, and a home direction that breaks the grammar each exit 2 naming the home and the fix and print nothing; read `home_refusal` in `product.py`; holds
- S-071-8: ran the S-071-8 tests, and `shipmill product show --section goals --json` and `--section non-goals --json` in this repo (no home): the component's own keys only, no `product` key, no other repo read; holds
- S-071-9: ran the S-071-9 test and `shipmill product show --section goals --json` in this repo: each goal has `"serves": []`, and `product ids` lists no home id; holds
- S-071-10: ran the S-071-10 tests: `product serves` writes, replaces, and `--clear`s only the goal's serves line, under the item or measure line and in a moved section's file, exits 2 without writing on a file `check --local` refuses, and `retire` removes the line while `add`, `edit`, and `measure` keep it; holds
- S-071-11: ran the S-071-11 tests of `tests/test_pr_gate.py`, `tests/test_plans.py`, and `tests/test_specs.py`: each script reads the same ids with and without serves lines, with no error; holds
- S-071-12: read `skills/github-issue-triage/references/triage-rubric.md` and `references/comments.md` (a request hitting a product non-goal is **won't fix**, citing `<owner/home> N-n`), `skills/product-intake/SKILL.md` and `references/opportunity.md` (`hits <owner/home> N-n` on the `Serves` line, never proposed on demand), and `skills/github-pr-triage/references/reviewer-brief.md` (a finding citing `<owner/home> N-n`); each says nothing on new behaviour is given while `shipmill product show` exits 2 on the home's direction; holds
- S-071-13: read `hooks/delivery.py`, which runs `shipmill product check --local` after an edit of the direction, ran the S-071-13 tests (doctor's direction line reads nothing of the home), and read `skills/shipmill-setup/SKILL.md`'s component step, which shows the home's goals, asks which each serves, and writes the answer with `product serves`, never choosing; holds
