# S-028: A plan from a goal

status: approved
serves: G-6

## Problem

The delivery loop reacts to what comes in: issues the maintainer or users file, and
opportunities the maintainer accepts. Spec 024 gives a repo a written direction,
`docs/product.md`, whose goals the agents read, and nothing turns a goal into work. A goal
such as `G-3` is cited by triage and served by whatever happens to arrive, and a goal no
request touches is read on every pass and never pursued. G-6 asks for the missing step:
agents propose the work that reaches a goal, and the maintainer approves it. Filed by the
maintainer as #388.

D-32 removed the roadmap plan because it ranked requests with no goals above it, and said
planning comes back with a goals layer. Spec 024 is that layer; this spec plans from goals,
not from demand. It keeps every decision where it is today (N-3): the maintainer accepts or
declines a plan, each feature's spec is still approved by its own merge, and a milestone is
still the maintainer's list.

The maintainer settled the open choices on this spec's pull request (#430): a plan is
answered by a reply comment read by author association; an accepted plan creates the
milestone it names (D-38); a request on GitHub is a trusted `goal-plan` issue answered by a
separate plan issue; a declined plan is not proposed again by the `no-work` trigger; and
automatic plans wait for room under `[agents] wip`.

## Behaviour

### Where it lives

Planning is a step of product intake, which already proposes and never acts (D-10):

- `skills/product-intake/SKILL.md`: a new workflow section, Plan a goal, and the report
  lines for plans
- `skills/product-intake/references/plan.md`: the plan issue's template and the comments
  around it
- `skills/product-intake/scripts/plans.py`: the plan body's grammar (`check`) and its items
  (`items`), standard library only, Python 3.10+
- `skills/product-intake/scripts/intake_state.py`: the plan rows (below), and
  `goal-plan` added to `SKIP_LABELS`, so a plan issue is never read as feedback
- `skills/github-ship-watch/scripts/watch_state.py` and `skills/github-ship-watch/SKILL.md`:
  a PLANS row from those rows
- `src/shipmill/gate.py`: an action in PLANS starts a session, as ISSUES does
- `skills/github-issue-triage/references/spec-gate.md` (Where features come from): a feature
  item of an accepted plan

`[autonomy] intake` sets how far it goes, as for opportunities: under `observe` a pass
reports a due plan with its proposed text and writes nothing; under `propose` (the default)
it opens the plan issue, and once the maintainer accepts, files the plan's items. There is
still no `act`.

### Triggers

`intake_state.py <owner/repo> --plans` reads the goals with `shipmill product show
--section goals --json` and reports PLAN_DUE for a goal, with its trigger in the note, when
the goal has no open plan issue and one of these holds:

- **`no-work`:** nothing open serves the goal. Open work serves `G-n` when it is a spec in
  `docs/specs/` at the default branch's head with `status: draft` or `approved` whose
  `serves:` line names `G-n`; an open issue whose newest triage comment names `Serves: G-n`
  (S-024-8); an open pull request whose `## Plan` names `G-n` in `Serves:` (S-024-9); an
  open opportunity whose body names `G-n`; or an open plan item for `G-n` (below). Never raised
  again for a goal whose newest plan was declined, so a declined plan isn't argued twice
  (as D-10 keeps a declined opportunity); only a `stalled` report or a request proposes
  another. Not raised either for a goal spec 027 (#389) reports met once that spec is built
- **`stalled`:** spec 027 (#389) reports the goal stalled. The script reads that report
  through whatever command or row spec 027 defines; until spec 027 is built this trigger
  never fires, and nothing else in this spec depends on it
- **`requested`:** the maintainer asked. In a session, the user names the goal ("plan G-3").
  On GitHub, an open issue labelled `goal-plan`, opened by an OWNER, MEMBER, or COLLABORATOR,
  without the plan marker, whose title names exactly one goal id the direction lists; one
  opened by anyone else is never a request (D-16)

The `no-work` and `stalled` triggers wait while the work in progress is at the limit:
with `[agents] wip = N` (`src/shipmill/agents.py`), PLAN_DUE for them reads only when
`triage_state.py --wip N` reports room left, otherwise the goal is listed in the report as
`waits for room`, so automatic proposals don't pile up faster than the loop works them.
A `requested` plan never waits. A pass proposes at most one plan per goal
at a time, so an open plan is the goal's only plan.

### The plan issue

The session reads the goal, its measure from spec 027 (#389) when the goal has one, the
code, the specs, and the open issues and opportunities, and proposes the work that reaches
the goal. It opens one issue as the App (D-14), labelled `goal-plan`, titled `Plan for
G-n: <the goal's text>`, its body written from `skills/product-intake/references/plan.md`:

    <!-- shipmill:plan goal=G-3 rev=1 -->
    ## Goal

    G-3: <the goal's text, as `shipmill product show` prints it>

    Trigger: no-work | stalled | requested in #N
    Measure: <the goal's measure from spec 027, or "none yet">

    ## Work

    - W-1 existing: #212
    - W-2 feature: <the outcome a user gets>
    - W-3 fix: <what is wrong today> (after W-2)

    ## Order

    <why this order, and what reaching the goal looks like once the work is done>

    ## Milestone

    none

    ## Notes

    <what was considered and left out, the D-n rules it runs into; optional>

The grammar, which `plans.py check FILE` enforces (exit 0, or 2 naming the line and the
rule), and which `plans.py items` and `intake_state.py` read:

- The first line is the marker `<!-- shipmill:plan goal=G-<n> rev=<k> -->`, `G-<n>` an id
  `shipmill product ids` lists and `<k>` a revision from 1
- Then the level-two headings Goal, Work, Order, Milestone, and Notes, in this order; Notes
  may be absent, any other heading is an error
- Work holds at least one item and only list items of the form `- W-<n> <kind>: <text>`,
  ids numbered from 1 and unique, `<kind>` one of `feature`, `fix`, or `existing`. An
  `existing` item's text is one issue reference, `#N` or `owner/repo#N`, of an open issue.
  Any item may end with `(after W-<k>[, W-<j>])`, naming earlier items it depends on
- Milestone holds one line: `none`, or a milestone title

Items are listed in the order the work should start: the session files them in that order,
so triage's oldest-first dispatch under `[agents] wip` follows it. An `existing` item is
work that already serves the goal, so the plan never proposes it a second time. Intake then
comments `Triage: **plan**. ...` on the plan issue, so `triage_state.py` reads it TRIAGED,
not NEW. The plan is always its own issue, even for a request, so its body and grammar are
the App's and the maintainer's request text is never overwritten: for a `requested` plan
the session comments on the request issue linking the plan and closes the request as
completed.

### The maintainer's answer

Only the maintainer decides a plan (D-10, N-3). The answer is a comment on the plan issue,
read as `needs-decision.md` reads a reply (D-16): a comment counts only when its
`author_association` is OWNER, MEMBER, or COLLABORATOR and its author is not the
`--bot-login`, and only when it is newer than the plan's newest revision (the opening body,
or the App's newest comment whose first line is `<!-- shipmill:plan-revised rev=<k> -->`).
Every other comment, every reaction, and every label is never read as an answer: the
`planned` label opportunities use has no channel for an edit, and a reply carries the
maintainer's words and author association in one place a headless gate can read. The newest such
comment's first line decides:

| First line | Answer | The session |
|---|---|---|
| `accept` (any case, an optional final period) | accept | Files the items (below) |
| starts with `decline` | decline | Closes the plan as not planned; the rest of the comment is the reason |
| anything else | edit | Rewrites the body as asked, raising `rev`, and posts the `plan-revised` comment; the plan waits again |

The maintainer may also edit the body by hand before answering: an accept applies to the
body as it is when the accept was posted, so an accept older than the body's last edit is
stale and the plan reads PLAN_OPEN with the note `edited after accept`. A body
`plans.py check` refuses reads PLAN_MALFORMED: the session fixes the App's own body, or
asks through the needs-decision protocol when the maintainer's edit broke it. The session
never accepts, declines, or edits a plan on its own judgment, and never changes
`docs/product.md` because of one.

### Accepting files the work

On an accept, the session files each `feature` and `fix` item, in order, as an issue
through `shipmill gh` (D-14). Each body starts with the marker
`<!-- shipmill:plan-item #<plan> W-<n> -->`, states the item, names `Serves: G-n`, and links
the plan. Then:

- Each filed issue becomes a sub-issue of the plan (`chains.py link <plan> --child <item>`,
  spec 017), so the plan reads BLOCKED with `children K/N closed` until its work closes, and
  triage closes it like any parent
- Each `(after W-k)` becomes a `Depends on` line and GitHub's relation
  (`chains.py link <item> --blocked-by <W-k's issue>`); an `existing` item is named by its
  own number
- A `feature` item goes through the spec gate like any feature: triage writes its spec,
  and the spec's merge with `status: approved` approves it. The plan's accept chose the
  work, not its design, so no spec is approved by the plan. `spec-gate.md` adds the source:
  an issue the App filed with the plan-item marker, under a plan `intake_state.py` reads
  PLAN_ACCEPTED or PLAN_FILED
- A `fix` item goes to triage as any issue does, which gives it its own verdict
- An `existing` item is left as it is, except for the milestone

Filing starts no work: the session dispatches no implementer and writes no spec. Triage
takes the new issues up on its next pass, within `[agents] wip`.

### The milestone

A plan whose Milestone line names a title, once accepted, completes that milestone: the
session puts every filed item and every `existing` item of this repository in it, creating
the milestone when it doesn't exist (D-38). The maintainer chose it by accepting a plan that
names it, so D-32's rule that a milestone is the maintainer's list holds, as D-38 refines it. Spec 022 then treats the
milestone as done when the specs its issues hold are built, and `specs.py split
--milestone` carries it to each feature's build issues. A plan with `none` touches no
milestone.

### The plan rows

`intake_state.py --plans` prints one row per goal and per plan issue, as text or with
`--json` one JSON line each, after the opportunity rows:

| Row | Means | An action (exit 1) |
|---|---|---|
| PLAN_DUE | A trigger holds for the goal and it has no open plan; the note is the trigger | yes |
| PLAN_OPEN | An open plan without an answer newer than its newest revision | no |
| PLAN_ANSWERED | An open plan whose newest trusted answer is an edit or a decline the session hasn't acted on; the note is the answer | yes |
| PLAN_ACCEPTED | Accepted, and a `feature` or `fix` item has no issue carrying its marker, or a named milestone lacks an item | yes |
| PLAN_FILED | Accepted, every item filed and in the milestone | no |
| PLAN_MALFORMED | An open plan `plans.py check` refuses; the note names the line | yes |
| PLAN_DECLINED | Closed as not planned; the note is the reason | no |

`watch_state.py` runs `intake_state.py --plans --json` and lists the action rows in one
PLANS row; under "watch" the session runs product intake on them, and `shipmill gate`
starts a session for PLANS as it does for ISSUES. With `--trusted-only`, a plan opened by
anyone but the `--bot-login` is UNTRUSTED and starts no session (D-16).

## Acceptance criteria

- S-028-1: `intake_state.py --plans` reports PLAN_DUE with the note `no-work` for a goal served by no draft or approved spec, no open issue whose newest triage comment names it, no open pull request whose plan names it, no open opportunity naming it, and no open plan item, and reports nothing for a goal one of those serves
- S-028-2: No `no-work` PLAN_DUE is reported for a goal whose newest plan was declined
- S-028-3: An open issue labelled `goal-plan` without the plan marker, whose title names one listed goal id, reads PLAN_DUE with the note `requested in #N` when its author is an OWNER, MEMBER, or COLLABORATOR, and as no request when its author is anyone else
- S-028-4: With `--wip N`, a `no-work` or `stalled` PLAN_DUE is reported only while fewer than N issues are in progress, and a `requested` one regardless
- S-028-5: A goal with an open plan issue never reads PLAN_DUE
- S-028-6: `plans.py check` exits 0 on a well-formed plan body and 2 naming the line and rule for each of: a missing or malformed first-line marker, a goal id the direction doesn't list, a missing, extra, or out-of-order heading, a Work item not of the form `- W-<n> <feature|fix|existing>: <text>`, a duplicate item id, an `existing` item that isn't one issue reference, an `(after W-k)` naming an item not before it, and a Milestone section that isn't one line
- S-028-7: `plans.py items <owner/repo>#N --json` lists each item with its id, kind, text, the items it comes after, and the issue that carries its plan-item marker, or none
- S-028-8: A plan reads PLAN_OPEN while no comment newer than its newest revision comes from an OWNER, MEMBER, or COLLABORATOR other than the `--bot-login`; a comment by any other author, or a reaction, changes nothing
- S-028-9: A trusted answer whose first line is `accept` (any case, an optional final period) reads PLAN_ACCEPTED, one starting with `decline` reads PLAN_ANSWERED with the note `decline`, and any other reads PLAN_ANSWERED with the note `edit`; a `plan-revised` comment by the `--bot-login` with a higher `rev` makes an earlier answer stale
- S-028-10: An accept older than the body's last edit reads PLAN_OPEN with the note `edited after accept`
- S-028-11: An accepted plan reads PLAN_ACCEPTED while a `feature` or `fix` item has no issue whose body's first line is its plan-item marker, or while its Milestone names a title and an item of this repository isn't in that milestone, and PLAN_FILED once neither holds
- S-028-12: An open plan whose body `plans.py check` refuses reads PLAN_MALFORMED naming the line, and a plan closed as not planned reads PLAN_DECLINED with the reason
- S-028-13: `watch_state.py` lists PLAN_DUE, PLAN_ANSWERED, PLAN_ACCEPTED, and PLAN_MALFORMED in a PLANS row as an action, `shipmill gate` starts a session for it, and with `--trusted-only` a plan issue not opened by the `--bot-login` starts none
- S-028-14: `intake_state.py` never reads an issue labelled `goal-plan` as feedback, and `triage_state.py` reads a plan issue with intake's `Triage: **plan**` comment as TRIAGED
- S-028-15: product-intake's skill files each `feature` and `fix` item of an accepted plan in Work order with the plan-item marker and `Serves: G-n`, links it as a sub-issue of the plan, turns each `(after W-k)` into a `Depends on` line and GitHub's relation, and dispatches no implementer and writes no spec
- S-028-16: The spec gate's Where features come from lists a feature item of an accepted plan as chosen work, and still requires its own spec to merge with `status: approved` before its build
- S-028-17: product-intake's skill never accepts, declines, or edits a plan without a trusted answer, never adds a goal or edits `docs/product.md` for a plan, and under `[autonomy] intake = "observe"` reports a due plan's text without opening an issue

## Out of scope

- Measuring a goal and deciding it is met or stalled: spec 027 (#389) and the per-goal
  retro (#387); this spec reads their report and adds no measure of its own
- Proposing changes to the direction (a new goal, a retired one): the maintainer's (N-3);
  G-7's proposals belong to spec 027's line of work
- Designing a feature inside the plan: each feature's spec is written and approved through
  the spec gate, after the accept
- Plans across repositories: an `existing` item may name another repository's issue, but
  filed items and the milestone stay in this one; a cross-repo goal is a chain (spec 017)
- Dates, estimates, or capacity beyond `[agents] wip`: the maintainer's (D-32)
- Re-planning on its own while a plan is open: an open plan changes only on the
  maintainer's answer

## Decisions relied on

- D-5: a feature item links its spec, it doesn't hold it
- D-10: only the maintainer accepts or declines; intake proposes
- D-14: every write is the App's
- D-16: only a trusted author's comment is an answer or a request
- D-29: a first-line marker counts only from the App or a trusted author
- D-32: a milestone is the maintainer's list, and the WIP limit is `[agents] wip`
- D-34: the work serves the product's written direction
- D-38: an accepted goal plan may create the milestone it names

## Issues

## Verification
