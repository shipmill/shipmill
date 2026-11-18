# S-082: Whom agents write to GitHub as is chosen once per repo, at setup

status: approved
serves: G-1

## Problem

Whom an agent writes to GitHub as is decided in two places that drift apart: the repo's
`.github/shipmill.toml` (`[agents] app_id`, `identity`) and the prose a maintainer keeps in
their own instructions ("these repos have an App, the others don't"). An agent that trusts
the prose picks plain `gh` in a repo that has had an App for weeks, the delivery hook refuses
it (D-14), and the agent retries through `shipmill gh`. Where a repo has no config, the agent
stops and asks the maintainer again whom to write as (#1223, grouped into #1235, which the
maintainer accepted on 2026-11-18).

The config already holds the answer for most repos. Three things are missing:

1. **No value for "nobody".** A maintainer who wants neither the App nor their own login in a
   repo can't say so. `identity = "app"` without `app_id` refuses a write, but reads the same
   as a setup that isn't finished, so the refusal recommends the App or `identity = "host"`
   (spec 037): advice the maintainer already declined
2. **Setup doesn't ask.** The choice is left to whoever edits the config later, so most repos
   never record it
3. **Setup doesn't check that the App reaches the repo.** An `app_id` whose App isn't
   installed on the repo fails at the first write, not at setup

It hits maintainers connecting repos one by one, and the agents in them, which retry refused
writes or stop to ask: each is a human step G-1 counts.

## Behaviour

This spec builds on spec 037 (`identity = "host"`, the refusal of a write without an App) and
spec 033 (`shipmill app-token --check`, drafting where the App isn't available). It
supersedes two sentences of them, named below, and nothing else: with `app_id` set, every
read and write goes as the App as before (D-14), and D-54 and D-65 stand as they are.

### `[agents] identity` has three values

`src/shipmill/agents.py` (`WriteAs`, `identity_of`) reads `[agents] identity` as `"app"` (the
default, also when absent), `"host"`, or the new `"none"`: agents don't write to GitHub in
this repo. Any other value, or one that isn't a string, exits 2 naming the three values.
`identity = "none"` with `app_id` exits 2 naming both keys, as `identity = "host"` with
`app_id` does today. `skills/shipmill-setup/scripts/setup_state.py` reads the key the same
way. The choice is **recorded** when the config sets `app_id`, `identity = "host"`, or
`identity = "none"`; every other config, no config, and a folder outside a checkout are
**not chosen**.

| Config | A read through `shipmill gh` | A write through `shipmill gh` |
|---|---|---|
| `app_id` set | As the App (unchanged) | As the App (unchanged) |
| `identity = "host"`, no `app_id` | As the host's `gh` login (unchanged) | As the host's `gh` login (unchanged) |
| `identity = "none"` (new) | As the host's `gh` login | Refused: exit 2, the owner's-choice message |
| Not chosen | As the host's `gh` login (unchanged) | Refused: exit 2, naming the three choices |

A refused write mints no token and starts no process, `gh` included, as in spec 037.

### What the two refusals say

`src/shipmill/cli.py` (`_gh`, `_host_write_refused`, and `_spec_writes` for `shipmill spec
open`). With `identity = "none"`, exit 2 with two lines on stderr:

```
shipmill: refusing a write to owner/name: .github/shipmill.toml sets [agents] identity = "none", so this repo's owner chose that agents don't write to GitHub here
shipmill wrote nothing: hand the text to a person, who posts it as themselves
```

It recommends no other identity: no `app-create`, no `identity = "host"`, no `--as-host`.
A leading `--as-host` doesn't lift it: the call exits 2 with the same two lines, since the
repo's recorded choice outranks one call's flag.

Not chosen, exit 2 with spec 037's first line unchanged, then the choices, the setup that
records one, and spec 037's one-call line (left out for `spec open`, as today):

```
shipmill: refusing a write to owner/name as the host's gh login: .github/shipmill.toml sets no [agents] app_id
choose whom agents write as here, in [agents] of .github/shipmill.toml: the App (app_id = <id>, from `shipmill app-create`), your own login (identity = "host"), or nobody (identity = "none")
or let setup ask once and record it: /shipmill:shipmill-setup owner/name
allow this one call: shipmill gh --as-host <the same arguments>
```

This replaces the second line of spec 037's "What the refusal says" and the text S-037-1 pins
for it; the first and last lines, the repo's naming, and the no-config wordings stay.

### `shipmill app-token --check` answers for every repo

`shipmill app-token --check` (`src/shipmill/cli.py`, `_app_check`) is the one question a skill
asks before its first write. With `app_id` set it is unchanged (S-033-16). Without `app_id`
it no longer always names `[agents] app_id`:

- `identity = "host"`: exit 0, printing that writes go as the host's `gh` login because the
  repo chose `identity = "host"`
- `identity = "none"`: exit 2 with the owner's-choice message above
- Not chosen: exit 2 naming the three choices and the setup line above

In every case it prints no token, mints none, and makes no network call. This replaces
S-033-16's clause "without `app_id` ... it exits 2 naming `[agents] app_id`".

### The skills ask the config, not their instructions

The "Write as the App" rule of the six skills (`skills/github-issue-triage/SKILL.md`,
`skills/github-issue-resolve/SKILL.md`, `skills/github-pr-triage/SKILL.md`,
`skills/github-ship-watch/SKILL.md`, `skills/product-intake/SKILL.md`,
`skills/shipmill-setup/SKILL.md`) changes in three places:

- Every write to GitHub runs as `shipmill gh`, in every repo, whatever the config sets; the
  rule no longer starts "when the config sets `app_id`". The config is the only place the
  choice lives, and an instruction file's prose about identity is never read for it
- The skill runs `shipmill app-token --check` before its first write, a push included, in
  every repo, not only with `app_id` set
- On the owner's-choice exit 2, from the check or from `shipmill gh`, the skill does what
  spec 033 has it do where the App isn't available: it stops, its report's first line says
  the owner chose that agents don't write here and that shipmill wrote nothing, and it hands
  over the text of each write it would have made, with its target. It never offers or passes
  `--as-host` there. The not-chosen exit 2 stays a stop that reports the message

### Setup asks once and records the answer

`skills/shipmill-setup/scripts/setup_state.py` gains one Identity row, the first that
applies: `IDENTITY_APP` (`app_id` set), `IDENTITY_HOST`, `IDENTITY_NONE`, or
`IDENTITY_UNCHOSEN`. `IDENTITY_UNCHOSEN` names the Apps the host already has, each as
`<app_id> (<where>)`: one with a key file at `~/.config/shipmill/app-<app_id>.pem` (the file
is never opened), and the `app_id` of each sibling checkout's `.github/shipmill.toml` (the
siblings the Product row already reads, spec 043). The row is done (`DONE`) for the three
recorded values; `IDENTITY_UNCHOSEN` is an action (exit 1) only when the config has an
`[agents]` section, and informational without one, as `AGENTS_MISSING` is.

