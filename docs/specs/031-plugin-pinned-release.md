# S-031: The plugin pins its release; the gate loads it per session

status: approved
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
3. **The gate loads the latest release per session, without a pause.** It materializes
   the latest version once into an immutable versioned cache and starts each session with
   `--plugin-dir` on that folder. No global install changes, running sessions keep their
   folder, and a new release is picked up on the next tick
4. **Report, don't pause.** `doctor`, `status`, and the tick report each install that lags,
   the gate's own CLI when it lags, and a config whose `requires` the plugin doesn't meet,
   each with its fix, plus one desktop notification per release. Only a failed
   materialization of the needed version stops the gate's sessions

This supersedes D-35's "starts no session" and D-23's updates (D-41).

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

### The gate loads the latest release per session

Before a session, on every tick that would launch (`src/shipmill/gate.py`,
`src/shipmill/plugin.py`), the gate:

1. **Reads the latest version** from the marketplace, as above
2. **Checks PyPI serves it**: `https://pypi.org/pypi/shipmill/<version>/json` answers
   200. The tag is pushed before `publish.yml` uploads the package, so for a few minutes
   a release is in the marketplace and not on PyPI, and its plugin's `uvx
   shipmill==<version>` would fail. Until PyPI serves it, the gate uses the newest version
   already in the cache and the tick says `plugin: 0.55.0 waits for PyPI; sessions load
   0.54.0`. A 404 is "not yet"; any other answer is a failure, below
3. **Materializes it once** into `~/.cache/shipmill/plugin/<version>/`
   (`$XDG_CACHE_HOME/shipmill/plugin/` when that is set): `git clone --depth 1 --branch
   v<version> https://github.com/shipmill/shipmill` into a temporary folder beside it
   (`.tmp-<random>`), the clone's `.git` removed, its `.claude-plugin/plugin.json` checked
   to hold `<version>`, then renamed to `<version>`. A folder that already exists is never
   written again; when another gate on the host renamed its copy first, the gate deletes
   its own temporary folder and uses the existing one. An existing folder whose
   `plugin.json` doesn't hold its name is a failure naming it and the fix (`rm -rf
   <folder>`)
4. **Starts the session on it**: `claude -p` (headless, D-17) and `claude --bg`
   (interactive) both get `--plugin-dir <that folder>`, and their `--settings` JSON gains
   `"enabledPlugins": {"shipmill@shipmill": false}` beside the `env` it carries today
   (D-14), so an install of shipmill at user, project, or local scope doesn't load a
   second copy. The gate refuses `--plugin-dir` and `--plugin-url` in `--claude-arg`, as
   it refuses the flags in `HEADLESS_REFUSED`

**Verify first**, in the build issue that adds step 4 and before its code: with
`shipmill@shipmill` enabled at user scope, start `claude -p --plugin-dir <cache folder>`
with and without the `enabledPlugins` setting, and record in the pull request which
`shipmill:` skills and hooks load from where. The setting stays either way (it costs
nothing when Claude Code already prefers the folder), and if it also disables the
`--plugin-dir` copy, the pull request stops and asks.

No global install is changed. A session keeps the folder it started with, so a release
during a session changes nothing for it; the next tick's session loads the new folder.
Five gates on one host share the cache and clone each release once. The cache is never
pruned by this spec.

**What stops a session.** Only a failure to get a usable version: the marketplace can't be
read, PyPI answers with an error, the clone or the check fails, and the cache holds no
version PyPI serves. The tick is then `PLUGIN_FAILED`, naming the step, its error, and the
fix, and stops no session and starts none; the next tick tries again. A failure while an
older cached version PyPI serves exists starts the session on that version and reports the
failure. `PLUGIN_STALE` and its pause are gone.

The hooks' self-test (spec 026, S-026-15 and S-026-16) runs the `hooks/delivery.py` of the
folder the session will load, so it tests what the session runs.

### Report, don't pause

`doctor` (`src/shipmill/doctor.py`), `shipmill status` (`src/shipmill/status.py`, through
`watch_state.py`'s `SHIPMILL_VERSION` and `SHIPMILL_OUTDATED` rows), and the gate's tick
report, each as one line with its fix:

- **Each install that lags the latest release**, at user, project, or local scope: the fix
  #480 prints, `claude plugin marketplace update shipmill && claude plugin update
  shipmill@shipmill --scope <scope>`, run in the install's folder for a keyed one. The
  rows no longer say a gate pauses
- **An install keyed on a gate checkout, a linked worktree** (#485): Claude Code never
  loads it (a session there loads the main checkout's installs, and gate sessions load the
  cache), and no `claude plugin` command run there reaches it. The line says so and gives
  the fix: delete the entry keyed on that folder under `shipmill@shipmill` in
  `~/.claude/plugins/installed_plugins.json`. shipmill doesn't edit that file
- **The gate's own CLI when it lags**: `shipmill <version>` older than the latest, with
  `uv tool upgrade shipmill` for a tool install, and for a launchd job on the old
  `git+https://github.com/shipmill/shipmill@v0` source, `shipmill launchd install <repo>`
  again, which now writes `shipmill@latest` (`src/shipmill/launchd.py`)
