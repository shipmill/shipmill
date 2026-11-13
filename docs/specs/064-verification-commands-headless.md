# S-064: A repo's verification commands are known to work from a headless session

status: built
serves: G-2

## Problem

The commands a repo relies on for verification can be unavailable to headless gate sessions,
and nothing finds out until a session needs them; the failure then reads as a permission
problem or goes unnoticed (#967, grouped into #1054). In one connected repo:

- A command the maintainer had approved for the gate exited 127 across 18 sessions, because
  the program is not on the gate host's PATH (the launchd job's PATH, which
  `src/shipmill/launchd.py` builds from where claude, gh, git, and uvx live). The question
  put to the maintainer said the allowlist denied it, so the fix made was the wrong one
- An allowlist rule of the form `Bash(pnpm api:*)` never matched the command it was added for
- A rule for `pnpm --dir web` matched worktrees under the gate checkout, but not the
  `.claude/worktrees` that implementers use

Database and web checks therefore ran for the first time in CI, at 18 to 30 minutes a job,
and one pull request reached CI with eight tests that used an undefined fixture.

A headless session can't prompt: its allowlist is the gate's `--allowedTools`
(`HEADLESS_TOOLS` in `src/shipmill/gate.py`), widened by `--claude-arg` flags and by Claude
Code's settings files, and since D-82 the delivery hook (`hooks/delivery.py`) also refuses a
`uv run` of a program outside its list. A command can fail at any of the three: no allow rule
matches it, the hook refuses it, or the shell doesn't find its program. This spec declares
the commands once and checks them through all three, where and as a session would run them,
before a session depends on them.

## Behaviour

### The declared commands

`[agents] verify` in `.github/shipmill.toml` (D-4) is a list of command strings, each one
line, as a session would pass it to the Bash tool:

```toml
[agents]
verify = ["pnpm install --frozen-lockfile", "pnpm --dir web test", "uv run pytest -q tests/db"]
```

They run in the order given, in one worktree, so a list may start with its setup command.
`AgentsConfig.parse` (`src/shipmill/agents.py`) exits 2 naming `[agents] verify` for a value
that isn't a list of strings, an empty or blank string, a string holding a newline, or a
string given twice. An absent key is an empty list: nothing is checked and nothing is
reported. The list is read from the config on `origin/<default>`, as the gate reads every
`[agents]` key, never from a pull request (D-16).

### The check

A new module, `src/shipmill/verify.py`, checks the list in a fresh worktree,
`<checkout>/.claude/worktrees/shipmill-verify-<8 hex>`, created detached at
`origin/<default>`, the folder Claude Code's worktrees for implementers use. It removes the
worktree when the check ends, passed, failed, or interrupted by an error (D-24).

Each command's **parts** are its simple commands, split on `&&`, `||`, `;`, `|`, and newlines
as the delivery hook's `commands` splits them. Each command goes through three steps; the
first that fails names the result, and a command that fails step 1 or 2 is not run:

