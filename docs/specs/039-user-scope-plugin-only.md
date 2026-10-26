# S-039: One user-scope install of the plugin; shadowing installs reported as one row and removed on request

status: approved
serves: G-1

## Problem

Spec 031 made each install of `shipmill@shipmill` an older release consistent with itself,
and has `doctor`, `status`, `setup_state.py`, and the tick report every install that lags,
one row per install with the fix to run in its folder. That assumes few installs. On one
maintainer's host `~/.claude/plugins/installed_plugins.json` held 17 installs of the
plugin: one at user scope (0.73.1) and 16 at project or local scope, at versions from
0.25.0 to 0.73.1, keyed on repo checkouts, gate checkouts (`tmp/shipmill-gate`), and four
linked worktrees that no longer existed (shipmill/shipmill#645).

A project or local install wins over the user install in its folder, so the update shipmill
prints for the user install, `claude plugin update shipmill@shipmill --scope user`, reached
one install in 17. Sessions in the other folders, gates included, kept loading old
releases: one gate ran 0.25.0. Each folder needed its own update or reinstall, run in that
folder, which is easy to run in the wrong one. The earlier fixes (#233, #240, #417, #477,
#485, #551) each handled one stale install; none asked where the installs come from.

What fixed the host was removing every project- and local-scope install and keeping only
the user one. Every folder then loads the user install, and one command updates them all:

```bash
claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user
```

A repo keeps `enabledPlugins` in its `.claude/settings.json`: that enables the plugin, and
the user install supplies it. The removal has a trap: `claude plugin uninstall
shipmill@shipmill --scope project` also rewrites the folder's `.claude/settings.json` and
drops `"shipmill@shipmill": true` from `enabledPlugins`, turning the plugin off for the
repo, so the file has to be saved before and written back after. An entry keyed on a folder
that is gone stays until the folder is recreated for the uninstall.

shipmill adds to the pile itself. The fixes it prints for a keyed install are an update or
a reinstall at project or local scope (`plugin_fix` in `watch_state.py`, `update_command`
in `src/shipmill/plugin.py`), and the hooks self-test's fix for a folder with no install is
`claude plugin install shipmill@shipmill --scope project` (`src/shipmill/hooks.py`). Each
keeps a keyed install alive, or creates one, where the user install would serve.

## Behaviour

### One install: the user's

The supported layout on a host is one install of `shipmill@shipmill` at user scope, and
`enabledPlugins` with the marketplace in each repo's `.claude/settings.json`. shipmill never
creates a project- or local-scope install, and never prints a command that creates or
updates one:

- `skills/shipmill-setup/SKILL.md`: setup writes nothing about the plugin into a repo but
  `enabledPlugins` and `extraKnownMarketplaces` in its `.claude/settings.json`, as
  `setup_state.py --fix` does today (whether it writes them at all is spec 033's, in
  shipmill/shipmill#521). When the host has no user install, setup gives the person `claude plugin
  install shipmill@shipmill --scope user`; it never installs at project or local scope, and
  its text on `PLUGIN_OUTDATED` no longer describes per-folder updates or a reinstall
- `src/shipmill/hooks.py`: the self-test's fix for a folder no install applies to becomes
  `claude plugin install shipmill@shipmill --scope user`
- `src/shipmill/gate.py`: unchanged in this respect: the gate runs no `claude plugin
  install`, `update`, or `uninstall`, as D-50 has it
- `src/shipmill/plugin.py` (`update_command`) and
  `skills/github-ship-watch/scripts/watch_state.py` (`plugin_fix`): the fix for the user
  install is the single command above, with no `in <folder>:`. The reinstall at project or
  local scope for a folder with a nested install goes: a keyed install's fix is the
  shadowing row's below
- `src/shipmill/requires.py`, `src/shipmill/doctor.py` (the `requires` WARN), and
  `watch_state.py`'s `requires` text: the update they print names `--scope user`, not
  `--scope <scope>`

A test greps `src/`, `skills/`, `hooks/`, `README.md`, and `docs/install.md` for a `claude
plugin install` or `claude plugin update` with `--scope project` or `--scope local`, and
finds none.

### One shadowing row

`watch_state.py`'s `shipmill_rows` reads every project- and local-scope entry for
`shipmill@shipmill` that `claude plugin list --json` lists on the host, whichever folder it
is keyed on, and reports them as one row, in place of a `SHIPMILL_OUTDATED` row per keyed
install and the S-031-16 row for a gate's linked worktree:

```
PLUGIN_SHADOWING  plugin keyed  16 project- or local-scope installs of shipmill@shipmill (0.25.0 to 0.73.1, 12 folders, 4 missing) shadow the user install; uvx shipmill==0.73.1 plugin-clean
```

- **The count, the versions, the folders, and how many folders are missing** are in the
  detail; the folders themselves are listed by `plugin-clean`, not in the row
- **Its fix** is `uvx shipmill==<version> plugin-clean` (the dry run, below), with
  `<version>` the plugin's own, as spec 031 pins it; with no user install the fix first
  names `claude plugin install shipmill@shipmill --scope user`
- **No keyed install, no row.** The user install keeps its own `SHIPMILL_OUTDATED` row when
  it lags, whose fix is the single command above
- **Any version.** A keyed install at the latest release still shadows the user install and
  goes stale on the next release, so it is reported too
- `SHIPMILL_VERSION` keeps its `a session loads <scope> <version> (<project>)` part

The row is an action for a person, never an agent's, like `SKILL_SHADOWED`:

- `src/shipmill/doctor.py` shows it as a WARN under `plugin`, which leaves the exit code as
  the other checks set it
- `src/shipmill/status.py` lists it among the reasons that wait on the person
  (`YOURS_ROWS`), with its fix; `skills/github-ship-watch/scripts/fleet.py` knows the state
- `skills/shipmill-setup/scripts/setup_state.py` shows it as `PLUGIN_SHADOWING`, not done
  (exit 1), and `--fix` leaves it
- `skills/github-ship-watch/SKILL.md` and `skills/shipmill-setup/SKILL.md` describe the row
  and its fix in place of the per-folder updates

The tick (`src/shipmill/gate.py`, `plugin_read`) reports a keyed install a session loads as
shadowing, naming the `plugin-clean` fix, and starts the session, as spec 031 has it for any
lagging install. The once-per-release notification (S-031-20) names the same fixes.

### `shipmill plugin-clean`

A new command in `src/shipmill/cli.py`, which needs no `--repo` and no config, removes the
keyed installs for a person. It reads `claude plugin list --json` and prints one line per
project- or local-scope entry of `shipmill@shipmill`, deepest folder first:

```
remove  project  0.25.0  /Users/me/repo-a                       restores .claude/settings.json
remove  local    0.58.0  /Users/me/repo-b/tmp/shipmill-gate      missing: created for the uninstall, then removed
manual  local    0.70.0  /Users/me/repo-c/tmp/shipmill-gate      a linked worktree: delete the entry with "projectPath": "/Users/me/repo-c/tmp/shipmill-gate" under "shipmill@shipmill" in ~/.claude/plugins/installed_plugins.json
then: claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user
```

- **A dry run by default.** Without `--apply` it changes nothing, writes no file, and runs
  no `claude plugin` command but the list; it exits 0
- **`--apply` acts, from a person's terminal only.** It refuses with exit 2, before any
  change, when its standard input is not a terminal: an agent's Bash tool and a headless
  gate session (stdin from `/dev/null`, D-17) never have one, so no agent session removes
  an install, in line with D-50. It also refuses with exit 2, before any change, when the
  host has no user-scope install, naming `claude plugin install shipmill@shipmill --scope
  user`: removing the keyed installs would leave those folders with none
- **Each removal**, in the folder it is keyed on: save the bytes of `.claude/settings.json`
  and `.claude/settings.local.json` (or that each is absent), run `claude plugin uninstall
  shipmill@shipmill --scope <scope>` there, then write each file back byte for byte, and
  delete a file the uninstall created where none was. A folder created for the uninstall
  gets no restore step: it is removed with what the uninstall wrote in it
- **Checked after each removal.** It reads `claude plugin list --json` again: the target
  entry must be gone and every other entry, of any plugin and scope, unchanged. Anything
  else (the entry still there, another one gone, as #233's nested-folder bug would do) stops
  the run with exit 2, naming the change, after that folder's settings are restored
- **A missing folder** is created for the uninstall, with each missing parent, and after the
  check every folder it created is removed again, provided it holds nothing but what the
  uninstall wrote (`.claude/` and its settings files); otherwise it is left and named, exit 1
- **A linked git worktree on disk** is `manual`: Claude Code resolves a `claude plugin`
  command run there to the main checkout (#417, #485), so no command reaches its entry.
  The line gives spec 031's fix, deleting the entry by hand; shipmill never writes
  `~/.claude/plugins/installed_plugins.json`
- **Never touched:** the user and managed installs, any other plugin's install, any other
  key or file in a folder, and Claude Code's plugin cache
- **The last line** is the user install's update when it lags the latest release, and
  nothing when it doesn't
- **Exit codes:** 0 when no keyed install is left, 1 when some are (`manual` lines, or a
  created folder left behind), 2 on a refusal, a failed `claude` command, a malformed
  listing, or a check that fails

### Docs

- `docs/install.md`: one install at user scope; a repo's `.claude/settings.json` enables it;
  the `PLUGIN_SHADOWING` row and `shipmill plugin-clean`; the single update command
- `skills/shipmill-setup/SKILL.md` and `skills/github-ship-watch/SKILL.md`: as above

## Acceptance criteria

- S-039-1: No file under `src/`, `skills/`, or `hooks/`, nor `README.md` or `docs/install.md`, contains a `claude plugin install` or `claude plugin update` command with `--scope project` or `--scope local`; the gate's commands include no `claude plugin install`, `update`, or `uninstall`
- S-039-2: The fix `doctor`, `status`, `setup_state.py`, and the tick print for a lagging user-scope install is exactly `claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user`, with no folder named; the `requires` message of `src/shipmill/requires.py` and `watch_state.py`, and `doctor`'s `requires` WARN, name `--scope user`
- S-039-3: The hooks self-test, finding no install that applies to the checkout, FAILs with the fix `claude plugin install shipmill@shipmill --scope user`
- S-039-4: With one or more project- or local-scope entries of `shipmill@shipmill` in `claude plugin list --json`, at any version and keyed on any folder, `watch_state.py` prints exactly one `PLUGIN_SHADOWING` row whose detail gives their count, their lowest and highest versions, the number of folders, and how many are missing, and whose fix is `uvx shipmill==<the plugin's version> plugin-clean`; it prints no `SHIPMILL_OUTDATED` row for a keyed install and no S-031-16 row; with none it prints no `PLUGIN_SHADOWING` row
- S-039-5: With no user-scope install and a keyed one, the `PLUGIN_SHADOWING` row's fix names `claude plugin install shipmill@shipmill --scope user` before `plugin-clean`
- S-039-6: `doctor` shows the `PLUGIN_SHADOWING` row as a WARN under `plugin` that alone leaves its exit code 0; `shipmill status` lists it among the reasons waiting on the person with its fix; `setup_state.py` prints `PLUGIN_SHADOWING`, exits 1 on it, and `--fix` leaves the installs as they were
- S-039-7: A tick whose session loads a project- or local-scope install reports it with the `plugin-clean` fix and starts the session
- S-039-8: `shipmill plugin-clean` without `--apply` prints one `remove` or `manual` line per keyed entry, deepest folder first, runs no `claude` command but `claude plugin list --json`, writes no file, and exits 0
- S-039-9: `shipmill plugin-clean --apply` with a standard input that is not a terminal exits 2 before any `claude plugin uninstall`, and so does a run on a host with no user-scope install, naming `claude plugin install shipmill@shipmill --scope user`
- S-039-10: `shipmill plugin-clean --apply` removes each keyed entry with `claude plugin uninstall shipmill@shipmill --scope <scope>` run in its folder, and afterwards that folder's `.claude/settings.json` and `.claude/settings.local.json` are byte-identical to before, or absent where they were absent, even when the uninstall rewrote or created them
- S-039-11: When `claude plugin list --json` after an uninstall still lists the target entry, or lists any other entry changed or gone, `plugin-clean --apply` restores that folder's settings files and exits 2 naming the change, and runs no further uninstall
- S-039-12: For an entry keyed on a missing folder, `plugin-clean --apply` creates the folder and its missing parents, uninstalls there, and then removes every folder it created; a created folder holding anything but `.claude/` and its settings files is left, named, and makes the exit 1
- S-039-13: An entry keyed on an existing linked git worktree is a `manual` line with the fix to delete its entry in `~/.claude/plugins/installed_plugins.json`; `plugin-clean --apply` runs no uninstall there, exits 1 while it is left, and shipmill writes nothing to that file
- S-039-14: `plugin-clean --apply` never runs an uninstall for a user- or managed-scope install or another plugin's, and exits 0 when no keyed entry of `shipmill@shipmill` is left; when the user install lags the latest release, its last line is the S-039-2 update command
- S-039-15: `docs/install.md`, `skills/shipmill-setup/SKILL.md`, and `skills/github-ship-watch/SKILL.md` describe one user-scope install, the `PLUGIN_SHADOWING` row, `shipmill plugin-clean`, and the single update command, and none tells the person to update or reinstall an install in a repo's folder

## Out of scope

- Repos whose own docs pin `uvx shipmill==<version>` and go stale on each release (#645's
  closing remark): those docs are the maintainer's (D-42), so shipmill neither rewrites
  them nor, in this spec, reports them; a `setup_state.py` row naming file and line, like
  `CHANGELOG_RULES`, can be its own issue
- Claude Code's plugin cache (`~/.claude/plugins/cache/shipmill/shipmill/`, 27 versions and
  129 MB on the reporting host): Claude Code's to prune
- Editing `~/.claude/plugins/installed_plugins.json`: Claude Code's file, as in spec 031
- Claude Code installing the plugin at project scope on its own, such as when a person
  accepts its prompt for a repo whose settings enable the plugin: not shipmill's command;
  the `PLUGIN_SHADOWING` row reports what results
- Any removal by the gate, the watch, or an agent session: `--apply` runs only from a
  person's terminal
- Updating the user install: still the person's, with the printed command (spec 031)

## Decisions relied on

- D-17: a headless gate session runs as `claude -p` with no terminal, which is what keeps `plugin-clean --apply` out of it
- D-42: a client repo's own docs are the maintainer's, so the stale `uvx shipmill==<version>` pins in them stay out of scope
- D-50: a gate session loads the install that applies to its checkout and never updates an install; doctor, status, and the tick report lagging installs with their fixes, and the one plugin check that holds a session stays PyPI's 404

## Issues

- shipmill/shipmill#701: S-039-1, S-039-2, S-039-3, S-039-4, S-039-5, S-039-6, S-039-7, S-039-8, S-039-9, S-039-10, S-039-11, S-039-12, S-039-13, S-039-14, S-039-15

## Verification