- **A config whose `requires` the version sessions load doesn't meet**: the config's
  bound, the version, and the fix (release, or lower `requires`). It starts the session:
  its CLI calls then refuse with the message above

In `doctor` each of these is a WARN; a materialization failure, run as the gate would run
it, is a FAIL. `[agents] notify = true` (the default) sends one desktop notification per
release on the host, when a release first finds an install that lags: the first gate to
create the marker `~/.cache/shipmill/plugin/<version>.notified` (exclusive create) sends
it, naming each lagging install and its fix, so five gates send one.

### `[agents] plugin_update`: deprecated, then refused

The gate no longer relies on installs keyed on its checkout, so the key has no job left.
It follows the path D-32 set for `[roadmap]`:

- **The minor release that ships this spec** accepts it and ignores it: the gate updates
  no install, whatever its value, and `doctor` WARNs `[agents] plugin_update is deprecated
  (spec 031): gate sessions load the latest release from the cache; delete the key, which
  the next minor release refuses`. The `plugin-update` upgrade (`src/shipmill/upgrades.py`)
  is no longer proposed, and `init` no longer writes the key's comment
- **The next minor release** refuses it: `src/shipmill/agents.py` exits 2 with `[agents]
  plugin_update was removed (spec 031); delete it`. `daily_update`, `check`, and
  `plugin-check.json` go with it

### Docs

