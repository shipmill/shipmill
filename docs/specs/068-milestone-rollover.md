# S-068: A release closes its milestone and rolls what's left to the next

status: built
serves: G-1

## Problem

A milestone tied to a release (`milestone = true`) works once and then stops (#336). When
its version ships, nothing closes the milestone, opens the next one, or moves what was left
in it, so the stable lane loses its milestone trigger until the maintainer notices. In
practice the milestone becomes a manual hold: an issue is parked in it to stop a release,
and "close the milestone" is a step the maintainer has to remember after a soak.

Two public repos that set `milestone = true` met this in the same week (2026-10-10): one
shipped its version and kept an empty open milestone with no next one; in the other, the
last open issue in the milestone was a question to the maintainer, and closing the
milestone was a manual step after the soak.

Spec 022 decides when a milestone is done (its specs built) and renames a milestone a stable
release overtook while its issues were still open (S-022-10). It leaves a milestone whose
own release shipped it open (GitHub never closes one), and says nothing when the lane has
no next milestone to wait on. Spec 028 lets an accepted goal plan name and create the
milestone that completes a goal (D-38). This spec closes the loop between them: the release
closes its milestone, moves what's left to the next one, and says when there is none.

## Behaviour

### The key

A lane with `milestone = true` may set `close_milestone = true` in `.github/shipmill.toml`
(`src/shipmill/policy.py`). Absent, it is `false`, so no repo changes behaviour by upgrading
shipmill alone (D-63). A value that isn't a boolean, or `close_milestone = true` on a lane
without `milestone = true`, exits 2 naming the key and the lane. Setting the key is the
maintainer's decision to let the release edit the milestone the version is named after
(D-95).

### What the release does

After a stable version X is tagged and published by a lane with `close_milestone = true`,
including the waits and reference moves of `after_publish` (D-50), `land`
(`src/shipmill/land.py`) reads the open milestone titled X (`str` of the release, as spec 022
names it):

- **No open issues:** it closes milestone X
- **Open issues, and a later milestone:** the later milestone is the open milestone whose
  title is the lowest stable version above X (titles that aren't a stable version are
  ignored). `land` moves each open issue of X to it, then closes X. Closed issues stay in X,
  so X keeps the record of what its release shipped. A spec whose build issues span both
  milestones belongs to both (spec 022's belonging is unchanged), so an unfinished goal
  keeps holding the later one
- **Open issues, and no later milestone:** it writes nothing. X is then overtaken, and spec
  022's MILESTONE_OVERTAKEN row and its rename apply as today (S-022-10), so the goal keeps
  one milestone and nothing is created on the maintainer's behalf (D-32)
- **No milestone titled X, a pre-release, or a lane without `close_milestone`:** it reads and
  writes no milestone

The Release run's summary names what it did: `milestone 1.5.0 closed`, or
`milestone 1.5.0 closed; #12, #14 moved to 1.6.0`. The writes go through the code host port
(`src/shipmill/github.py`: closing a milestone and setting an issue's milestone, the one
milestone write #322 names) with the land job's token, which needs `issues: write`.

A milestone write that fails fails the land job after the tag and publish, naming the
milestone and the `shipmill gh api` command that does the write; the release stands, and
the MILESTONE_RELEASED row below carries the same fix until the milestone is closed.

### What status says

`shipmill milestones` and `shipmill status` (`src/shipmill/status.py`,
`src/shipmill/planner.py`), with a lane that sets `milestone = true`, gain two rows:

- **MILESTONE_RELEASED:** an open milestone titled a stable version whose tag exists, with
  no open issues. Its fix closes it
  (`shipmill gh api -X PATCH repos/<owner>/<repo>/milestones/<n> -f state=closed`). This is
  the proposed form of the close for a lane without `close_milestone`, and the safety net
  for a failed write with it. github-ship-watch (`skills/github-ship-watch/SKILL.md`,
  `watch_state.py`) reports it like MILESTONE_OVERTAKEN, and under "watch" runs the fix once
  as the App and says so where it says a rename
- **MILESTONE_MISSING:** no open milestone is titled a stable version above the newest
  stable tag, so the lane has nothing to wait on. Its detail names the version the lane cuts
  next (spec 022's `_next_release`) and says an accepted goal plan may name it (D-38); its fix
  creates it (`shipmill gh api -X POST repos/<owner>/<repo>/milestones -f title=<next>`).
  It is the maintainer's step: no watch or intake pass runs this fix, since which work a
  version holds stays the maintainer's list (D-32)

### A hold in a milestone reads as a hold

An issue parked in a milestone to stop a release is a hold, not unfinished work (D-8). A
milestone whose open issues are each labelled the hold label (`shipmill-hold`) or
`needs-decision` reads MILESTONE_WAITING, as a milestone with no open issues does under spec
022, and each such issue is one reason (`src/shipmill/milestones.py`):

- `milestone 1.5.0: #N holds it (shipmill-hold): <title>`
- `milestone 1.5.0: #N waits on a decision: <title>`

`shipmill plan` names the same reasons for the lane. A milestone with any other open issue
waits as today, with no row (S-022-8). Reading the labels adds `labels` to the milestone's
issue read in `github.py`; nothing else is read.

### doctor and setup

- `shipmill doctor` (`src/shipmill/doctor.py`) adds a reason to its land-grant WARN when a
  lane sets `close_milestone` and the caller's land job grants no `issues: write` (D-9)
- `shipmill init` (`src/shipmill/init.py`) writes `close_milestone = true` wherever it writes
  `milestone = true`, and the commented example beside `# milestone = true` in
  `docs/release-lanes.md` shows it
- `skills/shipmill-setup/SKILL.md`'s Milestones row offers `close_milestone = true` with
  `milestone = true`, and the first milestone, created with the MILESTONE_MISSING row's fix
  once the user names it
- `skills/shipmill-setup/scripts/setup_state.py` counts `opportunity` and `planned` among the
  labels it wants for a repo with `[agents]`, so LABELS_MISSING names them and `--fix`
  creates them; `[roadmap]` is not offered, since it is deprecated (D-32, D-63)

## Acceptance criteria

- S-068-1: The policy reads `close_milestone` on a lane as `false` when absent, and exits 2 naming the key and the lane when it isn't a boolean or is `true` on a lane without `milestone = true`
- S-068-2: After a stable release X by a lane with `close_milestone = true`, an open milestone titled X with no open issues is closed, and the Release run's summary says `milestone X closed`
- S-068-3: When milestone X has open issues and an open milestone titled the lowest stable version above X exists, `land` moves each open issue of X to it and then closes X, leaving X's closed issues in X, and the summary names the moved issues and the milestone they moved to
- S-068-4: When milestone X has open issues and no open milestone is titled a stable version above X, `land` writes no milestone, and `shipmill milestones` reports MILESTONE_OVERTAKEN for X as S-022-10 says
- S-068-5: `land` reads and writes no milestone for a pre-release, for a lane without `close_milestone`, or when no milestone is titled X
- S-068-6: A milestone write that fails makes the land job exit non-zero after the tag is pushed and the release published, with a message naming the milestone and the `shipmill gh api` command that does the write
- S-068-7: With a lane that sets `milestone = true`, `shipmill milestones` reports MILESTONE_RELEASED for an open milestone titled a stable version whose tag exists and which has no open issues, with the fix that closes it, and reports no such row for a milestone with open issues or whose version has no tag
- S-068-8: With a lane that sets `milestone = true`, `shipmill milestones` reports MILESTONE_MISSING, naming the version the lane cuts next and the fix that creates its milestone, when no open milestone is titled a stable version above the newest stable tag, and no such row when one is
- S-068-9: github-ship-watch's state lists MILESTONE_RELEASED and MILESTONE_MISSING from `shipmill milestones --json`, and its skill runs MILESTONE_RELEASED's fix under "watch" and never MILESTONE_MISSING's
- S-068-10: A milestone whose open issues each carry the hold label or `needs-decision` reads MILESTONE_WAITING with one reason per issue, `#N holds it (<label>): <title>` or `#N waits on a decision: <title>`, and a milestone with any other open issue reads no MILESTONE_WAITING row
- S-068-11: `shipmill doctor` warns, naming `close_milestone`, when a lane sets it and the caller's land job grants no `issues: write`, and gives no such reason when no lane sets it
- S-068-12: `shipmill init` writes `close_milestone = true` on every lane where it writes `milestone = true`, and the policy it writes loads
- S-068-13: `setup_state.py` reports LABELS_MISSING naming `opportunity` and `planned` for a repo with `[agents]` that lacks them, and `--fix` creates them

## Out of scope

- Choosing which issues go into a milestone, fixes triaged **implement** included: the maintainer's list (D-32); an accepted goal plan may fill and create one (spec 028, D-38)
- Creating the next milestone on the maintainer's behalf: MILESTONE_MISSING reports it, and only the maintainer or an accepted plan creates it
- Renaming an overtaken milestone: spec 022 (S-022-10), unchanged
- Closing a milestone for a pre-release, a hotfix, or a lane without `milestone = true`
- Milestones in other repositories of a product: a cross-repo goal is a chain (spec 017)
- Due dates on milestones

## Decisions relied on

- D-8: a hold stops every release; an issue parked to stop one reads as a hold
- D-9: the land job's `issues: write` is warned about only when a lane needs it
- D-32: a milestone is the maintainer's list; nothing proposes or creates one on its own
- D-38: an accepted goal plan may create the milestone it names
- D-50: a release publishes before it moves its references; the milestone write comes after both
- D-63: a new behaviour applies only to a config that sets its key
- D-95: a lane's `close_milestone` lets its release close the milestone and move what's left

## Issues

- shipmill/shipmill#1332: S-068-1, S-068-11, S-068-12
- shipmill/shipmill#1335: S-068-2, S-068-3, S-068-4, S-068-5, S-068-6
- shipmill/shipmill#1333: S-068-7, S-068-8, S-068-10
- shipmill/shipmill#1336: S-068-9
- shipmill/shipmill#1334: S-068-13

## Verification

- S-068-1: loaded configs with the key absent, `true` on a milestone lane, a string, `true` without `milestone`, and on hotfix (`tests/test_close_milestone_key.py`); absent reads `false`, each bad value exits 2 naming `close_milestone` and the lane
- S-068-2: landed 1.1.0 on a stable lane with the key and an empty open milestone 1.1.0 against a bare origin, then ran land.yml's milestone job, `shipmill close-milestone` (`tests/test_milestone_rollover.py`); the tag and release exist, milestone 1.1.0 is closed, and `shipmill close-milestone` prints `milestone 1.1.0 closed`, which the milestone job tees into the Release run's summary. land.yml's milestone job needs land, sets no permissions, so it takes the caller's grant, and no other job waits on it; `shipmill land` itself reads and writes no milestone
- S-068-3: the same with #12 and #14 open and #11 closed in 1.1.0 among milestones 2.0.0, 1.2.0, 1.1.1rc1, 1.0.9, and Someday; #12 and #14 move to 1.2.0, then 1.1.0 closes, #11 is never written, and the summary reads `milestone 1.1.0 closed; #12, #14 moved to 1.2.0`
- S-068-4: with an open issue in 1.1.0 and no stable milestone above it, the rollover writes no milestone, and `shipmill milestones`' read then gives MILESTONE_OVERTAKEN for 1.1.0 with its number
- S-068-5: an rc of a lane with the key, a stable lane without it, and no milestone titled 1.1.0; the first two read no milestone at all, and `shipmill close-milestone` on them exits 0 with a GitHub that fails every milestone call; the third reads the open milestones once and writes none
- S-068-6: `shipmill close-milestone` after `shipmill land` with the close, a move, and the issue read failing; each exits 1 after the tag is on origin, main moved, the GitHub release made, and publish.yml dispatched, and its message names the milestone and the `shipmill gh api -X PATCH repos/{owner}/{repo}/...` command for the write left undone
- S-068-7: `shipmill milestones` with a released, an open-issue, and an untagged milestone (`tests/test_milestone_rollover_status.py`); only the released one reads MILESTONE_RELEASED, with the close through `shipmill gh` when `app_id` is set and plain `gh` without it
- S-068-8: with and without an open milestone above the newest stable tag; MILESTONE_MISSING names the version the lane cuts next and the create only without one
- S-068-9: `watch_state.py` on `shipmill milestones --json` (`tests/test_milestone_rollover_watch.py`) lists both rows, MILESTONE_RELEASED as an action and MILESTONE_MISSING as a person's fix, and github-ship-watch's SKILL.md runs the close under "watch" and never the create
- S-068-10: milestones whose open issues each carry `shipmill-hold` or `needs-decision`, and one with another open issue or an open pull request; the first reads MILESTONE_WAITING with one reason per issue in both forms, the others read none
- S-068-11: `shipmill doctor` on a caller whose land job grants no `issues: write` (`tests/test_close_milestone_key.py`); its land-grant WARN names `close_milestone` and the lanes that set it, and gives no such reason without the key
- S-068-12: every config `shipmill init` writes, across styles, version files, and fragments; init writes `milestone = true` on no lane, so `close_milestone` matches it on every lane, and the policy loads; `docs/release-lanes.md` shows the commented `close_milestone = true` beside `# milestone = true`
- S-068-13: `setup_state.py` on a repo with `[agents]` lacking the labels (`tests/test_setup_state.py`); LABELS_MISSING names `opportunity` and `planned`, `--fix` creates them, and neither is wanted without `[agents]`
