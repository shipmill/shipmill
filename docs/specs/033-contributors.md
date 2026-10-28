# S-033: Contributors in a shipmill repo: the plugin per person; without the App, shipmill drafts and the person posts

status: built
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
   maintainer installs the plugin on their own host (user or local scope), and under D-50
   a gate session already loads an install at any scope. A repo where every session should load shipmill turns it
   on explicitly. By default `setup_state.py` accepts a user or local install instead of
   reporting `PLUGIN_MISSING`, `--fix` doesn't add the plugin to the repo's settings, and
   `docs/install.md` says so
2. **shipmill writes to GitHub only as the App, a separate identity.** Its skills and their
   scripts write only through `shipmill gh`, never as the person at the keyboard; Q-2 and
   D-14 stand as they are. The App is available to a session the gate started, or to one on
   a host where the App's key is present. **Without the App, shipmill drafts and the person
   posts:** in a session where the App isn't available, a skill stops before its first
   write, says the App isn't available here, and gives the person the text it would have
   written (the comment, the label, the pull request's title and body), ready to post
   themselves. **A contributor's own writes are theirs:** in a session without the App the
   `app-writes` hook refuses nothing, so a contributor writes as themselves, by hand or with
   their own Claude outside shipmill's skills. The other hook rules (default-branch push,
   rebase merge, force push, private paths) apply as they do today. (Chosen by @romamo on
   #521, replacing the first version of this spec, where a skill's `gh` write ran as the
   person wherever the App wasn't available)
3. **D-16 is documented in shipmill's own docs, not in the client repo.** `docs/install.md`
   tells the maintainer that a fork pull request or an outside issue waits for an
   interactive session and is never landed automatically. A client repo's
   `CONTRIBUTING.md` is the maintainer's: shipmill never writes to it, adds to it, or
   prints text for it (shipmill/shipmill#502)

The rule is recorded as D-54, which supersedes D-40 and restates its whole rule.

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
| `host` | `PLUGIN_COMMITTED` | `.claude/settings.json` enables `shipmill@shipmill` | Removes it (D-59, shipmill/shipmill#778): deletes `shipmill@shipmill` from `enabledPlugins`, and the `shipmill` entry from `extraKnownMarketplaces` when no other enabled `<name>@shipmill` uses it, keeping every other key, the file's indent, and its trailing newline; drops an object left empty, and deletes the file when no key is left. The detail says so, and that `[agents] plugin = "repo"` keeps it |
| `repo` | `PLUGIN_OK`, `PLUGIN_MISSING` | As today: whether `.claude/settings.json` enables it | `PLUGIN_MISSING`: writes the marketplace and `enabledPlugins`, keeping every other key, as today |
| either | `PLUGIN_DISABLED` | `enabledPlugins` sets it to `false` | Leaves it, as today |

`PLUGIN_COMMITTED` is not done (exit 1), so a repo connected before this spec hears once
that the default changed; since D-59 setup's `--fix` removes the committed plugin unless
the maintainer sets `plugin = "repo"`. `PLUGIN_OUTDATED` rows replace a `PLUGIN_OK` in both
modes, as today. Without `claude` on PATH a `host` repo reads `PLUGIN_OK` with "claude
isn't on PATH, installs not read", as the `repo` mode's outdated check does today. With
`host`, `--fix` never creates `.claude/settings.json`, and changes it only to remove a
committed plugin (D-59).

`skills/shipmill-setup/SKILL.md` asks where the plugin loads: per person (the default, and
the one to keep for a repo that takes outside contributions) or for everyone who opens the
repo (`"repo"`). With `host` it installs the plugin at user scope on the maintainer's host
after asking, and writes `plugin = "repo"` only when the maintainer chooses it.

### How the gate's sessions get the plugin

`[agents] plugin` changes nothing the gate loads. Under D-50 a gate session loads the
install of `shipmill@shipmill` that applies to its checkout, at any scope, with no
`--plugin-dir` and no change to `enabledPlugins`. With `host`, that is the maintainer's
user-scope install, or one keyed on the gate's checkout, which shipmill-setup and the
gate's own reports already handle; with `repo`, the committed setting loads the same
plugin. The gate's sessions don't depend on the committed settings, which is why the
default can be `host`.

### Where the App is available

`hooks/delivery.py`'s `app-writes` rule refuses a `gh` write only when `[agents] app_id`
is set **and** the App is available to the session. The App is available when either holds:

1. **The hook's own environment has a non-empty `SHIPMILL_APP_KEY`.** shipmill gate sets it
   on every session it starts, headless and interactive, to the absolute path of the key it
   uses (`--app-key`, else the default below): `src/shipmill/app.py`'s `session_env` adds
   it to the `--settings` env beside the git identity and helpers of D-14. The hook
   doesn't open or check the file the variable names
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
  in their own session without the variable: the App isn't available there, so shipmill's
  skills draft instead of writing, and a `gh` write the maintainer runs themselves goes out
  as them, as it would without the plugin. `docs/install.md` tells them to keep the key at
  the default path, or set `SHIPMILL_APP_KEY` in their shell, and `doctor` says which case
  the host is in

### Without the App, shipmill drafts and the person posts

In a repo with `[agents] app_id` set, shipmill's skills and their scripts write to GitHub
only as the App (D-14): every `gh` write goes through `shipmill gh`, and a gate session
pushes with the App's git credential helper; none of them writes with plain `gh` as the
person at the keyboard. In a session where the App isn't available, by the test above, a
skill doesn't write to GitHub at all, a push included:

1. **It checks before its first write.** In a repo with `[agents] app_id` set, before the
   first write to GitHub a run would make
   (a comment, a label, an issue, a pull request, a review, a merge, a push), the skill runs
   `shipmill app-token --check` (below). Exit 0: it goes on as today. Exit 2: it stops
   there, before that write. Reading, and local work in the checkout (a branch, a commit, a
   test run), come before the check and stay as they are
2. **It says why.** Its report's first line says the App isn't available in this session,
   quoting the check's reason (no `[agents] app_id`, or no key at the path and no
   `SHIPMILL_APP_KEY`), and that shipmill wrote nothing to GitHub
3. **It hands over the text it would have written,** one block per write in the order the
   skill would have made them, each naming its target (the repo and the issue or pull
   request number, or for a new pull request the base, and the local branch holding the
   commits) and the exact text: the comment's body, the label's name, the pull request's
   title and body, the review's verdict and body. The text is final, ready to paste or to
   post with the person's own `gh`; the skill may print that command beside it, and never
   runs it
4. **It never retries as the person.** A `shipmill gh` exit 2 that names the missing key,
   from a script or a step the check didn't cover, is the same stop: the skill hands over
   what it had prepared and never retries with plain `gh`, `GH_TOKEN`, or `git push`

The hook doesn't enforce this: in a session without the App, `app-writes` refuses nothing,
so the person's own writes, by hand or with their own Claude outside shipmill's skills, run
as them. The skills' rule is the control, and `shipmill gh`'s exit 2 without the key
(D-14) backs it for every write that goes through it.

A gate session always has the App, so nothing here changes what the gate's sessions do; a
headless session someone starts by hand without the App puts the drafts in its report.

#### `shipmill app-token --check`

`shipmill app-token --check` tells a skill whether the App is available to the session,
with the hook's test and nothing more:

- With `[agents] app_id` set and a non-empty `SHIPMILL_APP_KEY` in its environment, or a
  file at `$HOME/.config/shipmill/app-<app_id>.pem`, it exits 0 and prints one line naming
  the App's id and which test held
- Otherwise it exits 2 with one line naming the reason: no `[agents] app_id` in the
  checkout's `.github/shipmill.toml` (or no such file), or no key at the default path and
  no `SHIPMILL_APP_KEY`, naming the path
- It mints no token, prints no token, makes no network call, and reads no file's contents,
  so it costs a skill nothing and leaks nothing

#### A repo without an App

A repo without `[agents] app_id` is spec 037's case for `shipmill gh`, and a skill there
runs no check: its write through `shipmill gh` exits 2 unless `[agents] identity = "host"`
or `--as-host` allows the host's identity, and where it exits 2 the skill stops and hands
over its drafts as in step 4. This spec doesn't change spec 037's two
allowances; whether they stay under D-54 is the maintainer's call (see the pull request)

### `shipmill gh` reads the same variable

`shipmill gh` (`src/shipmill/cli.py`), with `[agents] app_id` set and no leading
`--app-key`, takes the key from a non-empty `SHIPMILL_APP_KEY` before the default path, so
a gate session whose gate runs with `--app-key` elsewhere and a maintainer who sets the
variable both reach the key the hook assumed. A leading `--app-key` still wins.
`shipmill app-token` reads the variable the same way.

When no key is found at the path it would use, it still exits 2 without running `gh`
(D-14), and its message gains a second line for the contributor's case:

```
no App private key at /home/ann/.config/shipmill/app-123.pem; download it from the App's settings to that path
the App isn't available here, so shipmill writes nothing: a skill hands you its text to post, and what you post yourself with gh is yours (spec 033)
```

The "Write as the App" rule of every skill (`skills/github-issue-triage/SKILL.md`,
`skills/github-issue-resolve/SKILL.md`, `skills/github-pr-triage/SKILL.md` rule 8,
`skills/github-ship-watch/SKILL.md`, `skills/product-intake/SKILL.md`,
`skills/shipmill-setup/SKILL.md`) gains the steps above: with `app_id` set, run
`shipmill app-token --check` before the first write; on exit 2, or a `shipmill gh` exit 2
naming the missing key, stop, say the App isn't available here, and hand over the text of
each write; never write with plain `gh`, `GH_TOKEN`, or a push as the person, and never ask
for or fetch the key.

### `doctor`

`src/shipmill/doctor.py`'s hooks block (S-026-15) says, for `app-writes`, which case the
host is in, each a PASS line:

- `app-writes: on (the App's key is at <path>)`
- `app-writes: on in gate sessions only (no key at <path> on this host; in your own sessions shipmill's skills draft and you post, or set SHIPMILL_APP_KEY)`
- `app-writes: off (no [agents] app_id)`, as today

### Docs

- `docs/install.md`, Install the skills: the plugin is installed per person by default,
  the install commands; `[agents] plugin = "repo"` and the `.claude/settings.json` snippet
  as the opt-in, with what it means for contributors (their Claude Code is offered the
  plugin and its hooks)
- `docs/install.md`, Go live step 3: `--fix` writes the plugin into `.claude/settings.json`
  only with `plugin = "repo"`
- `docs/install.md`, a new Contributors section, for the maintainer: the three kinds of
  contributor above; that shipmill writes only as the App, so where the App isn't available
  (a contributor's host) its skills stop before their first write and hand the person the
  text to post; that `app-writes` applies only where the App's key is or in gate sessions,
  so what a contributor posts themselves, by hand or with their own Claude outside
  shipmill's skills, goes out as them; that a fork pull request
  or an issue from someone outside the repo waits for an interactive session and is never
  landed automatically (D-16); that telling contributors so is the maintainer's choice, and
  shipmill writes nothing to the repo's `CONTRIBUTING.md`, `README.md`, or other docs and
  prints no text for them; keeping the key at its default path, or `SHIPMILL_APP_KEY`
- `docs/release-lanes.md`: `[agents] plugin`, next to the other `[agents]` keys
- `skills/shipmill-setup/SKILL.md`: the question and rows above
- The six skills' "Write as the App" rules: the steps above
- `docs/specs/026-delivery-hooks.md`, Decisions relied on: D-54 in place of D-40. Spec 026's
  `app-writes` tests run with the App available (a key file in the test's `HOME`), so
  S-026-3 keeps its meaning under D-54

## Acceptance criteria

- S-033-1: `src/shipmill/agents.py` reads `[agents] plugin` as `"host"` (also when absent) or `"repo"`, and any other value or a non-string exits 2 naming `[agents] plugin` and both values; `setup_state.py` refuses the same values with exit 2
- S-033-2: With `plugin` absent or `"host"`, `setup_state.py` reads `PLUGIN_OK` naming the scope and version when `claude plugin list --json` lists `shipmill@shipmill` at user scope, or at local or project scope keyed on the repo's main checkout, and `PLUGIN_MISSING` with the `claude plugin install shipmill@shipmill --scope user` command when none applies; `--fix` leaves `.claude/settings.json` byte for byte as it was when it doesn't enable `shipmill@shipmill`, and absent when it was absent
- S-033-3: With `plugin` absent or `"host"` and `.claude/settings.json` enabling `shipmill@shipmill`, `setup_state.py` reads `PLUGIN_COMMITTED` naming `plugin = "repo"` and the `enabledPlugins` entry `--fix` removes, and exits 1; `--fix` deletes `shipmill@shipmill` from `enabledPlugins`, and the `shipmill` entry from `extraKnownMarketplaces` when no other enabled `<name>@shipmill` uses it, keeping every other key, the indent, and the trailing newline, drops an object left empty, and deletes the file when no key is left (D-59, shipmill/shipmill#778)
- S-033-4: With `plugin = "repo"`, `setup_state.py` reads `PLUGIN_MISSING` when the settings don't enable the plugin and `--fix` writes the marketplace and `enabledPlugins` keeping every other key, and `PLUGIN_OK` when they do; in either mode `enabledPlugins` set to false reads `PLUGIN_DISABLED` and `--fix` leaves it
- S-033-5: With `[agents] app_id` set, `SHIPMILL_APP_KEY` unset or empty in the hook's environment, and no file at `$HOME/.config/shipmill/app-<app_id>.pem`, every `gh` write S-026-3 lists, plain or after `GH_TOKEN=...`, exits 0 with no output
- S-033-6: With `[agents] app_id` set, every `gh` write S-026-3 lists exits 2 naming `app-writes` with its `shipmill gh` `Instead:` line both when the key file exists at `$HOME/.config/shipmill/app-<app_id>.pem` and `SHIPMILL_APP_KEY` is unset, and when `SHIPMILL_APP_KEY` is non-empty and no key file exists
- S-033-7: A command's own assignments don't change availability: with the key file present, `SHIPMILL_APP_KEY= gh pr create` and `HOME=/tmp gh pr create` exit 2 naming `app-writes`; with neither the key file nor the variable, `SHIPMILL_APP_KEY=/x gh pr create` exits 0; the availability check starts no subprocess and reads no file's contents
- S-033-8: With the App not available, `gh pr merge 1 --rebase` exits 2 naming `rebase-merge` with `Instead: gh pr merge 1 --squash`, and the `default-branch-push`, `force-push`, and `private-paths` fixtures of S-026-4, S-026-6, and S-026-7 exit as they do with the App available
- S-033-9: The `--settings` env of every session shipmill gate starts, headless and interactive, holds `SHIPMILL_APP_KEY` set to the absolute path of the key the gate used (`--app-key`, else `~/.config/shipmill/app-<app_id>.pem`), beside the env D-14 sets
- S-033-10: A hook in a real `claude -p` session started with `--settings` whose env sets `SHIPMILL_APP_KEY` sees the variable and refuses a plain `gh` write in a repo with `app_id` and no key file (a probe against a real `claude`, recorded in the pull request that builds S-033-9)
- S-033-11: `shipmill gh` with `[agents] app_id` set and no leading `--app-key` uses the key at a non-empty `SHIPMILL_APP_KEY`, and a leading `--app-key` wins over it; when no key is at the path it would use, it exits 2 without running `gh`, and stderr names the path and says that the App isn't available here, that shipmill writes nothing, that a skill hands over its text to post, and that what the person posts themselves is theirs; `shipmill app-token` reads `SHIPMILL_APP_KEY` the same way
- S-033-12: `shipmill doctor`'s hooks block reads `app-writes: on` naming the key's path when the key file exists, `app-writes: on in gate sessions only` naming the missing path and `SHIPMILL_APP_KEY` when `app_id` is set and no key file exists, and `app-writes: off` when `app_id` is unset
- S-033-13: `shipmill init` writes a commented `# plugin = "host"` line in its commented `[agents]` block, and the file it writes still parses
- S-033-14: `setup_state.py --fix` and `shipmill init`, run on a repo with a `CONTRIBUTING.md`, leave it byte for byte unchanged, and no file under `skills/` or `src/shipmill/` holds text meant for a client repo's `CONTRIBUTING.md`
- S-033-15: `docs/install.md` describes the per-person install as the default and `[agents] plugin = "repo"` with its `.claude/settings.json` snippet as the opt-in, has a Contributors section saying that shipmill writes only as the App and, where the App isn't available, its skills hand the person the text to post, that `app-writes` applies only where the App's key is or in gate sessions so a contributor's own posts go out as them, that a fork pull request or an outside issue waits for an interactive session and is never landed automatically (D-16), and that shipmill writes nothing to the repo's own docs; `docs/release-lanes.md` lists `[agents] plugin`; `skills/shipmill-setup/SKILL.md` names `PLUGIN_COMMITTED` and the question
- S-033-16: `shipmill app-token --check` with `[agents] app_id` set exits 0 naming the App's id and the test that held when the key file exists at `$HOME/.config/shipmill/app-<app_id>.pem` or `SHIPMILL_APP_KEY` is non-empty, and exits 2 naming the missing path and `SHIPMILL_APP_KEY` when neither holds; without `app_id`, or without `.github/shipmill.toml`, it exits 2 naming `[agents] app_id`; in every case it prints no token, mints none, makes no network call, and reads no file's contents
- S-033-17: The "Write as the App" rule of each of the six skills (`github-issue-triage`, `github-issue-resolve`, `github-pr-triage`, `github-ship-watch`, `product-intake`, `shipmill-setup`) says that with `app_id` set the skill runs `shipmill app-token --check` before its first write to GitHub, push included; that on its exit 2, or a `shipmill gh` exit 2 naming the missing key, it stops, says the App isn't available here, and hands over the text of each write it would have made (target and exact text: the comment, the label, the pull request's title and body); and that it never writes with plain `gh`, `GH_TOKEN`, or a push as the person, and never asks for or fetches the key
- S-033-18: An eval case under `evals/` runs `github-issue-resolve` on an issue in a repo with `[agents] app_id` set and no App available (no key file, no `SHIPMILL_APP_KEY`): the run makes no write to GitHub and no push, its report says the App isn't available here, and it holds the pull request's title and body and the local branch with the fix

## Out of scope

- A contributor's session writing as the App: the App's key is the maintainer's, and
  nothing here hands it out or fetches it
- Writing, appending to, or drafting text for a client repo's `CONTRIBUTING.md`,
  `README.md`, or other docs (shipmill/shipmill#502)
- Removing the committed plugin from a connected repo's `.claude/settings.json`: setup
  reports `PLUGIN_COMMITTED` and the maintainer chooses; shipmill's own repo makes the same
  choice in the build. Superseded by D-59 (shipmill/shipmill#778): `--fix` removes it
  unless `plugin = "repo"`
- Finding a key at a path other than the default in a person's own session without
  `SHIPMILL_APP_KEY`: the variable, or the default path, is the way
- Changing which items an unattended session works on: D-16 stays as it is
- A hostile agent that deletes the key file or edits the hook: spec 026's Out of scope
  still holds
- How the gate loads the plugin: D-50 and spec 031

## Decisions relied on

- D-4: `[agents] plugin` lives in `.github/shipmill.toml`
- D-14: agent writes go as the App or not at all where the App is set up; the gate refuses to start a session without its key, so every gate session carries `SHIPMILL_APP_KEY`, and `shipmill gh` still exits 2 rather than fall back, which backs the skills' stop
- D-16: unattended sessions work only on trusted authors' items; `docs/install.md` tells the maintainer, the client repo's docs don't
- D-37: the skills' new rule changes the agents' instructions, so it lands with S-033-18's eval case and only when the evals don't regress
- D-50 (superseding D-44, which superseded D-43, which superseded D-35): a gate session loads the install of `shipmill@shipmill` that applies to its checkout, at any scope, so a user-scope install is enough for the gate
- D-54 (superseding D-40): shipmill writes to GitHub only as the App; where the App isn't available, read from the host alone, a skill drafts and the person posts, and the `app-writes` rule refuses nothing; the other rules, the switches, the fail-open start, and the headless self-test pause are D-40's, unchanged; spec 037 (shipmill/shipmill#577) covers `shipmill gh` in a repo without `[agents] app_id`, whose exit 2 there is this spec's step 4 stop
- D-59: shipmill is each person's choice, not the repo's; with `plugin = "host"` setup's `--fix` removes a committed `shipmill@shipmill` (and its marketplace when unused)

## Issues

- shipmill/shipmill#698: S-033-1, S-033-2, S-033-3, S-033-4, S-033-5, S-033-6, S-033-7, S-033-8, S-033-9, S-033-10, S-033-11, S-033-12, S-033-13, S-033-14, S-033-15, S-033-16, S-033-17, S-033-18

## Verification

- S-033-1: `AgentsConfig.parse` and `setup_state.py`'s `plugin_mode` on absent, `"host"`, `"repo"`, and six bad values, on Python 3.14 and 3.10 (`tests/test_contributors.py`), pass
- S-033-2: `host_plugin_rows` on `claude plugin list --json` listings (user, local, project, nested, other folder, managed, none) and `setup_state.py --fix` run end to end with no settings file and another plugin's, comparing bytes, pass
- S-033-3: `PLUGIN_COMMITTED` naming `plugin = "repo"` and the `enabledPlugins` entry `--fix` removes, exit 1; `--fix` removing it keeping other keys, plugins, and marketplaces and the indent (four spaces, a tab, one line) and trailing newline, the marketplace kept while another `<name>@shipmill` is on and dropped when only a disabled one names it, empty objects dropped, the file deleted when empty (in process and end to end, D-59), and repo mode leaving a committed plugin byte for byte, pass
- S-033-4: repo mode's `PLUGIN_MISSING`, `--fix` writing the marketplace and `enabledPlugins` keeping other keys (in process and end to end), `PLUGIN_OK`, and `PLUGIN_DISABLED` in both modes, pass
- S-033-5: every S-026-3 write, plain and after `GH_TOKEN=...`, in four hook environments without the App (`tests/test_delivery_hooks.py`), exits 0 with no output, pass
- S-033-6: every S-026-3 write with the key file and no variable, and with the variable and no key file, exits 2 naming `app-writes` with its `shipmill gh` Instead line, pass
- S-033-7: `SHIPMILL_APP_KEY=`, `HOME=/tmp`, `env`, and `export` forms with the key file refused; `SHIPMILL_APP_KEY=/x` and `HOME=<a home with a key>` without either pass; the counting runner and reader see no process and one config read, and a key file of mode 000 still counts, pass
- S-033-8: `gh pr merge 1 --rebase` without the App refused naming `rebase-merge` with `Instead: gh pr merge 1 --squash`, and the default-branch-push, force-push, and private-paths fixtures answer alike with and without the App, pass
- S-033-9: `session_env` names the key's resolved absolute path, and the interactive (`claude --bg`) and headless (`claude -p`) launches carry it in `--settings`, from `--app-key` and from the default path, pass
- S-033-10: the maintainer ran the probe (`SHIPMILL_CLAUDE_PROBE=1 uv run pytest -q tests/test_contributors.py -k s033_10`) on b59da0b against a real `claude` on 2026-10-26: with the prompt passed right after `-p` (`--allowedTools` takes several values and had swallowed it), a hook in a session started with `--settings` whose env sets `SHIPMILL_APP_KEY` saw the variable and refused the plain `gh` write, so the gate needs no fallback; the probe is skipped unless `SHIPMILL_CLAUDE_PROBE=1`, pass
- S-033-11: `shipmill gh` with the variable, with a leading `--app-key` over it, and with no key (unset, empty, a missing path) exiting 2 with both lines and no gh, API call, or signature, in process and through `python -m shipmill`; `app-token` with the variable and with `--app-key` over it, pass
- S-033-12: `app_writes` for the three cases (the key file at mode 000 included) and doctor's hooks block on a repo with `app_id` and no key, pass
- S-033-13: `shipmill init`'s config holds `# plugin = "host"` with its comment, parses, and its uncommented example reads as `host`, pass
- S-033-14: `shipmill init --force` and `setup_state.py --fix` leave a `CONTRIBUTING.md` byte for byte; only `setup_state.py` (a read, D-42) and shipmill-setup's SKILL.md (its "never edit" rule) name the file under `skills/` and `src/shipmill/`, pass
- S-033-15: `docs/install.md`'s per-person default, opt-in snippet, Go live step 3, and Contributors section, `docs/release-lanes.md`'s `[agents] plugin`, and shipmill-setup's `PLUGIN_COMMITTED` and question, read by phrase, pass
- S-033-16: `app-token --check` exits 0 naming the App and the test (variable; key file at mode 000), exits 2 naming the path and `SHIPMILL_APP_KEY` (unset, empty), exits 2 naming `[agents] app_id` (no file, no key, no `[agents]`), refuses other arguments, and makes no API call, signature, or token cache, pass
- S-033-17: each of the six skills' "Write as the App" rule read for the check before the first write and a push, the stop on either exit 2, the hand-over of each write's target and text, and the never-as-the-person and never-the-key lines, pass
- S-033-18: `evals/github-issue-resolve/no-app-drafts` (kind `fix`, at bd2381f, whose config sets `app_id`, with `fixture/no-app`) is well formed (`shipmill evals check`), and the eval shim answers the check and refuses `shipmill gh` without the App; the case itself runs only in the `evals` workflow, not run here
