# S-106: States of a goal, a plan, and a project, with a plan's answer date and a goal on every accepted opportunity

status: approved
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

- S-106-1: `shipmill product check` accepts a goal of kind goal ending `. Met: 2026-12-20` or `. Dropped: 2026-12-01: <reason>`, and exits 2 naming the goal for either on a measure or a goal of kind none, a malformed date, an empty reason, or both sentences
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
- S-106-16: `triage_state.py` reads a held head and each of its open sub-issues as BLOCKED with the note `project #<head> held`, and a head in any other state as it reads any parent
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

## Verification
