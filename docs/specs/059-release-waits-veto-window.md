# S-059: A release waits for the veto window of a notify decision it ships

status: approved
serves: G-1

## Problem

A pull request carrying a `notify` decision merges when it is otherwise ready, inside its veto
window too (S-030, D-48). That is fine while a merge can be reverted. It stops being fine on a
repo whose lane publishes soon after a merge: the release goes out while the veto is still
open, and a published version can only be yanked (shipmill/shipmill#1047, from #1008).

In one connected repo the rc lane has `quiet_minutes = 30` and dispatches a publish to a
package index with no approval step; two merged pull requests were published 53 and 57
minutes after their merges, while `veto_hours` is 24. That repo keeps `security` and
`protected` at `ask`, because `notify` would promise a veto that can't undo the release.

Config can't close the gap: `quiet_minutes` stops at 300, `schedule` windows don't count from
the merge, a short `veto_hours` lapses overnight and applies to every zone, and
`[autonomy] release = "propose"` adds a person's step to every release.

## Behaviour

### The setting

`[gates]` in `.github/shipmill.toml` (D-4) gains `veto_lanes`, in the shape of
`blocker_lanes` and `freeze_lanes`, parsed in `src/shipmill/policy.py` into
`Policy.veto_lanes`:

```toml
[gates]
veto_lanes = ["rc", "stable"]     # a release waits for the veto window of each notify decision it ships
```

Its default is `[]`, so a repo that doesn't set it plans, reads, and releases as it does
today (D-63). A value that isn't a list of lane names exits 2 as `blocker_lanes` does.
`hotfix` is refused with exit 2: a hotfix is started by hand, which never waits (below).

### What a release would ship

The release side tells which notify decisions a candidate ships from the forge alone (N-2),
with no agent running (Q-6). A new read in `src/shipmill/github.py`, used by a new module
`src/shipmill/veto.py`:

- **The items.** The merged pull requests whose merge commit is in the candidate's base and
  not in the lane's newest tag (for a stable promotion, the rc's base and the newest stable
  tag), and the issues each closes by GitHub's closing references. A lane with no tag yet
  reads the pull requests merged in the last 168 hours, the longest veto window
- **The decided markers.** On each item, every comment whose first line is a decided marker,
  `<!-- shipmill:decided zone=<id> until=<UTC time> -->` (S-030), written by the App of
  `[agents] app_id` or by an OWNER, MEMBER, or COLLABORATOR, as `src/shipmill/milestones.py`
  trusts a close-confirmed marker (D-29). An outsider's marker never counts
- **The vetoes.** A comment newer than the marker by an OWNER, MEMBER, or COLLABORATOR,
  without the agent marker (D-62), whose first word is `veto` in any case, that no newer
  trusted `<!-- shipmill:veto-handled -->` comment answers: the reading `triage_state.py`
  gives VETOED (S-030-14), done here in the package

A trusted marker whose `until` isn't a UTC time, or lies more than 168 hours after the
comment, fails the plan with exit 2 naming the item and the comment (Q-1). The read needs
no permission the release caller lacks: its `prepare` job grants `issues: write` and
`pull-requests: read` already.

### The wait

In `src/shipmill/planner.py`, a lane in `veto_lanes` that a trigger made due, and that no gate
holds (`_held`), is read for decisions before it releases. It waits while any item it would
ship has:

- a decided marker whose `until` is later than now, or
- a veto not yet handled, whatever its `until`

The wait is a trigger condition, not a gate: it reads nothing for a lane started by hand, so
a person's hand start (`--lane`, a `workflow_dispatch` run with a lane) releases anyway, the
way to ship an urgent fix. A hand start whose `--actor` is a bot (a login ending in `[bot]`),
or that names no actor, waits as a trigger does, the reading spec 029 gives a breaking
stable release, so an agent that starts a lane can't skip the window. A lane not in
`veto_lanes` reads nothing new.

The waiting lane skips with one reason naming each item, its zone, and when its window ends,
oldest window first:

```
rc: 0.8.0rc17 waits for veto windows: #196 security until 2026-11-10 14:00 UTC, #194 protected until 2026-11-10 14:30 UTC
rc: 0.8.0rc17 waits for veto windows: #196 security vetoed, until the veto is handled
```

The plan goes on to the next lane, as it does for any skip, and `shipmill plan` and
`shipmill plan --dry-run` print the same reason. Once every window has ended and every veto
is handled, the next run's trigger is still due (the main quiet, the window opened since the
last release, the milestone closed), so the first run after the window releases.

### The tick that re-plans

A waiting release ends with no push, so `src/shipmill/ticks.py`'s `needed` asks for the
hourly tick when `veto_lanes` names a lane the policy enables, as it does for a milestone
lane, and `shipmill doctor`'s `schedule` check warns when `release.yml` lacks it (S-015).

### `doctor`

`src/shipmill/doctor.py` adds one `gates` line for a config that sets `veto_lanes`: PASS naming
the lanes, or WARN when the config has no `[agents] app_id`, since only a member's own marker
can then hold a lane.

