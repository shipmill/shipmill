# S-031: The plugin pins its release; gate sessions load the installed plugin

status: built
serves: G-1, G-2

## Problem

Under D-35 the gate starts no session while the plugin a session would load is older than
the latest release, at any scope. The gate never updates a user-scope install, so every
shipmill release pauses every gate on a host until the maintainer updates that install by
hand (shipmill/shipmill#477). On 2026-10-18 shipmill released four times; after 0.53.0
four gates read `PLUGIN_STALE` all night, and romamo/linkedin-agent#22 sat green with no
session to land it. The update shipmill printed could fail too, while the marketplace
clone was behind (fixed in #480).

The pause treats the symptom. The cause is drift between three things that move apart:

- **The plugin a session loads**, from an install at user, project, or local scope, each
  updated on its own
- **The CLI that plugin runs**, `uvx --from git+https://github.com/shipmill/shipmill@v0`
  in 44 places on main, or a bare `shipmill` from PATH: whatever `@v0` or the person's
  tool install holds today, not the release the skills were written against
- **What the marketplace serves**, `"source": "./"` on `main`: every unreleased commit,
  under the last release's version number

`[agents] plugin_update` (D-23) adds a fourth: it updates the installs keyed on the gate's
checkout, but that checkout is a linked git worktree, and Claude Code resolves a project
or local install there to the main checkout's folder. The update reports success while the
worktree's own entry never moves (shipmill/shipmill#485).

The maintainer decided on #477 to remove the drift instead of pausing on it:

1. **The plugin pins its CLI from PyPI.** Skills and their scripts run `uvx
   shipmill==<the plugin's own version>`. Whatever plugin a session loads, its CLI is the
   same release. `@v0` stops being something shipmill relies on; the tag may stay for
   outside users
2. **The marketplace points at releases, not `main`.** The marketplace entry names the
   release tag, moved by the release workflow with `plugin.json`. The config may declare
   the minimum plugin version it needs; an older plugin stops with "update to >= X" and
   the command, instead of exiting 2 on a key it doesn't know
3. **Gate sessions load the installed plugin, without a pause.** A gate session loads the
   plugin installed from the marketplace, as any session on the host does. Once the
   plugin pins its CLI, a lagging install is an older release that is consistent with
   itself, not a drift, so it is no reason to stop
4. **Report, don't pause.** `doctor`, `status`, and the tick report each install that lags,
   the gate's own CLI when it lags, and a config whose `requires` the plugin doesn't meet,
   each with its fix, plus one desktop notification per release. Only a plugin version
   PyPI doesn't serve yet holds a session, for the minutes until it does

This supersedes D-35's "starts no session" and D-23's updates (D-43, amended by D-44).

The first version of this spec had the gate materialize the latest release into a
versioned cache of its own and start each session with `--plugin-dir` on it. The
maintainer dropped that on 2026-10-21 in shipmill/shipmill#564: the marketplace stays the
single registry and the single way the plugin reaches a host, and Claude Code already
keeps its own copy of each installed version. S-031-8 to S-031-12 and S-031-14 are
dropped; S-031-24 replaces the PyPI wait of S-031-9.

## Behaviour

### The latest release is the marketplace's

`.claude-plugin/marketplace.json` names the release tag instead of `./`:

```json
"plugins": [
  {
    "name": "shipmill",
    "source": {"source": "github", "repo": "shipmill/shipmill", "ref": "v0.54.0"},
    "description": "..."
  }
]
```

A second `[[version_lines]]` entry in `.github/shipmill.toml` moves it with
`.claude-plugin/plugin.json` on every release's stamp commit:

```toml
[[version_lines]]
file = ".claude-plugin/marketplace.json"
pattern = '"ref": "v[^"]+"'
replace = '"ref": "v{version}"'
```

So the marketplace on `main` always serves the files of a tagged release whose
`plugin.json` holds the same version, never the commits merged since. A hotfix cut from
`release/X.Y` stamps that branch, not `main`; it reaches the marketplace with the next
stable release.

D-50 (#598) moves the `ref` after publish instead. The land step supports it through a
lane's `after_publish` (docs/release-lanes.md), and `move-major-tag.yml` now moves the `ref`
with `@v0`. shipmill's own config turns it on, dropping the version line above, in a
follow-up, once a release that knows `after_publish` is on PyPI and the plugin installs
have it: until then a pinned older plugin would refuse the key.

Everywhere shipmill compares an install against "the latest release" (the gate, `doctor`,
`status`, and `skills/github-ship-watch/scripts/watch_state.py`), the latest is the
version in the marketplace entry's `ref` on shipmill/shipmill's default branch, read with
`gh api repos/shipmill/shipmill/contents/.claude-plugin/marketplace.json`, not `gh release
view`. An install can only be updated to what the marketplace serves, so a lag it can't
close is never reported. A `source` that isn't a `github` object with a `ref` of the form
`vX.Y.Z` is refused with exit 2, naming the file and the entry.

### The plugin pins its CLI

Every place the plugin runs the CLI runs `uvx shipmill==<version>`, where `<version>` is
the `version` in the `.claude-plugin/plugin.json` of the same plugin:

- **Skills' prose** (`skills/*/SKILL.md` and `skills/*/references/*.md`): the command is
  written out, `uvx shipmill==0.54.0 <command>`. Further `[[version_lines]]` entries move
  each one on every release, as they move `plugin.json`, so the prose and `plugin.json`
  always name the same version. The prose drops "when `shipmill` isn't on PATH": the
  pinned form is the one form, in a person's session and a headless one (whose allowlist
  already has `Bash(uvx *)`)
- **Skill scripts** (`skills/github-ship-watch/scripts/watch_state.py`,
  `skills/shipmill-setup/scripts/setup_state.py`,
  `skills/github-pr-triage/scripts/shipped.py`): they stay Python 3.10 with no
  dependencies and read the version at run time from `.claude-plugin/plugin.json` three
  folders above `scripts/` (`Path(__file__).resolve().parents[3]`). The wheel force-includes
  `.claude-plugin/plugin.json` as `shipmill/.claude-plugin/plugin.json` (`pyproject.toml`),
  so the same relative path holds when the gate or `doctor` runs a script from the wheel.
  A missing `plugin.json`, one that isn't JSON, or a `version` that isn't `X.Y.Z` exits 2
  naming the path. `watch_state.py --tool` keeps working for a person who passes it
- **The hooks** (`hooks/delivery.py`): the PostToolUse checks (spec 026) run `uvx
  shipmill==<version>` with the version read from `.claude-plugin/plugin.json` one folder
  above `hooks/`, the same way
- **The CLI's own hints** (`UVX` in `src/shipmill/__init__.py`): a command the CLI prints
  for a person to run reads `uvx shipmill==<its own version>`

The 44 matches of `git+https://github.com/shipmill/shipmill@v0` on main split as follows:

| Where | What changes |
|---|---|
| `skills/`, `hooks/`, `src/shipmill/__init__.py` | The pinned form above; a test fails on any `@v0` left under `skills/` or `hooks/` |
| `src/shipmill/launchd.py` (`DEFAULT_TOOL`) | `shipmill@latest` from PyPI (below) |
| `docs/install.md`, `docs/release-lanes.md`, `README.md`, `docs/design/ephemeral-mode.md` | The pinned form for the plugin's commands, `uv tool install shipmill` for a person's CLI |
| `.github/workflows/prepare.yml`, `land.yml`, `operate.yml` (`tool` input default) | Unchanged: outside users' CI, which the floating tag serves (D-31) |
| `CHANGELOG.md`, `docs/specs/0*.md`, tests and fixtures quoting the old form | Unchanged history; tests change only where they assert the new form |

### `requires` in the config

`.github/shipmill.toml` may set a top-level key:

```toml
requires = ">=0.55"   # the oldest shipmill this config is written for
```

Only a lower bound is accepted: `>=` and a version of two or three parts. Anything else
exits 2 naming the key. `src/shipmill/policy.py` reads `requires` before it checks the
other keys, so a config that uses a key this CLI doesn't know, and says which version
introduced it, fails with the cause and the fix, not with "unknown keys":

```
.github/shipmill.toml requires shipmill >=0.56; this is 0.55.0
update the plugin: claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope <scope>
or the CLI: uv tool upgrade shipmill
```

That message exits 2. `watch_state.py` and `setup_state.py`, which read the config
themselves, apply the same check with the same text. `shipmill init`
(`src/shipmill/init.py`) writes `requires = ">=<its own major.minor>"`, and an upgrade
(`src/shipmill/upgrades.py`, spec 014) that adds a key raises `requires` to the upgrade's
version when it is lower. A config without `requires` reads as today. A plugin from before
this spec can't learn the key: it still fails on it with "unknown keys", which is why
`init` and the upgrades write it only from the release that ships this spec.

### Gate sessions load the installed plugin

The gate starts `claude -p` (headless, D-17) and `claude --bg` (interactive) as it does
today: no `--plugin-dir`, no shipmill copy of the plugin, and no `enabledPlugins` change
in their `--settings`. A session loads whichever install of `shipmill@shipmill` applies to
the gate's checkout: a project or local install keyed on the main checkout (Claude Code
resolves a linked worktree's installs to its main checkout, #485), or else the user's.
The gate reads which one that is, as it reads it today for `PLUGIN_STALE`, and never
changes an install.

**The PyPI window.** The release tag, and with it the marketplace's `ref`, moves before
`publish.yml` uploads the package, so for a few minutes a person can install a plugin
whose `uvx shipmill==<version>` PyPI doesn't serve yet. Before a session the gate checks
`https://pypi.org/pypi/shipmill/<version>/json` for the version sessions load. On a 404
it starts no session on that tick and reports `plugin <version> waits for PyPI`; the next
tick tries again. Any other answer is reported and the session starts. This is the only
plugin check that holds a session. `PLUGIN_STALE` and its pause are gone.

The tick's own read, `watch_state.py`, runs the pinned CLI in the same window, and uv
caches PyPI's index up to ten minutes, so a version can stay unlisted after its upload
(#597). A skill script's `uvx shipmill==<version>` that uv finds no such version of runs
once more as `uvx --refresh-package shipmill ...`; when that fails the same way,
`watch_state.py` prints a report-only `PYPI_WAIT` row (`shipmill==<version> waits for
PyPI`, the publish run as its fix) in place of the rows that read owed, and reads the rest.

The hooks' self-test (spec 026, S-026-15 and S-026-16) runs the `hooks/delivery.py` of
the install the session loads, as it does today.

### Report, don't pause

`doctor` (`src/shipmill/doctor.py`), `shipmill status` (`src/shipmill/status.py`, through
`watch_state.py`'s `SHIPMILL_VERSION` and `SHIPMILL_OUTDATED` rows), and the gate's tick
report, each as one line with its fix:

- **Each install that lags the latest release**, at user, project, or local scope: the fix
  #480 prints, `claude plugin marketplace update shipmill && claude plugin update
  shipmill@shipmill --scope <scope>`, run in the install's folder for a keyed one. The
  rows no longer say a gate pauses
- **An install keyed on a gate checkout, a linked worktree** (#485): Claude Code never
  loads it (a session there loads the main checkout's installs or the user's), and no
  `claude plugin` command run there reaches it. The line says so and gives
  the fix: delete the entry keyed on that folder under `shipmill@shipmill` in
  `~/.claude/plugins/installed_plugins.json`. shipmill doesn't edit that file
- **The gate's own CLI when it lags**: `shipmill <version>` older than the latest, with
  `uv tool upgrade shipmill` for a tool install, and for a launchd job on the old
  `git+https://github.com/shipmill/shipmill@v0` source, `shipmill launchd <repo>` again,
  which now writes `shipmill@latest` (`src/shipmill/launchd.py`); the printed fix runs it
  as `uvx shipmill@latest --repo <checkout> launchd <repo>`, keeping the job's `--every`,
  `--app-key`, and `--claude-arg`, since the old CLI would write `@v0` again. A job on any
  other source but `shipmill@latest` (a pinned `--tool`, the pre-org `@v0` URL) gets the
  same fix (#570); a job on `shipmill@latest` gets `launchctl kickstart gui/<uid>/<label>`,
  since its uvx looks the release up on each run. A job on the `@v0` git source runs its
  newest commit, so its CLI never lags, while the tag moves minutes before PyPI serves the
  release the plugin then pins: it gets the same line and rewrite whether or not its CLI
  lags (#597). Every tick
  writes the gate's CLI version to `cli.json` in the gate's state folder, which `doctor`
  and `status` read; until a gate on this release has ticked once, they can't report its
  CLI
- **A config whose `requires` the version sessions load doesn't meet**: the config's
  bound, the version, and the fix (release, or lower `requires`). It starts the session:
  its CLI calls then refuse with the message above

In `doctor` each of these is a WARN, and so is a version sessions load that PyPI doesn't
serve. `[agents] notify = true` (the default) sends one desktop notification per
release on the host, when a release first finds an install that lags: the first gate to
create the marker `~/.cache/shipmill/plugin/<version>.notified` (exclusive create) sends
it, naming each lagging install and its fix, so five gates send one.

### `[agents] plugin_update`: deprecated, then refused

The gate no longer relies on installs keyed on its checkout, so the key has no job left.
It follows the path D-32 set for `[roadmap]`:

- **The minor release that ships this spec** accepts it and ignores it: the gate updates
  no install, whatever its value, and `doctor` WARNs `[agents] plugin_update is deprecated
  (spec 031): gate sessions load the installed plugin and report its lag; delete the key, which
  the next minor release refuses`. The `plugin-update` upgrade (`src/shipmill/upgrades.py`)
  is no longer proposed, and `init` no longer writes the key's comment. The update path,
  dead once nothing calls it, goes in the same release: `daily_update`, `check`, and
  `plugin-check.json` (an old file stays on disk unread), with the rest of
  `shipmill.plugin`'s update code; `shipmill gate --json` drops its `plugin` key with it
- **The same release withdraws an open proposal:** `upgrade --propose` (land.yml's upgrade
  job) closes an open `plugin-update` upgrade issue as withdrawn, with a comment naming spec
  031, and reports the new outcome `withdrawn`, so the issue doesn't read UPGRADE_PENDING
  for an `--apply` that no longer exists
- **The next minor release** only refuses it: `src/shipmill/agents.py` exits 2 with
  `[agents] plugin_update was removed (spec 031); delete it`

### Docs

- `docs/install.md`: the plugin pins its CLI; the marketplace serves releases; gate
  sessions load the installed plugin, and the tick reports its lag; `requires`
- `docs/release-lanes.md`: `requires` beside the other top-level keys; `[agents]
  plugin_update` deprecated
- `skills/shipmill-setup/SKILL.md` and `skills/github-ship-watch/SKILL.md`: the pinned
  command, and the report rows without the pause

## Acceptance criteria

- S-031-1: `.claude-plugin/marketplace.json` on main names the plugin's source as `{"source": "github", "repo": "shipmill/shipmill", "ref": "v<version>"}` with `<version>` equal to `.claude-plugin/plugin.json`'s `version`, and a release's stamp moves both to the new version (a `shipmill stamp` test on a copy of the repo's config)
- S-031-2: The latest release the gate, `doctor`, `status`, and `watch_state.py` compare against is the version in the marketplace entry's `ref` read from shipmill/shipmill's default branch; a marketplace entry without a `github` source or with a `ref` not of the form `vX.Y.Z` exits 2 naming the file and the entry
- S-031-3: No file under `skills/` or `hooks/` contains `git+https://github.com/shipmill/shipmill@v0`, and every `uvx shipmill==<version>` under `skills/` names the version in `.claude-plugin/plugin.json`; a release's stamp moves each of them
- S-031-4: `watch_state.py`, `setup_state.py`, `shipped.py`, and `hooks/delivery.py` run the CLI as `uvx shipmill==<version>` with the version read from the `.claude-plugin/plugin.json` of their own plugin, both in the repo's layout and from the built wheel; a missing or malformed `plugin.json`, or a `version` not of the form `X.Y.Z`, exits 2 naming the path; they run under Python 3.10 with no dependencies
- S-031-5: The built wheel contains `shipmill/.claude-plugin/plugin.json` with the package's version
- S-031-6: A config with `requires = ">=X.Y"` or `">=X.Y.Z"` that the running CLI meets reads as before; one it doesn't meet exits 2 with the bound, the running version, and both update commands, before any unknown-key error the same config would raise; any other `requires` value exits 2 naming the key; `watch_state.py` and `setup_state.py` apply the same check with the same text
- S-031-7: `shipmill init` writes `requires = ">=<its major.minor>"`, and `shipmill upgrade --apply <id>` raises a lower `requires` to the upgrade's version and leaves a higher one unchanged
- S-031-8: dropped in #564, see shipmill/shipmill#564: gate sessions load the installed plugin, no shipmill cache
- S-031-9: dropped in #564, see shipmill/shipmill#564: gate sessions load the installed plugin, no shipmill cache; S-031-24 replaces it
- S-031-10: dropped in #564, see shipmill/shipmill#564: gate sessions load the installed plugin, no shipmill cache
- S-031-11: dropped in #564, see shipmill/shipmill#564: gate sessions load the installed plugin, no shipmill cache
- S-031-12: dropped in #564, see shipmill/shipmill#564: gate sessions load the installed plugin, no shipmill cache
- S-031-13: No tick reads `PLUGIN_STALE`: an install at any scope older than the latest release, with every other check passing, starts the session and adds one tick line naming the install, its scope, its version, the latest, and its fix
- S-031-14: dropped in #564, see shipmill/shipmill#564: gate sessions load the installed plugin, no shipmill cache
- S-031-15: `doctor` and `shipmill status` report each lagging install at user, project, and local scope as a WARN or row with the fix `claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope <scope>` (run in its folder when keyed), and no row or check says a gate starts no session
- S-031-16: An install keyed on a linked git worktree that is a gate checkout is reported by `doctor`, `status`, and the tick as one no session loads, with the fix to delete its entry under `shipmill@shipmill` in `~/.claude/plugins/installed_plugins.json`; shipmill writes nothing to that file
- S-031-17: When the gate's own CLI version is older than the latest, `doctor`, `status`, and the tick report it with `uv tool upgrade shipmill` for a tool install, and with `shipmill launchd <repo>` for a launchd job whose tool is the `@v0` git source
- S-031-18: `shipmill launchd <repo>` writes a job running shipmill from `shipmill@latest` unless `--tool` names another source
- S-031-19: When the config's `requires` isn't met by the version sessions load, `doctor` WARNs and the tick reports the bound, the version, and the fix, and the session still starts
- S-031-20: With `[agents] notify = true`, the first tick on a host to find an install lagging a new release sends one desktop notification naming each lagging install and its fix and creates `~/.cache/shipmill/plugin/<version>.notified`; a tick of any gate on the host that finds the marker sends none; with `notify = false` none is sent and no marker is written
- S-031-21: In the minor release that ships this spec, `[agents] plugin_update = true` changes no install and runs no `claude plugin update`, `doctor` WARNs naming the key, spec 031, and that the next minor release refuses it, and `shipmill upgrade` no longer lists `plugin-update`; the same release removes the update path (`daily_update`, `check`, `plugin-check.json`), drops `shipmill gate --json`'s `plugin` key, and has `upgrade --propose` close an open `plugin-update` upgrade issue as `withdrawn`
- S-031-22: In the minor release after the one that ships S-031-21, a config whose `[agents]` sets `plugin_update` exits 2 naming the key and spec 031
- S-031-23: `docs/install.md`, `docs/release-lanes.md`, `skills/shipmill-setup/SKILL.md`, and `skills/github-ship-watch/SKILL.md` describe the pinned CLI, the marketplace serving releases, gate sessions loading the installed plugin, `requires`, and the `plugin_update` deprecation, and none describes a gate paused on a stale plugin
- S-031-24: While PyPI answers 404 for the version of the install sessions load, the tick starts no session and reports `plugin <version> waits for PyPI`, and the next tick tries again; any other PyPI answer is reported and the session starts; the gate's `claude -p` and `claude --bg` commands carry no `--plugin-dir`

## Out of scope

- The reusable workflows' `tool` input (`prepare.yml`, `land.yml`, `operate.yml`): outside
  users' CI keeps the floating `@v0` tag; moving callers to a pinned version is its own
  spec
- Updating a person's installs: shipmill reports them with the fix and changes none, at
  any scope
- Pre-release plugins (an rc channel in the marketplace): shipmill releases only stable
  and hotfix lanes today
- Editing `~/.claude/plugins/installed_plugins.json`: Claude Code's file, undocumented
- Removing the `@v0` tag: it stays for outside users (D-31 still moves it)

## Decisions relied on

- D-4: `requires` lives in `.github/shipmill.toml`
- D-17: headless sessions run as `claude -p`, unchanged by this spec
- D-31: the one delivery shipmill performs itself is moving its own references, which the marketplace `ref` is, like the floating major tag
- D-32: a deprecated key is accepted with a doctor warning for one minor release, then refused
- D-40: the headless gate's hook self-test still pauses a session; it tests the install the session loads
- D-44 (superseding D-43, which superseded D-35): the plugin pins its CLI from PyPI, the marketplace serves releases, gate sessions load the installed plugin, and stale installs are reported, never paused on

## Issues

- shipmill/shipmill#548: S-031-1, S-031-2, S-031-3, S-031-4, S-031-5
- shipmill/shipmill#549: S-031-6, S-031-7
- shipmill/shipmill#551: S-031-13, S-031-15, S-031-16, S-031-17, S-031-18, S-031-19, S-031-20, S-031-24
- shipmill/shipmill#552: S-031-21, S-031-23
- shipmill/shipmill#553: S-031-22

## Verification

Checked on main at v0.60.0 plus #553's pull request, on 2026-10-21.

- S-031-1: read `.claude-plugin/marketplace.json` and `plugin.json`: the source is `{"source": "github", "repo": "shipmill/shipmill", "ref": "v0.60.0"}` beside `"version": "0.60.0"`, and `.github/shipmill.toml`'s `[[version_lines]]` move both (`doctor` passes each line, one match), held
- S-031-2: `shipmill doctor` on this checkout reads `latest v0.60.0` from the marketplace `ref`, and `watch_state.py` and `src/shipmill/plugin.py` read `.claude-plugin/marketplace.json` from the default branch; the refusal of a non-`github` source or a bad `ref` read in `plugin.py` and `watch_state.py`, held
- S-031-3: no `git+https://github.com/shipmill/shipmill@v0` under `skills/` or `hooks/` (grep, 0 matches); all 11 `uvx shipmill==` under `skills/` read `0.60.0`, each one a `[[version_lines]]` entry, held
- S-031-4: `watch_state.py` and `hooks/delivery.py` read `plugin.json` at `parents[3]` and `parents[1]`, and `watch_state.py --help` names `shipmill==<the version in the plugin's plugin.json>`; `setup_state.py` and `shipped.py` share it; the wheel holds `plugin.json` at the same relative path (S-031-5), held
- S-031-5: `uv build --wheel`, then read `shipmill/.claude-plugin/plugin.json` from the wheel: `"version": "0.60.0"`, the package's version, held
- S-031-6: a config with `requires = ">=99.0"` and an unknown top-level key: `shipmill plan`, `watch_state.py`, and `setup_state.py` each exit 2 with the bound, `this is 0.60.0`, and both update commands, before the unknown key, held
- S-031-7: `init` in a fresh repo writes `requires = ">=0.60"`; `upgrades.py` raises a lower bound to the upgrade's version and keeps a higher or equal one (`bound.floor < needed.floor`), held
- S-031-8: dropped in #564
- S-031-9: dropped in #564
- S-031-10: dropped in #564
- S-031-11: dropped in #564
- S-031-12: dropped in #564
- S-031-13: no `PLUGIN_STALE` in `src/`, `skills/`, or `hooks/` (grep); the tick's launch reports a lagging install with its fix and starts the session (`gate.py`, `plugin_read`), held
- S-031-14: dropped in #564
- S-031-15: `shipmill doctor` on this host WARNs the user install 0.59.1 and the local install 0.58.0 behind v0.60.0, each with `claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope <scope>` (the keyed one run in its folder), and no line says a gate starts no session, held
- S-031-16: the same run WARNs the local install keyed on the gate's linked worktree `tmp/shipmill-gate` as one no session loads, with the entry to delete in `~/.claude/plugins/installed_plugins.json`; nothing in `src/` writes that file, held
- S-031-17: `doctor.plugin_checks` and the tick add the gate's lagging CLI with `GateCli.line`; `launchd.py`'s fix rewrites a job on `@v0` or any source but `shipmill@latest` and kickstarts one on it, held
- S-031-18: `src/shipmill/launchd.py` sets `DEFAULT_TOOL = "shipmill@latest"`, used unless `--tool` names another, held
- S-031-19: `doctor.plugin_checks` WARNs `requires` with the bound, the version sessions load, and the fix, and the tick reports it and launches, held
- S-031-20: `plugin.py` creates `~/.cache/shipmill/plugin/<version>.notified` with an exclusive create before it notifies, only under `notify`, held
- S-031-21: shipped in 0.60.0 (CHANGELOG): no `daily_update`, `check`, or `plugin-check.json` left in `src/` (grep), `upgrade` lists no `plugin-update`, and `WITHDRAWN` closes its open issue; the doctor WARN and the accepted key it describes were that release's, replaced by S-031-22's refusal, held for 0.60.0
- S-031-22: `shipmill plan` on a config with `[agents] plugin_update = false` exits 2 with `shipmill: [agents] plugin_update was removed (spec 031); delete it`, and `shipmill doctor` FAILs the policy with that line; `true` and a non-bool are refused the same way, held
- S-031-23: the four docs carry the pinned command, the marketplace serving release tags, gate sessions loading the installed plugin, `requires`, and `plugin_update` removed, and none matches a gate paused on a stale plugin, held
- S-031-24: `doctor` on this host asks PyPI for 0.58.0, the version sessions load, and passes on its answer; a 404 makes the tick `PYPI_WAIT` with `plugin <version> waits for PyPI` (`plugin.py`, `status.py`), and no `--plugin-dir` in `src/` (grep), held
