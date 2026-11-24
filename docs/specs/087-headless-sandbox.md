# S-087: A headless gate session runs in Claude Code's sandbox

status: approved
serves: G-2

## Problem

A headless gate session runs as the host's user, with that user's home directory, and its
allowlist is not a sandbox (spec 005, D-16). `uv run python -c`, `uvx <any package>` and
`uv run <script>.py` start any program, as D-82 says itself, and the Read and Grep tools reach
every file the user can. So a session can use every credential that user holds: passphrase-less
ssh keys and the hosts in `~/.ssh/config`, cloud CLI profiles, `.netrc`, the host's own `gh`
token, and the transcripts and memory of every other Claude Code project
(shipmill/shipmill#1439).

On a host whose user reaches production servers over ssh without a prompt, so can every gate
session there: nothing between the session and `ssh` stops it, for example
`uvx --from ansible-core ansible-playbook -i <host>, <playbook>`. No gate session has done it,
but one wrong step by the model, or text it read in a pull request, a dependency or a web page,
would run on a real server. The trust filter (D-16) keeps outsiders' issue text out; it does not
cover what the session reads while it works. The delivery hook and the allowlist cannot close
this: they judge a command's first words, and every allowed program can start another.

The maintainer chose to run headless gate sessions in Claude Code's sandbox (macOS seatbelt,
Linux bubblewrap). shipmill's evals already run sessions in it (spec 025, #929, #933, #936), so
two failure modes are known: a shared clone's alternates outside the readable area, and a `PATH`
entry outside the workspace.

The outcome: a headless gate session cannot read the host user's keys or reach a host the gate
did not declare, whatever program it starts, while the person's own sessions and scheduled jobs
on the same machine keep their access.

## Behaviour

### What Claude Code provides

