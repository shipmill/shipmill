# S-035: Gate sessions authenticate with a long-lived Claude token from a file

status: built
serves: G-1

## Problem

A gate on launchd starts its sessions under Claude Code's interactive login on the host.
On 2026-10-20 that login expired overnight, and every session five gates started died
within a second with `Failed to authenticate: OAuth session expired and could not be
refreshed` (#500). An interactive login isn't meant for unattended use, and several
unattended `claude` processes refreshing one OAuth login at once is a plausible cause of
the expiry. Nothing in the docs or in shipmill-setup says how a gate's sessions should
authenticate, so every gate leans on the one login a person made by hand (#501).

#500 adds the preflight (`claude auth status --json` before a launch, a `CLAUDE_AUTH` row
when it fails) and stops a dead session from counting as an attempt. This spec gives a
gate an unattended credential instead: the long-lived token `claude setup-token` prints for
a Claude subscription, read from a file only the gate's user can read and handed to each
session it starts as `CLAUDE_CODE_OAUTH_TOKEN`, never where `ps`, a plist, a log, or the
repo can show it.

## Behaviour

### Where the token lives

The token is per host and per user, never per repo, so it has no key in
`.github/shipmill.toml` (a committed file, D-4 covers the layers' settings, not a host's
secrets), as the App's private key has none (spec 004):

- **Default path:** `~/.config/shipmill/claude-token`, next to the App key's default
  (`~/.config/shipmill/app-<id>.pem`). One token serves every gate the user runs on the host
- **Override:** `shipmill gate --claude-token <path>` reads that file instead.
  `shipmill launchd install --claude-token <path>` writes the flag and the path (never the
  token) into the job's arguments, as `--app-key` does today (`src/shipmill/launchd.py`)
- **No file, no flag:** the gate uses the interactive login, exactly as today; the
  fallback is only for a token file that isn't there. A path named by `--claude-token`
  that doesn't exist is an error, not a fallback

### Reading the file, failing fast

A new `src/shipmill/claude_token.py` reads the file once per tick, before the state is
read (with the App check, D-14), in either mode, dry run or not. Each of these makes the
tick start no session and stop none, report `CLAUDE_AUTH` with the reason and the fix, and
exit 2 (Q-1); none falls back to the interactive login:

| The file | The reason names | The fix |
|---|---|---|
| Is not a regular file (a folder, a socket) | the path | `claude setup-token`, saved to the path |
| Is not owned by the gate's user | the path and its owner | `chown` it, or save a new one |
| Has any group or other permission bit (mode not `600` or `400`) | the path and its mode | `chmod 600 <path>` |
| Is empty, or only whitespace | the path | `claude setup-token`, saved to the path |
| Holds more than one non-empty line, whitespace inside the token, a non-ASCII byte, or doesn't start with `sk-ant-oat` | the path and which rule failed, never the bytes | `claude setup-token`, saved to the path; an API key (`sk-ant-api…`) goes nowhere here |
| Named by `--claude-token` but missing | the path | create it, or drop the flag |

One trailing newline is stripped, so `claude setup-token > <path>` style saving works. The
mode check comes before the content is read, so a file others can read is refused without
its bytes ever entering the gate's memory.

### Handing it to the session

- **Process environment only.** The token goes into the environment of the `claude`
  process that starts the session, as `CLAUDE_CODE_OAUTH_TOKEN`, replacing one the gate
  inherited. It is never in the command line: not in `--settings` JSON, not in a
  `--claude-arg`, not in the prompt. Spec 004's `--settings` env (the helpers' `PATH`, the
  git identity) keeps holding no secret, and a `ps` on the host shows no token
- **Headless** (`claude -p`, D-17): `headless_env` in `src/shipmill/gate.py` adds it to the
  process env `spawn_detached` passes
- **Interactive** (`claude --bg`): the `claude --bg` command runs with the token in its
  environment. Today `run_command` always runs with the gate's own environment, so it gains
  an env argument used only by this launch
- **Not to the session's tools.** The same env sets `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`,
  so Claude Code strips its credentials from the environment of the session's Bash tool,
  hooks, and MCP servers: an agent reading issue text can't print the token with `env`
- **Nothing outranks the token.** The same env, for a session and for the preflight, drops
  `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` when the gate inherited them. Claude Code
  ranks both above `CLAUDE_CODE_OAUTH_TOKEN` (its Authentication precedence), so a key left
  in the host's environment would silently move the gate's sessions off the subscription.
  Without a token file the gate's environment passes unchanged, both keys included