`skills/shipmill-setup/SKILL.md`, connecting the agent side: when the row reads
`IDENTITY_UNCHOSEN`, setup asks one question, in the round of its other questions (D-20),
"Whom do agents write to GitHub as in this repo?", and writes the answer to `[agents]` of
`.github/shipmill.toml` in the setup PR. A repo whose row reads a recorded value is not asked.

1. **The App (recommended).** With an App named by the row, setup offers it, so the usual
   answer is a confirmation; with none it offers `shipmill app-create` (spec 006). Before it
   writes `app_id`, it runs `shipmill app-install <owner/repo> --app-id <id> --check`. On
   exit 0 it writes `app_id = <id>`. On any other exit it writes no `app_id`, passes on the
   command's message, which names the App's installation settings page, and stops the
   identity step there; the user installs the App (`shipmill app-install`) and setup is run
   again
2. **The owner's login** (`identity = "host"`), said with a plain warning before it is
   written: on GitHub these writes can't be told from the owner's own
3. **Nobody** (`identity = "none"`): agents draft, a person posts

With `host` or `none` chosen, setup installs no gate: D-19 stands, and it says that the gate
needs the App.

### `shipmill app-install --check`

`shipmill app-install [<owner/repo>] [--app-id <id>] --check` (`src/shipmill/app_install.py`,
`src/shipmill/cli.py`) opens no page and waits for nothing. It mints an installation token
for the repo with the App's key and reads `GET /repos/<owner/repo>` with it, the check
`shipmill gate` makes before a launch (`app_reach` in `src/shipmill/github_auth.py`, spec
048). The token goes nowhere else: it isn't printed or cached. The repo and `--app-id`
default as spec 007 says (S-007-1, S-007-2), so setup can name an App the config doesn't
hold yet.

