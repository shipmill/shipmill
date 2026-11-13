# S-056: A land window: pull requests of a held class merge only inside configured hours, and the queue drains when it opens

status: approved
serves: G-1

## Problem

In repos where a merge to the default branch deploys, the maintainer wants risky changes to
land only while someone can watch, and never during a daily restart: green pull requests of
labelled classes merge only inside configured hours, and the rest queue (#1051, from #1031,
the maintainer's request). Today the rule is a line in `[agents] prompt`, which a session can
misread, and nothing drains the queue: on 2026-11-10 pull requests labelled `rollout:queued`
stayed unmerged inside an open window, because no tick noticed that the window had opened.

shipmill's only time-based hold is the release lanes' `freeze` (`docs/release-lanes.md`),
which holds a lane's release, not a pull request's merge.

The window decides when shipmill merges; the deploy that follows stays the platform's (N-1,
D-31).

## Behaviour

### The config

A new section of `.github/shipmill.toml` (D-4), read from the default branch, never from a
pull request, loaded and checked in `src/shipmill/land_window.py`:

```toml
[land.window]
timezone = "Asia/Nicosia"                      # required: an IANA zone
open = ["Mon-Thu 10:00-18:00", "Fri 10:00-14:00"]
closed = ["08:00-08:30"]                       # a daily restart
labels = ["rollout:normal", "rollout:high"]    # required: the held classes
queued_label = "rollout:queued"                # default "land-queued"
spacing_minutes = 30                           # default 0: no spacing
bypass_labels = ["revert", "incident"]         # default none
```

- An `open` or `closed` entry is `[<days> ]HH:MM-HH:MM`, its days in the lanes' schedule syntax
  (`daily`, `Mon`, `Mon-Fri`, `Mon,Wed`; `src/shipmill/schedule.py`), and no days meaning
  daily. The end is after the start on the same day: a window across midnight is two entries
- The window is open at a moment, in `timezone`, when the moment falls inside an `open` entry
  (any moment, when `open` is left out) and inside no `closed` entry; the start is inside, the
  end is not
- A pull request is held when it carries one of `labels` and none of `bypass_labels`. Any other
  pull request, unlabelled or bypassed, merges at any time, as today
- An unknown key, a missing `timezone` or `labels`, an unknown zone, a malformed entry, a
  negative `spacing_minutes`, or a label in both `labels` and `bypass_labels` exits 2 naming
  the key and the fix, from every command that reads the section (Q-1). `shipmill doctor`
  FAILs on it with the same message, and `skills/shipmill-setup/scripts/setup_state.py`
  reports `LABELS_MISSING` naming `queued_label` when the repo lacks it
- Without `[land.window]` nothing in this spec runs and every merge is judged as today

### `shipmill window`

`shipmill window --json [--ref <ref>]`, in `src/shipmill/cli.py`, reads the section at the
ref (default origin/HEAD) and prints one object: `configured`, `open` (now), `opens` (the next
opening, when closed now), `closes` (when open now), `labels`, `bypass_labels`,
`queued_label`, `spacing_minutes`, `last_held_merge` (the time of the newest merged pull
request into the default branch carrying one of `labels`, read from GitHub), and `next_merge`
(when the spacing allows the next held merge; now when it already does). It reads nothing
else and writes nothing.

### The gate's verdict: QUEUED

`skills/github-pr-triage/scripts/pr_gate.py` reads the window with `shipmill window --json
--ref <the base>`, run as it runs `decide classify`, once per base branch and pass, for a
base whose config has `[land.window]`. A held pull request that would otherwise read READY
reads QUEUED, exit 10, when the window is closed, with
`  queued: held by the land window (<its held labels>); opens <YYYY-MM-DD HH:MM> <timezone>`,
or when the window is open and `next_merge` is later than now, with
`  queued: spacing: the next held merge after <HH:MM> <timezone>`. A pull request that is red,
pending, refused, or waiting on a decision keeps that verdict: QUEUED only takes the place of
READY. QUEUED ranks between PENDING and BLOCKED, and `--wait` doesn't poll on it. A
`shipmill window` that fails makes `pr_gate.py` exit 2 for every pull request of that base,
so a malformed section holds every merge there rather than letting a held one through.

### Where the merge refusal lives

The window is a `pr_gate.py` verdict and nothing else: spec 055 makes `shipmill gh pr merge`
(and the merge API `PUT`) run `pr_gate.py` and refuse anything but READY, so a QUEUED pull
request is refused there with no check of the merge path's own. On that refusal the merge
also adds `queued_label` to the pull request, as the App, so the queue is on GitHub. After a
merge that gh ran and that exited 0, it removes `queued_label` when the pull request carries
it. A session asked to land a QUEUED pull request runs the merge as for a READY one, and the
merge queues it.

### The watch reports the queue, and the gate drains it

`skills/github-ship-watch/scripts/watch_state.py` reads the window with `shipmill window
--json`, and the queue as the open pull requests that carry `queued_label`, oldest first by
when the label was last added (the newest `LabeledEvent` adding it):

- When the window is open and `next_merge` is now or earlier, the oldest queued pull request
  is reported as an action, `LAND_DUE  #N <title>: the land window is open; queued since
  <time>`, with the fix `/shipmill:github-pr-triage <owner/repo>`, and the watch exits 1
