# S-070: Choose how fast an accepted outcome ships

status: approved
serves: G-1

## Problem

The maintainer can't say "this ships now" at the level where the decision is made (#478).
A fix they want in production at once waits like any other item: the gate's walk takes the
issues of a tier in a fixed order that knows nothing of urgency (S-046-12), and a stable
lane releases only once `main` has been quiet for `quiet_minutes` or on the next hourly
tick. The only fast path is by hand: start `github-issue-resolve` on the issue, then
dispatch `release.yml` with `lane=stable` or a hotfix, a human step G-1 rules out.

A label on each issue is the wrong level: one customer request often becomes several build
issues, and the decision to expedite belongs to the outcome the maintainer accepted, not to
each task.

Measured on shipmill/shipmill from 2026-09-19 to 2026-10-19 (160 issues closed by a merged
pull request): issue to release 2.1 h median, of which merge to release 24 min; 125 of 266
pull requests merged within 15 minutes of opening, so the work is fast and the time goes to
waiting. Evidence: the maintainer's request of 2026-10-19 that delivery to production starts
at a higher level than an issue, when an outcome is prioritised.

## Behaviour

**Classes of service.** An accepted opportunity (labelled `opportunity` and `planned`,
D-10) has one class of service, the Kanban terms:

- `standard`: no class label; everything works as it does today
- `expedite`: the `expedite` label on the opportunity issue
- `fixed date`: the `fixed-date` label on the opportunity issue, with the date taken from
  the due date of the milestone the opportunity issue is in (D-32: the milestone stays the
  maintainer's list, and its due date is theirs)

The class lives on the opportunity alone. Its outcome is the opportunity issue and its
sub-issues, which is where the spec gate files the build issues ("under #N"); a build issue
never carries a class label, and triage never copies one onto it. A class label counts only
when a person added it: the issue's timeline names the actor of the newest `labeled` event
for it, and a label the App added, or one whose actor can't be read, counts as no label, so
choosing a class stays the maintainer's decision (N-3, D-10). An opportunity with both
labels reads as `standard` and is reported as `CLASS_CONFLICT`, with the fix "remove one of
`expedite` and `fixed-date` from #N".

**Choosing it.** The opportunity comment of `skills/product-intake/references/opportunity.md`
names the choice with the accept step: accept with `planned`, and add `expedite` or
`fixed-date` (with a milestone due date) for a class other than standard.
`skills/shipmill-setup/scripts/setup_state.py`'s `LABELS` gains `expedite` and `fixed-date`
for a config with an `[agents]` section, so `LABELS_MISSING` names them until they exist.

**Taken first.** `skills/github-ship-watch/scripts/watch_state.py` reads, once per walk of
tier 3 or 6, the open opportunities labelled `expedite`, and marks each row whose subject is
one of their outcome's issues, or a pull request that closes one, as expedite.
`src/shipmill/walk.py`'s `order` puts an expedite row before every standard row of the same
tier, whatever its kind; among expedite rows, and among standard ones, the order stays
S-046-12's (kind, then subject). Tiers 1 and 2 (production and the release lane) still come
first, and no tier is skipped. With `[agents] wip`,
`skills/github-issue-triage/scripts/triage_state.py`'s `wip_room` lists expedite issues
first among those ready to start, and counts them in progress like any other: an expedite
issue takes the next free slot and never one beyond the limit.

**Released at once.** The run of `release.yml` that follows a merge (`src/shipmill/planner.py`)
makes a lane due with the reason `expedite #N complete` when the candidate holds the merge
that completed an expedite outcome: the opportunity #N labelled `expedite` has at least one
sub-issue, every sub-issue is closed, and the last of them was closed by a pull request
merged into the candidate's base since the lane's last release (or, with no sub-issue, #N
itself was closed that way). The lane is the stable lane when it releases from `main`; when
the stable lane promotes, the rc lane is due instead and the promotion keeps its own
triggers. It skips `quiet_minutes` and the schedule windows only: every gate still applies,
a `shipmill-hold` issue (D-8), a `release-blocker`, CI on the exact release commit (Q-3), a
major bump waiting for the maintainer (D-39), and a veto window in `[gates] veto_lanes`
(spec 059), each with its usual skip reason. An outcome whose completing merge a release of
that lane already shipped makes nothing due again. The hotfix lane stays hand-started (D-8).

**A date that will be missed.** `watch_state.py` reports `FIXED_DATE_AT_RISK` for an open
opportunity of class fixed date whose due date is at most 2 days away, or past, while it has
an open sub-issue or no sub-issue at all, as `#N due YYYY-MM-DD, K build issues open`, with
the fix "expedite #N or move its milestone's due date". A `fixed-date` opportunity in no
milestone, or in one without a due date, is reported as `FIXED_DATE_NO_DATE`, with the fix
"set the due date of #N's milestone". `CLASS_CONFLICT`, `FIXED_DATE_AT_RISK` and
`FIXED_DATE_NO_DATE` are rows of what waits on the maintainer, so `shipmill status`
(`src/shipmill/status.py`) counts them there, and the gate's walk never hands a session one
of them: they wait on the maintainer's choice, which no session makes.

## Acceptance criteria

- S-070-1: an open accepted opportunity whose `expedite` label a person added reads as class expedite; the same label added by the App, or with an actor that can't be read, reads as standard
- S-070-2: an opportunity labelled both `expedite` and `fixed-date` reads as standard and `watch_state.py` reports `CLASS_CONFLICT` for it with its fix line
- S-070-3: `watch_state.py` marks as expedite a row whose subject is the expedite opportunity, one of its sub-issues, or a pull request closing one, and no other row
- S-070-4: `walk.order` places an expedite row of tier 3 or 6 before every standard row of the same tier, and keeps S-046-12's order within each group; tiers 1 and 2 still come before it
- S-070-5: with no class label on any opportunity, the walk's order and every lane's plan are the same as before this spec
- S-070-6: `triage_state.py --wip N` lists expedite issues first among the ready ones and counts them in progress like any other, so its room never goes below 0 for them
- S-070-7: a run of `release.yml` whose candidate holds the merge that closed the last open sub-issue of an expedite opportunity makes the stable lane due with the reason `expedite #N complete` while `main` has been quiet for less than `quiet_minutes` and no window is open
- S-070-8: with a promoting stable lane, the same merge makes the rc lane due, and the stable lane's plan is unchanged
- S-070-9: a lane made due by an expedite outcome still skips, with its usual reason, for an open `shipmill-hold` issue, a `release-blocker`, CI not green on the release commit, a major bump, or an open veto window of a lane in `[gates] veto_lanes`
- S-070-10: once a release of the lane holds the completing merge, the same outcome makes the lane due no more
- S-070-11: `watch_state.py` reports `FIXED_DATE_AT_RISK` for a fixed-date opportunity due in 2 days or less, or past, with an open sub-issue or no sub-issue, and nothing for one due in more than 2 days or with every sub-issue closed
- S-070-12: `watch_state.py` reports `FIXED_DATE_NO_DATE` for a fixed-date opportunity in no milestone or in one without a due date
- S-070-13: `CLASS_CONFLICT`, `FIXED_DATE_AT_RISK` and `FIXED_DATE_NO_DATE` count as waiting on the maintainer in `shipmill status`, and a gate tick with only these rows launches no session
- S-070-14: `setup_state.py` reports `LABELS_MISSING` naming `expedite` and `fixed-date` for a config with `[agents]` whose repo lacks them
- S-070-15: product intake's opportunity comment names the `expedite` and `fixed-date` labels beside `planned`, and the spec gate's split files build issues with no class label

## Out of scope

- "For one customer first": it needs a flag or an early build per customer, and executing that rollout is the platform's (N-1, D-31); it waits for a spec of its own once a platform side exists
- A goal plan proposing a class of service (rung 3, G-6, spec 028): a later spec, once this one is built
- Expediting by hand-started hotfix: the hotfix lane stays cut by a person (D-8)
- Preempting work in progress: an expedite issue waits for a free `[agents] wip` slot and never stops a running session
- A class on a milestone of its own: the milestone gives a fixed date its date only

## Decisions relied on

- D-5
- D-8
- D-10
- D-31
- D-32
- D-39
- D-58
- D-62

## Issues

## Verification