- **Only session starts and the preflight get it.** The gate's other `claude` calls
  (`claude agents`, `claude stop`, `claude plugin ...`, the hooks self-test) and its GitHub
  reads keep the gate's own environment
- **Never stored or printed.** The token never appears in the tick's text or `--json`, in
  `gate.json`, `needs-decision.json`, or any file under the state directory, in the plist,
  in a notification, or in an error message; errors name the path

### The preflight with a token

#500's preflight runs `claude auth status --json`. With a token file it changes:

1. The file checks above run first; a failure is the `CLAUDE_AUTH` row from that table
2. `claude auth status --json` runs with the token in its environment and without
   `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` (the same env a session gets). It must report logged in, and when its JSON names the auth method, that
   method must be the environment token, not the stored login; otherwise `CLAUDE_AUTH`
   with the fix "the token in `<path>` was not accepted; run `claude setup-token` and save
   it to `<path>`"
3. A revoked or expired token may still pass step 2, since `auth status` reads local state.
   #500's dead-session handling catches it: when a token is in use, a dead session whose
   log holds an authentication failure reports the same token fix instead of `claude auth
   login`

Without a token file the preflight is #500's, unchanged.

### What `doctor` and `status` print

Both name the auth kind and never the token or any part of it:

- `shipmill status` adds a `claude auth` line under the gate's lines (`gate_lines` in
  `src/shipmill/status.py`): `token file ~/.config/shipmill/claude-token`, `login`, or
  `token file <path>: <the refusal>` with its fix on the next line (spec 011)
- `shipmill doctor` adds a `claude auth` check for a config with `[agents]`: OK with the
  kind; FAIL for a token file the gate would refuse, with the same reason and fix; WARN for
  `login` on a host with a launchd job for the repo, naming `claude setup-token` and the
  path; WARN when the token file was last written more than 330 days ago, since a
  `setup-token` token lasts a year
- The kind both read is the gate's: the launchd job's `--claude-token` path when the job
  names one, else the default path
- The tick's `--json` gains `"auth": "token-file"` or `"auth": "login"`, and the tick's
  text says `as token file` on a `LAUNCH` line that used one

### Docs and setup

- `docs/install.md` and `docs/design/agent-modes.md` describe the token: `claude
  setup-token`, saving it to `~/.config/shipmill/claude-token` with mode `600`, the
  override flag, what the gate refuses, and that it never goes in the plist or the repo
- `skills/shipmill-setup/SKILL.md` recommends the token for every gate it installs on
  launchd and tells the person to run `claude setup-token` and save the output themselves:
  the agent never runs it, never reads the file, and never asks for the token in the chat

## Acceptance criteria

