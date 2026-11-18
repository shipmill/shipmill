# S-069: One queue of what waits on the maintainer, across the fleet

status: approved
serves: G-4

## Problem

Every approval in the product layer is the maintainer's: answering a `needs-decision`
question, doing an item only a person can do, accepting or declining an opportunity,
accepting a goal plan, merging a spec pull request, and recording why an opportunity was
declined. These wait in every repo shipmill runs in, and nothing lists them together.
`fleet.py report` (spec 001) prints each repo's whole watch, agents' rows and report-only
rows mixed with the person's; `shipmill status` covers one repo; the forge's "assigned to
me" misses most of them. So the layer moves only as fast as the maintainer finds them
(shipmill/shipmill#337, gap 3 of `docs/design/product-layer.md`).

The maintainer runs shipmill in five repos and asked for a place where their own steps wait
across repos (2026-10-10). They accepted the opportunity on 2026-10-18 for G-4 and U-2.

## Behaviour

`skills/github-ship-watch/scripts/fleet.py queue --fleet <file> [--login LOGIN] [--bot-login LOGIN] [--json]`
reads the same fleet file as `fleet.py report`, with the same refusals (S-001-3, S-001-4),
and prints only what waits on a person, across every listed repo, oldest first. It keeps no
state: each row comes from a state script that already reads it, on the same fresh clone
`report` makes, and from the item's own timeline on GitHub for the time it started waiting.

### The rows

| Kind | What waits | Read from | Waiting since |
|---|---|---|---|
| `QUESTION` | an open issue or pull request labelled `needs-decision` whose newest question has no trusted reply | `skills/github-ship-watch/scripts/watch_state.py`'s NEEDS_DECISION rule | the newest needs-decision marker comment |
| `YOUR_ITEM` | a person's item (WITH_PERSON, spec 017) whose assignees include the reader | `skills/github-issue-triage/scripts/triage_state.py --json` | the `since` triage_state.py gives it |
| `OPPORTUNITY` | an opportunity waiting for accept or decline | `skills/product-intake/scripts/intake_state.py --json`, OPPORTUNITY_OPEN | the issue's opening |
| `PLAN` | a goal plan waiting for its answer | `intake_state.py --plans --json`, PLAN_OPEN | its newest revision |
| `SPEC_TO_MERGE` | an open, non-draft spec pull request (its body's first line `Spec for #N`) that no question holds and nothing lands by itself: no trusted answer taking every recommendation and no decided comment at `accepted-spec` by the gate's App, or one that edits `docs/product.md` or `docs/product/`, which only the maintainer merges (D-34) | the pull request's body, files, and comments, by `skills/github-pr-triage/scripts/pr_gate.py`'s readers | the pull request's ready-for-review time, else its opening |
| `TO_MERGE` | a pull request labelled `shipmill-ready` under `[autonomy] land = "propose"` | `watch_state.py`'s PRS_PARKED, TO_MERGE part | the newest event adding the label |
| `PROMOTION` | an open "Ready to promote" proposal issue of `shipmill operate` | `watch_state.py`'s PROMOTION_DUE, proposal part | the issue's opening |
| `NO_REASON` | an opportunity closed as not planned with no reason recorded | `intake_state.py --json`, NO_REASON | the close |

- A row whose item is in `QUESTION` is in no other row, so an item is listed once
- **The reader** is `--login`, else the login of the authenticated `gh` user (`gh api user`).
  Only `YOUR_ITEM` depends on it; an item assigned to a team and to no login of the reader is
  not theirs here
- **The table** prints one line per row: the repo, the kind, the item as `#N`, what is asked
  (a fixed phrase per kind, then the item's title), and how long it has waited (`3d 4h`,
  `5h`, `12m`). Rows are sorted by waiting since, oldest first, across all repos; a tie goes
  to the fleet file's order, then to the number
- **`--json`** prints one object: `login`, `items` (each with `repo`, `kind`, `number`, `url`,
  `asked`, `title`, `since` as ISO 8601 UTC, and `waited_minutes`) in the table's order, and
  `errors` (each with `repo`, `step`, and `error`)
- **Trust** is the watch's (D-16): each script runs with `--trusted-only` and `queue`'s
  `--bot-login` (the gate's App, `<slug>[bot]`), so an outsider's item is never on the queue;
  without `--bot-login`, an item the App opened is read as an outsider's
- **A repo whose read fails** (the clone, a state script, or a GitHub read) gets one
  REPO_ERROR line naming the step and the error's first line, printed after the queue; the
  other repos are still read
- **Exit codes**: 0 when the queue is empty, 1 when it lists a row, 2 after printing
  everything when a repo's read failed, and 2 on a malformed fleet file. It reads only and
  writes nothing on GitHub or on disk outside its temporary folder
- `skills/github-ship-watch/SKILL.md`'s Fleet section gains the queue: the command, its
  rows, and a `/schedule` routine prompt that runs it and reports the queue oldest first
- `fleet.py report` is unchanged

## Acceptance criteria

- S-069-1: `fleet.py queue --fleet F` lists a `needs-decision` item whose question has no trusted reply as a `QUESTION` row naming its repo and `#N`, and lists no row for an item whose question has a trusted reply
- S-069-2: a WITH_PERSON item assigned to the reader is a `YOUR_ITEM` row, and one assigned only to other logins or only to a team is not; the reader is `--login`, else `gh api user`'s login
- S-069-3: an OPPORTUNITY_OPEN opportunity is an `OPPORTUNITY` row, a PLAN_OPEN plan issue a `PLAN` row, and a NO_REASON opportunity a `NO_REASON` row; an ACCEPTED, HANDED_OFF, DECLINED, or PLAN_ACCEPTED one is no row
- S-069-4: an open spec pull request with no question waiting and no approval that lands it by itself is a `SPEC_TO_MERGE` row; one with a trusted answer taking every recommendation, or with the App's decided comment at `accepted-spec`, is no row, unless it edits `docs/product.md` or a file under `docs/product/`
- S-069-5: a pull request in PRS_PARKED's TO_MERGE is a `TO_MERGE` row, and an open "Ready to promote" proposal issue is a `PROMOTION` row
- S-069-6: an item in `QUESTION` appears in no other row
- S-069-7: rows from several repos print in one list ordered by their waiting-since time, oldest first, each with its repo, kind, `#N`, what is asked, and how long it has waited
- S-069-8: `--json` prints one object with `login`, `items` in the table's order, each holding `repo`, `kind`, `number`, `url`, `asked`, `title`, `since`, and `waited_minutes`, and `errors`
- S-069-9: an item opened by someone neither an OWNER, MEMBER, or COLLABORATOR nor the `--bot-login` is in no row
- S-069-10: a repo whose read fails gives one REPO_ERROR line with its step and the error's first line, the other repos' rows still print, and the run exits 2
- S-069-11: the run exits 0 when no repo has a row and 1 when any has; a fleet file `fleet.py report` refuses is refused by `queue` with the same exit 2 and message
- S-069-12: `queue` makes no write on GitHub: a run against a fake `gh` records only reads
- S-069-13: `skills/github-ship-watch/SKILL.md`'s Fleet section documents `fleet.py queue`, its rows, and a routine prompt that runs it

## Out of scope

- Doing or answering anything from the queue: each row's step stays where it is (the question, the item, the pull request); the queue only lists them
- Reminders and notifications: a desktop notification or a repeat mention of a waiting item is a later request (`docs/design/product-layer.md`, gap 1, says reminders come behind their own option)
- Team membership: an item assigned to a team the reader is in isn't resolved to the reader; `--login` names one person
- One repo's queue in `shipmill status`: `status` keeps reporting the whole pipeline of one repo (D-55)
- Who runs it: a product's coordinator (spec 038) or a routine may run `fleet.py queue`, and posting the queue anywhere is a later request
- Milestone proposals: gone with the roadmap plan (D-32); a goal plan's `PLAN` row stands where they were
- Items outside GitHub (another tracker, a calendar): the queue reads the forge only, as the fleet report does (D-6)

## Decisions relied on

- D-6
- D-16
- D-32
- D-34
- D-49
- D-55
- D-88

## Issues

- shipmill/shipmill#1244: S-069-1, S-069-5, S-069-6, S-069-7, S-069-8, S-069-9, S-069-10, S-069-11, S-069-12
- shipmill/shipmill#1245: S-069-2, S-069-3
- shipmill/shipmill#1246: S-069-4, S-069-13

## Verification
