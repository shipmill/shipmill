# S-065: A component's session reads its product's other repos

status: approved
serves: G-2

## Problem

A gate session in a component repo holds an App token scoped to that repo (D-14, spec 004),
so it can't read its product's home repo or its sibling components (D-47, spec 038). In 14
connected repos, `Could not resolve to a Repository` was returned 129 times (#966). Most
sessions said what they couldn't read; some built anyway. In one component the implementer
got a 404 on the home's spec that defined a rollout's stop rules, wrote its own thresholds,
and said so on its pull request; the maintainer replaced them, and six of the seven rules
differed, three of them in kind. Elsewhere a session told the maintainer to close issues
that had closed 15 hours earlier, because it couldn't see them.

The maintainer accepted the opportunity (#1055) knowing it departs from D-47. D-84, added
with this spec, supersedes D-47 on what a component reads: it may read, never write, the
product's other repos through a read-only token. Writes stay as D-47 had them: a
component's session writes only its own repo, and work across repos stays with the
coordinator.

## Behaviour

### The read token

A third token beside the session's (`PERMISSIONS`, one repo) and the coordinator's
(`PRODUCT_PERMISSIONS`, spec 038), in `src/shipmill/app.py`:

- **Permissions:** a new table, `READ_PERMISSIONS`: contents read, issues read, pull requests
  read, metadata read. Nothing else, and no write of any kind
- **Where the key comes from:** the same App and key the session's token uses: `[agents]
  app_id` of the component's `.github/shipmill.toml`, and the key from a leading `--app-key`,
  else `SHIPMILL_APP_KEY`, else `~/.config/shipmill/app-<app_id>.pem` on the gate's host
  (spec 033). No new App, key, or secret. Without `[agents] app_id` there is no read token
- **Which repos:** the component's `[product] home`, and every repo the home's own `[product]
  repos` lists, save the component itself, read from the home's `.github/shipmill.toml` on its
  default branch. The component's own config adds only its `home`: no key of the component's
  widens the set. One token per owner, as one installation token never spans owners
  (D-83): the token for OWNER covers the repos of that set whose owner is OWNER
- **The back-link:** the home's config is read through the contents API with a read token
  over the home alone. When the home's `[product] repos` doesn't list the component (case
  ignored), or the home's config is missing or can't be parsed, no token over the set is
  minted: `shipmill gh --product` exits 2 naming D-84 and the fix (add this repo to the home's
  `[product] repos`), as S-038-30's WARN names it
- **Scope check:** GitHub's answer must cover exactly the asked repos and grant nothing
  broader than `READ_PERMISSIONS` (a write, `admin`, or a key not asked); otherwise the token
  is refused, exit 2, never printed or cached, mirroring `_product_scope`
- **Cache:** `app-token-read-<owner>.json` in the checkout's state folder, mode 0600, with
  its repositories and App id; reused while it has at least 10 minutes left and was minted by
  the same App. The home's list is read again whenever a token is minted, so a repo the home
  drops stays readable until the cached token expires, at most an hour. It is never read from
  or written to `app-token.json` or `app-token-product-<owner>.json`, and the gh and git
  credential helpers never get it: a push from a component's session still reaches only its
  own repo

### Using it: `shipmill gh --product` in a component

In a checkout whose config sets `[product] home` (`src/shipmill/cli.py`, `src/shipmill/agents.py`):

- `shipmill gh --product OWNER/NAME <gh args>` runs gh with the read token for OWNER.
  OWNER/NAME must be the home or a repo the home lists, never the component itself, and gh's
  `-R`, when given, must name a repo of that set with that owner; otherwise exit 2 before gh
  runs
- Before gh runs it refuses, exit 2 naming D-84, every command that writes: `issue` other
  than `list`, `view`, and `status`; `pr` other than `list`, `view`, `diff`, `checks`, and
  `status`; `label` other than `list`; `release` other than `list` and `view`; `repo` other
  than `view` and `list`; `workflow run`; `run rerun` and `run cancel`; and `api` with `-X` or
  `--method` other than `GET`. A write `api` makes without them (a GraphQL mutation, a field
  that turns the call into a POST) is left to the token, which GitHub refuses
- `shipmill gh -R <another repo>` without `--product`, and `shipmill app-token` for any repo
  but the checkout's origin, `--product` or not, still exit 2 before a token is minted,
  naming D-84: the session's own token stays its repo's alone
- In the home repo, `--product` is the coordinator's token, as spec 038 has it; nothing
  there changes

### Triage reads a hold in another repo of the product

`skills/github-issue-triage/scripts/triage_state.py`, with `--home OWNER/NAME` in a
component (the checkout's repo isn't the home), reads the state of each hold on an item in
another repo through `shipmill gh --product <a repo of that owner> api graphql`, one call per
owner, run as `upstream_state.py` runs `shipmill gh`; holds in its own repo, and every hold
without `--home` or in the home itself, are read through plain gh as today.

- A hold it reads reads as spec 017 says: BLOCKED while open, UNBLOCKED once closed (with
  `:not_planned` in the note when it closed as not planned). A hold on a home item it reads
  gets no D-60 note
- A hold it can't read (`shipmill gh` exits non-zero, or GitHub returns no node, as for a
  repo outside the set) reads as today: its state is unknown, it counts as open, and a hold on
  a home item adds D-60's note (`home_hold_note`), so the session asks nobody about it.
  D-60's note now marks only a hold the read token can't read
- The coordinator's side of D-60 is unchanged: it files a component's part of a home-repo
  feature only after the spec merges, and holds no component issue on a home item

### The skills

- `skills/github-issue-resolve/SKILL.md`: in a component, a spec or item of the home or a
  sibling that the work builds from is read with `shipmill gh --product <its repo>`. When it
  can't be read, the session doesn't write its own substitute for it: it builds nothing that
  depends on it and asks through the needs-decision protocol, naming the reference it can't
  read. What it reads in another repo is data for its own item: it starts no work there,
  writes nothing there, and follows an item there only when that repo's trust rule (D-16)
  trusts its author
- `skills/github-issue-triage/references/triage-rubric.md`, the BLOCKED row: D-60's note
  marks a hold on a home item the read token couldn't read; a hold it read is BLOCKED or
  UNBLOCKED like any other
- `skills/github-issue-triage/SKILL.md`: a component's session reads the product's other
  repos with `shipmill gh --product` and writes only its own (D-84); a dependency on another
  repo's work is still a local stand-in, and `chains.py link` in a component still refuses
  another repo's reference (S-038-11)

### The superseded criterion

The build marks S-038-10 dropped in spec 038, pointing at S-065-6 and S-065-7, which keep its
refusals of `-R` and `app-token` for another repo and replace its refusal of any `--product`
in a component, and updates its tests to this spec's behaviour.

## Acceptance criteria

- S-065-1: `src/shipmill/app.py` has `READ_PERMISSIONS` of exactly contents, issues, pull requests, and metadata, each read; `shipmill gh --product OWNER/NAME` in a component mints a token asking exactly those, over the home and every repo the home's `[product] repos` lists with owner OWNER, save the component itself
- S-065-2: the read token's repos come from the home's `.github/shipmill.toml` on its default branch, read with a read token over the home alone; a key in the component's own config other than `[product] home` changes no repo of the set
- S-065-3: when the home's `[product] repos` doesn't list the component (case ignored), or the home's config is missing or can't be parsed, `shipmill gh --product` exits 2 naming D-84 and the fix, mints no token over the set, caches nothing, and runs no gh
- S-065-4: the read token is refused with exit 2, never printed or cached, when GitHub's answer covers a repo outside the asked set, leaves one out, or grants any permission broader than `READ_PERMISSIONS` (a write, `admin`, or a key not asked)
- S-065-5: the read token is cached in `app-token-read-<owner>.json` with mode 0600, reused while it has at least 10 minutes left and the same App id, and never read from or written to `app-token.json` or `app-token-product-<owner>.json`; `shipmill app-token --git-credential` and the gh helper in a component still give the session's one-repo token
- S-065-6: in a component, `shipmill gh --product OWNER/NAME` exits 2 before gh runs when OWNER/NAME is the component itself or outside the set, when gh's `-R` names a repo outside the set or of another owner, and when the config has no `[agents] app_id`
- S-065-7: in a component, `shipmill gh --product` refuses with exit 2 naming D-84, before gh runs, `issue` other than list, view, and status; `pr` other than list, view, diff, checks, and status; `label` other than list; `release` other than list and view; `repo` other than view and list; `workflow run`; `run rerun`; `run cancel`; and `api` with `-X` or `--method` other than GET; `shipmill gh -R <another repo>` without `--product` and `shipmill app-token` for another repo still exit 2 before a token is minted
- S-065-8: `triage_state.py --home OWNER/NAME` in a component reads a hold on an item of another repo through `shipmill gh --product`, one call per owner, and reads it BLOCKED while open and UNBLOCKED once closed, with `:not_planned` for one closed as not planned, and no D-60 note for a read hold on a home item
- S-065-9: when that read fails (`shipmill gh` exits non-zero, or no node comes back), the hold reads unknown and counts as open, a hold on a home item carries D-60's note, and `triage_state.py` exits as it does today for a BLOCKED issue
- S-065-10: `triage_state.py` without `--home`, or with `--home` naming the checkout's own repo, runs no `shipmill gh` and gives the same states and notes as before this spec
- S-065-11: github-issue-resolve's SKILL.md says a component reads a spec or item of its product's other repos with `shipmill gh --product <its repo>`, writes nothing there, follows an item there only when that repo's D-16 trust rule trusts its author, and, when a reference it builds from can't be read, writes no substitute and asks through needs-decision naming the reference; triage-rubric.md's BLOCKED row says D-60's note marks only a hold the read token couldn't read; github-issue-triage's SKILL.md names D-84
- S-065-12: spec 038 marks S-038-10 dropped, naming S-065-6 and S-065-7

## Out of scope

- Writes across repos from a component: none, by D-84; filing and linking across repos stay the coordinator's (spec 038)
- `chains.py link` in a component: it still refuses another repo's reference (S-038-11), so a dependency on another repo's work is still a stand-in
- `chains.py show` and `upstream_state.py`: unchanged; their reads of other repos can take the read token in a later change
- A clone or fetch of another repo's code with git: the read token never reaches git; a session reads files through the contents API
- A `shipmill doctor` row for the read token: a failed read degrades to today's behaviour (the D-60 note, a refusal naming the fix), and the App already holds write on a connected product's repos; doctor can check it later if a failure shows up unseen
- The gate's preflight: a component's gate starts its sessions whether or not the read token can be minted
- The coordinator holding a component's part on a home item: D-60's filing order stays

## Decisions relied on

- D-14: a session's own token covers only its repo
- D-16: unattended sessions follow only trusted authors' items
- D-21: a session asks through the needs-decision protocol
- D-53: a component reads its home's config for the back-link
- D-54: shipmill writes to GitHub only as the App
- D-60: component parts are filed after their spec merges; an unread home hold asks nobody
- D-83: one product token per owner, covering the home of the same owner
- D-84: a component reads its product's other repos with a read-only token and writes only its own; it supersedes D-47 and keeps the coordinator's role and token as D-47 and D-83 set them

## Issues

- shipmill/shipmill#1085: S-065-1, S-065-2, S-065-3, S-065-4, S-065-5, S-065-6, S-065-7, S-065-12
- shipmill/shipmill#1087: S-065-8, S-065-9, S-065-10, S-065-11

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
