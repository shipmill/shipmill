# S-100: A gate's headless sessions can be billed to a Console API key from a file

status: approved
serves: G-1

## Problem

A gate's sessions can only run on the maintainer's Claude subscription (#1478). They use the
long-lived token `claude setup-token` prints (spec 035), so every headless session draws on
the same weekly plan limit the maintainer needs for interactive work, and when that limit
runs out both the gates and the maintainer stop. Max and Ultra plans include a monthly API
credit on the Claude Console that covers the Claude API and `claude -p` run with a Console
API key, but not interactive Claude Code, and it doesn't roll over.

A gate can't use that credit today. Spec 035 puts an API key for gate sessions out of scope,
a token file drops `ANTHROPIC_API_KEY` from a session's environment on purpose (S-035-18), and
the token file refuses an API key. The only workaround is to remove the host-wide token file
and put the key in the launchd job's environment: a secret in the plist, every gate on the
host switched at once, and `shipmill doctor` warning on `claude auth`.

The maintainers affected run gates headless (U-1), often for several repositories (U-2). The
evidence is the maintainer's own ask on 2026-11-22, with the plan's weekly limit running out
and the month's API credit unused. Success is a per-gate choice to bill sessions to a Console
API key that never shows in argv, a plist, a log, or the repo, that `doctor` and `status`
name, and that never falls back to the subscription (D-14).

## Behaviour

This spec amends spec 035 (`docs/specs/035-gate-claude-token.md`) and spec 089
(`docs/specs/089-gate-wait-by-cause.md`) for one new credential kind, an API key file. A gate
without `--anthropic-api-key` behaves exactly as those specs say.

### Choosing the key, per gate

- **A flag, no default.** `shipmill gate --anthropic-api-key <path>` makes that gate's
  sessions authenticate with the Console API key in the file. There is no default path: a
  host-wide file would switch every gate on the host at once, the problem this spec solves.
  A gate without the flag reads the Claude token or the login as spec 035 says
- **launchd.** `shipmill launchd install --anthropic-api-key <path>` writes the flag and the
  resolved path (never the key) into the job's program arguments, as `--claude-token` does
  (`src/shipmill/launchd.py`), checks the file as the gate would before it writes the plist,
  and `cli_fix` keeps the flag when it rewrites a job. The plist never holds the key or an
  `ANTHROPIC_API_KEY` key
- **One credential per gate.** `--anthropic-api-key` and `--claude-token` together are a
  usage error, exit 2, for `shipmill gate` and `shipmill launchd install` alike. With
  `--anthropic-api-key`, the default token file `~/.config/shipmill/claude-token` is never
  opened: the gate chose the key
- **Headless only.** The credit covers `claude -p`, not interactive Claude Code, and an
  interactive `claude --bg` with an `ANTHROPIC_API_KEY` stops to ask whether to use it. A
  gate whose `[agents] mode` is `interactive` with `--anthropic-api-key` starts no session and
  reports `CLAUDE_AUTH`, exit 2, with the reason "an API key file bills headless sessions
  only" and the fix "set `[agents] mode = \"headless\"`, or drop `--anthropic-api-key`"
- The path is a host's secret, so it has no key in `.github/shipmill.toml` (D-4)

### Reading the file, failing fast

`src/shipmill/claude_token.py` gains the key's reader beside the token's, with the same order
and the same rules as spec 035's table: the file's kind, owner, and mode (`600` or `400`) are
checked before a byte is read, then one non-empty line, ASCII only, no whitespace inside it,
one trailing newline stripped. The key must start with `sk-ant-api`; a file starting with
`sk-ant-oat` is refused with the fix that it is a subscription token, which goes to
`--claude-token`. A path that doesn't exist, is a folder, or is owned by another user is
refused. Each refusal makes the tick start no session and stop none, report `CLAUDE_AUTH`
naming the path and the rule, never a byte of the file, and exit 2 (Q-1). None falls back to
the token file or the login.

### Handing it to the session

- **Process environment only.** `headless_env` in `src/shipmill/gate.py` puts the key in the
  `claude -p` process's environment as `ANTHROPIC_API_KEY`, with
  `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` so the session's Bash tool, hooks, and MCP servers
  don't get it. Never in the command line, the `--settings` JSON, a `--claude-arg`, or the
  prompt
- **Nothing outranks it, nothing falls back.** The same env drops `ANTHROPIC_AUTH_TOKEN` and
  the cloud-provider switches `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, and
  `CLAUDE_CODE_USE_FOUNDRY`, which Claude Code ranks above `ANTHROPIC_API_KEY`, and
  `CLAUDE_CODE_OAUTH_TOKEN`, so no subscription credential is in reach of the session
- **The preflight and the usage probe** (`src/shipmill/claude_auth.py`,
  `src/shipmill/claude_pause.py`) run in that same env. The preflight's `claude auth status
  --json` must report logged in and, when it names an auth method, the API key's; otherwise
  `CLAUDE_AUTH` with the fix "the key in `<path>` was not accepted; create a Console API key
  and save it to `<path>`"
- **The gate's other `claude` calls** (`claude agents`, `claude stop`, `claude plugin ...`,
  the hooks self-test) keep the gate's own environment and never get the key
- **Never stored or printed.** The key never appears in the tick's text or `--json`, in
  `gate.json`, `handed.json`, a pause file, or any other file under the state directory, in a
  notification, or in an error message; errors name the path

### When the key fails or the credit runs out

- **Rejected.** A headless session with the key whose log holds an authentication failure
  ends `auth` (S-089-1) and is reported with the key's fix, which `src/shipmill/status.py`
  and `skills/github-ship-watch/scripts/watch_state.py` pass on as they pass the token's
- **Credit exhausted.** A session whose log holds the API's `credit balance is too low` error
  ends `limit`, not `error`: the credential pauses and no item counts an attempt
- **The key's pause.** The key file's credential, as spec 089 names it, is the first 16 hex
  digits of the SHA-256 of the key file's content, so a pause on the login or a token never
  holds a key gate and the reverse. A `limit` pause on a key lifts at the log's `resetsAt`,
  else after `retry_hours` (S-089-8), since `/usage` names no plan window for a key; an `auth`
  pause lifts when the key file's content changes, and `GATE_PAUSED` reads "until the key
  changes"

### What `doctor`, `status`, and the tick print

Both name the kind and the path, never the key or any part of it, reading the gate's choice
from its launchd job's arguments as spec 035 does:

- `shipmill status` prints the `claude auth` line as `API key file <path>`, or `API key file
  <path>: <the refusal>` with its fix on the next line (`auth_lines` in
  `src/shipmill/status.py`)
- `shipmill doctor` (`token_check` in `src/shipmill/doctor.py`) reports `claude auth` PASS as
  `API key file <path> (--anthropic-api-key): sessions billed to the Console API`, FAIL with
  the refusal and its fix, and FAIL when the repo's `[agents] mode` is `interactive`; neither
  the login's WARN nor the 330-day age WARN applies to a key
- The tick's `--json` has `"auth": "api-key"` (a third `Kind`), and the text says `as API key
  file` on a `LAUNCH` line that used one

### Docs and setup

`docs/install.md`, `docs/design/agent-modes.md`, and `skills/shipmill-setup/SKILL.md`
describe the choice: create a key in the Claude Console, save it with mode `600` to a path of
the person's choosing, pass `--anthropic-api-key <path>` to `shipmill launchd install` for the
gates that should bill the credit, headless gates only. They say the gate never falls back to
the subscription and never shows the key, and that the Console's own billing settings decide
whether use past the month's credit is charged. The setup skill tells the person to create
and save the key themselves: the agent never reads the file and never asks for the key in the
chat.

## Acceptance criteria

- S-100-1: a headless gate run with `--anthropic-api-key <path>` and a valid key file starts `claude -p` with `ANTHROPIC_API_KEY` equal to the file's key without its trailing newline and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, and without `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, or `CLAUDE_CODE_USE_FOUNDRY`, even when the gate inherited each of them
- S-100-2: with `--anthropic-api-key` and a valid token file at `~/.config/shipmill/claude-token`, the gate never opens the token file and the tick's `--json` has `"auth": "api-key"`
- S-100-3: with a valid key file, the `claude -p` argument list, including its `--settings` JSON, holds no 8-character substring of the key outside its first 13 characters
- S-100-4: a key file with any group or other permission bit exits 2 with `CLAUDE_AUTH` naming the path and `chmod 600 <path>`, starts no session, stops none, and is never opened for reading
- S-100-5: a key file that is empty, holds two non-empty lines, inner whitespace, a non-ASCII byte, or no `sk-ant-api` prefix exits 2 with `CLAUDE_AUTH` naming the path and the failed rule, starts no session, and its message holds no 8-character substring of the file outside its first 13 characters; one starting with `sk-ant-oat` names `--claude-token` in its fix
- S-100-6: a `--anthropic-api-key` path that doesn't exist, is a folder, or is owned by another user exits 2 with `CLAUDE_AUTH` naming the path and starts no session, with a valid token file at the default path and a working login alike
- S-100-7: `shipmill gate` and `shipmill launchd install` given both `--anthropic-api-key` and `--claude-token` exit 2 and write nothing
- S-100-8: a gate whose `[agents] mode` is `interactive` run with a valid `--anthropic-api-key` exits 2 with `CLAUDE_AUTH` naming headless sessions and `--anthropic-api-key`, and runs no `claude --bg`
- S-100-9: `shipmill launchd install --anthropic-api-key <path>` writes `--anthropic-api-key` and the resolved path into the plist's program arguments, the plist holds no key and no `ANTHROPIC_API_KEY` key, a file the gate would refuse exits 2 before the plist is written, and `cli_fix` keeps the flag
- S-100-10: with `--anthropic-api-key`, the gate's `claude agents`, `claude stop`, `claude plugin`, and hooks self-test calls run in the gate's own environment, without the file's key in it
- S-100-11: with `--anthropic-api-key`, the preflight runs `claude auth status --json` with the key as `ANTHROPIC_API_KEY` and without `CLAUDE_CODE_OAUTH_TOKEN`, and a reply that says not logged in, or names an auth method other than the API key's, exits 2 with `CLAUDE_AUTH` naming the path and the key's fix
- S-100-12: with `--anthropic-api-key`, a headless session whose log holds an authentication failure ends `auth`, and its fix in the tick, `shipmill status`, and `watch_state.py` names the key file and creating a Console API key, not `claude setup-token` or `claude auth login`
- S-100-13: with `--anthropic-api-key`, a headless session whose log holds the API's `credit balance is too low` error ends `limit`, writes a pause for the key's credential, and counts no attempt against its item
- S-100-14: a key gate's pause file is named by the first 16 hex digits of the SHA-256 of the key file's content; a pause on `login` or on a token's credential doesn't hold it, its pause doesn't hold a token gate, an `auth` pause on it lifts once the key file's content changes, and `GATE_PAUSED` for it reads `until the key changes`
- S-100-15: on a tick that uses a sentinel key, the tick's text, its `--json`, every file the tick writes under the state directory (`gate.json`, `handed.json`, and the pause file among them), and every notification text hold no 8-character substring of the key outside its first 13 characters
- S-100-16: a `LAUNCH` tick with a key file says `as API key file` in its text
- S-100-17: `shipmill status` prints `claude auth` as `API key file <path>` for a gate whose launchd job names `--anthropic-api-key`, or the refusal with its fix on the next line, and never the key
- S-100-18: `shipmill doctor` with `[agents]` reports `claude auth` as PASS naming the key file and `--anthropic-api-key` for a valid key, FAIL with the refusal for a file the gate would refuse, FAIL when `[agents] mode` is `interactive`, and never the login's or the 330-day age WARN for a key
- S-100-19: `docs/install.md`, `docs/design/agent-modes.md`, and `skills/shipmill-setup/SKILL.md` name `--anthropic-api-key`, mode `600`, headless gates only, no fallback to the subscription, that the key never goes in the plist or the repo, and that the Console's billing settings decide charges past the credit; the setup skill tells the person to create and save the key themselves

## Out of scope

- A gate run as a job on a self-hosted runner trading the job's GitHub OIDC token through Workload Identity Federation, as `evals.yml` does since #442: no long-lived secret, but a runtime other than launchd (`docs/design/ephemeral-mode.md`), a larger change than the per-gate choice the issue asks for; it can follow as its own opportunity
- A local OIDC issuer for federation: unverified whether Anthropic's federation accepts an issuer other than a known provider, so it can't be specified yet
- Claude Code's `apiKeyHelper` setting or the macOS Keychain: a command in the session's settings or a Keychain read adds a moving part a mode-600 file doesn't need; either can follow behind its own flag, as spec 035 left the Keychain
- Interactive gates on the key: the credit doesn't cover interactive Claude Code, and `claude --bg` stops to approve the key (S-100-8 refuses it)
- A host-wide default key path or a key chosen in `.github/shipmill.toml`: a default switches every gate on the host at once, and a committed setting is no place for a host's secret (D-4)
- Reading the Console's credit balance, or switching a gate to the subscription when the credit runs out: shipmill can't see the balance, and a switch is the fallback D-14 rules out; the gate pauses instead (S-100-13)
- Rotating or creating keys: a person's step in the Console

## Decisions relied on

- D-4: the key's path is a host's secret, not a layer's setting, so it stays out of `.github/shipmill.toml`
- D-14: a gate set up with a credential starts sessions with it or not at all; a refused or rejected key never falls back to the token file or the login
- D-17: a headless session is a `claude -p` process the gate spawns, so its process environment is where the key goes
- D-20: setup asks for the mode; the key applies to headless gates only
- D-100: a limit or auth end pauses the session's credential on the whole host, keyed by a hash of the credential file's content and never holding the secret

## Issues

## Verification
