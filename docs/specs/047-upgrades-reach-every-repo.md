# S-047: The gate's sweep proposes config upgrades, and a fleet report shows who relies on a deprecated key

status: draft
serves: G-1

## Problem

A config upgrade (spec 014) reaches a repo only when that repo cuts a release:
`shipmill upgrade --propose` runs in the `upgrade` job of `.github/workflows/land.yml`, after
a release lands, and nowhere else. A repo that releases rarely, or whose releases wait on a
hold, never hears of the upgrade. Spec 040's `agent-autonomy` upgrade had reached two of eight
connected repos when shipmill/shipmill#761 closed its deprecation window, while one
user-scope plugin (spec 039) puts each new shipmill release in front of every gate on a host
at once.

D-63 (shipmill/shipmill#735) answered the breakage: a config that loaded keeps loading, a
deprecated key or reading warns, and refusing it waits until no connected repo relies on it.
That rule needs two things shipmill lacks today:

- **Migrations that reach every repo.** Without them a deprecated key is relied on forever,
  and D-63's removal never comes
- **A way to check "no connected repo relies on it".** Today the maintainer would open every
  repo's `.github/shipmill.toml` by hand and read it against the deprecation, with nothing
  telling them which repos to open

## Behaviour

### The sweep proposes

The gate's sweep (spec 046, every `[agents] sweep_hours`, 6 by default) runs the upgrade
proposal for its repo before it runs `watch_state.py --json --sweep`, so the sweep's
UPGRADE_PENDING rows already see the issue it opened. It is `upgrades.propose()`
(`src/shipmill/upgrades.py`), called in-process by `src/shipmill/gate.py`, the same code
`shipmill upgrade --propose` runs, with:

- the config of the default branch's head, which the gate's refresh moved its checkout to,
  never a session's branch
- the catalogue of the shipmill the gate runs, which is the plugin's pinned release (spec
  031): a shipmill release that adds an upgrade reaches every gate on the host within
  `sweep_hours` of the plugin moving to it, with no release in any repo
- the repo's `[autonomy] upgrade` level: under `observe` it opens nothing and only closes the
  issues of decided and withdrawn upgrades, as S-014-5 says for the command
- the App's identity (D-14, D-54): the gate writes the issue as the App. A gate whose config
  sets no `[agents] app_id` proposes nothing; its pending upgrades show in `shipmill status`
  and `shipmill doctor` as they do today (S-014-15), with the `--apply` command as the fix

The release workflow's `upgrade` job stays: a repo with no gate still hears of an upgrade on
its next release. Both write the same one issue per id, found by its marker, so a repo with a
gate and a release workflow gets one issue, not two.

### Two shipmills on one issue

The gate's shipmill and the one the release workflow runs (`land.yml`'s `$TOOL`) can be
different releases, and both rewrite the issue. A run never moves an issue backwards:

- it rewrites no issue whose marker records a version newer than its own catalogue's
  version of that upgrade, and reports it `UNCHANGED`
- it leaves alone an issue whose marker names an id its catalogue doesn't know and its
  `WITHDRAWN` map doesn't name (a newer shipmill's upgrade), neither closing nor rewriting it

### When the proposal fails

