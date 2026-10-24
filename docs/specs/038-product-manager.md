# S-038: Work across repos through the product's manager

status: approved
serves: G-1

## Problem

A product made of several repos, a home repo and its component repos, meets faults and
dependencies that cross repo lines, and today none of D-45 and D-46 is built
(shipmill/shipmill#580; the design is `docs/design/product-layer.md`, Across repos):

- A gate's App token covers only its own repo (D-14, spec 004), so an item in one private
  repo that depends on another reads UNREADABLE in `chains.py show`, counts as an open hold
  in `triage_state.py`, and the chain stalls; spec 017's direct holds work only where the
  waiting repo can read the other one
- An agent that traces a bug to another repo's module has nowhere to put it:
  `skills/github-issue-triage/references/comments.md` (Clarify) has it file the bug upstream
  itself ("Filed upstream as"), which D-45 now forbids for a component's session, and
  `shipmill gh -R other/repo` would mint a token for any repo the App is installed on
- No session owns the other side of a cross-repo step: nothing routes a report to the repos
  at fault, watches them, or tells the waiting repo when they are done

The maintainer runs one such product, a home repo and over a dozen component repos, and
accepted the opportunity on 2026-10-24, after #578 merged D-45 and D-46.

## Behaviour

### The config

A new optional table in `.github/shipmill.toml` (D-4), `[product]`, read by a
`ProductConfig` beside `app_id_of` in `src/shipmill/agents.py` (so the gate, `shipmill gh`
and `shipmill app-token` read it without the release keys, as they read `[agents]`), allowed
by `Policy.parse` in `src/shipmill/policy.py`, and read by the skill scripts through
`watch_state.py`'s config reader (tomllib on 3.11+, its regex fallback on 3.10), as
`chains.py` reads `[agents]` today. A component repo names its home:

```toml
[product]
home = "acme/product"
```

and the home repo names its components:

```toml
[product]
repos = ["acme/api", "acme/web", "other-org/sdk"]
```

- `home` names the product's home repo; `repos` names the home's component repos. A table
  holds one of the two keys, never both: a repo is the home or a component
- Each value is `owner/name` by the rule `repo_name` and the token cache's segment rule in
  `src/shipmill/app.py` apply; `repos` is a non-empty list with no repo twice (case
  ignored). Any other key, a malformed value, an empty list, a repeat, or both keys exits 2
  naming the key, as every table does
- `repos` needs `[agents] app_id` in the same file: the manager is the home repo's gate,
  and its second token comes from that App. Without it the config exits 2
- A repo never names itself: where the checkout's repo is known (`shipmill gate`,
  `shipmill app-token --product`, `shipmill gh`), a `home` equal to it or a `repos` that
  lists it exits 2
- No `[product]` table is today's behaviour: the repo is in no product, its token, states,
  rows and holds are unchanged, and an `upstream` report it files waits for the maintainer

### The manager's second token

D-45 refines D-14: a component's session keeps the one token limited to its repo, and the
home repo's gate, the manager, gets a second one over its product's repos.

- `shipmill app-token OWNER/NAME --app-id N --product`, run with `--repo` on the home
  repo's checkout, prints an installation token for every repo the config's `[product]
  repos` lists under OWNER, the one App installation that covers them. It asks a second
  table in `src/shipmill/app.py`, `PRODUCT_PERMISSIONS`: contents read, issues write, pull
  requests read, metadata read; no contents, pull requests, actions, or workflows write
- Repos that span owners get one token per installation (per owner); a gh call names the
  repo it works on, which picks the token
- It refuses the token (exit 2, the token never printed or cached) when GitHub's answer
  covers a repo outside that set or leaves one out, or grants any permission broader than
  asked, mirroring `_scope`; a listed repo the App isn't installed on, or whose
  installation lacks one of the permissions, exits 2 naming the repo with `installation`'s
  NotInstalled and Lacks messages. `shipmill gate` in the home repo checks the same before
  it starts a session and exits 2 rather than starting one without the manager's access
