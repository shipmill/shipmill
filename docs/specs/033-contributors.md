# S-033: Contributors in a shipmill repo: the plugin per person, app-writes only where the App is

status: approved
serves: G-1, G-2

## Problem

In a repo connected to shipmill, `.claude/settings.json` is committed with
`shipmill@shipmill` enabled (as `docs/install.md` tells the maintainer to do, and
`setup_state.py --fix` writes), and `.github/shipmill.toml` sets `[agents] app_id`. Three
kinds of contributor meet that repo (shipmill/shipmill#495):

1. **Claude Code with the shipmill plugin, not the maintainer.** The delivery hooks of
   spec 026 load in their sessions. The `app-writes` rule refuses every plain `gh` write
   (`gh pr create`, a comment, a label) and points at `shipmill gh`, which needs the App's
   private key they don't have, so it exits 2. Their Claude can't open a pull request,
   whether the plugin came from the committed settings or from their own install
2. **By hand, without Claude.** Unaffected by the settings file. Their issues and fork
   pull requests wait for an interactive session under D-16; telling contributors so is
   the maintainer's call
3. **Claude Code without shipmill.** Opening the repo, Claude Code offers to install the
   plugin from the committed settings; accepting turns them into case 1

Spec 026 never considers a session that has the plugin but not the App: "contributor"
appears nowhere in it.

The maintainer (@romamo) settled the direction on #495, and this spec builds it:

1. **Committing the plugin to `.claude/settings.json` is opt-in, off by default.** The
   maintainer installs the plugin on their own host (user or local scope), and D-35 already
   reads an install at any scope. A repo where every session should load shipmill turns it
   on explicitly. By default `setup_state.py` accepts a user or local install instead of
   reporting `PLUGIN_MISSING`, `--fix` doesn't add the plugin to the repo's settings, and
   `docs/install.md` says so
2. **The `app-writes` rule applies only where the App is available:** a session the gate
   started, or one on a host where the App's key is present. Anywhere else a `gh` write runs
   as the person at the keyboard. The other hook rules (default-branch push, rebase merge,
   force push, private paths) apply as they do today
3. **D-16 is documented in shipmill's own docs, not in the client repo.** `docs/install.md`
   tells the maintainer that a fork pull request or an outside issue waits for an
   interactive session and is never landed automatically. A client repo's
   `CONTRIBUTING.md` is the maintainer's: shipmill never writes to it, adds to it, or
   prints text for it (shipmill/shipmill#502)

The change to the `app-writes` rule is recorded as D-42, which supersedes D-40 and restates
its whole rule.

## Behaviour

### The plugin per person: `[agents] plugin`

A new optional key in the `[agents]` section of `.github/shipmill.toml` (D-4), parsed by
`src/shipmill/agents.py` like the section's other keys:

```toml
[agents]
plugin = "host"   # the default: each person installs the plugin on their own host
```

or, to enable it for everyone who opens the repo through `.claude/settings.json`:

```toml
[agents]
plugin = "repo"
```

| Value | Means |
|---|---|
| `"host"` (the default, also when the key is absent) | The plugin is installed per person, at user scope or at local or project scope for the repo's folder. Nothing in the repo turns it on, so a contributor's Claude Code is never offered it |
| `"repo"` | `.claude/settings.json` enables `shipmill@shipmill` and knows its marketplace, so every session in the repo loads it, a contributor's too. Today's behaviour, chosen on purpose |

Any other value, or a value that isn't a string, exits 2 naming `[agents] plugin` and the
two values. `skills/shipmill-setup/scripts/setup_state.py` reads the key itself, as it
reads the config's other keys, with the same refusal.

`src/shipmill/init.py` adds a commented `# plugin = "host"` line, with a one-line comment
saying what `"repo"` does, to the commented `[agents]` block it writes.

### The setup checklist's Plugin rows

`setup_state.py`'s Plugin rows read the key first:

| `[agents] plugin` | Row | When | `--fix` |
|---|---|---|---|
| `host` | `PLUGIN_OK` | An install of `shipmill@shipmill` applies to the repo's folder: user scope, or local or project scope keyed on the repo's folder (its main checkout, as watch_state.py's `plugin_rows` reads `claude plugin list --json`); the detail names its scope and version | Nothing to do |
| `host` | `PLUGIN_MISSING` | No install applies | Leaves it: an install changes the person's host. The detail gives the command, `claude plugin marketplace add shipmill/shipmill && claude plugin install shipmill@shipmill --scope user`, which the skill runs after asking |
| `host` | `PLUGIN_COMMITTED` | `.claude/settings.json` enables `shipmill@shipmill` | Leaves it. The detail names both ways out: set `[agents] plugin = "repo"` to keep it, or delete `shipmill@shipmill` from `enabledPlugins` (and the `shipmill` entry from `extraKnownMarketplaces` when no other plugin uses it) |
| `repo` | `PLUGIN_OK`, `PLUGIN_MISSING` | As today: whether `.claude/settings.json` enables it | `PLUGIN_MISSING`: writes the marketplace and `enabledPlugins`, keeping every other key, as today |
| either | `PLUGIN_DISABLED` | `enabledPlugins` sets it to `false` | Leaves it, as today |

`PLUGIN_COMMITTED` is not done (exit 1), so a repo connected before this spec hears once
that the default changed and chooses. `PLUGIN_OUTDATED` rows replace a `PLUGIN_OK` in both
modes, as today. Without `claude` on PATH a `host` repo reads `PLUGIN_OK` with "claude
isn't on PATH, installs not read", as the `repo` mode's outdated check does today. With
`host`, `--fix` never creates, reads for writing, or changes `.claude/settings.json`.

`skills/shipmill-setup/SKILL.md` asks where the plugin loads: per person (the default, and
the one to keep for a repo that takes outside contributions) or for everyone who opens the
repo (`"repo"`). With `host` it installs the plugin at user scope on the maintainer's host
after asking, and writes `plugin = "repo"` only when the maintainer chooses it.

### How the gate's sessions get the plugin, with or without spec 031

`[agents] plugin` changes nothing the gate loads:

- **Today (D-35):** the gate reads the install a session in its checkout loads, at any
  scope. With `host`, that is the maintainer's user-scope install, or one keyed on the
  gate's checkout, which shipmill-setup and the gate's own reports already handle
- **With spec 031 (shipmill/shipmill#490):** the gate starts each session with
  `--plugin-dir` on its cached release and `--settings` that set `shipmill@shipmill` to
  false. Flag settings rank above the project's `.claude/settings.json`, so a repo with
  `plugin = "repo"` still loads one copy in a gate session, the cached one; spec 031's own
  probe (S-031-12) covers that case once its build checks it with the project setting on as
  well as the user one

Either way the gate's sessions don't depend on the committed settings, which is why the
default can be `host`.

### Where the App is available

`hooks/delivery.py`'s `app-writes` rule refuses a `gh` write only when `[agents] app_id`
is set **and** the App is available to the session. The App is available when either holds:

1. **The hook's own environment has a non-empty `SHIPMILL_APP_KEY`.** shipmill gate sets it
   on every session it starts, headless and interactive, to the absolute path of the key it
   uses (`--app-key`, else the default below): `src/shipmill/app.py`'s `session_env` adds
   it to the `--settings` env beside the git identity and helpers of D-14. With spec 031
   the same `--settings` JSON also carries `enabledPlugins`; the two sit side by side. The
   hook doesn't open or check the file the variable names
2. **The App's key file exists on the host:** `$HOME/.config/shipmill/app-<app_id>.pem`,
   the path `default_key` in `src/shipmill/app.py` gives and `shipmill gh` reads, with
   `app_id` from the repo's config. The hook checks that the path is a file with one
   `stat`, never reads it, and starts no subprocess, so S-026-10 still holds. With `HOME`
   unset only the first test counts

Where neither holds, `app-writes` refuses nothing: a plain `gh` write, and a `GH_TOKEN=...
gh` write, exit 0 unless another rule refuses them. The other rules don't look at
availability. When `rebase-merge` refuses `gh pr merge N --rebase` in a session without
the App, its `Instead:` line keeps plain `gh` (`gh pr merge N --squash`), since only
`app-writes` turns `gh` into `shipmill gh`.

**Verify first**, in the build issue that adds `SHIPMILL_APP_KEY` to `session_env` and
before its code: start `claude -p --settings '{"env": {"SHIPMILL_APP_KEY": "/tmp/x"}}'`
with the plugin loaded in a repo with `[agents] app_id` and no key file, have it run `gh
label create probe --repo <a scratch repo>` through Bash, and record in the pull request
whether the hook refused it (the hook saw the variable) or let it run. If a hook doesn't
see the `--settings` env, the pull request stops and asks; the fallback would be the gate
also setting it on the environment of the `claude` process it spawns.

#### Why this is safe for the maintainer's sessions

- **Only the host decides.** Availability reads the hook process's environment and a file
  in the maintainer's home, nothing in the repo. A contributor's pull request can't add a
  file or a setting that turns the rule off in the maintainer's sessions; the one repo
  change that turns it off, deleting `[agents] app_id`, already did so under D-40 and goes
  through review
- **The variable only turns the rule on.** Unsetting `SHIPMILL_APP_KEY`, or never setting
  it, changes nothing while the key file is at its default path, so the maintainer's own
  interactive sessions keep every agent write attributed to the App (Q-2) wherever the key
  lives at `~/.config/shipmill/app-<app_id>.pem`. A contributor who sets it only puts the
  rule on themselves
- **A session can't switch it off for itself.** The hook reads its own environment, never
  a command's `NAME=value` assignments, so `SHIPMILL_APP_KEY= gh pr create` or `HOME=/tmp
  gh pr create` is judged by the hook's environment and the real home. An `export` in a
  Bash call doesn't reach the hook's process. Deleting or moving the key file is a hostile
  act, out of scope as in spec 026 (D-16 stays the control)
- **Gate sessions always have it.** D-14 already refuses to start a session without the
  App's key, and every session the gate starts carries the variable, so no unattended
  session writes through plain `gh` as the maintainer
- **What is left uncovered** is a maintainer whose key lives at another path and who works
  in their own session without the variable: their plain `gh` writes as them, as they
  would without the plugin. `docs/install.md` tells them to keep the key at the default
  path, or set `SHIPMILL_APP_KEY` in their shell, and `doctor` says which case the host is
  in

### `shipmill gh` reads the same variable

`shipmill gh` (`src/shipmill/cli.py`), with `[agents] app_id` set and no leading
`--app-key`, takes the key from a non-empty `SHIPMILL_APP_KEY` before the default path, so
a gate session whose gate runs with `--app-key` elsewhere and a maintainer who sets the
variable both reach the key the hook assumed. A leading `--app-key` still wins.

When no key is found at the path it would use, it still exits 2 without running `gh`
(D-14), and its message gains a second line for the contributor's case:

```
no App private key at /home/ann/.config/shipmill/app-123.pem; download it from the App's settings to that path
the App's key isn't on this host: if you aren't this repo's maintainer, run plain gh, which writes as you (spec 033)
```

`skills/github-pr-triage/SKILL.md` rule 8 gains one line: where `shipmill gh` says the
App's key isn't on this host, the session isn't the maintainer's, and plain `gh` writes as
the person; never ask for or fetch the key.

### `doctor`

`src/shipmill/doctor.py`'s hooks block (S-026-15) says, for `app-writes`, which case the
host is in, each a PASS line:

- `app-writes: on (the App's key is at <path>)`
- `app-writes: on in gate sessions only (no key at <path> on this host; your own sessions write with gh as you, or set SHIPMILL_APP_KEY)`
- `app-writes: off (no [agents] app_id)`, as today

### Docs

- `docs/install.md`, Install the skills: the plugin is installed per person by default,
  the install commands; `[agents] plugin = "repo"` and the `.claude/settings.json` snippet
  as the opt-in, with what it means for contributors (their Claude Code is offered the
  plugin and its hooks)
- `docs/install.md`, Go live step 3: `--fix` writes the plugin into `.claude/settings.json`
  only with `plugin = "repo"`
- `docs/install.md`, a new Contributors section, for the maintainer: the three kinds of
  contributor above; that `app-writes` applies only where the App's key is or in gate
  sessions, so a contributor's Claude writes as the contributor; that a fork pull request
  or an issue from someone outside the repo waits for an interactive session and is never
  landed automatically (D-16); that telling contributors so is the maintainer's choice, and
  shipmill writes nothing to the repo's `CONTRIBUTING.md`, `README.md`, or other docs and
  prints no text for them; keeping the key at its default path, or `SHIPMILL_APP_KEY`
- `docs/release-lanes.md`: `[agents] plugin`, next to the other `[agents]` keys
- `skills/shipmill-setup/SKILL.md`: the question and rows above
- `skills/github-pr-triage/SKILL.md`: the line above
- `docs/specs/026-delivery-hooks.md`, Decisions relied on: D-42 in place of D-40. Spec 026's
  `app-writes` tests run with the App available (a key file in the test's `HOME`), so
  S-026-3 keeps its meaning under D-42

## Acceptance criteria

- S-033-1: `src/shipmill/agents.py` reads `[agents] plugin` as `"host"` (also when absent) or `"repo"`, and any other value or a non-string exits 2 naming `[agents] plugin` and both values; `setup_state.py` refuses the same values with exit 2
- S-033-2: With `plugin` absent or `"host"`, `setup_state.py` reads `PLUGIN_OK` naming the scope and version when `claude plugin list --json` lists `shipmill@shipmill` at user scope, or at local or project scope keyed on the repo's main checkout, and `PLUGIN_MISSING` with the `claude plugin install shipmill@shipmill --scope user` command when none applies; `--fix` leaves `.claude/settings.json` byte for byte as it was, and absent when it was absent
- S-033-3: With `plugin` absent or `"host"` and `.claude/settings.json` enabling `shipmill@shipmill`, `setup_state.py` reads `PLUGIN_COMMITTED` naming `plugin = "repo"` and the `enabledPlugins` entry to delete, exits 1, and `--fix` leaves the file unchanged
- S-033-4: With `plugin = "repo"`, `setup_state.py` reads `PLUGIN_MISSING` when the settings don't enable the plugin and `--fix` writes the marketplace and `enabledPlugins` keeping every other key, and `PLUGIN_OK` when they do; in either mode `enabledPlugins` set to false reads `PLUGIN_DISABLED` and `--fix` leaves it
- S-033-5: With `[agents] app_id` set, `SHIPMILL_APP_KEY` unset or empty in the hook's environment, and no file at `$HOME/.config/shipmill/app-<app_id>.pem`, every `gh` write S-026-3 lists, plain or after `GH_TOKEN=...`, exits 0 with no output
- S-033-6: With `[agents] app_id` set, every `gh` write S-026-3 lists exits 2 naming `app-writes` with its `shipmill gh` `Instead:` line both when the key file exists at `$HOME/.config/shipmill/app-<app_id>.pem` and `SHIPMILL_APP_KEY` is unset, and when `SHIPMILL_APP_KEY` is non-empty and no key file exists
- S-033-7: A command's own assignments don't change availability: with the key file present, `SHIPMILL_APP_KEY= gh pr create` and `HOME=/tmp gh pr create` exit 2 naming `app-writes`; with neither the key file nor the variable, `SHIPMILL_APP_KEY=/x gh pr create` exits 0; the availability check starts no subprocess and reads no file's contents
- S-033-8: With the App not available, `gh pr merge 1 --rebase` exits 2 naming `rebase-merge` with `Instead: gh pr merge 1 --squash`, and the `default-branch-push`, `force-push`, and `private-paths` fixtures of S-026-4, S-026-6, and S-026-7 exit as they do with the App available
- S-033-9: The `--settings` env of every session shipmill gate starts, headless and interactive, holds `SHIPMILL_APP_KEY` set to the absolute path of the key the gate used (`--app-key`, else `~/.config/shipmill/app-<app_id>.pem`), beside the env D-14 sets
- S-033-10: A hook in a real `claude -p` session started with `--settings` whose env sets `SHIPMILL_APP_KEY` sees the variable and refuses a plain `gh` write in a repo with `app_id` and no key file (a probe against a real `claude`, recorded in the pull request that builds S-033-9)
- S-033-11: `shipmill gh` with `[agents] app_id` set and no leading `--app-key` uses the key at a non-empty `SHIPMILL_APP_KEY`, and a leading `--app-key` wins over it; when no key is at the path it would use, it exits 2 without running `gh`, and stderr names the path and says that someone who isn't the repo's maintainer runs plain `gh`, which writes as them
- S-033-12: `shipmill doctor`'s hooks block reads `app-writes: on` naming the key's path when the key file exists, `app-writes: on in gate sessions only` naming the missing path and `SHIPMILL_APP_KEY` when `app_id` is set and no key file exists, and `app-writes: off` when `app_id` is unset
- S-033-13: `shipmill init` writes a commented `# plugin = "host"` line in its commented `[agents]` block, and the file it writes still parses
- S-033-14: `setup_state.py --fix` and `shipmill init`, run on a repo with a `CONTRIBUTING.md`, leave it byte for byte unchanged, and no file under `skills/` or `src/shipmill/` holds text meant for a client repo's `CONTRIBUTING.md`
- S-033-15: `docs/install.md` describes the per-person install as the default and `[agents] plugin = "repo"` with its `.claude/settings.json` snippet as the opt-in, has a Contributors section saying that `app-writes` applies only where the App's key is or in gate sessions, that a fork pull request or an outside issue waits for an interactive session and is never landed automatically (D-16), and that shipmill writes nothing to the repo's own docs; `docs/release-lanes.md` lists `[agents] plugin`; `skills/shipmill-setup/SKILL.md` names `PLUGIN_COMMITTED` and the question; `skills/github-pr-triage/SKILL.md` rule 8 has the contributor line

## Out of scope

- A contributor's session writing as the App: the App's key is the maintainer's, and
  nothing here hands it out or fetches it
- Writing, appending to, or drafting text for a client repo's `CONTRIBUTING.md`,
  `README.md`, or other docs (shipmill/shipmill#502)
- Removing the committed plugin from a connected repo's `.claude/settings.json`: setup
  reports `PLUGIN_COMMITTED` and the maintainer chooses; shipmill's own repo makes the same
  choice in the build
- Finding a key at a path other than the default in a person's own session without
  `SHIPMILL_APP_KEY`: the variable, or the default path, is the way
- Changing which items an unattended session works on: D-16 stays as it is
- A hostile agent that deletes the key file or edits the hook: spec 026's Out of scope
  still holds
- How the gate materializes and loads the plugin: spec 031

## Decisions relied on

- D-4: `[agents] plugin` lives in `.github/shipmill.toml`
- D-14: agent writes go as the App or not at all where the App is set up; the gate refuses to start a session without its key, so every gate session carries `SHIPMILL_APP_KEY`, and `shipmill gh` still exits 2 rather than fall back
- D-16: unattended sessions work only on trusted authors' items; `docs/install.md` tells the maintainer, the client repo's docs don't
- D-35: the gate reads the install a session loads at any scope, so a user-scope install is enough for the gate today
- D-42 (superseding D-40): the `app-writes` rule applies only where the App is available, read from the host alone; the other rules, the switches, the fail-open start, and the headless self-test pause are D-40's, unchanged

## Issues

## Verification
