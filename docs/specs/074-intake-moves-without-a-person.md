# S-074: Handed-over requests and accepted opportunities start their own sessions

status: approved
serves: G-1

## Problem

A request triage hands to product intake waits until a person starts an intake pass by hand,
and an accepted opportunity waits the same way for the spec gate (#1224, from #1043). A gate
session runs triage only. `skills/github-ship-watch/scripts/watch_state.py` runs
`skills/product-intake/scripts/intake_state.py --plans` and keeps only the goal-plan rows
(PLAN_DUE, PLAN_MALFORMED, PLAN_ANSWERED, PLAN_ACCEPTED), so the NEW_FEEDBACK and ACCEPTED
rows reach no report and start no session. On 2026-11-18 `intake_state.py shipmill/shipmill`
lists 24 requests as NEW_FEEDBACK, the oldest #322 from 2026-10-09, and 6 opportunities as
ACCEPTED and not handed over, #336 and #337 since 2026-10-18. #1043 itself was stuck by the
gap it describes: its opportunity, #1224, was opened by hand.

Users who filed a request and were told intake will group it hear nothing; the maintainer
never gets the accept or decline question (D-10), or accepts an opportunity that then gets no
spec. `[autonomy] intake = "propose"` reads as if intake runs.

A second gap would trip an automatic pass at once. `intake_state.py` reads an issue as
feedback unless its newest triage verdict is one of `CLOSING_VERDICTS` (implement, feature,
duplicate, won't fix), and a postpone verdict isn't one. In a manual intake pass on
2026-11-18 it listed as NEW_FEEDBACK four issues triage had already postponed, #772, #836,
#837, and #842 (a bug and internal test and performance work, each labelled `postponed` with
a newer `Triage: **postponed**` comment). An unattended pass would read them as requests to
group.

## Behaviour

### `intake_state.py`: a postponed issue is triage's

`skills/product-intake/scripts/intake_state.py` adds `postpone` to `CLOSING_VERDICTS`: an
issue whose newest triage comment's verdict starts with `postpone` (`Triage: **postponed**`)
is not feedback, so it never reads NEW_FEEDBACK. A newer triage comment with another verdict
(an `opportunity` hand-off after triage revisits it) makes it feedback again, as for every
verdict today. Its docstring and product-intake's `skills/product-intake/SKILL.md` (rule 5)
name the verdict with the others.

### `intake_state.py --json`: what the watch needs to place a row

Each NEW_FEEDBACK and ACCEPTED line of `intake_state.py --json` gains three keys, and the
other lines keep theirs:

- `author`: the opener's login, a Bot's ending `[bot]` as the plan rows spell it, or null
  when GitHub returns none
- `association`: the opener's author association (`OWNER`, `MEMBER`, `COLLABORATOR`,
  `CONTRIBUTOR`, `NONE`, ...), or null for a discussion
- `handed`: for an issue whose newest triage comment's verdict is `opportunity` (triage's
  hand-off), that comment's `createdAt`; null for any other feedback (an issue no triage
  comment covers, or a discussion) and for an ACCEPTED opportunity

The text output is unchanged.

### `watch_state.py`: two rows from the feedback

`skills/github-ship-watch/scripts/watch_state.py` runs `intake_state.py --json` once per repo
it reports, with `--plans` (and its flags, as today) only when the checkout has
`docs/product.md`, and reads its feedback lines as well as its plan lines. A failure exits 2
as the `--plans` run does today; uv finding no pinned version is still the PyPI wait (#597).
From those lines it adds two rows, each naming issue numbers only, never an issue's text
(D-16):

- `SPEC_DUE`: the ACCEPTED opportunities, `ACCEPTED #N #M ...`, oldest first, with the fix
  `/shipmill:github-issue-triage <owner/repo>`: triage runs the spec gate on each. An
  accepted opportunity needs no wait: the maintainer's `planned` label is the decision, so
  the row lists it on the first sweep that reads it
- `FEEDBACK_DUE`: the NEW_FEEDBACK issues triage handed over (`handed` not null) at least
  `FEEDBACK_AFTER` (24 hours, a constant of `watch_state.py`) before the read,
  `NEW_FEEDBACK #N #M ...`, oldest hand-off first, with the fix
  `/shipmill:product-intake <owner/repo>`: one intake pass groups every request the repo
  has, so one row per repo, never one per request. A request handed over less than
  `FEEDBACK_AFTER` ago, an issue triage hasn't handed over (it is triage's, read NEW by
  `triage_state.py`), and a discussion make no row

The intake level is the `autonomy` line `intake_state.py --json` prints first. Under
`[autonomy] intake = "observe"`, FEEDBACK_DUE is a report-only row (it names the requests and
starts no session, as PRS_PARKED does); under `propose` it is an action row. SPEC_DUE's
session is triage's, so it is an action row at any intake level.

With `--trusted-only`, a NEW_FEEDBACK issue or an ACCEPTED opportunity whose `association`
is none of `OWNER`, `MEMBER`, and `COLLABORATOR` and whose `author` isn't the `--bot-login`
is in neither row and in UNTRUSTED instead, as an untrusted plan issue is (D-16): an
unattended session never starts for an outsider's text.