- `docs/install.md`: the plugin pins its CLI; the marketplace serves releases; how the
  gate loads the latest release; `requires`; the cache folder
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
- S-031-8: A tick that would launch, with the latest version not in the cache, clones the tag into a temporary folder beside `~/.cache/shipmill/plugin/`, checks its `plugin.json` holds the version, removes `.git`, and renames it to `<version>`; a second tick finds the folder and clones nothing; a folder renamed in first by another gate is used and the tick's own temporary folder is removed; `XDG_CACHE_HOME` moves the cache when set
- S-031-9: While PyPI answers 404 for the latest version, the tick starts the session on the newest cached version and reports `<latest> waits for PyPI; sessions load <cached>`
- S-031-10: When the marketplace read, the PyPI read (other than 404), the clone, or the version check fails and the cache holds no version PyPI serves, the tick is `PLUGIN_FAILED` naming the step, the error, and the fix, stops no session, and starts none; with such a cached version it starts the session on it and reports the failure; an existing cache folder whose `plugin.json` doesn't hold its name is a failure naming the folder
- S-031-11: The headless `claude -p` and interactive `claude --bg` commands the gate starts carry `--plugin-dir <cache>/<version>` and a `--settings` JSON whose `enabledPlugins` sets `shipmill@shipmill` to false beside the `env` it carried before; `--claude-arg --plugin-dir` and `--claude-arg --plugin-url`, alone or as `--flag=value`, are refused
- S-031-12: With `shipmill@shipmill` enabled at user scope on the host, a headless gate session lists each `shipmill:` skill once, loaded from the cache folder (a probe against a real `claude`, recorded in the pull request that builds S-031-11)
- S-031-13: No tick reads `PLUGIN_STALE`: an install at any scope older than the latest release, with every other check passing, starts the session and adds one tick line naming the install, its scope, its version, the latest, and its fix
- S-031-14: The hooks' self-test before a session runs the `hooks/delivery.py` of the cache folder the session will load
- S-031-15: `doctor` and `shipmill status` report each lagging install at user, project, and local scope as a WARN or row with the fix `claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope <scope>` (run in its folder when keyed), and no row or check says a gate starts no session
- S-031-16: An install keyed on a linked git worktree that is a gate checkout is reported by `doctor`, `status`, and the tick as one no session loads, with the fix to delete its entry under `shipmill@shipmill` in `~/.claude/plugins/installed_plugins.json`; shipmill writes nothing to that file
- S-031-17: When the gate's own CLI version is older than the latest, `doctor`, `status`, and the tick report it with `uv tool upgrade shipmill` for a tool install, and with `shipmill launchd install <repo>` for a launchd job whose tool is the `@v0` git source
- S-031-18: `shipmill launchd install` writes a job running shipmill from `shipmill@latest` unless `--tool` names another source
- S-031-19: When the config's `requires` isn't met by the version sessions load, `doctor` WARNs and the tick reports the bound, the version, and the fix, and the session still starts
- S-031-20: With `[agents] notify = true`, the first tick on a host to find an install lagging a new release sends one desktop notification naming each lagging install and its fix and creates `~/.cache/shipmill/plugin/<version>.notified`; a tick of any gate on the host that finds the marker sends none; with `notify = false` none is sent and no marker is written
- S-031-21: In the minor release that ships this spec, `[agents] plugin_update = true` changes no install and runs no `claude plugin update`, `doctor` WARNs naming the key, spec 031, and that the next minor release refuses it, and `shipmill upgrade` no longer lists `plugin-update`
- S-031-22: In the minor release after the one that ships S-031-21, a config whose `[agents]` sets `plugin_update` exits 2 naming the key and spec 031
- S-031-23: `docs/install.md`, `docs/release-lanes.md`, `skills/shipmill-setup/SKILL.md`, and `skills/github-ship-watch/SKILL.md` describe the pinned CLI, the marketplace serving releases, the gate's cache and `--plugin-dir`, `requires`, and the `plugin_update` deprecation, and none describes a gate paused on a stale plugin

## Out of scope

- The reusable workflows' `tool` input (`prepare.yml`, `land.yml`, `operate.yml`): outside
  users' CI keeps the floating `@v0` tag; moving callers to a pinned version is its own
  spec
- Pruning the cache: a version folder is small and a running session may still use it;
  removing old ones safely needs to know which sessions on the host use which folder
- Updating a person's installs: shipmill reports them with the fix and changes none, at
  any scope
- Pre-release plugins (an rc channel in the marketplace): shipmill releases only stable
  and hotfix lanes today
- Editing `~/.claude/plugins/installed_plugins.json`: Claude Code's file, undocumented
- Removing the `@v0` tag: it stays for outside users (D-31 still moves it)

## Decisions relied on

- D-4: `requires` lives in `.github/shipmill.toml`
- D-14: the session's `--settings` carries the App's env; `enabledPlugins` joins it there, never replaces it
- D-17: headless sessions run as `claude -p`, now with `--plugin-dir`
- D-31: the one delivery shipmill performs itself is moving its own references, which the marketplace `ref` is, like the floating major tag
- D-32: a deprecated key is accepted with a doctor warning for one minor release, then refused
- D-40: the headless gate's hook self-test still pauses a session; it now tests the cache folder
- D-41 (superseding D-35, which superseded D-23): the plugin pins its CLI from PyPI, the marketplace serves releases, the gate loads the latest release per session from a versioned cache, and stale installs are reported, never paused on

## Issues

## Verification