- Exit 0: `App <id> (<slug>[bot]) can read <owner/repo>`
- Exit 1: the App isn't installed on the repo, or its token can't read it. The message names
  the repo and the App's installation settings page, and says to run `shipmill app-install
  <owner/repo>`
- Exit 2: the key is missing or readable by others, or GitHub can't be reached, each naming
  its fix as spec 004 does

`--check` with `--json` prints one object with `app_id`, `slug`, `repo`, `reads` (true or
false), and `page`.

### `shipmill doctor` shows the choice

`src/shipmill/doctor.py` adds one `identity` row, in every repo:

| Config | Row |
|---|---|
| `app_id` set, the key on this host, the App reads the repo | `PASS identity: the App <id> (<slug>[bot]) can read <owner/repo>` |
| `app_id` set, the App can't read the repo | `FAIL identity: the App <id> can't read <owner/repo>`, with the installation page and `shipmill app-install <owner/repo>` |
| `app_id` set, no key on this host | `WARN identity: the App <id>, unchecked: its key isn't on this host` |
| `identity = "host"` | `PASS identity: host: writes through shipmill gh go as the host's gh login` |
| `identity = "none"` | `PASS identity: none: agents don't write to GitHub here` |
| Not chosen, with an `[agents]` section | `WARN identity: not chosen: a write through shipmill gh is refused`, naming the three choices and the setup line |
| Not chosen, no `[agents]` section | `PASS identity: not chosen (no [agents] section)`, with the same three choices |

A repo where shipmill only cuts releases has no `[agents]` section and so gets no new warning
(D-9, Q-6). The App's check is `app_reach`, read with the key on the host; `doctor` writes
nothing.

### Docs

`docs/install.md`, under "Give the sessions their own identity": the three values and the
setup question; that `identity = "none"` refuses every write and `--as-host` too; and a note
that an App installed with access to **All repositories** of an account reaches a new repo
there with no installation step, and what that grants: the App can then read and write every
repository of the account, private ones included.

Touched areas: `src/shipmill/agents.py` (`[agents] identity`), `src/shipmill/cli.py`
(`shipmill gh`, `shipmill spec open`, `shipmill app-token --check`, `shipmill app-install
--check`), `src/shipmill/app_install.py`, `src/shipmill/github_auth.py` (read),
`src/shipmill/doctor.py`, `skills/shipmill-setup/SKILL.md`,
`skills/shipmill-setup/scripts/setup_state.py`, the five other skills' `SKILL.md`,
`docs/install.md`, and `tests/test_agent_identity.py`.

## Acceptance criteria

