# S-029: Stable on every green batch; a breaking change waits for the maintainer

status: built
serves: G-1

## Problem

A time soak checks nothing (shipmill/shipmill#451). `[lanes.stable] promote_from = "rc"`
with `min_soak_days = 3` is what `shipmill init` writes and what romamo/treaty and
cloudfall-dev/cloudfall run: every stable release waits until an rc is three days old. In
those days nobody runs the rc and shipmill reads no telemetry, so the wait catches no
defect; it only adds lead time between a merged fix and the release a plain install gets.
The quality bar wrote that soak in as Q-3: "a stable release ships what a pre-release
already carried".

The maintainer decided in chat on 2026-10-18 (D-39):

- **Continuous delivery.** Proof goes before the merge: CI, the agent review, evals (spec
  025), the delivery hooks (spec 026), and `REVIEW.md` protected areas. After a release:
  fast fix-forward, yank, rollback
- **Stable on every green batch,** as shipmill itself releases (`[lanes.stable]
  quiet_minutes = 30`)
- **A pre-release only where a person's decision is needed:** a breaking change reaches a
  stable release only after the maintainer's decision
- **A soak only when something is observed during it:** users on the pre-release, or
  health, as `[environments]` `bake_minutes` already does. A signal-based soak in place of
  the time soak was considered and rejected
- **A milestone stays:** `milestone = true` (spec 022) is a scope decision, not a soak

Q-3 now reads: "A release ships only code whose CI passed on the exact release commit, and
a breaking change reaches a stable release only after the maintainer's decision". This
spec is the behaviour behind it.

## Behaviour

### Stable on every green batch

A stable lane without `promote_from` already releases main's head when a trigger is due,
and a release's CI runs on its stamp commit before anything is tagged. That stays as it
is; what changes is what shipmill recommends and writes. `shipmill init`
(`src/shipmill/init.py`) writes:

```toml
[lanes.stable]                      # X.Y.Z after every batch of merges; a breaking change waits for you
quiet_minutes = 30
github_release = true
```

No `promote_from`, `min_soak_days`, `schedule`, or `milestone` on the stable lane. The rc
lane is written commented out, as the dev lane is, with the comment "X.Y.ZrcN for people
who try a change first, by hand or on a schedule". The `release.yml` it derives then has no
schedule (`src/shipmill/ticks.py` needs none for this policy): every run starts from a push
or by hand.

### A breaking change waits for the maintainer

A stable candidate is **breaking** when its pending entries bump the major part: with
`[bump] from = "headings"`, at least one entry sits under a heading in the `major` list
(`Breaking` in the default policy). Before 1.0 such a bump moves the minor and the
candidate is still breaking. For a promotion (`promote_from = "rc"`) the entries are those
pending at the rc's base, as the fold reads them (D-25). With `from = "paths"`, which
never bumps the major, no candidate is breaking.

`src/shipmill/planner.py` treats a breaking stable candidate like the hold treats every
stage (D-8):

- **A trigger never releases it.** When quiet time, a window, or a milestone makes the
  stable lane due, the release stage is at most `propose` for that candidate, whatever
  `[autonomy] release` says (`observe` stays `observe`). The plan proposes it with the
  cause `a breaking change waits for the maintainer's decision`
- **The proposal issue** (`src/shipmill/propose.py`, the existing one per lane, labelled
  `shipmill-proposal`) is titled `Ready to release v2.0.0 on stable`. Its body says the
  release holds a breaking change and waits for the maintainer, lists the entries under
  the `major` headings first, then the others, and gives the command that releases it:
  `gh workflow run release.yml -f lane=stable -f dry-run=false`. Later runs keep it up to
  date as main moves, as they do today
- **A later lane still releases in the same run.** rc and dev aren't held: they cut
  pre-releases of the breaking version, so the people who asked for it can try it (spec
  021). A run whose stable candidate is a breaking proposal and that releases rc or dev
  still opens or updates the stable proposal issue; today a release in the same run drops
  the proposals
- **The maintainer's decision is a hand start.** A run started by hand with
  `lane=stable` releases the breaking candidate, and its reason names who started it:
  `stable 2.0.0: ...; breaking, started by @<login>`. A hand start whose triggering actor
  (`$GITHUB_TRIGGERING_ACTOR`, passed to `shipmill plan` as `--actor`) is a bot, a login
  ending in `[bot]`, skips the stable lane with `a breaking release is started by a person,
  not <login>`; an agent writing as the App can't make the decision. `lane=policy` plans
  as a scheduled run does (D-1), so it proposes. The hold still stops a hand start (D-8),
  and `land` closes the proposal issue once the release is tagged, as it does today
- **Non-breaking fixes wait with it.** Once a breaking entry is pending on main, main's
  head holds it, so no stable release cuts main's head without it. A fix that can't wait
  goes out as a hotfix from `release/X.Y`, which is a patch by definition and never
  breaking

Opening the proposal needs `issues: write` on the prepare job and closing it on the land
job, both of which `shipmill init` grants. Following D-9, `src/shipmill/doctor.py` warns
about a missing grant only for a config that can produce a breaking stable candidate: a
stable lane with `[bump] from = "headings"` and a non-empty `major` list. A run that must
open the proposal without the grant fails that step with the permission and the fix, and
never releases the stable lane instead.

### `min_soak_days`: deprecated, then refused

`[lanes.stable] min_soak_days` follows the path D-32 set for `[roadmap]`:

- **The minor release that ships this spec** still reads and honours it, so no repo's
  releases change until its maintainer merges the upgrade below. `shipmill doctor` WARNs:
  `[lanes.stable] min_soak_days is deprecated (spec 029): a time soak checks nothing; run
  shipmill upgrade --apply stable-every-batch, which the next minor release requires`
- **The next minor release** refuses it: `src/shipmill/policy.py` exits 2 with
  `[lanes.stable] min_soak_days was removed (spec 029); delete it, or run shipmill upgrade
  --apply stable-every-batch`. `LaneRule.min_soak_days` and the soak branch of
  `_promotion` go with it

Removing it at once with exit 2 was rejected: clients run shipmill from the floating `@v0`
tag, so the release that removed it would fail every Release run of treaty and cloudfall
before their maintainers saw the upgrade.

### What `promote_from = "rc"` means afterwards

`promote_from = "rc"` stays: the stable lane ships the code of the newest rc after the last
stable release, stamped on that rc's base (D-25), with no age requirement. It is promoted
once a stable trigger is due, so `quiet_minutes` or a window decides when, and D-28 still
skips a promotion whose CI workflows changed since the rc. `init` doesn't write it.
`docs/release-lanes.md` describes it as the choice for a repo that wants every stable
release to be bit for bit a pre-release people already installed (an app store build,
say), and says it adds lead time without adding a check unless someone runs the rc. A
breaking promotion waits for the maintainer like any breaking candidate.

### The upgrade for repos on a soak

A new entry in the spec 014 catalogue (`src/shipmill/upgrades.py`), id
`stable-every-batch`:

- **Applies** to a config whose `[lanes.stable]` sets `min_soak_days`, whatever its value.
  It is decided once that key is gone, so a repo that edits it out by hand is done
- **The edit** removes the `min_soak_days` line from `[lanes.stable]` and keeps
  `promote_from`: with `milestone = true` the promotion is the maintainer's choice of what
  a version holds, and dropping it would ship main's head once the milestone closes. It
  adds `quiet_minutes = 30` only when the table has no trigger at all (no `quiet_minutes`,
  `schedule`, or `milestone`), since a new trigger beside `milestone` would release before
  the milestone is done; every other byte stays (comments, `schedule`, `milestone`, the rc
  lane). The catalogue's edit today only adds a key, so it gains removals
- **The text for people:** stable releases ship every batch of merges whose CI passed,
  instead of an rc three days old that nobody ran; a breaking change still waits for the
  maintainer's hand start; the rc lane stays for people who pin pre-releases and can be
  deleted along with `promote_from` when no milestone gates the stable lane
- **Proposing and declining** work as for every upgrade (S-014): one `shipmill-upgrade`
  issue, the needs-decision question under `propose`, a pull request on an accepting
  answer. Closing the issue declines it, and its body says the next minor release refuses
  the key, so a decline means deleting it by hand before then

### Docs

- `docs/release-lanes.md`: the lanes table (stable "main's head after every green batch,
  or an rc with `promote_from`"), "How a release works", "When something is wrong in a
  batch" (fix-forward, revert, hotfix, rollback; no soak), the policy example without
  `min_soak_days`, the breaking hold, `promote_from` as above, and the deprecation
- `README.md` and `site/index.html`: no stable release described as a soaked rc
- `skills/shipmill-setup/SKILL.md`: the lane table recommends stable on `quiet_minutes`,
  an rc lane only for people who try pre-releases, and no soak
- `skills/github-issue-triage/references/triage-rubric.md`: the "Release candidate or
  soak" row becomes "a breaking release waiting for the maintainer"

## Acceptance criteria

- S-029-1: With `[lanes.stable] quiet_minutes = 30` and no `promote_from`, `[autonomy] release = "act"`, main quiet, and a pending entry under `### Breaking`, `shipmill plan` proposes stable `2.0.0` from `1.4.0` with the cause `a breaking change waits for the maintainer's decision` and releases nothing on stable; from `0.4.2` it proposes `0.5.0` the same way
- S-029-2: With `promote_from = "rc"`, a promotion whose rc's base holds a pending `### Breaking` entry is proposed the same way when its trigger is due, never released by the trigger
- S-029-3: A stable candidate with no entry under a `major` heading, and every candidate under `[bump] from = "paths"`, releases on its trigger under `act` exactly as before
- S-029-4: A run whose stable candidate is a breaking proposal and whose rc or dev lane releases reports the release and opens or updates the stable proposal issue in the same run
- S-029-5: The proposal issue for a breaking candidate is titled `Ready to release v<version> on stable`, its body says it waits for the maintainer's decision, lists the entries under `major` headings before the others, and gives `gh workflow run release.yml -f lane=stable -f dry-run=false`
- S-029-6: A `workflow_dispatch` run with `lane=stable` and `--actor <person>` releases the breaking candidate, with `breaking, started by @<person>` in its reason; with `--actor <name>[bot]` it skips stable with `a breaking release is started by a person, not <name>[bot]`; `lane=policy` proposes; an open `shipmill-hold` issue still skips the hand start
- S-029-7: `shipmill doctor` WARNs about the prepare or land job lacking `issues: write` for a config whose stable lane has `[bump] from = "headings"` with a non-empty `major` list, and stays silent about it when `major` is empty or `from = "paths"`
- S-029-8: While `min_soak_days` is deprecated, a policy that sets it still holds a promotion until the rc is that many days old, and `shipmill doctor` WARNs naming `min_soak_days`, spec 029, and `shipmill upgrade --apply stable-every-batch`
- S-029-9: In the minor release after the one that ships S-029-8, a policy whose `[lanes.stable]` sets `min_soak_days` exits 2 naming the key, spec 029, and `shipmill upgrade --apply stable-every-batch`
- S-029-10: `promote_from = "rc"` without `min_soak_days` promotes the newest rc after the last stable release as soon as a stable trigger is due, whatever the rc's age, and still defers when `.github/workflows/` changed since the rc (D-28)
- S-029-11: `shipmill init` writes `[lanes.stable]` with `quiet_minutes = 30` and `github_release = true` and none of `promote_from`, `min_soak_days`, `schedule`, or `milestone`, writes the rc lane only as comments, and the `release.yml` it derives has no `schedule` trigger
- S-029-12: `shipmill upgrade` lists `stable-every-batch` for a config whose `[lanes.stable]` sets `min_soak_days`, and not for one without it; `--apply stable-every-batch` removes the `min_soak_days` line, keeps `promote_from`, adds `quiet_minutes = 30` only when the table had no `quiet_minutes`, `schedule`, or `milestone`, and leaves every other byte of the file unchanged
- S-029-13: `docs/release-lanes.md`, `README.md`, `site/index.html`, `skills/shipmill-setup/SKILL.md`, and `skills/github-issue-triage/references/triage-rubric.md` describe no stable release as a soaked rc, and `docs/release-lanes.md` documents the breaking hold, `promote_from` without an age, and the `min_soak_days` deprecation

## Out of scope

- Consumer-side cooldown (Renovate `minimumReleaseAge`, uv `exclude-newer`): the
  consumer's tool for deciding when to take a release, not the publisher's
- A signal-based soak (promotion on downloads, requester confirmations, error rates):
  rejected in the decision; a soak comes back only with something observed, and health
  already has `bake_minutes` in `[environments]`
- Running downstream consumers' tests before a merge (a dependent's CI against the pull
  request): proof that moves before the merge, the direction this spec takes, but its own
  spec; a possible follow-up
- Yank and rollback of a package release: `operate` rolls back environments today, and a
  registry yank is the platform's (D-31)
- Holding a minor bump (`Added`, `Changed`, `Removed`) for the maintainer: additive or
  documented changes ship every batch; only the `major` list waits

## Decisions relied on

- D-1: `lane=policy` plans as a scheduled run does, so it proposes a breaking candidate
- D-4: the lane keys live in `.github/shipmill.toml`
- D-8: the hold stops a hand start; the breaking hold borrows its "act becomes propose"
- D-9: doctor warns about `issues: write` only for a config that can propose a breaking release
- D-14: the upgrade's issue and pull request are written as the App
- D-25: a promotion's pending entries are read at the rc's base, as the fold reads them
- D-28: a promotion still skips when the CI workflows changed since its rc
- D-31: yanking and redeploying are the platform's
- D-32: a deprecated key is accepted with a doctor warning for one minor release, then refused
- D-39: stable on every green batch; a breaking change waits for the maintainer; a soak only when something is observed

## Issues

- shipmill/shipmill#459: S-029-1, S-029-2, S-029-3, S-029-10
- shipmill/shipmill#462: S-029-4, S-029-5, S-029-6
- shipmill/shipmill#460: S-029-7, S-029-8
- shipmill/shipmill#461: S-029-11, S-029-12
- shipmill/shipmill#463: S-029-13
- shipmill/shipmill#464: S-029-9

## Verification

- S-029-1: ran the `test_s029_1` tests in `tests/test_breaking_hold.py` and read `src/shipmill/planner.py`, whose `BREAKING` cause turns a due breaking stable candidate under `act` into a proposal; `shipmill plan` proposes `2.0.0` from `1.4.0` and `0.5.0` from `0.4.2` with that cause and releases nothing on stable, `observe` stays `observe`; all pass
- S-029-2: ran the `test_s029_2` tests, a promotion whose rc's base holds a pending `### Breaking` entry is proposed with the same cause when its trigger is due, and a breaking entry merged after the rc doesn't hold it; all pass
- S-029-3: ran the `test_s029_3` tests, a candidate with no `major` entry and every candidate under `[bump] from = "paths"` release on their trigger under `act`; all pass
- S-029-4: ran the `test_s029_4` tests and the one in `tests/test_autonomy.py` naming it, and read the planner's release branch, which carries the waiting breaking stable proposal in the `Decision`; a run whose rc releases reports the release and opens or updates the stable proposal issue, and a non-breaking stable carries none; all pass
- S-029-5: ran `test_s029_5_the_breaking_proposal_issue_lists_the_breaking_entries_first` and read `src/shipmill/propose.py`, the issue is titled `Ready to release v2.0.0 on stable`, its body says it waits for the maintainer's decision, sorts the `major` headings first, and gives `gh workflow run release.yml -f lane=stable -f dry-run=false`; passes
- S-029-6: ran the `test_s029_6` tests and read the planner's hand-start branch, a `lane=stable` start with `--actor <person>` releases with `breaking, started by @<person>`, a `<name>[bot]` actor skips with `a breaking release is started by a person, not <name>[bot]`, `lane=policy` proposes, an open `shipmill-hold` issue skips the hand start, and `land` closes the proposal; all pass
- S-029-7: ran the `test_s029_7` tests in `tests/test_doctor_stable.py`, `doctor` WARNs about the prepare and land jobs lacking `issues: write` for `from = "headings"` with `major = ["Breaking"]`, and is silent for `major = []` and `from = "paths"`; all pass
- S-029-8: held in 0.53.0, the release that shipped it: at `v0.53.0`, `src/shipmill/planner.py` still skips a promotion with `no rc has soaked N day(s)`, `doctor` WARNs `[lanes.stable] min_soak_days is deprecated (spec 029) ... run shipmill upgrade --apply stable-every-batch`, and `test_s029_8_a_deprecated_soak_still_holds_a_promotion_and_doctor_warns` and `test_s029_8_doctor_warns_whatever_the_value_and_not_without_the_key` assert both; the window is over on main (S-029-9), where `test_s029_9_doctor_fails_the_policy_with_the_refusal_and_the_upgrade_fixes_it` proves the WARN became the policy FAIL; passes
- S-029-9: ran the `test_s029_9` tests, and `shipmill plan --dry-run` on a scratch repo whose `[lanes.stable]` sets `min_soak_days = 3` exits 2 with `[lanes.stable] min_soak_days was removed (spec 029); delete it, or run shipmill upgrade --apply stable-every-batch`; 0.53.0 to 0.55.0 honoured the key with the warning, and the refusal (#481, a `### Removed` entry) ships in the next minor release; all pass
- S-029-10: ran the `test_s029_10` tests, `promote_from = "rc"` without `min_soak_days` promotes an rc cut 0 days ago once a stable trigger is due, and still defers when `.github/workflows/` changed since the rc; all pass
- S-029-11: ran `shipmill init` in a scratch repo, `[lanes.stable]` holds only `quiet_minutes = 30` and `github_release = true`, the rc lane is comments only, and `release.yml` triggers on `push` and `workflow_dispatch` with no `schedule`; the `test_s029_11` tests pass
- S-029-12: ran `shipmill upgrade --apply stable-every-batch` on a scratch config with `promote_from = "rc"` and `min_soak_days = 3` and no trigger, it removed the `min_soak_days` line, kept `promote_from`, the comment, and the rc lane, and added `quiet_minutes = 30`; the `test_s029_12` tests (listing only while the key is set, no trigger beside `schedule` or `milestone`, every other byte unchanged, CRLF kept) pass
- S-029-13: searched the five files for "soak": only `skills/shipmill-setup/SKILL.md` ("no soak", the refused key) and `docs/release-lanes.md`'s deprecation paragraph mention it; `docs/release-lanes.md` documents the breaking hold, `promote_from` "whatever its age", and the deprecation; the `test_s029_13` tests pass