The sandbox confines the Bash tool and every process it starts: which paths it may read and
write, and which hosts it may reach through the sandbox's proxy. It does not cover the Read,
Edit, Write, Glob and Grep tools, which follow `permissions` rules, nor hooks and MCP servers,
which run outside it. The settings it reads, under `sandbox`: `enabled`,
`allowUnsandboxedCommands`, `failIfUnavailable` (#929), `excludedCommands`,
`filesystem.denyRead`, `filesystem.allowWrite`, `filesystem.denyWrite`, and
`network.allowedDomains`.

The first build issue is a probe, as spec 005's was (S-005-4): a real `claude -p` started as
this spec's launch starts it, on a named Claude Code version, on macOS and on Linux, recorded in
`docs/design/agent-modes.md`, What Claude Code provides. It settles the exact key names and their
merge rules across `--settings`, the user's settings and the project's, the text Claude Code
writes when the sandbox refuses a path or a host, and whether a sandboxed command can reach a
local port. No other build issue of this spec merges before it, and a criterion the probe shows
Claude Code can't meet becomes a "decision for you" on its build issue, never a quiet change.

### The headless launch

`ClaudeCli.start` in `src/shipmill/gate.py` already passes `--settings` with the session's `env`.
In a sandboxed launch the same JSON also carries `sandbox` and `permissions`, built by a new
module, `src/shipmill/sandbox.py`, from the gate's checkout, its git common dir, the App's key
path, and the config. Nothing is written to a settings file: the person's
`~/.claude/settings.json`, the repo's `.claude/settings*.json`, and every other session on the
host are untouched, and `ClaudeCli.launch` (interactive mode) is unchanged.

| Key | Value |
|---|---|
| `sandbox.enabled` | `true` |
| `sandbox.allowUnsandboxedCommands` | `false`: the session cannot ask to run a command outside |
| `sandbox.failIfUnavailable` | `true`: no command runs unconfined when the sandbox can't start |
| `sandbox.excludedCommands` | absent: an excluded command would run outside the sandbox |
| `sandbox.filesystem.denyRead` | the credential stores, below |
| `sandbox.filesystem.allowWrite` | the write scope, below |
| `sandbox.filesystem.denyWrite` | the paths inside the write scope that would let a later unsandboxed process run the session's code, below |
| `sandbox.network.allowedDomains` | the default domains plus `[agents.sandbox] domains` |
| `permissions.deny` | `Read(...)` and `Edit(...)` on every denyRead path, so the file tools see what Bash sees |

### What a session can't read

`denyRead` and `permissions.deny` `Read(...)` hold, whether or not the path exists on the host:

- `~/.ssh`, `~/.gnupg`, `~/.netrc`, `~/.git-credentials`, `~/.pypirc`, `~/.npmrc`,
  `~/.docker/config.json`, `~/.kube`, `~/.aws`, `~/.azure`, `~/.config/gcloud`,
  `~/.password-store`, `~/Library/Keychains`
- `~/.config/gh/hosts.yml`: the host's own GitHub login; a session writes as the App through its
  helper (spec 004)
- Every entry of `~/.config/shipmill` other than the App key the session's `SHIPMILL_APP_KEY`
  names: other Apps' keys and the Claude token file (spec 035). The key the session writes with
  stays readable, since its helpers mint the App's token inside the sandbox; the token is limited
  to the gate's repo (D-14)
- `~/.claude.json`, `~/.claude/.credentials.json`, `~/.claude/history.jsonl`, and every folder
  under `~/.claude/projects` other than the session's own project: other projects' transcripts
  and memory. `~/.claude/plugins` stays readable, since the skills' references and scripts live
  there
- Each `[agents.sandbox] read` entry is taken out of the list: the repo's declared exception

The gate lists the entries of `~/.config/shipmill` and `~/.claude/projects` at each launch and
denies each by its path, so an entry added later is denied on the next launch.

### What a session can write

`allowWrite` is the write scope:

- the gate's checkout (`git.root`), where the session runs
- `<main working tree>/.claude/worktrees`, where Claude Code places a subagent's isolated
  worktree when the gate's checkout is a linked worktree
- the git common dir, which a linked worktree's commits, refs and worktree records need
- the session's own uv cache, `<state dir>/uv-cache`, which the session's `env` names as
  `UV_CACHE_DIR`; the person's uv cache stays readable but not writable, so nothing the session
  builds reaches the person's own unsandboxed `uv run`

`denyWrite`, inside that scope:

- `<common dir>/config` and `<common dir>/hooks`: either would make the person's own git run the
  session's code
- the gate's state directory (`<common dir>/shipmill`), except the token caches the session's
  helpers write and its uv cache: the gate reads its records unsandboxed, and writes the helpers
- `.claude/settings.json`, `.claude/settings.local.json` and `.mcp.json` of the gate's checkout
  and of the main working tree: each changes what the next session may do, and an MCP server runs
  outside the sandbox

The Edit and Write tools follow the same scope: `HEADLESS_TOOLS` names them as
`Edit(//<path>/**)` and `Write(//<path>/**)` for each write-scope path and the session's own
`~/.claude/projects/<project>/memory`, instead of a bare `Edit` and `Write`, so an edit outside
it is denied without a prompt (this amends S-005-3's constant; its Bash entries are unchanged).

### Where a session can connect

A sandboxed command reaches only `allowedDomains`, through the sandbox's proxy. The default:

- GitHub: `github.com`, `*.github.com`, `*.githubusercontent.com`
- PyPI: `pypi.org`, `files.pythonhosted.org`
- uv's downloads: `astral.sh`, `*.astral.sh` (Python builds come from GitHub, above)

plus each `[agents.sandbox] domains` entry. Plain `ssh` cannot connect from inside, even to an
allowed domain: the proxy carries HTTP and HTTPS, and git already sends SSH remotes over https in
a gate session (spec 004).

### The repo's declared escape

A repo that legitimately needs more declares it in `.github/shipmill.toml` (D-4), read from
`origin/<default>` as every `[agents]` key is, never from a pull request (D-16):

```toml
[agents.sandbox]
domains = ["registry.npmjs.org"]          # extra hosts a session's commands may reach
read = ["~/.config/some-tool"]            # paths taken out of the deny list
write = ["~/.cache/pnpm"]                 # extra paths a session may write

[[agents.sandbox.tunnels]]                # a port the gate opens before the session starts
ssh = "readonly@db.example.com"           # an ssh destination the host's own ssh reaches
local = 15432                             # the session reaches 127.0.0.1:15432
remote = "127.0.0.1:5432"                 # what that port forwards to, on the far side
```

`AgentsConfig.parse` (`src/shipmill/agents.py`) reads each key: `domains` a list of host names,
each a name or `*.` and a name, no scheme, port or path; `read` and `write` lists of absolute or
`~/` paths, without `..`; `tunnels` a list of tables with exactly `ssh` (`[user@]host`, no
options), `local` (1024 to 65535, unique) and `remote` (`host:port`). A malformed key is refused
as D-64 says: the config still loads, that key is dropped, so the session runs with the narrower
default, and doctor, the tick and every command that loads the config name it.

**A tunnel** is opened by the gate before it starts the session, outside the sandbox, as
`ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:<local>:<remote> <ssh>`, with
the host's own ssh and its config: no command runs on the far side, and the session gets a port,
never a shell or a key. The gate records the tunnel's pid and start time in `gate.json` beside
the session's (D-17) and stops it on the first tick that finds the session ended. A tunnel that
fails to open within 30 seconds is a failed feature, not a failed tick (D-64): the session starts
without it and the tick's line names the tunnel and ssh's last stderr line. The sandbox lets
commands reach `127.0.0.1` on each declared `local` port.

Today a host reaches the same tunnel by allowlisting `ssh -N -L ...` with `--claude-arg`; that
keeps working only outside the sandbox, and the sandboxed session needs the tunnel declared.

**A change that widens `[agents.sandbox]`** (adds a domain, a read or write path, or a tunnel)
classifies in the `security` zone at `ask` whatever `[decisions] security` sets: an agent never
lands it without the maintainer's answer. `shipmill decide classify` (`src/shipmill/decide.py`)
reports it so, and `pr_gate.py` holds it. A change that only narrows it follows `[decisions]
security`. This refines D-48's floor for `security`, which stays `notify` for every other change,
and needs its own `D-n`, added with the build issue that builds it.

### What the host can't loosen

- **`--claude-arg`**: with the sandbox on, `--settings` and `--add-dir` (alone or as
  `--flag=value`) join `HEADLESS_REFUSED`: the first could turn the sandbox off or widen it, the
  second widens the write scope. The gate exits 2 naming the flag before it stops or starts any
  session (as S-005-5). A host keeps `--allowedTools` and `--disallowedTools`: they widen what the
  session may call, not where its commands reach
- **Settings files**: before a sandboxed launch the gate reads `.claude/settings.json` and
  `.claude/settings.local.json` of its checkout and the user's `~/.claude/settings.json`; a
  `sandbox` key or a `permissions.additionalDirectories` key in any of them would merge into the
  session's sandbox, so the tick launches nothing and fails with
  `<file> sets <key>, which would widen a headless session's sandbox`, its fix naming
  `[agents.sandbox]`. A person who sandboxes their own sessions moves those keys to a project's
  settings outside the gate's checkout, or to the gate's `[agents.sandbox]`

### When the sandbox refuses a command

A refused read, write or connection is an error the command sees, as any other. Two places say
what the sandbox refused:

- **The tick.** On the first tick after a sandboxed session ends, the gate reads its stream-json
  log (spec 048) for the tool results that carry the refusal text the probe recorded, and the
  tick's line and `tick.json` gain `sandbox refused <n>: <first words of the command> (<path or
  host>)`, naming the first, with the fix the `[agents.sandbox]` key that would allow it. It
  changes no decision: the session ran
- **The session.** `skills/github-issue-triage/references/needs-decision.md`, A denied tool call
  is a decision, gains a fourth failure beside spec 064's three: **refused by the sandbox**. The
  question names the command and the path or host, and its option is the `[agents.sandbox]` entry
  in a pull request the maintainer approves; it never proposes `--claude-arg`, and the session
  never retries through another program

### Verification commands (spec 064)

The `[agents] verify` check's step 3 (`src/shipmill/verify.py`) runs each command inside the same
sandbox a session gets, built by the same `sandbox.py` from the same inputs, so a command that
works for the gate's shell but not for a session reads as failing before a session needs it
(#967, #1054). It runs through Anthropic's sandbox runtime (`srt`), the library Claude Code's
sandbox is built on, given the same filesystem and network rules as a settings file; the probe
confirms both refuse the same paths and hosts. A command whose run the sandbox refused is a new
result, `refused by sandbox`, naming the path or host; doctor's fix for it is the
`[agents.sandbox]` entry, never an allowlist change. The check's fingerprint gains the sandbox's
rules. When `srt` isn't on the gate's PATH, step 3 doesn't run and each command reads
`not checked: srt is not on the gate's PATH`, with the install command as doctor's fix.

### Linux

Claude Code confines commands on Linux with bubblewrap and socat. On a host without either, or
where the kernel refuses bwrap a user namespace (Ubuntu 24.04's AppArmor default, which evals
meet, #929), `failIfUnavailable` would refuse every command. So before a sandboxed launch on
Linux the gate runs `bwrap --ro-bind / / --unshare-user true` and looks for `socat` on its PATH;
when either fails it starts no session, and the tick fails with
`the sandbox can't start on this host: <what failed>`, its fix the package install, and for the
user-namespace refusal the `kernel.apparmor_restrict_unprivileged_userns` setting. The deny list
and the write scope are the same paths; `~/Library/Keychains` simply doesn't exist there. A
headless gate never runs unconfined because its host can't confine it.

### Doctor

`shipmill doctor` (`src/shipmill/doctor.py`), with `[agents] mode = "headless"`, prints one
`sandbox` row: PASS `on: <n> default domains, <declared domains>, <k> read and <w> write
exceptions, <t> tunnels`; WARN `off: headless sessions run unconfined; pass --sandbox`, while the
host hasn't opted in (Rollout); FAIL for a settings file that would widen it, or a Linux host
where it can't start, with the same text and fix as the tick. No row without headless mode (D-9).

### Rollout

1. **One gate first.** `shipmill gate --sandbox` turns the sandbox on for that gate's headless
   sessions, and `shipmill launchd --sandbox` writes the flag into the job. Without it a headless
   launch is today's, and doctor WARNs. Opting in is a host step, so no pull request can turn the
   sandbox off, and the maintainer chooses the first gate
2. **Every gate.** A later release, once the first gate has run sandboxed for a week with each
   refusal the tick named either declared or fixed, makes the sandbox the default for every
   headless gate. `--sandbox` is then accepted and ignored with one line saying it is the default,
   and is refused no sooner than D-64 allows. There is no flag or key to turn it off

### Docs

`docs/design/agent-modes.md` (the probe, the sandbox, the trust filter's place beside it),
`docs/install.md` and `skills/shipmill-setup/SKILL.md` (The gate: `--sandbox`, `[agents.sandbox]`,
tunnels, Linux packages), and `needs-decision.md` (the fourth failure). The "Not a sandbox"
comment on `HEADLESS_TOOLS` and the same sentence in spec 005's docs say a sandboxed session runs
confined.

## Acceptance criteria

- S-087-1: `docs/design/agent-modes.md`, What Claude Code provides, names the Claude Code version on which a real `claude -p` started with this spec's settings, on macOS and on Linux, was refused `cat ~/.ssh/<file>` in Bash and `Read` of it, was refused a connection to a host outside `allowedDomains` and an `ssh` to an allowed one, fetched, committed and pushed a branch as the App, ran `uv run pytest` in the gate's checkout, kept a project `.claude/settings.json` `sandbox` key from widening it, and records the refusal text the tick reads; the build issue that delivers it merges before any other of this spec
- S-087-2: a sandboxed headless launch passes one `--settings` JSON holding the session's `env` and `sandbox.enabled: true`, `sandbox.allowUnsandboxedCommands: false`, `sandbox.failIfUnavailable: true`, and no `sandbox.excludedCommands`; an interactive launch's command line is unchanged, and no launch writes a settings file
- S-087-3: the settings' `sandbox.filesystem.denyRead` and `permissions.deny` `Read(...)` and `Edit(...)` each name every path of "What a session can't read", existing or not, minus each `[agents.sandbox] read` entry
- S-087-4: with `SHIPMILL_APP_KEY` naming `~/.config/shipmill/app-<id>.pem`, every other entry of `~/.config/shipmill` is denied and that key is not; every folder of `~/.claude/projects` other than the session's own is denied, and `~/.claude/plugins` is not; an entry created after one launch is denied at the next
- S-087-5: `sandbox.filesystem.allowWrite` is exactly the gate's checkout, the main working tree's `.claude/worktrees`, the git common dir, `<state dir>/uv-cache`, and each `[agents.sandbox] write` entry; the session's `env` sets `UV_CACHE_DIR` to `<state dir>/uv-cache`
- S-087-6: `sandbox.filesystem.denyWrite` names `<common dir>/config`, `<common dir>/hooks`, the state directory's entries other than the token caches and `uv-cache`, and `.claude/settings.json`, `.claude/settings.local.json` and `.mcp.json` of the gate's checkout and of the main working tree
- S-087-7: in a sandboxed launch `--allowedTools` names Edit and Write only as `Edit(//<path>/**)` and `Write(//<path>/**)` rules for the write-scope paths and the session's own project memory folder, with the Bash entries of `HEADLESS_TOOLS` unchanged
- S-087-8: `sandbox.network.allowedDomains` is exactly `github.com`, `*.github.com`, `*.githubusercontent.com`, `pypi.org`, `files.pythonhosted.org`, `astral.sh`, `*.astral.sh`, and each `[agents.sandbox] domains` entry, read from the config on `origin/<default>`
- S-087-9: `AgentsConfig.parse` reads `[agents.sandbox]` `domains`, `read`, `write` and `tunnels` as Behaviour says, and a malformed key (a domain with a scheme, port or path; a relative path or one with `..`; a tunnel with a missing, extra or invalid field, or a repeated `local`) is dropped with its refusal named by doctor, the tick and stderr, while the config loads and the session starts without that key
- S-087-10: with a declared tunnel, the gate runs `ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:<local>:<remote> <ssh>` before it starts the session, records its pid and start time in `gate.json`, allows `127.0.0.1:<local>` in the sandbox, and stops it on the first tick that finds the session ended; a tunnel that fails within 30 seconds leaves the session starting without it and the tick's line naming the tunnel and ssh's last stderr line
- S-087-11: `shipmill decide classify --pr N` reports `security` at `ask` for a pull request that adds a `domains`, `read`, `write` or `tunnels` entry under `[agents.sandbox]`, also when `[decisions] security = "notify"`, and follows `[decisions] security` for one that only removes entries
- S-087-12: with the sandbox on, a `--claude-arg` of `--settings` or `--add-dir`, alone or as `--flag=value`, exits 2 naming the flag and stops and starts no session; `--allowedTools` and `--disallowedTools` pass
- S-087-13: before a sandboxed launch, a `sandbox` or `permissions.additionalDirectories` key in the checkout's `.claude/settings.json` or `.claude/settings.local.json` or in `~/.claude/settings.json` fails the tick with `<file> sets <key>, which would widen a headless session's sandbox` and a fix naming `[agents.sandbox]`, and starts no session
- S-087-14: on the first tick after a sandboxed session ended, a log holding a tool result with the recorded refusal text adds `sandbox refused <n>: <first words> (<path or host>)` and the `[agents.sandbox]` fix to the tick's line and `tick.json`, and changes no decision; a log with none adds nothing
- S-087-15: `needs-decision.md`'s "A denied tool call is a decision" tells a sandbox refusal from a denial, a hook refusal and a not-found, and its option is an `[agents.sandbox]` entry, never `--claude-arg`
- S-087-16: with the sandbox on, the `[agents] verify` check runs each command through `srt` with the session's filesystem and network rules; a command the sandbox refused reads `refused by sandbox` naming the path or host, with doctor's fix an `[agents.sandbox]` entry; the sandbox's rules are part of the check's fingerprint; without `srt` on the gate's PATH each command reads `not checked: srt is not on the gate's PATH`
- S-087-17: on Linux, a sandboxed launch where `bwrap --ro-bind / / --unshare-user true` fails or `socat` isn't on PATH starts no session and fails the tick with `the sandbox can't start on this host: <what failed>` and its fix
- S-087-18: with headless mode, `shipmill doctor` prints one `sandbox` row: PASS listing the domains, exceptions and tunnels when on, WARN `off: headless sessions run unconfined; pass --sandbox` when off, FAIL with the tick's text for a widening settings file or a Linux host that can't confine; no row without headless mode
- S-087-19: `shipmill gate --sandbox` turns the sandbox on for a headless launch and `shipmill launchd --sandbox` writes the flag into the job and its `--print`; without it a headless launch's command line is the one before this spec
- S-087-20: from the release that makes it the default, a headless launch without `--sandbox` is sandboxed, `--sandbox` prints one line saying it is the default, and no flag or `[agents]` key turns the sandbox off
- S-087-21: `docs/design/agent-modes.md`, `docs/install.md` and `skills/shipmill-setup/SKILL.md` document the sandbox, `--sandbox`, `[agents.sandbox]` with its tunnels, the Linux packages, and the refusal on the tick, and no longer call a sandboxed headless session unconfined

## Out of scope

- Sandboxing the person's own sessions, interactive gate sessions, or the person's scheduled jobs: a person approves each command there, and the outcome asks that they keep their access
- MCP servers and hooks: they run outside the sandbox by Claude Code's design. A headless session reaches an MCP tool only when the host widens `--allowedTools` to it, which stays the host's choice; the delivery hook (D-82) keeps judging commands as it does
- Replacing the trust filter (D-16) or D-82's `uv run` rule: the sandbox bounds what any program can reach, the filter bounds whose text steers the session, and the hook keeps refusing what it refuses
- Network limits on Claude Code's own API traffic: it leaves from the `claude` process, not from a sandboxed command
- Moving the gate to a separate OS user or a container: a stronger boundary at a cost in setup per host, for a later spec if the sandbox falls short
- A per-repo off switch: the escape widens what the repo declares, it never turns the sandbox off
- Windows hosts: the gate runs on macOS and Linux

## Decisions relied on

- D-4: `[agents.sandbox]` lives in `.github/shipmill.toml`
- D-9: no `sandbox` doctor row without headless mode
- D-14: the App's key stays readable, as the token it mints is limited to the gate's repo
- D-16: the escape is read from the default branch, and the trust filter stays
- D-17: a tunnel is tracked by pid and start time beside the session
- D-48: refined for `[agents.sandbox]` widenings, which classify `security` at `ask` whatever `[decisions]` sets; a new `D-n` records it with its build issue
- D-54: `SHIPMILL_APP_KEY` names the key the session keeps
- D-55: a refusal and a host that can't confine are reported on the host, not filed on GitHub
- D-63: the default changes in a release after the opt-in, with the flag deprecated before it is refused
- D-64: a malformed escape key or a failed tunnel costs only itself; the session runs narrower, never wider
- D-82: the hook's `uv run` rule is unchanged

## Issues

- shipmill/shipmill#1524: S-087-1
- shipmill/shipmill#1528: S-087-9, S-087-11
- shipmill/shipmill#1531: S-087-2, S-087-3, S-087-4, S-087-5, S-087-6, S-087-7, S-087-8, S-087-12, S-087-19
- shipmill/shipmill#1534: S-087-10, S-087-13, S-087-17, S-087-18
- shipmill/shipmill#1535: S-087-14, S-087-15, S-087-16
- shipmill/shipmill#1536: S-087-20, S-087-21

## Verification
