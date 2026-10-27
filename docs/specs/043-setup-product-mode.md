# S-043: Setup connects several repos as one product

status: built
serves: G-1

## Problem

`skills/shipmill-setup/SKILL.md` connects one repo at a time: lanes, `[agents]`, labels,
`docs/product.md`. It never mentions `[product]`, and `setup_state.py` never reads it, so a
maintainer whose product spans a home repo and component repos gets one independent gate
per repo and never hears of the coordinator (spec 038, D-47), though `shipmill app-token
--product`, `shipmill gh --product`, `upstream_state.py`, and `chains.py link --product
--child` already ship (shipmill/shipmill#677).

What goes wrong without it, as seen: a maintainer connected a knowledge repo and two code
repos of one product, each on its own. The first feature that crossed repos (7 issues in 7
repos) needed ordering and a production check, and with no `[product]` they built their own
convention: an umbrella issue in the home repo, `Depends on` lines across repos written with
`shipmill gh -R <other repo>` (the path spec 038 closes for components), and a hand-written
decision record and issue templates for it. All of it duplicates what the coordinator is for.

Three gaps:

- **Setup never asks.** Nothing in the agents step asks whether the repo is one of several
  that make up a product, or writes `[product] home` or `[product] repos`
- **The checklist never notices.** `setup_state.py` reports nothing when the same owner has
  other repos connected to the same App and none of them has a `[product]` table, or when
  another repo's `[product] repos` lists this one and this one has no `home`
- **The skill isn't found for it.** Its description doesn't name the case, so "connect
  these repos as one product" doesn't reach it

## Behaviour

### The question, in the agents step

`skills/shipmill-setup/SKILL.md`, under The gate, gains a **Product** step after Config and
before the App's identity, asked in the same round as the App and mode questions (D-20),
with AskUserQuestion, or through the needs-decision protocol in a gate session (D-21):

1. **One product or several repos?** "Is `<owner/repo>` one of several repos that make up
   one product?" When `setup_state.py` reports `PRODUCT_SIBLINGS` (below), the question
   lists the siblings it found as the likely other repos. Options: "No, it stands alone"
   (recommended when no sibling was found), "Yes" (recommended when one was)
2. **On yes, the home and the components.** Which repo is the home, the one that holds
   planning and cross-repo work and whose `docs/product.md` describes the product as a
   whole (D-46), and which repos are its components. The siblings found are offered; the
   maintainer may name other repos, of any owner
3. **Write this repo's half** into `.github/shipmill.toml` (D-4), in the same pull request
   as the `[agents]` section:
   - In the home: `[product] repos = [...]`, the components, which needs `[agents] app_id`
     in the same file (S-038-2)
   - In a component: `[product] home = "<owner/home>"`
   - On "No, it stands alone": `[product] standalone = true` (below), so the question is
     not asked again
4. **The other repos' halves are not written from here.** Setup writes only the repo it
   runs in (D-14: a session writes its own repo; S-038-10 refuses a component's `shipmill
   gh -R <other repo>` anyway). For each other repo of the product, it prints one line
   with the table that repo needs and how to get it there, and shows the list to the
   maintainer before the pull request opens:

   ```
   acme/api: [product] home = "acme/product"  run /shipmill:shipmill-setup acme/api in its checkout
   ```

   Run in that repo, `setup_state.py` reads `PRODUCT_LISTED` (below) and the Product step
   writes the `home` it names, with no question, since the maintainer already answered in
   the home
5. **The App on every repo.** For each component the App doesn't cover yet, run `$CR
   app-install <component>` as for any repo connected later. The coordinator's product
   permissions (contents, issues, and pull requests read, issues write, metadata read)
   are a subset of the session's, so an installation made for a session covers them

The step then says what works today and what doesn't, reading the open issues of spec 038
and the specs it names:

- **Works today:** the home's gate is the coordinator, with its token over the listed repos
  (`shipmill app-token --product`, `shipmill gh --product`); a component's agent reports a
  fault in another repo as an `upstream` issue in its own repo; the coordinator routes it
  (`upstream_state.py`, `chains.py link --product --child`) and closes it
- **Not yet:** `doctor` checking the product's repos and their links back
  (shipmill/shipmill#604); routing a report filed in the home repo itself
  (shipmill/shipmill#596); a plan across repos (D-46, on hold); the maintainer's queue
  across repos; a component reading its home's direction. Each line goes when its issue
  closes

### `[product] standalone`

The maintainer's "no" is recorded in the repo's own config, the one file setup already
writes (D-4); shipmill keeps no state of its own (N-2), and the config is on the forge with
the rest. A third form of the table:

```toml
[product]
standalone = true
```

- `standalone` takes only `true`, and is never set beside `home` or `repos`; `false`, any
  other value, or a second key exits 2 naming the key, as every `[product]` error does
  (S-038-1). It needs no `[agents] app_id`
- Every reader of `[product]` treats it as no table: `ProductConfig` in
  `src/shipmill/agents.py` (`Policy.parse` in `src/shipmill/policy.py`, `shipmill gh`,
  `shipmill app-token`, the gate) and the skill scripts' reader in
  `skills/github-ship-watch/scripts/watch_state.py` (`product_home`, `product_repos`, and
  their 3.10 fallbacks, which `chains.py`, `triage_state.py`, and `upstream_state.py` use),
  so tokens, states, and rows are what S-038-4 pins for a config without `[product]`
- `docs/release-lanes.md`, where `[product]` is documented, names the key
- Changing the answer later is a config edit: replace the table with `home` or `repos`

### The checklist: `setup_state.py`

`skills/shipmill-setup/scripts/setup_state.py` gains a Product row, read only when the
config has an `[agents]` section with `app_id` (a product's repos meet through the App),
placed after the agents rows. It reads siblings with the host's `gh` login, as the script
reads everything else, and as `shipmill app-create --dry-run` finds gated repos (S-006-2),
so it needs no App key and no new permission:

- **Siblings:** the owner's unarchived repos other than this one (`gh api
  /orgs/<owner>/repos`, or `/user/repos?affiliation=owner` when the owner is the `gh`
  login's own account, so its private repos are listed, paged), each
  one's `.github/shipmill.toml` read from its default branch with `gh api
  repos/<repo>/contents/.github/shipmill.toml`, and kept when its `[agents] app_id` equals
  this repo's. A 404 means no config, so no sibling; any other failure exits 2, as a gh
  failure does today. Each sibling's config is read with the reader the script already
  uses (tomllib, or the 3.10 fallback), and a sibling whose config it can't parse is named
  in the row's detail and skipped, since it is another repo's to fix
- The row, the first that applies:

  | Row | When | Fix |
  |---|---|---|
  | `PRODUCT_LISTED` | this repo has no `[product]`, and a sibling's `[product] repos` lists it | write `[product] home = "<that sibling>"`, the Product step's 3 with no question; two siblings listing it name both, and the maintainer picks |
  | `PRODUCT_SIBLINGS` | this repo has no `[product]`, and one or more siblings exist; the detail names them | the Product step asks the maintainer, once: its answer writes `home`, `repos`, or `standalone`, and the row never shows again |
  | `PRODUCT_OK` | the repo has `[product]` (any form), or no sibling exists, or no `[agents] app_id` | none |

- `PRODUCT_LISTED` and `PRODUCT_SIBLINGS` are actions (exit 1) that `--fix` leaves: each
  needs the maintainer or a pull request. `PRODUCT_OK` is done
- "Once" is the config: the row shows until the answer is in `.github/shipmill.toml` on
  the default branch, and never after, whatever the answer was
- With `[product]` already set, the row reads nothing more: the links back are `doctor`'s
  (below)

### With `[product]` already set: the links back

Setup checks no link itself. Before it reports the agent side connected, it already runs
`$CR doctor` (step 5); in a repo with `[product]`, it reads doctor's product lines, the
checks shipmill/shipmill#604 builds (S-038-27 and S-038-28 in the home, S-038-30 in a
component, as amended by shipmill/shipmill#601), and relays each one with its fix: a
component that lacks its `home` or names another repo, named with the line from step 4 to
run in it. Until #604 lands, doctor prints no product lines, and the step says so with
the "Not yet" list above.

### The skill's description

`skills/shipmill-setup/SKILL.md`'s description names the case: "Use too when the user asks
to connect several repos as one product (a home repo and its components)", so a request
phrased that way reaches the skill.

## Acceptance criteria

- S-043-1: a `[product]` table with `standalone = true` alone parses in `ProductConfig` and in `watch_state.py`'s reader (3.11+ and the 3.10 fallback) and reads as no table; `standalone = false`, a non-boolean, or `standalone` beside `home` or `repos` exits 2 naming the key
- S-043-2: with `[product] standalone = true`, `shipmill app-token`, `shipmill gh`, the gate's helpers, `triage_state.py`, and `watch_state.py` give the tokens, states, and rows S-038-4 pins for a config without `[product]`
- S-043-3: `setup_state.py` in a checkout with `[agents] app_id` and no `[product]` reports `PRODUCT_SIBLINGS`, exit 1, naming each repo of the same owner whose default-branch `.github/shipmill.toml` sets the same `app_id`, and leaves out repos with another `app_id`, no config (404), or archived
- S-043-4: `setup_state.py` reports `PRODUCT_LISTED`, exit 1, naming the sibling and the `home = "<sibling>"` line to write, when a sibling's `[product] repos` lists this repo (case ignored) and this repo has no `[product]`; it reads before `PRODUCT_SIBLINGS`
- S-043-5: `setup_state.py` reports `PRODUCT_OK` and makes no sibling read when the config has `[product]` in any form, including `standalone = true`, or has no `[agents] app_id`; with no sibling found it reports `PRODUCT_OK`
- S-043-6: `setup_state.py` exits 2 when a sibling read fails with anything but 404, names a sibling whose config it can't parse in the row's detail and skips it, and `--fix` changes nothing for a Product row
- S-043-7: `skills/shipmill-setup/SKILL.md` has a Product step under The gate that asks whether the repo is one of several making up a product, asks for the home and the components on yes, writes `[product] repos` in the home, `[product] home` in a component, or `[product] standalone = true` on no in the same pull request as `[agents]`, and writes `home` with no question on `PRODUCT_LISTED`
- S-043-8: the Product step writes only the checkout's own config, prints one line per other repo of the product naming the table it needs and `/shipmill:shipmill-setup <repo>` to run in its checkout, and names `$CR app-install` for a component the App doesn't cover
- S-043-9: the Product step lists what works today (`shipmill app-token --product`, `shipmill gh --product`, `upstream` reports, `upstream_state.py`, `chains.py link --product --child`) and what doesn't yet, naming shipmill/shipmill#604 and shipmill/shipmill#596
- S-043-10: with `[product]` set, the Product step relays doctor's product lines (S-038-27, S-038-28, S-038-30) with their fixes, and runs no check of the links back of its own
- S-043-11: `skills/shipmill-setup/SKILL.md`'s description names "connect several repos as one product", and the eval suite (spec 025) has a case where "connect acme/api and acme/web to acme/product as one product" loads shipmill-setup and the session writes `[product] home = "acme/product"` in the component's config only

## Out of scope

- `doctor`'s checks of the product's repos and their links back: spec 038's S-038-27, S-038-28, and S-038-30, built in shipmill/shipmill#604; this spec only relays them
- Writing another repo's config from this checkout, or opening its pull request: each repo's half is written by setup run there (D-14)
- Finding siblings under another owner, or connected to another App: the maintainer names those repos in the Product step
- A product's `docs/product.md` in the home and in each component (D-46, D-34): the agents step's direction question already covers each repo's own
- The plan across repos, the maintainer's queue, and component directions: spec 038's Out of scope, unchanged

## Decisions relied on

- D-4: `[product]`, `standalone` included, lives in `.github/shipmill.toml`
- D-14: setup writes only the repo it runs in
- D-19: the Product row is read only with `[agents] app_id`, the App the product's repos share
- D-20: the Product question is asked with the App and mode questions
- D-21: in a gate session the question goes through the needs-decision protocol
- D-34: each repo keeps its own direction
- D-42: setup writes no client doc; the Product step writes only the config
- D-46: the home is the repo whose direction describes the whole product
- D-47: the coordinator is the home's gate; a component's session stays in its repo

## Issues

- shipmill/shipmill#720: S-043-1, S-043-2
- shipmill/shipmill#721: S-043-3, S-043-4, S-043-5, S-043-6
- shipmill/shipmill#722: S-043-7, S-043-8, S-043-9, S-043-10, S-043-11

The feature is shipmill/shipmill#677. The build issues landed in shipmill/shipmill#726
(#720), shipmill/shipmill#732 (#721), and shipmill/shipmill#738 (#722), which set this
spec to `built`.

## Verification

- S-043-1: `tests/test_product_config.py` parses `[product] standalone = true` in `ProductConfig` as no table, and exits 2 naming `standalone` for `false`, a non-boolean, and `standalone` beside `home` or `repos`, in `plan` and the gate; `tests/test_watch_product_standalone.py` runs `watch_state.py`'s reader on 3.11+ and under Python 3.10's fallback with the same results
- S-043-2: `tests/test_product_absent.py` runs every S-038-4 test (`app-token`, `shipmill gh`, the gate's helpers, `triage_state.py`, `watch_state.py`) on the no-product configs plus each with `[product] standalone = true` appended, and pins the same tokens, states, and rows for both
- S-043-3: `tests/test_setup_state.py` reads `PRODUCT_SIBLINGS`, exit 1, naming `me/api` and `me/Web` (same `app_id`), leaving out another `app_id`, a 404, a config with no `[agents]`, an archived repo, and this repo, and listing the owner as a user, the gh login itself, or an organization; it runs under Python 3.10 too
- S-043-4: `PRODUCT_LISTED`, exit 1, with `write [product] home = "me/product"` when a sibling's `repos` lists this repo in either case, ahead of `PRODUCT_SIBLINGS`; two homes are both named and the maintainer picks; a home on another App is no sibling
- S-043-5: each `[product]` form, `standalone = true` included, and a config with no `app_id` read `PRODUCT_OK` with no gh call at all; no sibling found reads `PRODUCT_OK` naming the owner and the `app_id`
- S-043-6: a sibling read failing with 403 or a network error exits 2 naming the repo, a 404 reads as no config, a sibling config that can't be parsed is named in the detail as skipped, and the Product rows make only gh reads and never take `--fix`
- S-043-7: `tests/test_setup_product_step.py` reads `skills/shipmill-setup/SKILL.md`'s `**Product (spec 043).**` step under The gate, between Config and the App's identity, in the D-20 round: it asks "Is `<owner/repo>` one of several repos that make up one product?", asks for the home and the components on yes, writes `repos` in the home, `home` in a component, or `standalone = true` on no in the pull request with `[agents]`, and writes `home` with no question on `PRODUCT_LISTED`; the keys it writes are exactly the three `ProductConfig` allows
- S-043-8: the step writes only this checkout's config (D-14), never a `$CR gh -R <other repo>` write, prints one line per other repo with its table and `/shipmill:shipmill-setup <repo>` to run in its checkout, and names `$CR app-install <owner/component>` for a component the App doesn't cover, `$CR` being the pinned CLI the skill defines
- S-043-9: the step's Works today list names `shipmill app-token --product`, `shipmill gh --product`, `upstream` issues, `upstream_state.py`, and `chains.py link --product --child`, and its Not yet list holds the plan across repos, the maintainer's queue, and a component reading its home's direction; shipmill/shipmill#604 and shipmill/shipmill#596 had both closed (released in v0.81.0) when it was written, so the step names them as done under Works today, as the Behaviour's "each line goes when its issue closes" says, instead of under Not yet
- S-043-10: the step runs no check of the links back of its own and relays doctor's `product` lines with their fixes: S-038-27's `the coordinator can't reach it: run $CR app-install <repo>`, S-038-28's `set [product] home = "<home>" in <repo>'s .github/shipmill.toml`, and S-038-30's `add "<repo>" to [product] repos in <home>'s .github/shipmill.toml`; the test checks each fix against `src/shipmill/doctor.py`'s own text
- S-043-11: the test reads the description's "connect several repos as one product (a home repo and its components)" within 1024 characters, and the `evals/shipmill-setup/product-component` case (listed in `evals/cases.toml`, well formed under `shipmill evals check`): the prompt "connect acme/api and acme/web to acme/product as one product" with no slash command, graded on a Skill load, `[product] home = "acme/product"` in this checkout's `.github/shipmill.toml`, no `repos` or `standalone` there, no write to GitHub, and the other repos' lines printed