### Docs

`docs/release-lanes.md` documents `veto_lanes` beside `blocker_lanes` and `freeze_lanes`: what
a release ships, the wait, a person's hand start, and the hourly tick.
`skills/github-issue-triage/references/needs-decision.md`, where it says a `notify` pull request
merges without waiting, adds that a lane in `veto_lanes` holds its release instead.

## Acceptance criteria

- S-059-1: `Policy.parse` of a config without `veto_lanes` gives `Policy.veto_lanes` empty; `veto_lanes = ["rc", "stable"]` gives those lanes; `veto_lanes = ["hotfix"]` and a value that isn't a list of lane names exit 2 naming the key
- S-059-2: With `veto_lanes` empty, `shipmill plan` makes no read of pull requests, issues, or comments beyond today's, and gives the same decision and reason as before this spec for a candidate whose merged pull request carries a decided marker with `until` in the future
- S-059-3: For an rc lane in `veto_lanes` that a trigger made due, a merged pull request in the candidate's base and not in the lane's newest tag that carries the App's decided marker `zone=security until=<now + 1h>` makes the plan skip the lane with `rc: <version> waits for veto windows: #<n> security until <time> UTC`, and with `until=<now - 1m>` the plan releases
- S-059-4: A decided marker on an issue that a merged pull request in the range closes holds the lane as one on the pull request does, and a marker on a pull request merged before the lane's newest tag holds nothing
- S-059-5: A decided marker by an author who is neither the App of `[agents] app_id` nor an OWNER, MEMBER, or COLLABORATOR holds nothing, and a decided marker that isn't the comment's first line holds nothing
- S-059-6: A veto by a COLLABORATOR, its first word `Veto`, after the marker, holds the lane after `until` with the reason `#<n> <zone> vetoed, until the veto is handled`; a newer trusted `<!-- shipmill:veto-handled -->` comment, a veto from a CONTRIBUTOR, or a veto body that carries the agent marker leaves the lane to its window alone
- S-059-7: A lane started by hand with `--lane rc --actor <person>` releases while a window is open; with `--actor shipmill[bot]` or with no `--actor` it skips with the wait's reason
- S-059-8: A lane with no tag yet reads the pull requests merged in the last 168 hours, and a stable promotion reads the range from the newest stable tag to the rc's base
- S-059-9: A trusted decided marker whose `until` isn't a UTC time, or lies more than 168 hours after the comment, makes `shipmill plan` exit 2 naming the item
- S-059-10: `ticks.needed` returns the hourly tick for a policy whose `veto_lanes` names an enabled lane, and `shipmill doctor`'s `schedule` check warns when `release.yml` lacks it
- S-059-11: `shipmill doctor` on a config with `veto_lanes` prints a PASS `gates` line naming the lanes, and a WARN one when the config has no `[agents] app_id`; a config without `veto_lanes` prints no such line
- S-059-12: `docs/release-lanes.md` documents `veto_lanes` (what a release ships, the wait, a person's hand start, the hourly tick), and `needs-decision.md` says a lane in `veto_lanes` holds a `notify` decision's release until its window ends

## Out of scope

- Holding the merge: D-48 keeps a `notify` pull request merging without waiting; this spec holds only the release
- Choosing zones per lane (holding only `security` and `protected`): every decided marker on a shipped item holds; a per-zone filter is a later spec once a repo asks for it
- A veto that arrives after `prepare` planned the release and before `land` publishes it: the window between the two is the run's minutes, and `land` doesn't re-plan
- Deploys under `shipmill operate`: an environment's promotion reads its own bake, not decided markers
- The stable lane's breaking-change proposal (D-39) and `[autonomy] release = "propose"`: they keep their own causes, and a lane they hold is never read for decisions
- A gate-side row for a waiting lane: the plan's reason is the record, and `watch_state.py`'s `BOT_STALLED` stays quiet since the plan doesn't release

## Decisions relied on

- D-1: a hand-started `lane=policy` run evaluates triggers as a scheduled run does, so it waits; only a run that picks a lane is a hand start
- D-4: `veto_lanes` lives in `.github/shipmill.toml`
- D-9: no new permission is asked for, and no new warning shows on a repo that doesn't set `veto_lanes`
- D-16: only an OWNER, MEMBER, or COLLABORATOR's veto counts
- D-29: a decided marker is trusted from the App or an OWNER, MEMBER, or COLLABORATOR
- D-39: a bot's hand start is no person's decision, as for a breaking stable release
- D-48: a `notify` pull request still merges without waiting; the release waits
- D-62: a veto that carries the agent marker is no person's
- D-63: a config that doesn't set the new key behaves as before

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

- shipmill/shipmill#1083: S-059-1, S-059-10, S-059-11
- shipmill/shipmill#1084: S-059-2, S-059-3, S-059-4, S-059-5, S-059-6, S-059-7, S-059-8, S-059-9
- shipmill/shipmill#1086: S-059-12

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