- It is cached apart from the session's: `app-token-product-<owner>.json` in the
  checkout's state folder (`$(git rev-parse --git-common-dir)/shipmill`), mode 0600,
  reused while it has 10 minutes left and its repositories match the config's. The
  session's `app-token.json`, the gh and git credential helpers, and their one-repo token
  are unchanged, so a push or a pull request from the manager's session still reaches only
  the home repo
- `shipmill gh --product OWNER/NAME <gh args>` (a leading flag that is shipmill's, like
  `--app-key`) runs gh with the product token for OWNER. It exits 2 when the checkout has no
  `[product] repos`, when OWNER/NAME isn't listed, or when gh's `-R` names a repo that isn't
  listed or has another owner. Before gh runs it refuses, exit 2 naming D-45, the commands
  that write code or pull requests: `pr` other than `list`, `view`, `diff`, `checks` and
  `status`; `release` other than `list` and `view`; `repo` other than `view` and `list`;
  `workflow run`; `run rerun` and `run cancel`. A write through `gh api` is left to the
  token, which GitHub refuses
- In a component (`[product] home` set), `shipmill gh` whose `-R` names any repo but the
  checkout's origin repo, and `shipmill app-token` for any repo but it, exit 2 naming D-45
  before a token is minted; `--product` there exits 2 too

### A report labelled `upstream`

An agent that traces a fault to a module another repo owns reports it in its own repo
(`skills/github-issue-resolve/SKILL.md`, Phase 2, and `comments.md`, Upstream report):