- Every other queued pull request is reported as `LAND_QUEUED  #N <title>: <why>`, the why
  being the next opening, the spacing, or `behind #M`; it is no action and leaves the exit
  code as it was
- A queued pull request leaves the `PRS_OPEN` row, so it is reported once

`src/shipmill/walk.py` places `LAND_DUE` in tier 3, before `PRS_OPEN`, as a land-stage item
(taken only when `[autonomy] land` isn't `observe`, like `PRS_OPEN`). The change check counts
as a change, while an open pull request carries `queued_label`, the window opening since the
cursor, and `next_merge` passing since the cursor while the window is open, so a tick that
reads nothing else on GitHub still hands the queue's head. The change check already reads the
open pull requests' labels, so this costs no GitHub read beyond `shipmill window`'s.

### The skills

`skills/github-pr-triage/SKILL.md` and `references/landing.md` name the QUEUED verdict and
`LAND_DUE`, and `skills/github-ship-watch/SKILL.md` lists `LAND_DUE` and `LAND_QUEUED`.
`skills/shipmill-setup/SKILL.md` names `[land.window]` as the way to hold merges to hours, in
place of a line in `[agents] prompt`.

## Acceptance criteria

- S-056-1: A config whose `[land.window]` has an unknown key, no `timezone` or `labels`, an unknown zone, an entry that isn't `[<days> ]HH:MM-HH:MM` with its end after its start, a negative `spacing_minutes`, or a label in both `labels` and `bypass_labels` makes `shipmill window` exit 2 naming the key, and `shipmill doctor` FAIL with the same message
- S-056-2: `shipmill window --json` reads the window as open at a moment inside an `open` entry and inside no `closed` entry, in `timezone`, with an entry without days read as daily and a config without `open` read as open outside `closed`; it prints `opens` when closed and `closes` when open, and `configured: false` without the section
- S-056-3: `shipmill window --json` prints `last_held_merge`, the newest merge into the default branch of a pull request carrying one of `labels`, and `next_merge`, that time plus `spacing_minutes`, or now when that has passed or `spacing_minutes` is 0
- S-056-4: `pr_gate.py`, on a base with `[land.window]`, reads a pull request carrying a held label and no bypass label, that would otherwise read READY, as QUEUED, exit 10, with a `queued:` line naming its labels and the next opening, while the window is closed
- S-056-5: `pr_gate.py` reads such a pull request QUEUED with a `queued: spacing:` line while the window is open and `next_merge` is later than now, and READY once it isn't
- S-056-6: `pr_gate.py` reads READY, at any time, a pull request with no held label, one carrying a bypass label, and any pull request on a base without `[land.window]`; a held pull request that is red, pending, refused, or waiting on a decision keeps that verdict
- S-056-7: `pr_gate.py` exits 2 for a pull request whose base's `shipmill window` fails
- S-056-8: With spec 055's merge gate (S-055-1), `shipmill gh pr merge` of a QUEUED pull request exits 2 without running gh and adds `queued_label` to it as the App; a merge gh ran that exited 0 removes `queued_label` from the pull request carrying it
- S-056-9: `watch_state.py`, with the window open and `next_merge` now or earlier, reports the oldest queued pull request (by its newest `LabeledEvent` adding `queued_label`) as `LAND_DUE` with the fix `/shipmill:github-pr-triage <owner/repo>` and exits 1, and every other queued one as `LAND_QUEUED` with its reason, an info row
- S-056-10: `watch_state.py`, with the window closed, reports each queued pull request as `LAND_QUEUED` naming the next opening and reports no `LAND_DUE`; a queued pull request is not in `PRS_OPEN`
- S-056-11: The gate's change check reads a change when, with an open pull request carrying `queued_label`, the window opened or `next_merge` passed while it is open since the cursor, with no other change on GitHub; without a queued pull request, neither counts
- S-056-12: `walk.py` places `LAND_DUE` in tier 3 before `PRS_OPEN` and takes it only when `[autonomy] land` isn't `observe`
- S-056-13: `setup_state.py` reports `LABELS_MISSING` naming the config's `queued_label` when the repo lacks it, and wants no such label without `[land.window]`
- S-056-14: `github-pr-triage`'s `SKILL.md` and `landing.md` name QUEUED and `LAND_DUE`, `github-ship-watch`'s `SKILL.md` lists `LAND_DUE` and `LAND_QUEUED`, and `shipmill-setup`'s `SKILL.md` names `[land.window]` for holding merges to hours

## Out of scope

- Labelling pull requests with a class (`rollout:normal`): the repo's own triage or prompt does it, as today; this spec reads the labels
- Holding the deploy itself or anything after the merge: the platform's (N-1, D-31)
- Release lanes' `freeze` and `schedule`: unchanged; a land window doesn't hold a release
- A window per base branch or per path: one window per repo, for pull requests into the default branch
- Merges outside `shipmill gh` (plain gh, the web UI): a person's merge is theirs, as in spec 055
- Ordering enforced by refusal: a younger queued pull request isn't refused while an older one waits; the gate hands the oldest first, and the spacing holds the rate

## Decisions relied on

- D-4
- D-31
- D-51
- D-58
- D-63

## Issues

## Verification