- S-035-1: with no file at `~/.config/shipmill/claude-token` and no `--claude-token`, the started `claude -p` and `claude --bg` get the gate's environment unchanged and the tick's `--json` has `"auth": "login"`
- S-035-2: with a valid token file at the default path, a headless launch's `claude -p` process environment has `CLAUDE_CODE_OAUTH_TOKEN` equal to the file's token without its trailing newline, and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`
- S-035-3: with a valid token file, an interactive launch runs `claude --bg` with `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` in its environment
- S-035-4: with a valid token file, neither launch's argument list, including its `--settings` JSON, contains the token or any 8-character substring of it
- S-035-5: a token file with any group or other permission bit exits 2 with `CLAUDE_AUTH` naming the path and `chmod 600 <path>`, starts no session, stops none, and never opens the file for reading
- S-035-6: an empty or whitespace-only token file exits 2 with `CLAUDE_AUTH` naming the path, starts no session, and stops none
- S-035-7: a token file with two non-empty lines, inner whitespace, a non-ASCII byte, or no `sk-ant-oat` prefix exits 2 with `CLAUDE_AUTH` naming the path and the failed rule, starts no session, and its message holds none of the file's bytes
- S-035-8: a token path that is a folder, or a file owned by another user, exits 2 with `CLAUDE_AUTH` naming the path, and starts no session
- S-035-9: `shipmill gate --claude-token <path>` reads that file instead of the default, and a `--claude-token` path that doesn't exist exits 2 naming it rather than falling back to the login
- S-035-10: `shipmill launchd install --claude-token <path>` writes `--claude-token` and the resolved path into the plist's program arguments, and the plist holds no token and no `CLAUDE_CODE_OAUTH_TOKEN` key
- S-035-11: with a token file, the gate's `claude agents`, `claude stop`, `claude plugin`, and hooks self-test calls run without `CLAUDE_CODE_OAUTH_TOKEN` in their environment
- S-035-12: with a token file, the preflight runs `claude auth status --json` with the token in its environment, and a reply that says not logged in, or names an auth method other than the environment token, exits 2 with `CLAUDE_AUTH` naming the path and `claude setup-token`
- S-035-13: with a token file, a dead session whose log holds an authentication failure is reported with the token fix (the path and `claude setup-token`), not `claude auth login`
- S-035-14: on a tick that uses a sentinel token, the tick's text, its `--json`, `gate.json`, every file the tick writes under the state directory, and every notification text hold neither the token nor any 8-character substring of it
- S-035-15: `shipmill status` prints a `claude auth` line reading `token file <path>`, `login`, or the refusal with its fix on the next line, and never the token
- S-035-16: `shipmill doctor` with `[agents]` reports `claude auth` as OK with the kind, FAIL with the refusal for a file the gate would refuse, WARN for `login` when the repo has a launchd job, and WARN when the token file is older than 330 days
- S-035-17: `docs/install.md`, `docs/design/agent-modes.md`, and `skills/shipmill-setup/SKILL.md` name `claude setup-token`, the path `~/.config/shipmill/claude-token`, mode `600`, `--claude-token`, and that the token never goes in the plist or the repo; the setup skill tells the person to run `claude setup-token` themselves
- S-035-18: with a valid token file and `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` in the gate's environment, the headless `claude -p` process, the interactive `claude --bg` command, and the preflight's `claude auth status --json` each run with `CLAUDE_CODE_OAUTH_TOKEN` and with neither `ANTHROPIC_API_KEY` nor `ANTHROPIC_AUTH_TOKEN` in their environment, checked by `test_s035_18_a_token_file_drops_the_api_key_and_auth_token_from_sessions_and_the_preflight`

## Out of scope

- The preflight itself, the dead-session handling, and the watch's report of dead sessions: #500, which this builds on
- An Anthropic API key (`ANTHROPIC_API_KEY`) or a cloud provider's credentials for gate sessions: a different billing path; the format check refuses an API key in the token file, and a gate with a token file drops one from the host's environment (S-035-18)
- Rotating or renewing the token automatically: `claude setup-token` is a person's step, and doctor's age warning says when it is due
- A per-repo token: one host-wide file serves every gate; a gate that needs another passes `--claude-token`
- Reading the token from the macOS Keychain: a file with mode `600` matches how the App key is kept; the Keychain can follow behind its own flag if a user asks

## Decisions relied on

- D-4: the token's path is a host's secret, not a layer's setting, so it stays out of `.github/shipmill.toml`, as the App key's path does
- D-14: a gate set up with a credential starts sessions with it or not at all; a bad token file never falls back to the interactive login
- D-17: a headless session is a `claude -p` process the gate spawns, so its process environment is where the token goes
- D-20: setup asks for the mode; the token is recommended for launchd gates in either mode
- D-54 (superseding D-40): a failed preflight starts no session, as a failed hooks self-test already does for a headless gate

## Issues

- shipmill/shipmill#699: S-035-1, S-035-2, S-035-3, S-035-4, S-035-5, S-035-6, S-035-7, S-035-8, S-035-9, S-035-10, S-035-11, S-035-12, S-035-13, S-035-14, S-035-15, S-035-16, S-035-17, S-035-18

## Verification

- S-035-1: `claude_token.read_token` returns None for a missing default file, `session_env` then passes the gate's env unchanged to `claude -p` (through `headless_env`, as before) and `claude --bg` runs through the gate's own runner; `tick_record` writes `"auth": "login"`; test_s035_1_without_a_token_file_sessions_get_the_gates_env_unchanged_and_auth_reads_login passes, holds
- S-035-2: `Token.env` sets `CLAUDE_CODE_OAUTH_TOKEN` to the file's text with one trailing newline stripped and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, and `ClaudeCli.start` spawns `claude -p` with it; test_s035_2_a_headless_session_gets_the_token_without_its_newline_and_the_scrub passes, holds
- S-035-3: `ClaudeCli.launch` with a token runs `claude --bg` through `run_command`'s new env argument with the same env; test_s035_3_an_interactive_launch_runs_claude_bg_with_the_token_and_the_scrub passes, holds
- S-035-4: the token is passed to `launch` and `start` as a `Token`, used only for the process env, never in the command list or `--settings` JSON, and `Token`'s repr hides its value; test_s035_4_no_launch_argument_holds_any_8_characters_of_the_token scans both commands for every 8-character substring, holds
- S-035-5: `read_token` stats the file and refuses any `0o077` bit with `chmod 600 <path>` before `fs.read` is called; `gate` reads the credential first, before the waiting step and the state read, so the tick stops and starts nothing, and `cli._gate_exit` returns 2; test_s035_5_a_file_with_a_group_or_other_bit_exits_2_unopened_starting_and_stopping_none uses a file system whose read fails the test, holds
- S-035-6: `checked` refuses an empty or whitespace-only file naming the path; test_s035_6_an_empty_or_blank_file_exits_2_naming_the_path passes with a blocked session the waiting step would otherwise stop, holds
- S-035-7: `checked` names the path and the rule (more than one non-empty line, whitespace in the token, a non-ASCII or control byte, no `sk-ant-oat` prefix) and never the bytes; test_s035_7_a_malformed_token_exits_2_naming_the_rule_and_none_of_its_bytes scans the tick's text and record for every 8-character substring of the file, holds
- S-035-8: `read_token` refuses a path that isn't a regular file, and one whose owner isn't the gate's user, naming the path and the owner; test_s035_8_a_folder_or_a_file_of_another_user_exits_2_naming_the_path passes, holds
- S-035-9: `shipmill gate --claude-token <path>` makes a named `TokenSource`, whose missing file is refused with `create <path>, or drop --claude-token`, never the login; test_s035_9_claude_token_reads_that_file_and_a_missing_one_never_falls_back passes, holds
- S-035-10: `launchd.build(claude_token=...)` adds `--claude-token <resolved path>` to `ProgramArguments`, the plist has no token and no `CLAUDE_CODE_OAUTH_TOKEN`, `_launchd` validates the file before it installs, and `cli_fix` keeps the flag; test_s035_10_launchd_writes_the_flag_and_path_never_the_token passes, holds
- S-035-11: `claude agents` and `claude stop` run through `ClaudeCli`'s two-argument runner, the plugin reads and the hooks self-test through their own, all in the gate's env, which the gate never changes; test_s035_11_claude_agents_stop_plugin_and_the_hooks_self_test_run_without_the_token passes, holds
- S-035-12: `claude_auth.token_auth` runs `claude auth status --json` in the session's env and `parse_token_auth` refuses `loggedIn` false and an `authMethod` other than `oauth_token` with the fix naming the path and `claude setup-token`; the tick exits 2; test_s035_12_the_preflight_runs_with_the_token_and_refuses_another_method passes, holds. The `oauth_token` value is the one Claude Code's CLI reference lists for the env token; not checked against a live `claude`
- S-035-13: `Dead.fix` with a token is `rejected_fix(<path>)`, and status and `watch_state.py` pass that fix on from the gate's line; test_s035_13_a_dead_session_with_an_auth_failure_names_the_token_fix passes, holds
- S-035-14: test_s035_14_a_tick_with_a_sentinel_token_writes_none_of_it_anywhere scans the tick's text, `--json`, every file under the state directory (`gate.json` and `needs-decision.json` among them), the notifications, and the started command for every 8-character substring of a sentinel token, and a refused tick's text and record too, holds
- S-035-15: `status.auth_lines` prints `claude auth` as `token file ~/.config/shipmill/claude-token`, `login`, or `token file <path>: <refusal>` with its fix on the next line, from the launchd job's `--claude-token` or the default path; test_s035_15_status_names_the_kind_or_the_refusal_never_the_token passes, holds
- S-035-16: `doctor.token_check` is PASS with the kind, FAIL with the refusal and its fix (and the preflight is skipped), WARN for `login` with a launchd job, and WARN for a file written more than 330 days ago; test_s035_16_doctor_reports_the_kind_the_refusal_the_login_and_an_old_token and test_s035_16_doctor_runs_the_token_check_with_agents_and_skips_the_preflight_on_a_refusal pass, holds
- S-035-17: `docs/install.md` (Give the sessions a Claude token), `docs/design/agent-modes.md` (The session's Claude credential), and `skills/shipmill-setup/SKILL.md` step 7 name each item; test_s035_17_the_docs_and_the_setup_skill_name_the_token_steps passes, holds
- S-035-18: `Token.env` drops `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` for the headless start, the interactive launch, and the preflight, and a gate without a token passes them through; test_s035_18_a_token_file_drops_the_api_key_and_auth_token_from_sessions_and_the_preflight passes, holds