- It files an issue in its own repo, through `shipmill gh`, labelled `upstream`, whose body
  has `## Reproduce` (how to reproduce it), `## Touches` (the object it touches: an
  endpoint, a table, an index, a package) and `## Suspected code` (the place in the
  module's source when it found the cause; a guess it could not trace starts `Guess:`)
- It holds its issue on the report with `chains.py link <owner/repo#N> --blocked-by
  <owner/repo#R>`, both in its repo, which writes the `Depends on` line and the native
  relation, and posts the hold line on its issue
- It posts the report's triage comment: `Triage: **upstream**`, then "Routed by
  {owner/home}, the product's manager" when the config sets `[product] home`, else "No
  manager routes it: it waits for @{maintainer}, who reports it to the owning repo and
  closes this with what changed"
- It never files an issue in another repo, never vendors the other module, patches an
  installed dependency, or opens a pull request elsewhere. A workaround in its own code is
  fine when it is a real change there, said to be temporary in its pull request
- This replaces "Filed upstream as" in the Clarify template of `comments.md` and the step of
  github-issue-resolve's Phase 2 that files an issue on another repo

A stand-in for a dependency on another repo's work has the same label and shape: an issue
in the waiting repo, labelled `upstream`, saying what work it needs, with a `Stands in for
owner/repo#N` line when the other repo's issue already exists. In a component the triage
rubric (`skills/github-issue-triage/references/triage-rubric.md`, Links between issues)
writes a dependency on another repo as a stand-in instead of a direct `Depends on` line.

`chains.py link` run from a component's checkout exits 2, before any write, when either
reference names another repo than its own: an item there waits only on items in the same
repo.

### Local triage reads a report as waiting outside

- `skills/github-issue-triage/scripts/triage_state.py` reads an open issue labelled
  `upstream` as UPSTREAM, right after UNTRUSTED and before NEEDS_DECISION, DECIDED, and every
  other state, triaged or not, whatever its holds and children. UPSTREAM is not in
  `ACTION`: it starts nothing, like NEEDS_DECISION
- A new `--home OWNER/NAME` gives its note: `routed by OWNER/NAME`; without it, `no manager:
  waits for the maintainer`. A report labelled needs-decision whose question has no reply
  adds `asks the maintainer` (the manager asked on it; the component acts on no reply)
- `skills/github-ship-watch/scripts/watch_state.py` passes the config's `[product] home` as
  `--home`, and lists UPSTREAM issues in ISSUES_OPEN as `UPSTREAM #N`, never in ISSUES,
  NEEDS_DECISION, or an agent row, so the gate starts no session for one
- A closed issue labelled `upstream` never reads SUSPECT_CLOSE: the manager, or the
  maintainer without one, closes it by hand by design, as a `human` item is
- The issue that waits on the report reads BLOCKED while it is open and UNBLOCKED once it
  closes, `:not_planned` in the note when it closed as not planned, as spec 017 reads any
  hold; the agent then reads the report's closing summary and resumes, or decides again

### The manager routes and closes reports

A new state script, `skills/github-issue-triage/scripts/upstream_state.py`, run in the home
repo's checkout: `upstream_state.py <owner/home> [--bot-login LOGIN] [--json]`. It lives
beside `triage_state.py` and `chains.py` because it reads holds and trust with their
functions (`dependency_refs`, `native_holds`, `trusted`, `waits_on_decision`) and its
session writes with `chains.py link`.

- It reads the open issues labelled `upstream` in the home repo (through the session's gh)
  and in every listed repo (through `shipmill gh --product`), one line per report,
  `owner/repo#N STATE note`:
  - ROUTE_DUE: no children and no needs-decision label: find the owning repos and route it.
    A `Stands in for owner/repo#N` line puts `link owner/repo#N` in the note
  - ASKED: labelled needs-decision, its question has no reply: waits on the maintainer
  - ANSWERED: labelled needs-decision, its question has a reply: route it by the answer
  - ROUTED: it has a child still open; the note starts `children K/N closed`
  - CLOSE_DUE: every child closed; the note says `completed`, or `not_planned` when any child
    closed as not planned
  - UNTRUSTED: its author is neither an OWNER, MEMBER, or COLLABORATOR of its repo nor the
    `--bot-login` (D-16): its text, children, and comments are never read or followed
- A report's children are its sub-issues and the `Depends on` lines of its body, as
  `triage_state.py` reads holds, so a link the forge refused (`text only:`) still counts
- Exit 1 when any report reads ROUTE_DUE, ANSWERED, or CLOSE_DUE, else 0; 2 on a gh
  failure or a config it refuses
- `watch_state.py`, in a checkout whose config has `[product] repos`, runs it and reports
  UPSTREAM_DUE (an agent row) naming those reports, UPSTREAM_ASKED (a person's action,
  never an agent's) and UPSTREAM_UNTRUSTED (reported, never an action); a failing run is one
  UPSTREAM_UNREADABLE row with its first error line while the rest of the watch stands, as
  CHAIN_UNREADABLE is. Without `[product] repos` it never runs and none of these rows appear

The manager's session (github-issue-triage's SKILL.md, Reports from other repos):

- **Route:** for ROUTE_DUE, it reads the product's code and items with the product token,
  files an issue in each owning repo (often more than one) with `shipmill gh --product`,
  naming the report and quoting its sections, and makes each one a child of the report with
  `chains.py link --product <report> --child <issue>`; a stand-in's named issue is linked
  the same way, with no new issue. `--product` sends `link`'s writes through `shipmill gh
  --product <the parent's repo>`, and exits 2 when the checkout has no `[product] repos` or
  a reference is in neither a listed repo nor the home repo
- **Ask:** when it can't tell which repos own the fault, it asks on the report through the
  needs-decision protocol (D-21), with `shipmill gh --product`
- **Close:** for CLOSE_DUE, it comments a summary of what changed (each child, how it
  closed, and the pull request that closed it) and closes the report as completed, or as
  not planned when a child closed not planned, so the agent decides again
- It never changes files, pushes, creates a branch, opens a pull request, or merges outside
  the home repo (D-45)

### Without a manager

A repo with no `[product] home` has no manager: its `upstream` report or stand-in reads
UPSTREAM with `no manager: waits for the maintainer`, its triage comment says so, and the
maintainer reports it where it belongs and closes it by hand. A home repo has a manager only
with `[product] repos` and `[agents] app_id`; a component whose home runs no gate keeps
waiting, which the maintainer's queue (#337) is to show.

### Spec 017's direct holds

`Depends on owner/repo#N` lines and native relations naming another repo keep reading as
spec 017 says, with or without `--home`: BLOCKED while open, an unreadable one counted as
open, UNBLOCKED once closed. They keep working where the waiting repo can read the other
one (a public repo) or where the product has no manager; in a component, triage writes a
stand-in instead.

### Labels

`skills/shipmill-setup/scripts/setup_state.py` reports the `upstream` label missing wherever
it reports `needs-decision` missing, and shipmill-setup creates it with the others.

## Acceptance criteria

- S-038-1: a `[product]` table with `home = "owner/name"` or `repos = [...]` parses; an unknown key, a value that isn't `owner/name`, an empty `repos`, a repo listed twice (case ignored), or both keys in one table exits 2 naming the key, in `shipmill plan` and in the gate's loader alike
- S-038-2: a config with `[product] repos` and no `[agents] app_id` exits 2 saying the manager needs the App
- S-038-3: `shipmill gate`, `shipmill app-token --product`, and `shipmill gh` exit 2 when `[product] home` names the checkout's own repo or `[product] repos` lists it
- S-038-4: with no `[product]` table, `shipmill app-token`, `shipmill gh`, the gate's helpers, `triage_state.py`, and `watch_state.py` give the same tokens, states, and rows as before this spec
- S-038-5: `shipmill app-token OWNER/NAME --app-id N --product` in a home checkout mints one token over every listed repo of OWNER, asking exactly contents read, issues write, pull requests read, and metadata read, and prints it; it exits 2 when the checkout has no `[product] repos` or OWNER/NAME isn't listed
- S-038-6: `app-token --product` exits 2 without printing or caching the token when GitHub's answer covers a repo outside the asked set, leaves one out, or grants a permission broader than asked (contents write, pull requests write, or a key not asked)
- S-038-7: `app-token --product` exits 2 naming the repo when the App isn't installed on a listed repo or its installation lacks one of the product permissions, and `shipmill gate` in the home repo exits 2 for the same before starting a session
- S-038-8: the product token is cached in `app-token-product-<owner>.json` with mode 0600, reused while it has at least 10 minutes left and its repositories match the config's, and never read from or written to `app-token.json`; a session's `app-token <repo>` still mints for its one repo with `PERMISSIONS`
- S-038-9: `shipmill gh --product OWNER/NAME <args>` runs gh with the product token; it exits 2 when OWNER/NAME isn't listed, or gh's `-R` names a repo not listed or of another owner, and, before gh runs, for `pr` other than list, view, diff, checks, and status, `release` other than list and view, `repo` other than view and list, `workflow run`, `run rerun`, and `run cancel`
- S-038-10: in a checkout whose config sets `[product] home`, `shipmill gh` whose `-R` names a repo other than the checkout's origin, `shipmill app-token` for such a repo, and any `--product` exit 2 naming D-45 before a token is minted
- S-038-11: `chains.py link` run from a checkout whose config sets `[product] home` exits 2 before any write when either reference names another repo than its own
- S-038-12: `chains.py link --product P --child C` writes through `shipmill gh --product <P's repo>`, and exits 2 before any write when the checkout has no `[product] repos` or a reference is in neither a listed repo nor the home repo
- S-038-13: `triage_state.py` reads an open issue labelled `upstream` as UPSTREAM before NEEDS_DECISION, DECIDED, and every other state but UNTRUSTED, triaged or not, whatever its holds; UPSTREAM is not in `ACTION`, so a repo whose only open issue reads UPSTREAM exits 0
- S-038-14: UPSTREAM's note is `routed by OWNER/NAME` with `--home OWNER/NAME` and `no manager: waits for the maintainer` without it, and adds `asks the maintainer` when the report is labelled needs-decision and its question has no reply
- S-038-15: `watch_state.py` passes `[product] home` as `--home` and lists UPSTREAM issues in ISSUES_OPEN as `UPSTREAM #N`, in no ISSUES, NEEDS_DECISION, or agent row, and the gate starts no session for a repo whose only open issue reads UPSTREAM
- S-038-16: an issue with a `Depends on #R` line and a native blockedBy on an `upstream` report #R reads BLOCKED while #R is open, UNBLOCKED once #R closes as completed, and UNBLOCKED with `#R:not_planned` in its note once #R closes as not planned
- S-038-17: a closed issue labelled `upstream` never reads SUSPECT_CLOSE, whoever closed it and however
- S-038-18: `upstream_state.py <owner/home>` prints one line per open `upstream` issue of the home repo and every listed repo, reading ROUTE_DUE, ASKED, ANSWERED, ROUTED (note `children K/N closed`), or CLOSE_DUE (note `completed`, or `not_planned` when any child closed as not planned), and exits 1 when any is ROUTE_DUE, ANSWERED, or CLOSE_DUE, else 0, and 2 on a gh failure
- S-038-19: a report whose author is neither an OWNER, MEMBER, or COLLABORATOR of its repo nor the `--bot-login` reads UNTRUSTED in `upstream_state.py`, with no read of its children or comments, and is never ROUTE_DUE, ANSWERED, or CLOSE_DUE
- S-038-20: `upstream_state.py` counts a report's sub-issues and the `Depends on` lines of its body as its children, and puts `link owner/repo#N` in a ROUTE_DUE note for a `Stands in for owner/repo#N` line
- S-038-21: `watch_state.py` in a checkout with `[product] repos` reports UPSTREAM_DUE as an agent row naming the ROUTE_DUE, ANSWERED, and CLOSE_DUE reports, UPSTREAM_ASKED as a person's action, and UPSTREAM_UNTRUSTED as reported; a failing `upstream_state.py` is one UPSTREAM_UNREADABLE row while the rest of the watch stands; without `[product] repos` it runs no `upstream_state.py`
- S-038-22: github-issue-triage's SKILL.md has a Reports from other repos section saying the manager routes with `shipmill gh --product` and `chains.py link --product`, asks through needs-decision when it can't tell the owner, closes with a summary of each child, how it closed, and its pull request, as completed or not planned, and never changes files, pushes, branches, opens a pull request, or merges outside the home repo
- S-038-23: `comments.md` has an Upstream report section (the body's Reproduce, Touches, and Suspected code sections, a guess starting `Guess:`, and the triage comment's two variants), its Clarify template no longer says "Filed upstream as", triage-rubric.md has a component write a stand-in for a dependency on another repo, and github-issue-resolve's Phase 2 has the upstream verdict: report in its own repo, hold with `chains.py link --blocked-by`, never file in another repo, vendor, patch an installed dependency, or open a pull request elsewhere
- S-038-24: `setup_state.py` reports the `upstream` label missing wherever it reports `needs-decision` missing, and shipmill-setup creates it
- S-038-25: with or without `--home`, a `Depends on owner/repo#N` line or a native relation naming another repo's issue reads as spec 017 says: BLOCKED while open or unreadable, UNBLOCKED once closed
- S-038-26: over one scripted forge of a home repo and two components, an issue in component A waits on its `upstream` report, the manager routes the report to an issue in component B as its child, B's issue closes, the manager closes the report as completed with its summary, and A's issue reads UNBLOCKED; along the way no write from A's session names another repo and no write with the product token touches contents or a pull request

## Out of scope

- The plan across repos and the maintainer's trusted marker that carries it to each repo (D-46): on hold with #338
- The maintainer's queue (#337), which is to show what waits on the maintainer across repos, a component whose home runs no gate included
- Component directions (#579): a component's session reading its home repo's `docs/product.md`, which D-45 allows
- GitHub Projects, and GitLab's group boards, epics, and milestones (through the code host port, #322)
- A release in one repo held by a stand-in in its milestone: a stand-in is an ordinary issue, so a milestone may hold one, with nothing built for it here
- Reporting where chains stall (`chains.py show`, CHAIN_NO_GATE): unchanged

## Decisions relied on

- D-4
- D-14
- D-16
- D-21
- D-29
- D-34
- D-37
- D-40
- D-44
- D-45
- D-46

## Issues

## Verification