1. **The allowlist.** Each part must match an allow rule and no deny rule of a headless
   session in that worktree. The allow rules are `HEADLESS_TOOLS`, the values of the gate's
   `--claude-arg` `--allowedTools` and `--allowed-tools` flags, and `permissions.allow` of the
   settings files Claude Code reads for a session there (the user's `~/.claude/settings.json`,
   the worktree's `.claude/settings.json`, and `.claude/settings.local.json` of the checkout
   the gate sessions run in, since an untracked file never exists in a fresh worktree); the
   commands inside a `$(...)` or backtick substitution are parts of their own, and the
   wrappers Claude Code strips (`timeout`, `nohup`, `nice`, `command`, `xargs`) are stripped
   before a part is matched (#1123); the deny rules are
   the `--disallowedTools` values and `permissions.deny` of the same files. A Bash rule matches
   a part as Claude Code documents: `Bash` or `Bash(*)` any part; `Bash(<prefix>:*)` a part
   that is the prefix or starts with it followed by a space; `Bash(<pattern>)` with `*`
   matching any run of characters, else the exact text. A deny rule wins. A part no allow rule
   matches is `denied`, naming the part; a part a deny rule matches is `denied`, naming the
   part and the rule
2. **The delivery hook.** Each part goes to the delivery hook a gate session loads (the
   script the gate's hook self-test runs, spec 026) as a PreToolUse Bash input whose cwd is
   the worktree, or the directory a `cd` in an earlier part set (#1123), in an environment with `SHIPMILL_GATE=1` as a headless session's
   `--settings` env sets it. An exit 2 is `refused by hook`, naming the rule from the hook's
   first stderr line (`shipmill hook <rule>: ...`), such as D-82's `uv-run`
3. **The run.** The command runs through the shell the gate's environment names in `SHELL`
   (`/bin/sh` without one) with `-c`, cwd the worktree, stdin from `/dev/null`, in the
   environment a headless session's process gets (`headless_env`, the gate's own PATH
   included) plus `SHIPMILL_GATE=1`, for at most 30 minutes. Exit 0 is `ok`; exit 127 is
   `not found`, naming the first part's program the PATH lacks (read with the same PATH);
   another exit is `failed`, naming the code and the last line of stderr; a run past 30
   minutes is stopped and is `timed out`

The check's result is one entry per command: the command, its result (`ok`, `denied`,
`refused by hook`, `not found`, `failed`, `timed out`), and its detail.

### When the gate checks

`shipmill gate` (`src/shipmill/gate.py`) runs the check on a real headless tick whose
decision is LAUNCH, after the hook self-test and the preflight and before it starts the
session, when the list isn't empty and the state directory's `verify.json` holds no result
for the current **fingerprint**: a hash of the list, the allow and deny inputs of step 1 (the
gate's tool flags and the settings files' text), the gate's PATH, and the version of the
plugin whose hook step 2 runs. A result with any failing command is checked again on the
first such tick `[agents] retry_hours` after it, since installing a program into a folder
already on PATH changes no input.

It writes `verify.json` (the fingerprint, the time, and the entries), and the tick's decision
line ends with `; verify: <k> of <n> commands fail: <first failing command> (<result>)` or
`; verify: <n> commands pass`. With `[agents] notify = true`, a result with a failing command
sends one desktop notification, once per fingerprint, naming the count and the first failing
command. The session starts whatever the result (D-64): an unavailable verification command
costs only that check, never every agent. An interactive tick, a dry run, or an empty list
runs no check.

### Where a result shows

`shipmill doctor` (`src/shipmill/doctor.py`) reads `verify.json` from the checkout's state
directory and prints one row named `verify command` per command of the current list:

- PASS, `<command>: ok at <time>`
- FAIL, `<command>: <result>: <detail>`, with its fix: for `denied`, the allow rule to add with
  `--claude-arg=--allowedTools --claude-arg "Bash(<part>)"` on `shipmill launchd`, or the deny
  rule that blocks it; for `refused by hook`, the hook's own Instead line; for `not found`,
  install the program into a folder of the gate's PATH, which it names, never an allowlist
  change; for `failed` and `timed out`, run the command in a worktree under
  `.claude/worktrees` to see why
- WARN, `<command>: not checked yet`, when `verify.json` holds no result for the current list,
  saying the gate checks it before its next headless session

With no list, doctor prints no `verify command` row (D-9).

### The question about a failed command

`skills/github-issue-triage/references/needs-decision.md`, A denied tool call is a decision,
tells three failures apart, so a question names the right cause and the right fix:

- **Denied**: Claude Code refused the call (no allow rule): the options stay as today, widen
  the allowlist with `--claude-arg` or do the step by hand
- **Refused by the hook**: the hook printed `shipmill hook <rule>`: the option is the hook's
  Instead line (for `uv-run`, `[hooks] uv_run`), never the allowlist
- **Not found**: the command ran and exited 127, or the shell said `command not found`: the
  allowlist let it through, so the question says the program is not on the gate host's PATH,
  names the program, and its option is installing it there; it never proposes widening the
  allowlist

## Acceptance criteria

- S-064-1: `AgentsConfig.parse` reads `[agents] verify` as a list of command strings and an absent key as an empty list, and exits 2 naming `[agents] verify` for a value that isn't a list of strings, an empty or blank string, a string with a newline, or a duplicate
- S-064-2: The allowlist step matches each part of a command against `HEADLESS_TOOLS`, the gate's `--allowedTools`/`--allowed-tools` and `--disallowedTools` flag values, and the settings files' `permissions.allow` and `permissions.deny`, by the `Bash`, `Bash(*)`, `Bash(<prefix>:*)`, and `Bash(<pattern>)` forms, a deny rule winning; `pnpm --dir web api` under only `Bash(pnpm api:*)` is `denied` naming the part
- S-064-3: A command whose part the delivery hook refuses with `SHIPMILL_GATE=1` (such as `uv run env`) is `refused by hook` naming the hook's rule, and is not run
- S-064-4: An allowed command runs in a worktree under `<checkout>/.claude/worktrees/` created at `origin/<default>`, through `$SHELL -c` with the gate's PATH; exit 0 is `ok`, exit 127 is `not found` naming the program, another exit is `failed` with its code and last stderr line, and a run past 30 minutes is `timed out`
- S-064-5: The commands run in the list's order in the one worktree, a `denied` or `refused by hook` command is not run, and the worktree is removed when the check ends, a failing or erroring check included
- S-064-6: A real headless LAUNCH tick with a non-empty list and no `verify.json` result for the fingerprint runs the check before it starts the session, writes `verify.json`, ends its decision line with the `; verify: ...` suffix, and starts the session whatever the result
- S-064-7: A tick doesn't check again while `verify.json` holds a passing result for the fingerprint; it checks again when the list, the tool flags, a settings file, the PATH, or the plugin's version changes, and when a failing result is `retry_hours` old; an interactive tick, a dry run, and an empty list run no check
- S-064-8: With `notify = true`, a failing result sends one desktop notification per fingerprint, and a tick that finds the same failing fingerprint sends none
- S-064-9: `shipmill doctor` prints one `verify command` row per command: PASS for `ok`, FAIL with the result, detail, and the fix its result calls for (never an allowlist change for `not found`), WARN `not checked yet` when `verify.json` has no result for the current list, and no row with an empty list
- S-064-10: `needs-decision.md`'s "A denied tool call is a decision" tells a denial, a hook refusal, and a not-found (exit 127) apart, gives each its fix, and says a not-found's question never proposes widening the allowlist

## Out of scope

- Running the check on demand from a person's shell: their PATH is not the gate's, which is the failure this spec catches; the gate runs it, and doctor shows the result
- A per-command timeout or environment in the config: one fixed 30-minute limit, and the session's own environment
- Filing an issue for a failing command (#967's proposal): a program missing on the host is host state, which D-55 keeps out of the pipeline's records; the tick, the notification, and doctor report it
- Holding sessions while a command fails: they start, as D-64 keeps a broken piece to its own feature
- Adding folders to the launchd job's PATH from the config: the fix names the PATH; changing how `shipmill launchd` builds it is its own change
- Interactive gates: a person approves each command there, so no allowlist stands between a session and its command
- Checking that the commands pass on the default branch as a quality gate: a `failed` result says the command ran; whether its tests pass is CI's

## Decisions relied on

- D-4: `[agents] verify` lives in `.github/shipmill.toml`
- D-9: no `verify command` row without a list
- D-24: whoever creates a worktree removes it; the check's has no pull request, so it goes when the check ends
- D-16: the list is read from the default branch, never from a pull request
- D-17: the check runs where headless sessions run, with their environment
- D-55: a host-side failure is reported on the host, not filed on GitHub
- D-64: a failing command turns off only its own check
- D-82: the hook step runs the same `uv run` rule a gate session meets

## Issues

- shipmill/shipmill#1072: S-064-1, S-064-2, S-064-3, S-064-4, S-064-5
- shipmill/shipmill#1074: S-064-6, S-064-7, S-064-8
- shipmill/shipmill#1077: S-064-9
- shipmill/shipmill#1078: S-064-10

## Verification

- S-064-1: read `agents.py`'s `verify_of` and ran tests/test_verify.py's S-064-1 tests: a list of commands parses, an absent key is `()`, and a non-list, a non-string, an empty or blank string, a newline, and a duplicate exit 2 naming `[agents] verify`, holds
- S-064-2: read `verify.py`'s `matches`, `flag_rules`, `permissions`, and `Allowlist.denial`, and ran tests/test_verify.py's S-064-2 tests: the four rule forms match as documented, a deny rule wins, and `pnpm --dir web api` under only `Bash(pnpm api:*)` is `denied` naming the part, holds
- S-064-3: ran tests/test_verify.py's S-064-3 test: `uv run env` through the delivery hook with `SHIPMILL_GATE=1` is `refused by hook` naming `uv-run`, and the shell never runs, holds
- S-064-4: read `worktree` and `judge`, and ran tests/test_verify.py's S-064-4 tests: the run is in `.claude/worktrees/shipmill-verify-<hex>` at `origin/<default>` through `$SHELL -c` with the gate's PATH; exits 0, 127, and another, and a run past the limit, read `ok`, `not found` naming the program, `failed` with the code and last stderr line, and `timed out`, with 30 minutes by default, holds
- S-064-5: ran tests/test_verify.py's S-064-5 tests: the commands run in order in one worktree, a setup command's files reach the next, denied and refused commands don't run, and the worktree is removed after a failing and an erroring check, holds
- S-064-6: ran tests/test_gate_verify.py's S-064-6 tests: a headless LAUNCH tick checks before the session, writes `verify.json`, ends its decision line with `; verify: ...`, starts the session on a failing or erroring check, and fails on a malformed `verify.json`, holds
- S-064-7: ran tests/test_gate_verify.py's S-064-7 tests: a passing result isn't checked again until the fingerprint changes, each input changes it, a failing result is checked again `retry_hours` later, and an interactive tick, a dry run, and an empty list check nothing, holds
- S-064-8: ran tests/test_gate_verify.py's S-064-8 tests: a failing result notifies once per fingerprint, a failed send stays owed, and a pass or `notify = false` sends nothing, holds
- S-064-9: ran `shipmill doctor` on this repo's config with `verify = ["uv run pytest --version"]` added and no `verify.json`: one `WARN verify command: uv run pytest --version: not checked yet` row; tests/test_doctor_verify.py covers the PASS row with its time, a FAIL per result with its fix (`not found` naming the PATH, never an allow rule), an older list's result read as not checked, a malformed `verify.json` as one FAIL naming the file, and no row without a list, holds
- S-064-10: read `needs-decision.md`'s "A denied tool call is a decision", which tells a denial, a hook refusal, and a not-found (exit 127) apart with each its fix and says a not-found never proposes widening the allowlist, and ran tests/test_needs_decision.py's S-064-10 test, holds