- S-082-1: `AgentsConfig.parse` reads `[agents] identity` as `"app"` when absent, `"host"`, or `"none"`; any other value or a non-string exits 2 naming `[agents] identity` and the three values; `identity = "none"` with `app_id` exits 2 naming both keys; `setup_state.py` reads the same three values and refuses the same input with exit 2, on Python 3.10
- S-082-2: with `identity = "none"` and no `app_id`, a write through `shipmill gh` exits 2 without running `gh` or minting a token; stderr names the repo and `[agents] identity = "none"`, says the repo's owner chose that agents don't write to GitHub here and to hand the text to a person, and contains none of `app-create`, `app_id`, `"host"`, and `--as-host`; a read (`pr view`) runs as the host's `gh` login with exit `gh`'s
- S-082-3: with `identity = "none"`, `shipmill gh --as-host <a write>` exits 2 with the same two lines, and `gh` never runs
- S-082-4: a write through `shipmill gh` with no `.github/shipmill.toml`, with no `[agents]` section, with an `[agents]` section setting neither key, and with `identity = "app"` and no `app_id`, exits 2 with a message that names the three choices (`app_id` with `shipmill app-create`, `identity = "host"`, `identity = "none"`), the line `/shipmill:shipmill-setup <owner/name>`, and the `--as-host` line repeating the arguments; with `identity = "host"` the same write runs as the host's `gh` login, as before
- S-082-5: `shipmill spec open` in a checkout with `identity = "none"` exits 2 with the owner's-choice message before its first write, pushing nothing; not chosen, it exits 2 naming the three choices and the setup line, with no `--as-host` line
- S-082-6: `shipmill app-token --check` without `app_id` exits 0 naming the host's `gh` login and `identity = "host"` when the config sets it, exits 2 with the owner's-choice message for `identity = "none"`, and exits 2 naming the three choices and the setup line when not chosen; with `app_id` set it answers as S-033-16 says; in every case it prints no token, mints none, and makes no network call
- S-082-7: `setup_state.py` prints one Identity row: `IDENTITY_APP` naming the id with `app_id` set, `IDENTITY_HOST`, `IDENTITY_NONE`, or `IDENTITY_UNCHOSEN`; `IDENTITY_UNCHOSEN` names each App with a key file at `~/.config/shipmill/app-<app_id>.pem` and each sibling checkout's `app_id`, opening no key file; it exits 1 for `IDENTITY_UNCHOSEN` when the config has an `[agents]` section and leaves the exit code alone without one
- S-082-8: `shipmill app-install <owner/repo> --app-id <id> --check` opens no page and doesn't wait; it exits 0 printing `App <id> (<slug>[bot]) can read <owner/repo>` when a token minted for the repo reads `GET /repos/<owner/repo>` with 200, exits 1 naming the repo and the App's installation settings page when the App isn't installed or the read doesn't answer 200, and exits 2 for a missing key; the token is never printed or cached, and `--json` prints `app_id`, `slug`, `repo`, `reads`, and `page`
- S-082-9: `skills/shipmill-setup/SKILL.md` has setup ask "Whom do agents write to GitHub as in this repo?" only when the row reads `IDENTITY_UNCHOSEN`, with the options in the order the App (recommended, offering an App the row names, else `shipmill app-create`), the owner's login with the warning that its writes can't be told from the owner's own, and nobody; write the answer to `[agents]`; run `shipmill app-install ... --check` before writing `app_id` and write none unless it exits 0; and install no gate for `host` or `none`
- S-082-10: `shipmill doctor` prints one `identity` row: PASS naming the App's id, its bot login, and the repo when its token reads the repo; FAIL naming the repo, the installation page, and `shipmill app-install` when it can't; WARN when the key isn't on the host; PASS `host` and PASS `none` for those values; WARN `not chosen` naming the three choices with an `[agents]` section, and PASS `not chosen (no [agents] section)` without one
- S-082-11: the "Write as the App" rule of each of the six skills says that every write to GitHub runs as `shipmill gh` in every repo whatever the config sets, that the skill runs `shipmill app-token --check` before its first write in every repo, that on the owner's-choice exit 2 it stops, says the owner chose that agents don't write here, hands over the text of each write with its target, and never passes `--as-host`, and that no instruction file's prose decides the identity
- S-082-12: `docs/install.md` names the three `[agents] identity` values, the setup question, that `identity = "none"` refuses `--as-host` too, and that an App installed on All repositories reaches a new repo of the account with no installation step and can then read and write every repository of the account, private ones included

## Out of scope

- The delivery hook's `app-writes` rule (`hooks/delivery.py`): it stays as D-54 sets it, on only with `app_id` and the App available, so a person's own plain `gh` write in an `identity = "none"` repo goes out as them. The skills never write that way (S-082-11); refusing it in the hook would change D-54 and takes its own decision
- `shipmill gate` in a repo with `identity = "none"` or `"host"`: the gate and `AGENTS_NO_APP` read as D-19 has them; setup installs no gate there, and a gate someone adds by hand starts sessions that stop at their first write
- Writing to, or reporting on, the prose about identity in a repo's own instruction files (D-42): the maintainer removes it; the skills stop reading it
- One answer for every repo of a product at once (spec 043): the question is asked per repo, as each is connected
- A CLI command that writes the choice into the config: setup, a skill, writes it in its PR; see "Decisions for you" in the spec PR
- Installing the App on a repo for the user: `shipmill app-install` still only guides (spec 007)
- What else an `[agents]` section turns on (the delivery hooks, spec 034's direction row): unchanged for a section that holds only `identity`

## Decisions relied on

- D-4
- D-9
- D-14
- D-19
- D-20
- D-42
- D-54
- D-63
- D-65

## Issues

## Verification
