# S-106: States of a goal, a plan, and a project, with a plan's answer date and a goal on every accepted opportunity

status: built
serves: G-6

## Problem

The maintainer decided lifecycles for a goal, a plan, and a project on 2026-11-26, rule by
rule (shipmill/shipmill#1688). Decided is not running: until the gate carries each state, a
person reads it from prose, and `shipmill status --item`, `queue`, and the gate's sessions
cannot say what an item waits on or move it.

Parts are built or specified already: a plan's partial accept (spec 096), a finished plan's
outcome (spec 097), a held plan with its wake condition (spec 098), a limit on the outcomes
waiting on the maintainer (spec 101), an accepted plan's `existing` items linked as its
sub-issues (shipmill/shipmill#1706), and the direction's two kinds, a goal with its check and
horizon and a standing measure with its threshold and source (spec 105). What is left:

- **A goal** has no state. Nothing records that it is met or dropped, and a goal past its
  horizon reaches nobody
- **A plan** waits for its answer for as long as it takes, and nothing stops new work while
  a decision is overdue. A second plan for the same goal is never proposed while one is
  open, so a request or an accepted opportunity for that goal waits behind it
- **A project**, the unit the maintainer orders and limits (one head issue, at most one
  spec, a `Check:` issue that closes it), is not a thing shipmill knows. Nothing limits
  how many run at once, nothing holds the rest, a project that stopped moving stays silent,
  and stopping one is done by hand
- **An accepted opportunity** goes straight to the spec gate without naming the goal it
  serves, so work enters with no parent

## Behaviour

### Where it lives

- `src/shipmill/product.py`: a goal's `Met:` and `Dropped:` sentences, and the `product met`
  and `product drop` commands
- `skills/product-intake/scripts/intake_state.py`: the goal rows (`--goals`), the plan's
  answer date and replacement (`--plans`), the project rows (`--projects`), and an accepted
  opportunity's goal
- `skills/product-intake/SKILL.md`, `skills/product-intake/references/plan.md`,
  `skills/product-intake/references/opportunity.md`: each new state's step and comment
- `skills/github-issue-triage/scripts/triage_state.py` and
  `skills/github-issue-triage/scripts/specs.py`: a held project is not split; a spec's
  `stopped` status
- `skills/github-ship-watch/scripts/watch_state.py`, `skills/github-ship-watch/scripts/fleet.py`,
  `src/shipmill/gate.py`: the new actions start sessions, and the overdue items show in the
  queue
- `src/shipmill/agents.py`: `[agents] projects`
- `src/shipmill/item_status.py`, `src/shipmill/status.py`, `src/shipmill/queue.py`:
  `shipmill status --item` on a goal, a plan, and a project's head issue
- `docs/flow.md`: the lifecycles as shipmill runs them

### Goal

A goal's state is read from the direction (spec 105) and the repository's issues. Only goals
of kind goal have states; a standing measure and a goal of kind none read none, as today.

| State | Read when | Holder | Moved by |
|---|---|---|---|
| proposed | an open issue labelled `goal-proposal`, opened by an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` (not yet in the direction) | maintainer | writing it into the direction and closing the issue, or closing it as not planned |
| written | in the direction with no `Met:` or `Dropped:` sentence and not planned | agent (a plan is due), or maintainer (a plan waits for the answer) | an accepted plan |
| planned | an accepted plan of the goal is open (PLAN_ACCEPTED or PLAN_FILED), or a project head of one of its plans is open | the projects | its last project closing, when its check is read again |
| met | its text ends `. Met: <YYYY-MM-DD>` | none | nothing |
| dropped | its text ends `. Dropped: <YYYY-MM-DD>: <reason>` | none | nothing |

- **Met and dropped are the maintainer's record** in the direction (D-34): spec 105's goal
  form may end with one more sentence, `. Met: <date>` or `. Dropped: <date>: <reason>`,
  after its horizon. `product check` refuses either on a measure or a goal of kind none, a
  malformed date, an empty reason, or both at once. `product show --json` adds `state`
  (`"met"`, `"dropped"`, or null) and `ended` (the date) to every goal's record, and
  `shipmill product met G-n [--on DATE]` and `shipmill product drop G-n --reason TEXT` write
  the sentence in the working tree (the date defaults to today in UTC). A met or dropped goal
  keeps its id, so references to it still resolve; it reads no plan trigger, and `specs.py
  check` refuses a `draft` or `approved` spec whose `serves:` names it
- **A goal past its horizon** reads GOAL_OVERDUE, an action, while it is written or planned
  and its horizon has passed (`past` from `product show --json`, or for a release horizon a
  stable tag of that version exists on the forge), until an issue whose first line is
  `<!-- shipmill:goal-overdue G-<n> by=<horizon> -->`, by the `--bot-login`, exists for that
  goal and horizon. Its session opens that issue, labelled `goal-review`, with the
  needs-decision protocol's question to the maintainer: extend (a new horizon), rewrite (a new
  check), or drop (with a reason). On the answer the session opens a pull request with the
  edit (`product goal`, `product drop`), which only the maintainer merges (D-34), and closes
  the issue when it merges. A new horizon makes a new question possible when it passes
- **When a planned goal's last project closes**, its check is read again with the plan's
  outcome (spec 097): the outcome comment gains a `Goal check:` line saying the goal's check
  holds, fails, or can't be run by an agent, with what showed it, read the way spec 042 reads
  a parent's check (it only reads, never writes to production). When it holds, the session
  opens a pull request adding `. Met: <date>` to the goal and, where the goal must stay true,
  a standing measure in its place, both for the maintainer to merge or change (D-34); the
  goal reads planned until then. When it fails or can't be run, the goal reads written, and
  its next plan follows the outcome (spec 097)

`intake_state.py --goals` prints one row per goal of kind goal: `GOAL_PROPOSED`,
`GOAL_WRITTEN`, `GOAL_PLANNED`, `GOAL_MET`, `GOAL_DROPPED`, and `GOAL_OVERDUE`, with `--json`
carrying `state`, `holder`, and `by`.

### Plan

- **An answer date.** A plan's answer is due seven days after its newest revision's
  marker comment or body was written, unless a trusted reply (an OWNER, MEMBER, or COLLABORATOR
  other than the `--bot-login`, or the `--bot-login`'s relay naming a maintainer, D-68) whose
  first line is `answer by YYYY-MM-DD` sets another; the newest such reply counts, and it is no
  answer to the plan. A PLAN_OPEN plan's note gains `answer by <date>`, and with `--json` its
  row carries `answer_by`. Past that date (the date has ended in UTC) it reads PLAN_OVERDUE
  in its place: no action for an agent (exit 0 when it is the only row), the maintainer's
  overdue decision. A held plan (spec 098) has no answer date until it reads PLAN_OPEN again,
  when the seven days start from its re-check
- **An overdue plan stops new starts** in its whole product: while any plan of any repository
  of the product (the repos the limit below counts) reads PLAN_OVERDUE, no goal of
  any of them reads a `no-work` PLAN_DUE (it reads PLAN_WAITS with the note
  `plan <owner/repo>#P overdue`), and no held project of any of them starts (below). Work already started goes on: build issues of active
  projects are dispatched as today, and a plan the maintainer requested (`requested in #N`)
  is still proposed
- **One open plan per goal.** A goal with an open plan now reads PLAN_DUE for a
  `requested in #N` trigger and for an accepted opportunity (below), and the new plan
  replaces the open one: once a newer plan issue of the same goal is open, the older open
  one reads PLAN_REPLACED, an action, its note `by #<new>`, and its session closes it as not
  planned with a comment whose first line is `<!-- shipmill:plan-replaced #<new> -->`. The
  new plan keeps the open plan's items it still proposes and names under Notes the ones it
  drops. A replaced plan counts as neither declined nor answered, so its goal's `no-work`
  trigger reads as for any closed plan
- **An accept at the limit becomes a hold of its projects.** An accepted plan always files
  its project heads (below). With `[agents] projects` set, the heads beyond the room are held:
  only the head issue exists, and each starts when a slot frees. The accept stands, so the
  maintainer is not asked again

### Project

A project is a head issue labelled `project`, opened or labelled by an OWNER, MEMBER, or
COLLABORATOR or the `--bot-login`. Each `feature` and `fix` item an accepted plan files after
this spec is labelled `project`, so its carrier issue is the head, and the maintainer can
make any issue a head by labelling it. Its check issue is the head's sub-issue whose title
starts `Check: ` and whose body has a `## Check` section (spec 042). Its parts are the head's
other sub-issues and the check issue's sub-issues, two levels deep. Issues not labelled
`project` read as today, so plan items filed before this spec are not projects.

| State | Read when | Holder |
|---|---|---|
| held | the head is open and has no check issue, or is labelled `held` | its start (a free slot, its turn, no overdue plan) |
| active | the head is open, its check issue open, and a part open or none filed yet | agents and the maintainer's steps |
| in focus | active and labelled `focus` | the maintainer's steps first |
| closing | the check issue is open and every part is closed | someone other than the builder, who runs the check |
| closed | the head is closed as completed | none |
| stopped | the head is closed as not planned with a trusted stop record (below) | none |

`intake_state.py --projects` prints one row per open head and per head closed within 30 days:
PROJECT_HELD, PROJECT_ACTIVE, PROJECT_FOCUS, PROJECT_CLOSING, PROJECT_CLOSED, PROJECT_STOPPED,
and the actions below, with `--json` carrying `state`, `holder`, `check` (the check issue or
null), and `parts` (open and closed counts). A closing row's note lists the unchecked
`- [ ]` lines of the check issue's `## Cleanup` section, or `no cleanup listed`.

- **The limit is the product's.** `.github/shipmill.toml` gains `[agents] projects = N`, an
  integer from 1 up to `[agents] wip`'s ceiling, read by `AgentsConfig` as
  `projects: int | None` and refused as `[agents] outcomes` is (spec 101) when malformed. A
  product's limit is set once, in its home: a config with `[product] home` (a component)
  that sets `[agents] projects` is refused, naming the home whose config holds the product's
  limit (`src/shipmill/policy.py`). The product is read as spec 101 reads it: the repo alone
  without a `[product]` table, the home and every repo its `[product] repos` lists in a home,
  and the same set in a component, whose limit comes from the home's config on its default
  branch. The active count is the product's heads reading active or in focus, across all
  those repos; held and closing ones count nothing. Other repos are read through
  `shipmill gh --product <repo> api graphql`, one call per owner, with the coordinator's token
  in the home (D-83) and the read token in a component (D-84); a read that fails exits 2
  naming the repo and never counts it as empty. The room is N minus the count, never below
  0. Without the key there is no limit. `intake_state.py --projects` prints
  `projects active: K of N (product <owner/home>)` as its second line and, with `--json`,
  a `projects` key `{"limit": N, "active": K, "room": R}` on its first line
- **Starting a held project.** While the room is above 0 and no plan reads PLAN_OVERDUE, the
  held heads of the product read PROJECT_START_DUE, an action, as many as the room, oldest
  accepted plan first (by the time of its accept, across the product's repos) and in its
  Work order, then heads with no plan by the time they were labelled. Each repo's pass starts
  only its own heads among those. Its session files the check
  issue first, as the head's sub-issue (`chains.py link --child`), titled `Check: <what will
  be true>` with a `## Check` a person other than the builder can run, and for a head
  labelled `held` removes the label instead when the check issue exists already. Only then
  does triage split or dispatch it
- **A started project's check waits on its work.** Once its check issue exists, the head is
  built like any issue or split into parts, and never held on its own check issue as on a
  child. A head with no parts is built by pull requests saying `Part of #<head>`, so it stays
  open. The project's work is done once every part is closed, no pull request linked to the
  head is open, and, with no part filed, one of them merged. Until then `triage_state.py`
  reads the check issue BLOCKED `project #<head>: check waits on its work`; after it, the
  check issue reads by its `## Check` as a parent's does (spec 042: VERIFY_DUE, CHECK_FAILED,
  or WITH_PERSON) once its own holds closed, and the head reads BLOCKED `project #<head>:
  check #<check> due`. Its session runs the check, then closes the check issue and the head.
  Neither the check issue nor any sub-issue titled `Check: ` with a `## Check` section reads
  as new work to triage or as feedback to group
- **A held project is not split into issues.** `triage_state.py` reads a head in held, and
  each open sub-issue under it, as BLOCKED with the note `project #<head> held`, so no spec,
  build issue, or implementer starts for it
- **A project with no change for two weeks.** A head reading active, in focus, or closing
  whose tree (the head, its check issue, its parts, and the pull requests that link them) has
  no update for 14 days reads PROJECT_IDLE, an action, until an idle question is on it. Its
  session asks the maintainer on the head with the needs-decision protocol, whose question's
  first option set is continue, hold, or stop. `continue` needs nothing (the answer is the
  change), `hold` has the session label the head `held`, and `stop` is a stop
- **A stop.** A trusted reply on the head whose first line is `stop: <reason>`, or `stop` as
  the answer to the idle question with the reason on its next line, reads PROJECT_STOP_DUE,
  an action. Its session closes each open part and the check issue as not planned with the
  comment `Project stopped: <reason>`, closes the parts' open pull requests unmerged, keeps
  merged work unless the check issue's body has a `Revert on stop: #<pr>[, #<pr>]` line, for
  which it opens each revert with `shipmill revert open` (spec 079), and opens a pull request
  setting the status of the project's approved spec (the one its head's body links) to
  `stopped`. Then it closes the head as not planned with a comment whose first line is
  `<!-- shipmill:project-stopped -->` and whose body gives the reason. That comment, from the
  `--bot-login`, is the stop record, and product intake reads a stopped project as it reads a
  declined opportunity, so a new request for the same outcome is matched against it
- **A spec's `stopped` status.** `specs.py check` accepts `status: stopped`, needs no
  Verification for it, and `split` refuses a stopped spec

### Opportunity

An accepted opportunity names the goal it serves: the goal in a trusted accept whose first
line is `accept G-<n>`, or, for a plain accept, the one goal the opportunity's `Serves:` line
names. `intake_state.py` reads an accepted opportunity:

- **ACCEPTED_INTO** `G-<n>`, when the goal is written or planned: the goal reads PLAN_DUE with
  the trigger `opportunity #<n> accepted`, even while it has an open plan, and the new plan
  proposes the opportunity as a `feature` item naming it. On the plan's accept, intake files no
  new issue for that item: it labels the opportunity `project` and links it as the plan's
  sub-issue, so the opportunity is the project's head
- **GOAL_PROPOSAL_DUE**, an action, when the accept is `accept new goal`: its session opens an
  issue labelled `goal-proposal` with the outcome, a proposed check and horizon, and the
  opportunity as its sub-issue. The goal reads proposed; once the maintainer writes it into the
  direction and closes the proposal, the opportunity reads ACCEPTED_INTO the new goal
- **NEEDS_GOAL**, when it names no goal, or a goal that is not written or planned (a measure,
  a goal of kind none, a met or dropped goal, an id the direction lacks): it files nothing.
  Its session asks once, with a comment naming the two answers (`accept G-<n>`,
  `accept new goal`), and it waits on the maintainer in `fleet.py queue`

An opportunity accepted before this spec's build keeps today's path to the spec gate
(ACCEPTED, then HANDED_OFF), so no accepted work is stranded.

### `shipmill status --item`

`shipmill status --item` takes a goal id (`--item G-3`) as well as an issue or pull request
number, and for a goal, a plan issue, and a project's head issue names the state above, its
holder, and what moves it, as one condition of spec 094's records (`state`, `who`, `clear`).
An overdue plan's condition says `answer due <date>, overdue`; a held project's names what it
waits for (`a free slot: 2 of 2 active`, `plan #P overdue`, or `held by the maintainer`).

### Report and queue

`watch_state.py` lists GOAL_OVERDUE, PLAN_REPLACED, PROJECT_START_DUE, PROJECT_IDLE,
PROJECT_STOP_DUE, GOAL_PROPOSAL_DUE, and NEEDS_GOAL's question as actions of the PLANS row, so
`shipmill gate` starts a session for each. `fleet.py queue` shows a PLAN_OVERDUE plan as an
overdue `PLAN` row and a NEEDS_GOAL opportunity as an `OPPORTUNITY` row; the goal-review and
idle questions reach it as any needs-decision item does.

## Acceptance criteria

- S-106-1: `shipmill product check` accepts a goal of kind goal ending `. Met: 2026-12-20` or `. Dropped: 2026-12-01: <reason>`, and exits 1 naming the goal for either on a measure or a goal of kind none, a malformed date, an empty reason, or both sentences
- S-106-2: `shipmill product show --json` gives every goal `state` (`"met"`, `"dropped"`, or null) and `ended`, and `product met G-n [--on DATE]` and `product drop G-n --reason TEXT` write the sentence in the working tree, refusing a measure and a goal already met or dropped
- S-106-3: `specs.py check` refuses a `draft` or `approved` spec whose `serves:` names a met or dropped goal, and `intake_state.py --plans` reads no trigger for such a goal
- S-106-4: `intake_state.py --goals` reads a `goal-proposal` issue by a trusted author or the `--bot-login` as GOAL_PROPOSED, a goal with no accepted open plan and no open head as GOAL_WRITTEN, one with an accepted open plan or an open head of its plans as GOAL_PLANNED, and the met and dropped goals as GOAL_MET and GOAL_DROPPED, each with `state`, `holder`, and `by` in `--json`; a measure and a goal of kind none have no row
- S-106-5: a written or planned goal whose date horizon has passed, or whose release horizon has a stable tag of that version, reads GOAL_OVERDUE, an action, until the `--bot-login` opened an issue whose first line is `<!-- shipmill:goal-overdue G-<n> by=<horizon> -->`; the same marker by anyone else counts for nothing, and a goal with a new horizon reads GOAL_OVERDUE again once that one passes
- S-106-6: product-intake's SKILL.md gives GOAL_OVERDUE's step (the `goal-review` issue, the question with extend, rewrite, and drop, and the direction edit as a pull request only the maintainer merges) and, on PLAN_DONE, the outcome comment's `Goal check:` line and the pull request adding `. Met: <date>` and any standing measure when the check holds
- S-106-7: a PLAN_OPEN plan's note ends `answer by <date>`, seven days after its newest revision, and with `--json` its row carries `answer_by`; a trusted `answer by YYYY-MM-DD` reply sets the date, the newest one counts, and it is read as no answer to the plan; an untrusted one changes nothing
- S-106-8: a plan whose answer date has ended in UTC reads PLAN_OVERDUE, which adds nothing to the exit code, and a held plan reads no answer date until it reads PLAN_OPEN again, its seven days counted from its re-check
- S-106-9: while a plan of any repo of the product reads PLAN_OVERDUE, every `no-work` PLAN_DUE of every repo of the product reads PLAN_WAITS with the note `plan <owner/repo>#P overdue`, no head of the product reads PROJECT_START_DUE, and a `requested in #N` PLAN_DUE still reads PLAN_DUE
- S-106-10: a goal with an open plan reads PLAN_DUE for a `requested in #N` trigger and for an accepted opportunity; once a newer plan of the same goal is open the older reads PLAN_REPLACED `by #<new>`, an action, until it is closed, and a replaced plan does not stop the goal's `no-work` trigger as a declined one does
- S-106-11: an accepted plan's filed `feature` and `fix` items carry the `project` label, and plan items filed before this spec and issues without the label read no project row
- S-106-12: `intake_state.py --projects` reads an open head with no check issue, or labelled `held`, as PROJECT_HELD; with an open `Check: ` sub-issue holding `## Check` and an open or no part as PROJECT_ACTIVE (PROJECT_FOCUS when labelled `focus`); with every part closed at both levels and the check issue open as PROJECT_CLOSING, its note the unchecked `## Cleanup` lines or `no cleanup listed`; a head closed as completed as PROJECT_CLOSED; and one closed as not planned with the `--bot-login`'s stop record as PROJECT_STOPPED
- S-106-13: a config with `[agents] projects` set to 0, a negative number, a number above `[agents] wip`'s ceiling, or a non-integer is refused naming the key; with 2 it loads as `projects == 2`, and without it is None
- S-106-14: with `[agents] projects = 2`, one active and one in-focus head (in any repos of the product), and held and closing heads, no head reads PROJECT_START_DUE; with one slot free, the held head of the oldest accepted plan, first in its Work order, reads PROJECT_START_DUE, an action, and no other does; without the key every held head reads PROJECT_START_DUE
- S-106-15: product-intake's SKILL.md gives PROJECT_START_DUE's step: file the check issue as the head's sub-issue before any part, titled `Check: ` with a `## Check` someone other than the builder runs, or remove the `held` label when the check issue exists already
- S-106-16: `triage_state.py` reads a held head and each of its open sub-issues as BLOCKED with the note `project #<head> held`, and a head in any other state as it reads any parent, its check issue aside (S-106-29)
- S-106-17: a head in active, in focus, or closing whose tree has had no update for 14 days reads PROJECT_IDLE, an action, until a needs-decision question by the `--bot-login` is on the head newer than the tree's last update; a tree updated 13 days ago reads its state
- S-106-18: a trusted reply on a head whose first line is `stop: <reason>`, or the answer `stop` to the idle question, reads PROJECT_STOP_DUE, an action; the same reply by an untrusted author changes nothing
- S-106-19: product-intake's SKILL.md gives PROJECT_STOP_DUE's step: close the open parts and the check issue as not planned with `Project stopped: <reason>`, close their open pull requests unmerged, open a revert with `shipmill revert open` only for each pull request a `Revert on stop:` line of the check issue names, open the pull request setting the project's spec to `stopped`, and close the head as not planned with the `<!-- shipmill:project-stopped -->` record
- S-106-20: `specs.py check` accepts `status: stopped` without a Verification section, and `specs.py split` refuses a stopped spec
- S-106-21: product intake matches a new request against a stopped project's outcome as it matches a declined opportunity, and its report names the stop record
- S-106-22: an accepted opportunity whose accept is `accept G-<n>`, or a plain accept with one goal in its `Serves:` line, of a written or planned goal reads ACCEPTED_INTO with the goal, and that goal reads PLAN_DUE `opportunity #<n> accepted` with or without an open plan
- S-106-23: on the accept of a plan that proposes an accepted opportunity as a `feature` item, intake files no issue for that item, labels the opportunity `project`, and links it as the plan's sub-issue
- S-106-24: an accept `accept new goal` reads GOAL_PROPOSAL_DUE, an action, until a `goal-proposal` issue by the `--bot-login` has the opportunity as its sub-issue; an accept naming no goal, or a goal that is a measure, of kind none, met, dropped, or not listed, reads NEEDS_GOAL and files nothing; an opportunity accepted before this spec's build reads ACCEPTED and HANDED_OFF as before
- S-106-25: `shipmill status --item G-3` and `--item N` on a plan issue or a project head print the state, the holder, and what moves it as a spec 094 condition, an overdue plan's as `answer due <date>, overdue` and a held project's naming the free slot, the overdue plan, or the maintainer's hold it waits for
- S-106-26: `watch_state.py` lists GOAL_OVERDUE, PLAN_REPLACED, PROJECT_START_DUE, PROJECT_IDLE, PROJECT_STOP_DUE, GOAL_PROPOSAL_DUE, and NEEDS_GOAL as actions of the PLANS row and `shipmill gate` starts a session for each; `fleet.py queue` shows a PLAN_OVERDUE plan as an overdue `PLAN` row and a NEEDS_GOAL opportunity as an `OPPORTUNITY` row
- S-106-27: `docs/flow.md` and the skills' references give the states, the labels (`project`, `held`, `focus`, `goal-proposal`, `goal-review`), and the markers this spec adds
- S-106-28: a config with `[product] home` that sets `[agents] projects` is refused with a message naming the home; in a home `intake_state.py --projects` counts the active and in-focus heads of the home and of every repo its `[product] repos` lists, reading other repos through `shipmill gh --product`, one call per owner, and in a component it reads the limit from the home's config on its default branch and counts the same set; a read that fails exits 2 naming the repo; the second line reads `projects active: K of N (product <owner/home>)` and `--json`'s first line carries `projects` with `limit`, `active`, and `room`
- S-106-29: on a started project whose head has no parts, `triage_state.py` reads the head NEEDS_PR once it has an implement verdict, never held on its check issue, and the check issue BLOCKED `project #<head>: check waits on its work`, never NEW; once a `Part of #<head>` pull request merged and none is open (or, with parts, every part closed) the check issue reads VERIFY_DUE and the head BLOCKED `project #<head>: check #<check> due`; `intake_state.py` reads no sub-issue titled `Check: ` with a `## Check` section as NEW_FEEDBACK

## Out of scope

- A held plan and its wake condition: spec 098
- A finished plan's outcome: spec 097, which this spec extends only with the `Goal check:` line
- The limit of outcomes waiting on the maintainer: spec 101; `[agents] projects` bounds what
  runs, not what waits for an answer
- A limit across several products, or the portfolio: the limit and an overdue plan's stop
  are each product's, and one project in focus across all products is the maintainer's to
  keep with the `focus` label; moving the focus by itself is a later request
- Ordering held projects by how close they are to done: they start in the order of their
  plans, which the maintainer accepted; a held head has no progress to measure
- The weekly and quarterly reviews: they read these states, and run outside shipmill
- A standing measure's value read from its source: shipmill/shipmill#1446
- Writing the direction: only the maintainer merges it (D-34); sessions open pull requests

## Decisions relied on

- D-10: the maintainer accepts or declines plans and opportunities; agents propose
- D-16: only a trusted author's reply is an answer
- D-29: a first-line marker counts only from the App or a trusted author
- D-32: `[agents] wip` bounds work in progress; `[agents] projects` sits beside it
- D-34: only the maintainer changes the direction
- D-62: a trusted author's text carrying the agent marker is an agent's
- D-68: the App's relay of a maintainer's answer is that answer
- D-83: the home reads the product's repos with the coordinator's product token
- D-84: a component reads its product's other repos with a read-only token

## Issues

- shipmill/shipmill#1736: S-106-1, S-106-2, S-106-3, S-106-20
- shipmill/shipmill#1737: S-106-4, S-106-5, S-106-6
- shipmill/shipmill#1738: S-106-7, S-106-8
- shipmill/shipmill#1739: S-106-11, S-106-12, S-106-13, S-106-28
- shipmill/shipmill#1740: S-106-9, S-106-14, S-106-15
- shipmill/shipmill#1741: S-106-16, S-106-17, S-106-18, S-106-19, S-106-21
- shipmill/shipmill#1742: S-106-10, S-106-22, S-106-23, S-106-24
- shipmill/shipmill#1743: S-106-25, S-106-26, S-106-27
- shipmill/shipmill#1802: S-106-29

## Verification

Checked on this spec's last build branch (#1743), on main at 886df5b8 (after #1781), by
running the tests named below, every one whose name carries its criterion's id
(`pytest -k s106`: 151 passed), and reading the code they exercise; `specs.py coverage
--spec 106` exits 0.

- S-106-1: `product.py`'s goal reader takes `. Met: <date>` or `. Dropped: <date>: <reason>` right after the horizon, and `product check` exits 1 naming the goal for one on a measure or a goal of kind none, a malformed date, an empty reason, or both (`test_s106_1_an_end_reads_only_right_after_the_horizon`, `test_s106_1_check_accepts_a_met_or_dropped_goal`, `test_s106_1_check_refuses_a_malformed_end_naming_the_goal`); holds
- S-106-2: `product show --json` gives every goal `state` and `ended`; `product met` and `product drop` write the sentence in the working tree and refuse a measure, an unknown goal, and an ended one (`test_s106_2_met_and_drop_refuse_a_measure_and_an_unknown_goal`, `test_s106_2_a_goal_already_ended_is_refused`, `test_s106_2_product_goal_keeps_an_ended_goals_record`, `test_s106_2_drop_writes_a_reason_holding_any_text_and_the_direction_still_reads`, `test_s106_2_show_json_gives_every_goal_its_state_and_end`, `test_s106_2_product_met_and_drop_write_the_sentence`); holds
- S-106-3: `specs.py check` refuses a draft or approved spec serving a met or dropped goal, and `intake_state.py --plans` reads no trigger for it (`test_s106_3_a_met_or_dropped_goal_reads_no_trigger`, `test_s106_3_the_goals_state_is_read_strictly`, `test_s106_3_a_draft_or_approved_spec_serving_a_met_or_dropped_goal_is_refused`, `test_s106_3_a_goal_without_an_end_or_written_otherwise_is_open`); holds
- S-106-4: `intake_state.py --goals` reads GOAL_PROPOSED, GOAL_WRITTEN, GOAL_PLANNED, GOAL_MET, and GOAL_DROPPED with `state`, `holder`, and `by` in `--json`, and no row for a measure or a goal of kind none (`test_s106_4_the_goals_horizon_is_read_strictly`, `test_s106_4_a_goal_whose_finished_plan_check_holds_reads_planned`, `test_s106_4_a_goals_other_plan_is_named_in_its_note`, `test_s106_4_no_plan_is_due_for_a_goal_whose_check_holds`, `test_s106_4_each_goal_of_kind_goal_reads_its_state`, `test_s106_4_a_measure_and_a_goal_of_no_kind_read_no_row`, `test_s106_4_a_trusted_goal_proposal_reads_proposed`, `test_s106_4_json_carries_state_holder_and_by`, `test_s106_4_the_skill_lists_the_goal_rows`); holds
- S-106-5: a written or planned goal past its date, or with its release tagged, reads GOAL_OVERDUE until the `--bot-login`'s goal-overdue issue for that horizon; anyone else's marker counts for nothing (`test_s106_5_a_goal_past_its_horizon_reads_overdue_until_the_bots_review`, `test_s106_5_only_the_bots_marker_counts_as_the_review`, `test_s106_5_a_release_horizon_is_past_once_its_version_is_tagged`); holds
- S-106-6: product-intake's SKILL.md gives GOAL_OVERDUE's step and PLAN_DONE's `Goal check:` line and Met pull request (`test_s106_6_the_skill_gives_goal_overdues_step`, `test_s106_6_plan_done_gives_the_goal_check_and_the_met_pull_request`); holds
- S-106-7: an open plan's note ends `answer by <date>` seven days after its newest revision, `--json` carries `answer_by`, and only a trusted `answer by` reply sets it, as no answer (`test_s106_7_an_open_plans_answer_is_due_seven_days_after_its_revision`, `test_s106_7_a_trusted_answer_by_reply_sets_the_date_and_answers_nothing`, `test_s106_7_an_untrusted_answer_by_changes_nothing`); holds
- S-106-8: past its answer date a plan reads PLAN_OVERDUE, no action, and a held plan reads no date until its re-check (`test_s106_8_the_watch_reads_an_overdue_plan_as_waiting_on_the_maintainer`, `test_s106_8_the_queue_still_lists_an_overdue_plan`, `test_s106_8_past_its_answer_date_a_plan_reads_overdue_no_action`, `test_s106_8_a_held_plan_has_no_date_until_it_reads_open_from_its_recheck`); holds
- S-106-9: an overdue plan of the product turns every `no-work` PLAN_DUE into PLAN_WAITS `plan <owner/repo>#P overdue` and starts no head, while a request's PLAN_DUE stays (`test_s106_9_the_checkouts_own_plans_read_as_plans_prints_them`, `test_s106_9_an_overdue_plan_holds_every_no_work_plan_but_a_request`, `test_s106_9_the_products_plans_are_read_for_overdue_and_accept_time`, `test_s106_9_no_head_starts_while_a_plan_is_overdue`); holds
- S-106-10: a goal with an open plan reads PLAN_DUE for a request and an accepted opportunity, the older open plan reads PLAN_REPLACED `by #<new>`, and a replaced plan is no decline (`test_s106_10_a_request_or_an_accepted_opportunity_reads_due_with_an_open_plan`, `test_s106_10_the_older_open_plan_reads_replaced_by_the_newer`, `test_s106_10_a_replaced_plan_is_no_decline`, `test_s106_10_the_skill_gives_the_replaced_plans_step`); holds
- S-106-11: an accepted plan's filed items carry `project`, and an issue without the label reads no project row (`test_s106_11_an_issue_without_the_project_label_reads_no_row`, `test_s106_11_an_accepted_plans_filed_items_are_labelled_project`); holds
- S-106-12: `intake_state.py --projects` reads PROJECT_HELD, PROJECT_ACTIVE, PROJECT_FOCUS, PROJECT_CLOSING with its cleanup note, PROJECT_CLOSED, and PROJECT_STOPPED from the head, its check issue, and its parts (`test_s106_12_a_head_with_no_check_issue_or_labelled_held_reads_held`, `test_s106_12_an_open_check_and_an_open_or_no_part_reads_active_or_focus`, `test_s106_12_every_part_closed_reads_closing_with_its_cleanup`, `test_s106_12_a_closed_head_reads_closed_or_stopped_by_the_bots_record`, `test_s106_12_a_head_is_a_trusted_authors_or_labelled_by_another`, `test_s106_12_a_second_check_issue_is_no_part`, `test_s106_12_more_sub_issues_than_read_is_refused`, `test_s106_12_fetch_projects_reads_open_heads_and_those_closed_within_30_days`, `test_s106_12_the_run_prints_a_row_per_head_after_the_other_rows`, `test_s106_12_the_project_reads_cost_a_few_points`); holds
- S-106-13: `AgentsConfig` reads `[agents] projects` from 1 to `wip`'s ceiling, None without it, and refuses a bad value naming the key (`test_s106_13_the_projects_limit_reads_1_to_wips_ceiling_and_is_none_when_omitted`, `test_s106_13_a_bad_projects_limit_is_refused_naming_the_key`); holds
- S-106-14: with `[agents] projects` the product's full slots start no head, a free slot starts the oldest accepted plan's first item, then heads by label time, and without the key every held head starts (`test_s106_14_one_slot_starts_the_oldest_accepted_plans_first_item`, `test_s106_14_heads_with_no_plan_start_by_when_they_were_labelled`, `test_s106_14_without_the_key_every_held_head_starts`, `test_s106_14_a_heads_work_order_comes_from_its_plan_item_marker`, `test_s106_14_no_head_starts_while_the_products_slots_are_full`); holds
- S-106-15: product-intake's SKILL.md gives PROJECT_START_DUE's step (`test_s106_15_the_skill_gives_project_start_dues_step`); holds
- S-106-16: `triage_state.py` reads a held head and its open sub-issues BLOCKED `project #<head> held`, and a head in any other state as any parent (`test_s106_16_a_head_with_no_check_issue_and_its_open_sub_issues_read_blocked`, `test_s106_16_a_head_labelled_held_holds_the_check_issues_parts_too`, `test_s106_16_a_head_in_any_other_state_reads_as_any_parent`, `test_s106_16_the_run_reads_the_held_projects_issues_blocked`, `test_s106_16_the_query_reads_sub_issues_titles_and_bodies_at_no_more_cost`, `test_s106_16_a_persons_item_whose_parent_closed_reads_stale_handoff_first`); holds
- S-106-17: a head whose tree had no update for 14 days reads PROJECT_IDLE until the `--bot-login`'s question newer than the last update (`test_s106_17_the_idle_note_dates_the_last_update`, `test_s106_17_a_tree_with_no_update_for_14_days_reads_idle`, `test_s106_17_any_part_or_pull_request_of_the_tree_counts_as_an_update`, `test_s106_17_the_bots_question_after_the_last_update_ends_idle`); holds
- S-106-18: a trusted `stop: <reason>`, or `stop` answering the idle question, reads PROJECT_STOP_DUE; an untrusted or older one changes nothing (`test_s106_18_stop_answering_the_idle_question_reads_stop_due`, `test_s106_18_a_bare_stop_answers_only_the_question_right_before_it`, `test_s106_18_an_untrusted_or_older_stop_changes_nothing`, `test_s106_18_a_trusted_stop_reply_reads_stop_due`); holds
- S-106-19: product-intake's SKILL.md gives PROJECT_STOP_DUE's step (`test_s106_19_the_skill_gives_the_stop_step`); holds
- S-106-20: `specs.py check` accepts `status: stopped` without Verification, and `split` refuses a stopped spec (`test_s106_20_check_accepts_a_stopped_spec_without_verification`, `test_s106_20_split_refuses_a_stopped_spec`, `test_s106_20_a_stopped_specs_sections_keep_their_order`); holds
- S-106-21: a stopped project's row names its stop record and reason, which intake matches a new request against (`test_s106_21_a_stopped_projects_row_names_its_record_and_reason`); holds
- S-106-22: an accept naming `G-<n>`, or one goal in `Serves:`, of an open goal reads ACCEPTED_INTO, and the goal reads PLAN_DUE `opportunity #<n> accepted` (`test_s106_22_a_plan_since_the_accept_answers_it_open_or_closed`, `test_s106_22_an_accepted_opportunity_reads_into_its_goal`, `test_s106_22_only_a_trusted_accept_names_the_goal`, `test_s106_22_accepted_reads_the_label_time_and_parent`); holds
- S-106-23: a plan item naming an accepted opportunity files no issue; the opportunity is labelled `project` and linked as the plan's sub-issue (`test_s106_23_a_plan_item_naming_an_accepted_opportunity_files_no_issue`, `test_s106_23_a_closed_opportunity_still_carries_its_item`, `test_s106_23_an_opportunity_item_files_no_issue`); holds
- S-106-24: `accept new goal` reads GOAL_PROPOSAL_DUE until the App's goal-proposal issue holds it, no open goal reads NEEDS_GOAL, and an opportunity accepted before the build reads as before (`test_s106_24_a_goal_naming_opportunity_line_carries_its_opener`, `test_s106_24_a_new_goal_waits_on_its_proposal_and_no_goal_needs_one`, `test_s106_24_an_opportunity_accepted_before_the_build_reads_as_before`, `test_s106_24_the_skill_gives_the_goal_questions`); holds
- S-106-25: `shipmill status --item G-<n>` (`item_status.parse_item`, `cli._status_goal`, `explain_goal`) and `--item N` on a plan or a head give one condition with its reason, who, and clears, read from the watch's GOAL_STATE, PLAN_STATE, and PROJECT_STATE rows (`watch_state.item_states`, in an `--item` read only): `answer due <date>, overdue` for an overdue plan, and `plan #P overdue`, `a free slot: K of N active`, or `held by the maintainer` for a held head, the product's overdue plans read from intake's first line (`test_s106_25_status_hands_a_goal_id_to_the_watch`, `test_s106_25_the_first_line_names_the_products_overdue_plans`, `test_s106_25_a_plan_names_its_answer_date_overdue_past_it`, `test_s106_25_a_held_project_names_what_it_waits_for`, `test_s106_25_an_open_head_names_its_state`, `test_s106_25_an_unreadable_state_row_is_refused`, `test_s106_25_item_takes_a_goal_id`, `test_s106_25_status_item_explains_a_goal`, `test_s106_25_a_goal_names_its_state_holder_and_what_moves_it`, `test_s106_25_the_item_read_gives_each_goal_plan_and_head_its_state`, `test_s106_25_an_overdue_plan_of_another_repo_reaches_the_heads`, `test_s106_25_item_reads_a_goal_id`, `test_s106_25_the_products_overdue_plans_reach_the_heads`); holds
- S-106-26: `watch_state.py` runs intake with `--goals --projects`, checks every goal, project, and opportunity row and the first line's `projects` and `overdue`, and lists GOAL_OVERDUE, PLAN_REPLACED, PROJECT_START_DUE, PROJECT_IDLE, PROJECT_STOP_DUE, GOAL_PROPOSAL_DUE, and NEEDS_GOAL on the PLANS row, on which the gate launches, an accepted opportunity trusted by its opener and a replaced plan listed only for a trusted newer plan (D-16); `fleet.py queue` lists a PLAN_OVERDUE plan as a PLAN row adding `answer due <date>, overdue` and a NEEDS_GOAL opportunity as an OPPORTUNITY row (`test_s106_26_an_overdue_plan_and_an_opportunity_needing_a_goal_are_rows`, `test_s106_26_a_question_on_the_plan_keeps_its_own_phrase`, `test_s106_26_an_overdue_plan_without_its_date_is_refused`, `test_s106_26_the_gate_starts_a_session_for_each_spec_106_action`, `test_s106_26_a_row_intake_could_not_print_is_refused`, `test_s106_26_a_malformed_projects_count_is_refused`, `test_s106_26_an_outsiders_opportunity_or_plan_starts_no_session`, `test_s106_26_an_opportunity_row_without_its_opener_is_refused`, `test_s106_26_the_plans_row_lists_every_spec_106_action`, `test_s106_26_the_watch_knows_every_state_intake_prints`); holds
- S-106-27: docs/flow.md's "Goals, plans, and projects" and product-intake's plan.md give the states, the five labels, and the three markers, the names intake_state.py reads (`test_s106_27_the_labels_and_markers_are_documented`, `test_s106_27_flow_gives_each_state`, `test_s106_27_the_documented_names_are_the_ones_intake_reads`); holds
- S-106-28: a component setting `[agents] projects` is refused naming its home; the home counts its own and its repos' active and in-focus heads, one call per owner, a component reads the limit from its home, a failed read exits 2 naming the repo, and the text and `--json` carry the count (`test_s106_28_the_product_counts_active_and_focus_heads_one_call_per_owner`, `test_s106_28_a_product_count_reads_a_check_issues_parts_as_counts`, `test_s106_28_a_failed_read_exits_2_naming_the_repo`, `test_s106_28_without_the_key_nothing_is_read`, `test_s106_28_a_component_reads_the_limit_from_its_home`, `test_s106_28_a_component_that_sets_projects_is_refused_naming_the_home`, `test_s106_28_the_run_counts_the_homes_product`, `test_s106_28_a_component_that_sets_the_projects_limit_is_refused_naming_the_home`, `test_s106_28_the_home_and_a_lone_repo_keep_their_projects_limit`); holds
- S-106-29: a started project's head is built like any issue, its check issue waits on its work and then reads by its `## Check`, and no check issue is feedback (`test_s106_29_a_head_with_no_parts_is_built_like_any_issue_not_held_on_its_check`, `test_s106_29_the_check_is_due_once_the_heads_part_of_prs_merged`, `test_s106_29_a_head_with_parts_waits_on_them_and_then_on_its_check`, `test_s106_29_a_due_check_still_waits_on_its_own_holds`, `test_s106_29_the_run_reads_a_started_project`, `test_s106_29_a_project_check_issue_is_no_feedback`); holds
