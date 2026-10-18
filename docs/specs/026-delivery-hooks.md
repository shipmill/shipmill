# S-026: Hooks that enforce the delivery rules

status: approved
serves: G-2

## Problem

The rules agents must always keep are written in skills, and a skill is advice: an agent
can miss it, misread it, or lose it to a long context. The costly mistakes are ones a hook
could refuse before they happen (shipmill/shipmill#381):

- **A write through plain `gh` when the repo has an App.** github-pr-triage rule 8 says
  every write goes through `shipmill gh`. A plain `gh`, or a `GH_TOKEN=$T gh` whose `$T`
  came back empty, writes as the maintainer's own login, so the comment, label, or merge
  is attributed to a person who didn't make it (D-14, Q-2)
- **A push to the default branch.** Work lands through a pull request, reviewed and gated
- **A rebase merge.** D-33 lands with a squash, or a merge commit for a stack's base, and
  never rebase-merges
- **A force push without a lease pinned to a commit.** It can drop a commit someone else
  pushed since the agent last fetched
- **A copy of a private path.** Some repos keep a folder (an `owner/` folder, for example)
  whose files must never leave the repo for a public one

Spec 024 also relies on this one: after an agent edits `docs/product.md`, `docs/product/`,
or a `REVIEW.md`, a hook runs `shipmill product check` and `shipmill review check`, so a
broken line shows with its number before the commit, not in CI.

The skills keep their text. A hook is a second line under it, for the mistakes whose cost
is a write nobody can take back. The maintainer settled the choices below in chat when
approving this spec, recorded as D-36.

## Behaviour

### The hooks file

The plugin gains `hooks/hooks.json` at its root, which Claude Code loads with the plugin
(`.claude-plugin/plugin.json` is unchanged), and one stdlib-only script,
`hooks/delivery.py`:

```json
{
  "description": "shipmill: refuse the writes the delivery rules forbid",
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "timeout": 10,
        "command": "uv run --no-project --python '>=3.11' python \"${CLAUDE_PLUGIN_ROOT}/hooks/delivery.py\" pre"}]}
    ],
    "PostToolUse": [
      {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "timeout": 60,
        "command": "uv run --no-project --python '>=3.11' python \"${CLAUDE_PLUGIN_ROOT}/hooks/delivery.py\" post"}]}
    ]
  }
}
```

`uv run` picks a Python with `tomllib` (3.11+) whatever `python3` is on PATH; a probe on
the maintainer's machine, whose `python3` is 3.8, measured its startup at 20 to 30 ms.

**When the hook can't start the script, the command runs** (D-40, shipmill/shipmill#458).
uv exits 2 when it can't get a Python 3.11 or newer (offline, or `python-downloads =
"never"`), and Claude Code reads a PreToolUse exit 2 as a refusal, so the command above
would block every shell command in such a session. Each hook command therefore first gets
the interpreter (one uv already has, else one uv installs) and checks that
`hooks/delivery.py` exists, and only then runs the script with it. When uv is missing, no
Python 3.11 or newer can be found or installed, or the script is missing, the hook prints
one stderr line, `shipmill hook: can't start hooks/delivery.py (<the reason>); this
command runs unchecked, see shipmill doctor`, and exits 1. Only the script's own refusal
exits 2. `shipmill doctor`'s self-test (S-026-15) still FAILs on that case, and a headless
gate whose self-test fails starts no session (S-026-16), so only a person's session runs
unchecked.

The script reads Claude Code's hook input from stdin, the JSON object every hook gets:
`session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, `tool_name`,
`tool_input` (for Bash, `command`; for Edit, Write, and MultiEdit, `file_path`), and for
PostToolUse `tool_response`. It answers with its exit code:

| Exit | Means | Claude Code |
|---|---|---|
| 0 | Allowed, or nothing to check | Runs the tool (pre), goes on (post); no output |
| 2 | Refused (pre), or a check failed (post) | Blocks the tool call (pre), and shows stderr to the model either way |
| 1 | The input wasn't the JSON object above, or the hook couldn't start the script | Runs the tool, and shows stderr in the transcript |

A hook runs before the permission check, so it applies under `--permission-prompts none`
and `--allowedTools` too: headless gate sessions (D-17) are covered with no gate change.

### Where the rules apply

The script finds the repo from the directory the command runs in: the hook input's `cwd`,
then a leading `cd <dir> &&` and `git -C <dir>` in the command, by walking up to the
nearest `.git` (a folder, or a worktree's file) with no subprocess. The rules apply only
when that repo's `.github/shipmill.toml` (D-4) has an `[agents]` section, the condition
D-34 uses for a repo whose agents implement. Anywhere else, including a repo where
shipmill only cuts releases and every folder outside a repo, every call exits 0.

### What a refusal says

Every refusal is exit 2 with three lines on stderr, so the model can correct itself in one
step:

```
shipmill hook rebase-merge: gh pr merge 412 --rebase
Rule: land with a squash, or a merge commit for a stack's base; never rebase-merge (D-33)
Instead: gh pr merge 412 --squash
```

The first names the rule and the refused command (cut to 200 characters), the second the
rule and where it is written, the third the command to run instead, built from the refused
one where the rule allows it.

### The rules

Bash rules read the command with `shlex`, split it into simple commands at `&&`, `||`,
`;`, `|`, and newlines, skip leading `NAME=value` assignments, and judge each simple
command by its program's base name. A command `shlex` can't split, and constructs the
script doesn't parse (`bash -c`, `sh -c`, `eval`, `$(...)`, here-documents), are allowed:
the hooks catch an agent's mistake, and the trust filter (D-16) stays the control against
hostile text.

| Rule | Refuses | Switch |
|---|---|---|
| `app-writes` | A `gh` write (table below) when `[agents] app_id` is set, unless the program is `shipmill gh` (directly or through `uvx --from ... shipmill gh`). An inline `GH_TOKEN=$T gh` is refused too: an empty `$T` falls back to the maintainer's login, while `shipmill gh` exits 2; `shipmill gh` is the way to write (D-36) | Always on where `app_id` is set |
| `default-branch-push` | A `git push` whose destination is the default branch: a refspec naming it (`main`, `HEAD:main`, `+main`, `refs/heads/main`, `:main`), or no refspec while the current branch's push target is it | `[hooks] default_branch = false` |
| `rebase-merge` | `gh pr merge` with `--rebase` or `-r`; a `gh api` call with `merge_method=rebase` | Always on |
| `force-push` | A `git push` with `--force`, `-f`, a `+` refspec, `--force-with-lease` with no value, or `--force-with-lease=<ref>` with no `:<sha>`. `--force-with-lease=<ref>:<sha>` is allowed, as landing.md and watch's WORK_BRANCH_STALE use it | Always on |
| `private-paths` | `cp`, `mv`, or `rsync` with a source matching a `[hooks] private` glob (relative to the repo root) and a destination outside the repo | On when `private` lists a glob |

A `gh` **write** is any of these; every other `gh` command is a read and passes:

- `gh issue` `create`, `comment`, `edit`, `close`, `reopen`, `delete`, `lock`, `unlock`,
  `pin`, `unpin`, `transfer`, `develop`
- `gh pr` `create`, `comment`, `edit`, `close`, `reopen`, `merge`, `review`, `ready`,
  `lock`, `unlock`, `update-branch`
- `gh label` `create`, `edit`, `delete`, `clone`
- `gh release` `create`, `edit`, `delete`, `delete-asset`, `upload`
- `gh workflow` `run`, `enable`, `disable`; `gh run` `rerun`, `cancel`, `delete`
- `gh repo` `create`, `edit`, `delete`, `rename`, `archive`, `unarchive`, `fork`;
  `gh secret` and `gh variable` `set`, `delete`
- `gh api` with `-X`/`--method` other than `GET`, or with `-f`, `-F`, `--field`,
  `--raw-field`, or `--input` and no `-X GET`; for `gh api graphql`, only a query that
  holds `mutation`

The default branch is the target of `refs/remotes/origin/HEAD`. Only a `git push` costs a
subprocess (`git symbolic-ref` and, for a push with no refspec, `git rev-parse
--symbolic-full-name @{push}`); when `origin/HEAD` is unset, `default-branch-push` can't
tell and allows, and `doctor` reports it. No command but `git push` spawns a process, and
the config is read at most once per call.

There is no switch a session can set for itself, such as an environment variable: a rule
that is in the way is switched off in the config, through a pull request, or the person
runs the command in their own terminal.

### After an edit: the direction and the rubric

The PostToolUse hook looks at `tool_input.file_path` of an Edit, Write, or MultiEdit
inside a repo with `[agents]`:

- `docs/product.md` or a file under `docs/product/` runs `shipmill product check --repo
  <root>` (spec 024)
- a file named `REVIEW.md` anywhere in the repo runs `shipmill review check --repo <root>`

It runs `shipmill` from PATH, else `uvx --from git+https://github.com/shipmill/shipmill@v0
shipmill`, as the skills do. A check that exits 1 makes the hook exit 2 with the check's
output on stderr, which shows the model the file, line, and rule; the edit is already
written, so the model fixes it. A check that exits 2, or a `shipmill` that can't be run,
exits 1, a visible non-blocking error. Any other path starts no subprocess.

### The config

A new optional section in `.github/shipmill.toml`, parsed by `src/shipmill/policy.py`
like every other (an unknown key or a wrong type fails with exit 2, naming the key):

```toml
[hooks]
default_branch = true      # refuse a push to the default branch (the default)
private = ["owner/**"]     # globs, relative to the repo root, whose files never leave it (default: none)
```

`app-writes`, `rebase-merge`, and `force-push` have no switch: they hold settled rules
(D-14, D-33, and landing's lease), and a repo that needs otherwise changes the rule first.
`default-branch-push` is the one rule a repo may switch off, and `private-paths` stays
narrow (copies out of the repo only; see Out of scope), both as D-36 settles.
The hook script parses `[agents] app_id` and `[hooks]` itself with `tomllib`, since the
plugin can't import the installed `shipmill`. When the config doesn't parse or a key is
malformed, a guarded command (a `gh` write, a `git push`, `gh pr merge`, a copy) is
refused with the config's error as the rule line, and every other command passes, so the
agent can still read and fix the file.

### `doctor` and setup

`src/shipmill/doctor.py`, for a repo whose config has `[agents]`, adds a `hooks` block:

- One PASS line per rule naming it and whether it is on or off, and why when off (no
  `app_id`, `default_branch = false`, no `private` globs)
- A **self-test**: it runs the `hooks/delivery.py` of the install a session in the repo
  would load (the install D-35 reads, through `src/shipmill/plugin.py`) with a PreToolUse
  input for `gh pr merge 1 --rebase` and `cwd` set to the repo, and expects exit 2. The
  command is only shown to the hook, never run. FAIL when the hook allows it, when the
  install has no `hooks/hooks.json` (an install older than this spec), when `uv` isn't on
  PATH, or when the project, local, or user Claude Code settings set `disableAllHooks`,
  each naming the fix
- WARN when `refs/remotes/origin/HEAD` is unset, with `git remote set-head origin --auto`

A repo without `[agents]` gets no hooks block. `skills/shipmill-setup/SKILL.md` says the
hooks come with the plugin, asks whether the repo has paths to list under `[hooks]
private`, and reads the doctor block before it reports the agent side connected.

A headless gate (`src/shipmill/gate.py`) runs the same self-test before it starts a
session, at most once per tick, and when it fails starts no session and reports the
failure on the tick, as D-35 does for stale skills: an unattended session is where an
advice miss goes unseen, and the maintainer chose a paused gate over report-only (D-36).
An interactive gate reports it and still starts.

### One rule list with the headless allowlist: no

`HEADLESS_TOOLS` in `src/shipmill/gate.py` is an allow list with another job: it names the
tools a `claude -p` session may run without a prompt, so nothing blocks it. The hooks are
deny rules on the arguments of tools already allowed (`Bash(gh *)`, `Bash(git *)`), which
a permission pattern can't express (`git -C <dir> push`, a refspec, `--force-with-lease`
with or without a SHA). Merging them would let a change to one widen or narrow the other.
They stay apart: the rules live in `hooks/delivery.py` alone, and a comment above
`HEADLESS_TOOLS` points to it.

### How the tests drive a hook

`tests/test_delivery_hooks.py` runs `hooks/delivery.py` as a subprocess, as Claude Code
does, with stdin set to the hook input JSON and `cwd` a temporary git repo holding a
`.github/shipmill.toml` and an `origin` remote with `origin/HEAD` set, and asserts the exit
code and stderr. The inputs are files in `tests/fixtures/hooks/`, one per case, in the
exact shape above (taken from a real session's hook input, `session_id` and paths
replaced), so a change in Claude Code's format shows as one fixture to update. Each rule
has a refused and an allowed case, and the PostToolUse cases run a stub `shipmill` first
on PATH that records its arguments and exits as the test sets. A test also reads
`hooks/hooks.json`, checks its events and matchers, and that each command names a file
that exists.

### Docs

- `skills/github-pr-triage/SKILL.md` (rule 8) and `skills/github-pr-triage/references/landing.md`
  (Merge style, force-push): one line each that a hook refuses the forbidden form
- `docs/release-lanes.md`: the `[hooks]` keys, next to `[agents]`
- `docs/install.md`: the hooks come with the plugin, need `uv`, and `doctor` tests them

## Acceptance criteria

- S-026-1: dropped in #458, see S-026-19
- S-026-2: In a folder outside a git repo, in a repo with no `.github/shipmill.toml`, and in one whose config has no `[agents]` section, every fixture the other criteria refuse exits 0 with no output
- S-026-3: With `[agents] app_id` set, each `gh` write the Behaviour lists, plain or after `GH_TOKEN=... `, exits 2 naming `app-writes` and D-14 with an `Instead:` line using `shipmill gh` and the same arguments; a `gh` read, a `gh api` GET, a `gh api graphql` query without `mutation`, `shipmill gh <write>`, and `uvx --from <spec> shipmill gh <write>` exit 0; without `app_id` every one exits 0
- S-026-4: `git push origin main`, `git push origin HEAD:main`, `git push origin +main`, `git push origin refs/heads/main`, `git push origin :main`, and a bare `git push` on `main` with its upstream on `origin/main` exit 2 naming `default-branch-push`, where `origin/HEAD` points at `main`; a push of another branch exits 0, and every one exits 0 with `[hooks] default_branch = false` or with `origin/HEAD` unset
- S-026-5: `gh pr merge N --rebase`, `gh pr merge N -r`, and a `gh api` call with `merge_method=rebase` exit 2 naming `rebase-merge` and D-33 with `--squash` in the `Instead:` line; `gh pr merge N --squash` and `--merge` exit 0
- S-026-6: `git push` with `--force`, `-f`, a `+` refspec to a non-default branch, a bare `--force-with-lease`, or `--force-with-lease=<ref>` exits 2 naming `force-push`; `git push --force-with-lease=<ref>:<sha> origin <src>:<ref>` exits 0
- S-026-7: With `[hooks] private = ["owner/**"]`, `cp`, `mv`, and `rsync` with a source under `owner/` and a destination outside the repo exit 2 naming `private-paths`; a copy inside the repo, a copy of another path, and every copy with no `private` key exit 0
- S-026-8: A refused simple command is found inside a compound command (`&&`, `||`, `;`, `|`, newlines), after leading `NAME=value` assignments, after a leading `cd <dir> &&`, and with `git -C <dir>`, where the directory reached decides the repo; a command `shlex` can't split, and one the rule reaches only through `bash -c`, `sh -c`, `eval`, or `$(...)`, exits 0
- S-026-9: Every refusal writes exactly three stderr lines: `shipmill hook <rule>: <command, cut to 200 characters>`, `Rule: <rule> (<source>)`, and `Instead: <command>`
- S-026-10: A Bash command other than `git push`, and an edit of a path other than the direction or a `REVIEW.md`, makes the hook start no subprocess (the test counts them through the script's injected runner), and every call reads `.github/shipmill.toml` at most once
- S-026-11: Stdin that isn't a JSON object with `hook_event_name`, `tool_name`, and `tool_input` exits 1 with a message naming the missing field; a `tool_name` the hook doesn't check exits 0
- S-026-12: With a config that fails to parse, or a malformed `[hooks]` or `[agents] app_id`, a guarded command exits 2 with the config's error on the `Rule:` line, and an unguarded command (`ls`, `git status`, `gh pr view`) exits 0
- S-026-13: After an Edit, Write, or MultiEdit of `docs/product.md` or a file under `docs/product/`, the PostToolUse hook runs `shipmill product check --repo <root>`, and after one of any `REVIEW.md` it runs `shipmill review check --repo <root>`; a check exiting 0 gives exit 0 with no output, exiting 1 gives exit 2 with the check's output on stderr, and exiting 2 or failing to start gives exit 1
- S-026-14: `src/shipmill/policy.py` reads `[hooks]` with `default_branch` (a boolean, default true) and `private` (a list of strings, default empty), and refuses any other key or a wrong type with exit 2 naming the key
- S-026-15: `shipmill doctor`, for a repo with `[agents]`, prints one line per rule saying on or off and why, and FAILs naming the fix when the self-test against the install a session would load doesn't exit 2, when that install has no `hooks/hooks.json`, when `uv` isn't on PATH, or when a Claude Code settings file sets `disableAllHooks`; it WARNs when `origin/HEAD` is unset; a repo without `[agents]` gets no hooks block
- S-026-16: A headless gate whose hook self-test fails starts no session and reports the failure on the tick; an interactive gate reports it and starts the session
- S-026-17: `tests/fixtures/hooks/` holds the inputs the hook tests use, each in the shape Claude Code sends, with a refused and an allowed case for each rule and a PostToolUse case for each check
- S-026-18: `skills/github-pr-triage/SKILL.md` rule 8, `skills/github-pr-triage/references/landing.md`, `skills/shipmill-setup/SKILL.md`, `docs/release-lanes.md`, and `docs/install.md` name the hooks as the Behaviour's Docs list says, and a comment above `HEADLESS_TOOLS` in `src/shipmill/gate.py` points to `hooks/delivery.py`
- S-026-19: `hooks/hooks.json` declares a PreToolUse hook matching `Bash` and a PostToolUse hook matching `Edit|Write|MultiEdit`, each running `hooks/delivery.py` under `${CLAUDE_PLUGIN_ROOT}` with a Python 3.11 or newer that uv finds or installs, and the file each names exists; run with no such Python (uv offline with none installed, or `python-downloads = "never"`), with no `uv` on PATH, or with the script missing, each hook command exits 1 with one stderr line naming `shipmill doctor`, never 2, and a refused fixture through the same command still exits 2

## Out of scope

- Stopping a determined or hostile agent: a hook reads one command's text, so `bash -c`,
  a script file, or retyping a private file's content gets past it; who may steer an
  unattended session stays the trust filter's job (D-16)
- A `git add` or commit of a private path: whether that is a leak depends on where the
  repo is pushed, which needs a network read per call; a later spec can add it
- Merging the headless allowlist and the hook rules into one list: they do different jobs
  (above)
- Hooks for other agents than Claude Code: the plugin is Claude Code's; a hook format for
  another agent is its own spec
- Checking `docs/specs/` or `docs/decisions.md` after an edit: CI runs `specs.py check`
  and `decisions.py check` already, and the issue asked for the direction and the rubric
- A switch an agent can set in its own session to turn a rule off

## Decisions relied on

- D-4: the `[hooks]` section lives in `.github/shipmill.toml`
- D-14: agent writes go as the App or not at all, which `app-writes` enforces
- D-16: the trust filter, not a hook, keeps an outsider's text from steering a session
- D-17: headless sessions run as `claude -p` with a tool allowlist, which hooks still apply under
- D-33: no rebase merge, which `rebase-merge` enforces
- D-34: a repo with `[agents]` keeps a direction and an optional rubric, which the PostToolUse hook checks
- D-35: the gate starts no session when a session would load stale skills, the model for the self-test pause
- D-40 (superseding D-36): delivery rules that guard irreversible writes are enforced by plugin hooks in repos with `[agents]`; it settles the inline `GH_TOKEN=$T gh` refusal, the switches, the headless pause, and that a hook which can't start its script exits 1 and lets the command run

## Issues

- shipmill/shipmill#440: S-026-14
- shipmill/shipmill#441: S-026-1, S-026-2, S-026-3, S-026-5, S-026-6, S-026-8, S-026-9, S-026-10, S-026-11, S-026-12
- shipmill/shipmill#444: S-026-4, S-026-7, S-026-17
- shipmill/shipmill#445: S-026-13
- shipmill/shipmill#446: S-026-15, S-026-16
- shipmill/shipmill#447: S-026-18
- shipmill/shipmill#458: S-026-19

## Verification