### The gate's walk

`src/shipmill/walk.py` and `watch_state.py` place both rows in tier 7, after
DIRECTION_PENDING and PLANS: `7: ("DIRECTION_PENDING", "PLANS", "SPEC_DUE", "FEEDBACK_DUE")`.
Both are timed sections: they join `SWEPT` in both files, so `watch_state.py --sweep` prints
them, `--tier 7` reads them from the sweep, and a tick reads them from `sweep.json` like
PLANS (D-58). A sweep runs every `[agents] sweep_hours` (default 6), so a request handed
over waits at most `FEEDBACK_AFTER` plus `sweep_hours` before a session starts, and an
accepted opportunity at most `sweep_hours`.

Each row is one item, handed by its fingerprint (S-046-13): a session started for it gets
the row and its fix line in the launch prompt, as any item does, and the row's numbers
change only when the set of due issues does.

### Docs

- `docs/flow.md` (Issue states): a handed-over request's action reads that the gate starts an
  intake pass once it has waited `FEEDBACK_AFTER`, and an accepted opportunity's that the
  gate hands it to the spec gate
- `skills/github-ship-watch/SKILL.md` and `watch_state.py`'s docstring describe SPEC_DUE and
  FEEDBACK_DUE, the tier list, and the swept sections
- `skills/product-intake/SKILL.md`: a pass the gate starts for FEEDBACK_DUE runs the usual
  workflow, and the ACCEPTED rows are triage's (SPEC_DUE), so an intake pass started by the
  gate leaves them to triage
- `shipmill status`, which reads the watch's rows (`src/shipmill/status.py`), lists both rows
  with their fix, like PLANS

## Acceptance criteria

- S-074-1: `intake_state.py` never reads an open issue as NEW_FEEDBACK when its newest triage comment's verdict is `postponed`, and reads it NEW_FEEDBACK again once a newer triage comment's verdict is `opportunity`
- S-074-2: each NEW_FEEDBACK and ACCEPTED line of `intake_state.py --json` carries `author`, `association`, and `handed`; `handed` is the `createdAt` of the newest triage comment when its verdict is `opportunity`, and null for an issue with no triage comment, for a discussion, and for an ACCEPTED opportunity
- S-074-3: `watch_state.py` runs `intake_state.py --json` on a repo whose checkout has no `docs/product.md`, without `--plans`, and with `--plans` when it has one; a run that exits 2 stops the watch with exit 2
- S-074-4: `watch_state.py` reports one SPEC_DUE row per repo naming every ACCEPTED opportunity as `#N`, oldest first, with the fix `/shipmill:github-issue-triage <owner/repo>`, and no SPEC_DUE row when `intake_state.py` reads none
- S-074-5: `watch_state.py` reports one FEEDBACK_DUE row per repo naming each NEW_FEEDBACK issue whose `handed` is at least 24 hours before the read, oldest hand-off first, with the fix `/shipmill:product-intake <owner/repo>`; an issue handed over less than 24 hours before, one with `handed` null, and a discussion are in no row
- S-074-6: under `[autonomy] intake = "observe"` (the `autonomy` line `intake_state.py` prints) FEEDBACK_DUE is report-only: the full report prints it, and `--tier 7` and `--sweep` don't; under `propose` both print it, and SPEC_DUE prints in all three at either level
- S-074-7: with `--trusted-only`, a NEW_FEEDBACK issue or an ACCEPTED opportunity opened by neither an OWNER, MEMBER, or COLLABORATOR nor the `--bot-login` is in neither row and is listed in UNTRUSTED
- S-074-8: `walk.py`'s and `watch_state.py`'s tier 7 is `DIRECTION_PENDING, PLANS, SPEC_DUE, FEEDBACK_DUE` in that order, and both files' `SWEPT` holds SPEC_DUE and FEEDBACK_DUE, so a tick takes them from `sweep.json` and starts a session for the first one no session was handed within `retry_hours`
- S-074-9: no SPEC_DUE or FEEDBACK_DUE row, in any output, holds an issue's or a discussion's title or body text: only the state and `#N` numbers

## Out of scope

- A configurable wait: `FEEDBACK_AFTER` is a constant; a config key for it is a change of its own if a repo needs another wait
- Discussions: a discussion makes no FEEDBACK_DUE row, since triage never hands one over; an intake pass the row starts still groups the repo's discussions with the rest
- An issue no triage comment covers stays triage's (`triage_state.py` reads it NEW), even though `intake_state.py` lists it as NEW_FEEDBACK; this spec doesn't change that reading
- The `clarify` verdict: an issue waiting on its filer keeps reading as feedback; only `postpone` joins the closing verdicts here
- What an intake pass or the spec gate does once started: product intake's workflow (D-10: it only proposes) and the spec gate are unchanged

## Decisions relied on

- D-10
- D-16
- D-58
- D-88

## Issues

## Verification