A failed proposal (GitHub refused the App's write, or a read failed) never stops the tick:
the sweep's reads still run, the tick still walks and launches, and the release lane and
landing go on, as S-014-8 keeps a failed `upgrade` job from stopping a release. The failure is
recorded in `sweep.json` as `"upgrades": {"error": "<first line, naming the upgrade>"}`, and a
successful proposal as `"upgrades": {"proposed": [{"id", "issue", "outcome"}]}`. `shipmill
factory`'s `gate` check (spec 044) reads it and reports a failed proposal as a problem, with
the error and its fix (the App's `issues: write`, as `_named` gives it). The decision line
of the tick that swept names the outcome: `upgrades: 1 opened` or `upgrades failed: <first
line>`.

`shipmill gate --dry-run` proposes nothing and prints the proposal the sweep would make,
from `shipmill upgrade --json`'s list; `--sweep` with `--dry-run` does the same.

### Deprecations, catalogued

Every deprecated key and reading D-63 keeps alive gets an entry in a new catalogue,
`src/shipmill/deprecations.py`:

- an id, such as `agents-prs` or `agents-prompt-land`
- the key or reading, and the release that deprecated it
- its replacement, and the upgrade id that migrates it (`agent-autonomy` for both of spec
  040's), or none
- a check over the parsed config that says whether the config relies on it

The entries at the start are `[agents] prs`, the `[agents] prompt` reading of the land
level (spec 040), and `[roadmap]` (D-32). `shipmill doctor`'s deprecation warnings
(`src/shipmill/doctor.py`) come from this catalogue, so the warning a repo shows and the
report below never disagree. A key shipmill already refuses (`[lanes.stable] min_soak_days`,
`[agents] plugin_update`) has no entry: nothing can rely on it, since its config fails to
load.

### `shipmill deprecations`

A new read-only command (`src/shipmill/cli.py`) answers D-63's question for the maintainer's
connected repos:

- `shipmill deprecations` reads the repos of this host's gate jobs (the launchd jobs `shipmill
  factory` reads); `--repo owner/name`, repeatable, and `--fleet <file>`, github-ship-watch's
  fleet file (`[[repos]] repo = ...`), name the repos instead, together with the host's when
  `--host` is given too. A maintainer whose gates run on several hosts keeps them in one
  fleet file
- for each repo it reads `.github/shipmill.toml` on the default branch through the contents
  API, with no clone, and the repo's `shipmill-upgrade` issues
- it prints one block per catalogued deprecation: its id, its replacement, and each repo
  that relies on it with the state of the migrating upgrade there: `issue #N open`,
  `asked, waiting`, `not now` (`shipmill-upgrade-later`), `declined` (closed without the
  key), `pull request #N open`, or `not proposed`. A deprecation no repo relies on reads
  `none of N repos`
- `shipmill deprecations <id>` prints that deprecation's block alone
- `--json` prints `{"repos": [...], "deprecations": [{"id", "replacement", "upgrade",
  "relied_on_by": [{"repo", "upgrade_state", "issue"}]}]}`

Exit 0 when no repo relies on the deprecations asked about, 1 when one does, and 2 when a
repo can't be read (no access, no config on the default branch, a config that fails to
parse): an unread repo is never counted as one that relies on nothing. No repos to read
(no gate job on this host and no `--repo` or `--fleet`) exits 2 saying so.

### Removing a deprecated key

The decision that refuses a deprecated key or ends a reading (D-63) cites the output of
`shipmill deprecations <id>` that read `none of N repos`, with its date and the repos it read,
in its Why. `docs/release-lanes.md`, where it says how shipmill retires a config key, gives
the steps: release the upgrade, let the sweeps propose it, run `shipmill deprecations <id>`
until it reads none, then decide.

### Docs

- `skills/shipmill-setup/SKILL.md`, The gate: the sweep proposes config upgrades as the App
- `skills/github-ship-watch/SKILL.md`, Config upgrades: issues come from the gate's sweep as
  well as the release workflow
- `docs/install.md`, where it lists the commands: `shipmill deprecations`
- Spec 014, under S-014-8, and spec 046, under S-046-8: a line saying spec 047 adds the
  sweep's proposal

## Acceptance criteria

- S-047-1: a sweep with a pending upgrade, `[autonomy] upgrade = "propose"`, and
  `[agents] app_id` set opens that upgrade's `shipmill-upgrade` issue as the App before
  `watch_state.py --sweep` runs, and that sweep's rows hold its UPGRADE_PENDING row
- S-047-2: the sweep reads the config of the default branch's head, not of a branch a session
  left checked out
- S-047-3: under `[autonomy] upgrade = "observe"` the sweep opens and updates no upgrade
  issue, and still closes the issue of a decided or withdrawn upgrade
- S-047-4: a gate whose config sets no `[agents] app_id` writes no upgrade issue, and
  `shipmill status` lists the pending upgrade with its `--apply` command
- S-047-5: a tick that doesn't sweep runs no upgrade proposal
- S-047-6: with an issue opened by the release workflow, the sweep updates that issue and
  opens no second one for the same id
- S-047-7: a run whose catalogue's version of an upgrade is older than the version the
  issue's marker records leaves the issue's title, body, and labels as they are
- S-047-8: a run leaves open, unchanged, an upgrade issue whose marker names an id that
  neither its catalogue nor `WITHDRAWN` knows
- S-047-9: a failed proposal leaves the tick's walk and launch as they would be without it,
  writes the error to `sweep.json`'s `upgrades`, and `shipmill factory`'s `gate` check
  reports it as a problem with its fix
- S-047-10: the decision line of a tick that swept names the proposal's outcome, and
  `shipmill gate --dry-run` writes no issue
- S-047-11: `src/shipmill/deprecations.py` holds an entry for `[agents] prs`, the
  `[agents] prompt` land reading, and `[roadmap]`, each with its replacement and migrating
  upgrade, and `shipmill doctor`'s deprecation warnings are exactly that catalogue's entries
  the config relies on
- S-047-12: `shipmill deprecations` with `--repo` read for two repos, one setting
  `[agents] prs`, lists that repo under `agents-prs` with its upgrade's state and exits 1;
  with neither setting a deprecated key it reads `none of 2 repos` for each and exits 0
- S-047-13: `shipmill deprecations` reports each of `issue #N open`, `asked, waiting`,
  `not now`, `declined`, `pull request #N open`, and `not proposed` from the repo's
  `shipmill-upgrade` issues and pull requests
- S-047-14: `shipmill deprecations` exits 2 naming the repo when a repo can't be read or its
  config fails to parse, and exits 2 when it has no repos to read
- S-047-15: `shipmill deprecations` with no `--repo` or `--fleet` reads the repos of this
  host's gate jobs, and `--fleet` reads github-ship-watch's fleet file format
- S-047-16: `shipmill deprecations --json` prints the shape given above
- S-047-17: `docs/release-lanes.md` gives the steps to retire a config key, ending with
  `shipmill deprecations <id>` reading none before the decision

## Out of scope

- Opening the upgrade pull request from the sweep: an agent session still does, after the
  maintainer's answer or under `act` (S-014-11, S-014-12); the sweep only opens the issue,
  as the release workflow does
- Refusing a deprecated key automatically once the report reads none: the refusal stays a
  maintainer's decision under D-63, and a repo outside the maintainer's fleet can't be read
- Repos that use shipmill but aren't connected to the maintainer (another owner's public
  repos): `shipmill deprecations` reads only the repos it is given or the host's gates
- A sweep that proposes for a component's home or a chain (spec 017, 043): each repo's own
  gate proposes for its own config
- Changing `[agents] sweep_hours`'s default to reach repos sooner: 6 hours is soon enough for
  an offer

## Decisions relied on

- D-4: settings live in `.github/shipmill.toml`; the proposal reads that file
- D-10: the maintainer accepts or declines; shipmill proposes
- D-14, D-54: the gate writes as the App, and without it shipmill writes nothing
- D-58: the gate's timed sections run on its sweep (it supersedes D-57)
- D-63: a deprecated key is refused only once no connected repo relies on it

## Issues

The build issues, filled in once they are filed.

## Verification

Filled in when the spec reaches `built`.
