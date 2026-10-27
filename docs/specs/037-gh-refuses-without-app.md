# S-037: `shipmill gh` refuses a write in a repo without an App

status: built
serves: G-2

## Problem

On 2026-10-20 a Claude Code session opened romamo/myfleet#8 with `shipmill gh pr create`,
run from a checkout of romamo/myfleet. That repo has no `.github/shipmill.toml`, so `_gh()`
in `src/shipmill/cli.py` ran `gh` with the host's login: the pull request was authored by
the maintainer, exit 0, with no warning. The agent expected `shipmill gh` to post as the
App or refuse (shipmill/shipmill#576).

That is spec 012's Behaviour step 3 working as written: with `[agents] app_id` unset, or no
config, `shipmill gh` "runs `gh` as it is, with the host's login ... That is the repo's
chosen identity, not a fallback". Exit 2 only happens when `app_id` is set and the token
can't be had, and the delivery hooks of spec 026 act only in repos with an `[agents]`
section. So in a repo without an App an agent's write through `shipmill gh` silently
carries the maintainer's name, which is the attribution D-14 and spec 012 set out to
prevent: a reader can't tell the maintainer's decision from agent text.

The maintainer (@romamo) asked for one identity rule on #576: a write through `shipmill gh`
posts as the App, or as the maintainer only because someone said so, per repo or per call.

## Behaviour

### What this changes in spec 012

This spec supersedes spec 012's Behaviour step 3, and only that step. With `app_id` unset
or no `.github/shipmill.toml`, `shipmill gh` no longer runs every command as the host:
it runs a read as the host, as before, and refuses a write unless the repo or the call
allows the host's identity (below). Steps 1, 2, and 4, the App's token, the caches, the
skills' rule, relayed decisions, and `AGENT_AS_PERSON` stay as spec 012 built them, and
spec 012 stays `built`. S-012-4 still holds for a read, and for a write the repo or the
call allows: `gh` runs with the arguments, no `GH_TOKEN` when the caller's was empty, and
no token minted.

### The rule

`shipmill gh <args>` (`src/shipmill/cli.py`, `_gh`) reads the checkout's
`.github/shipmill.toml` as it does today (the `--repo` folder, its checkout's top, or the
nearest folder holding a `.git` that git can't read). Then:

| Config | A read | A write |
|---|---|---|
| `[agents] app_id` set | As the App (spec 012, unchanged) | As the App (spec 012, unchanged) |
| No `app_id`, `[agents] identity = "host"` | As the host's `gh` login | As the host's `gh` login |
| No `app_id`, the call passes `--as-host` | As the host's `gh` login | As the host's `gh` login, this call only |
| No `app_id`, nothing allows it | As the host's `gh` login | Refused: exit 2, `gh` never runs |

"No `app_id`" covers a config with no `[agents]` section, an `[agents]` section without
`app_id`, no `.github/shipmill.toml`, and a folder outside any git checkout (no config to
read). A refused write mints no token and starts no process, `gh` included.

With `app_id` set, nothing changes (D-14): reads and writes go as the App, and any failure
to get its token exits 2 as spec 012 says. Spec 033's second line for a host without the
App's key, if that spec is built, is unaffected.

### What the refusal says

Exit 2 with three lines on stderr, after `shipmill: ` as every `ReleaseError` prints:

```
shipmill: refusing a write to owner/name as the host's gh login: .github/shipmill.toml sets no [agents] app_id
allow it for this repo: give it an App (shipmill app-create), or set [agents] identity = "host" in .github/shipmill.toml
allow this one call: shipmill gh --as-host <the same arguments>
```

- The repo is the `-R`/`--repo` value in the `gh` arguments when given (as `named_repo`
  reads it), else `origin`'s `owner/name`, else the checkout's path; outside any checkout
  it is `the folder <path> (no git checkout)`
- With no config file the first line ends `<checkout> has no .github/shipmill.toml, so no
  [agents] app_id`; with a config whose `[agents]` section has no `app_id` or which has no
  `[agents]` section, it ends as above
- The third line repeats the refused arguments, shell-quoted, so the caller can run it
  once a person approved it

### Telling a write from a read

`src/shipmill/cli.py` has no classifier today: `_gh` passes the arguments through. The one
that exists is `is_gh_write` in `hooks/delivery.py` (spec 026), which the package can't
import, since `hooks/` isn't in the wheel. The build adds `is_read(args)` to
`src/shipmill/app_gh.py`, beside `named_repo`, reusing the hook's parsing of the command
group and of `gh api`, with one difference: the hook fails open (an unknown command
passes, it catches mistakes, D-40), while `shipmill gh` fails safe. **A command is a read
only when this list names it; every other command is a write**, so a `gh` subcommand added
later, or one this list forgot, is refused until it is listed.

The reads:

- `gh` with no arguments, `gh --version`, `gh version`, `gh help ...`, `gh status`
- `gh issue` `list`, `view`, `status`; `gh pr` `list`, `view`, `status`, `diff`, `checks`
- `gh release` `list`, `view`, `download`; `gh label` `list`
- `gh run` `list`, `view`, `watch`, `download`; `gh workflow` `list`, `view`
- `gh repo` `view`, `list`, `clone`; `gh search` (every subcommand)
- `gh secret` `list`; `gh variable` `list`, `get`; `gh cache` `list`
- `gh ruleset` `list`, `view`, `check`; `gh gist` `list`, `view`; `gh org` `list`
- `gh project` `list`, `view`, `field-list`, `item-list`
- `gh auth` `status`, `token`; `gh config` `get`, `list`; `gh alias` `list`; `gh extension` `list`
- `gh api` when it is a read by the rule below

`gh api` is a read when its method is `GET` or `HEAD`, given with `-X`/`--method`
(`-XGET`, `--method=get`, any case) or implied, and a write otherwise. gh implies `POST`
when the call passes `-f`, `-F`, `--field`, `--raw-field`, or `--input` and no method, so
such a call is a write; with an explicit `-X GET`, gh sends the fields as query
parameters, so `gh api -X GET search/issues -f q=...` is a read. `gh api graphql` is a read
only when every `query=` field is given inline and holds no `mutation`; a query read from a
file (`-F query=@file`) or through `--input` is a write, since `shipmill gh` reads no file.
This is the hook's `_api_write` rule, plus `HEAD` as a read.

`--help` and `-h` make nothing a read: `gh pr create --help` is refused like the write it
names. Only the arguments before `--` are read, as `named_repo` reads them.

### Allowing the host's identity for a repo: `[agents] identity`

A new optional key in the `[agents]` section of `.github/shipmill.toml` (D-4), parsed by
`AgentsConfig.parse` in `src/shipmill/agents.py` like the section's other keys:

```toml
[agents]
prompt = "..."
identity = "host"   # agent writes through shipmill gh run as the host's gh login
```

| Value | Means |
|---|---|
| `"app"` (the default, also when the key is absent) | Writes go as the App when `app_id` is set, and are refused when it isn't |
| `"host"` | No App: writes through `shipmill gh` run as the host's `gh` login, as the repo chose |

- Any other value, or a value that isn't a string, exits 2 naming `[agents] identity` and
  the two values, wherever the section is parsed (`shipmill gh`, `gate`, `doctor`, and the
  rest), as `mode` does
- `identity = "host"` together with `app_id` exits 2 naming both keys: the two contradict,
  and the error keeps an App from being silently bypassed (D-14). `identity = "app"` with
  `app_id` is fine
- The key lives in `[agents]`, so it brings the section's other rules: `prompt` stays
  required, and the delivery hooks (spec 026) apply to the repo. `app_id_of` gains a
  sibling that returns both keys, so `_gh` parses the section once
- `hooks/delivery.py` parses `[agents] app_id` itself and ignores other keys; it needs no
  change, and a config with `identity` must keep passing it
- D-19 is unchanged: an `[agents]` prompt without `app_id` still reads as `AGENTS_NO_APP`
  in `setup_state.py` and `GATE_NO_APP` in `watch_state.py`, `identity = "host"` or not

### Allowing it for one call: `--as-host`

`shipmill gh --as-host <gh args>` allows that one call to write as the host's `gh` login
in a repo without `app_id`. Like `--app-key`, it is shipmill's own option, read only
before the first `gh` argument, and never passed to `gh`; `_app_key` becomes a small
parser of the leading options (`--app-key PATH`, `--app-key=PATH`, `--as-host`, in either
order). An `--as-host` after the first `gh` argument goes to `gh` untouched.

- With `app_id` set, `--as-host` exits 2 naming `[agents] app_id`, and `gh` never runs: a
  repo with an App writes as the App or not at all (D-14), and a contributor without the
  App's key uses plain `gh`, as spec 033 says
- With `identity = "host"`, `--as-host` changes nothing
- `--as-host` with `--app-key` exits 2, as `--app-key` with no `app_id` does today

The skills say a session passes `--as-host` only for a write a person approved in that
session's chat, never on its own judgment and never in a headless session, and says so in
its report. Spec 026 keeps "no switch a session can set for itself" for the hook rules:
`--as-host` turns off no hook rule, applies only where `app_id` is unset (where the hooks'
`app-writes` rule is already off), and only makes explicit a write the session could
otherwise run with plain `gh`.

### How it relates to spec 033

Spec 033 (D-54) is about plain `gh` from a contributor's session in a repo
that has an App: where the App's key isn't on the host, the `app-writes` hook lets a plain
`gh` write run as the person at the keyboard, and `shipmill gh` still exits 2. This spec is
about `shipmill gh` in a repo with no App. Together: `shipmill gh` never writes as a person
unless the repo (`identity = "host"`) or the call (`--as-host`) says so, and never where
an App is set; a write as a person goes through plain `gh` by that person (spec 033) or
through an explicit allow (this spec). Neither spec changes the other's case.

### Who breaks, and the migration

A repo without `[agents] app_id` whose scripts, agents, or people run `shipmill gh` for a
write: the write now exits 2 instead of posting as the host's login. The skills' own
scripts (`chains.py`, `shipped.py`, `setup_state.py`, `watch_state.py`) already pick
`shipmill gh` only when `app_id` is set and plain `gh` otherwise, so they don't break.
The migration is one of:

- give the repo an App (`shipmill app-create`, then `[agents] app_id`), the path D-19 asks for
- set `[agents] identity = "host"` when the maintainer wants agent writes under their name
- pass `--as-host` on a one-off write a person approved

`shipmill doctor` adds nothing: the refusal names its fixes on the call that hits it, and
D-19's rows already report a gate without an App. Spec 014's config upgrades offer no
`identity = "host"` upgrade: proposing it to every repo would make the host's identity a
default by another route, which is what #576 asks to end.

The build's changelog fragment goes under `### Changed`, a minor bump: the break is
narrow, fails safe, and names its own fix (see the pull request's decisions).

### Docs

The build updates every place that describes `shipmill gh` in a repo without an App:

- The "Write as the App when the repo has one" rule in `skills/github-issue-triage/SKILL.md`
  (hard rule 12), `skills/github-issue-resolve/SKILL.md`, `skills/github-pr-triage/SKILL.md`
  (rule 8), `skills/github-ship-watch/SKILL.md` (rule 7), `skills/product-intake/SKILL.md`
  (rule 7), and `skills/shipmill-setup/SKILL.md` (The gate): without `app_id`, a write
  through `shipmill gh` exits 2 unless `[agents] identity = "host"`; that exit 2 is a stop
  like any other, never retried with plain `gh`, and `--as-host` is passed only for a
  write a person approved in the chat
- The places that tell a session to run `shipmill gh` for a write with no `app_id`
  condition: `skills/github-issue-triage/SKILL.md` `SUSPECT_CLOSE` and `OFF_MILESTONE`,
  and `skills/github-ship-watch/SKILL.md` `MILESTONE_OVERTAKEN` (and the fix text
  `skills/github-ship-watch/scripts/watch_state.py` prints for it) say "through
  `shipmill gh` with `[agents] app_id` set", as the other rows do
- `docs/install.md` (Give the sessions their own identity, the `shipmill gh` part): the
  refusal, `identity = "host"`, and `--as-host`
- `docs/release-lanes.md`: `[agents] identity`, next to the other `[agents]` keys

## Acceptance criteria

- S-037-1: In a checkout with no `.github/shipmill.toml`, `shipmill gh pr create -R owner/name --title t --body-file f` and `shipmill gh issue comment 1 --body-file f` exit 2 without running `gh` or minting a token, and stderr names `owner/name`, the missing `.github/shipmill.toml` and `[agents] app_id`, `[agents] identity = "host"`, and `shipmill gh --as-host` with the same arguments
- S-037-2: The same writes exit 2 with the same message (its first line naming `[agents] app_id`) in a checkout whose config has only `[release]`, and in one whose `[agents]` section has no `app_id`; outside any git checkout the message names the folder
- S-037-3: In each case of S-037-1 and S-037-2, a read (`pr view 1`, `issue list`, `api user --jq .login`, `api -X GET search/issues -f q=x`) runs the `gh` on `PATH` with exactly its arguments and no `GH_TOKEN`, even when the caller's was empty, mints no token, prints nothing extra, and exits with `gh`'s code
- S-037-4: `is_read` in `src/shipmill/app_gh.py` returns true for every command the Behaviour lists as a read, and false for every group and subcommand in `GH_WRITES` of `hooks/delivery.py`, for a command the list doesn't name (`gist create`, `project item-add`, `codespace create`), and for `pr create --help`
- S-037-5: `gh api` with no method and no field, with `-X GET`, `-XGET`, `--method=get`, or `-X HEAD` with or without `-f`/`-F` fields, and `gh api graphql -f query='{ viewer { login } }'` are reads; `gh api` with `-X POST`, `PATCH`, `PUT`, or `DELETE`, with `-f`, `-F`, `--field`, `--raw-field`, or `--input` and no method, `gh api graphql` with a `mutation` query, and one with `-F query=@file` are writes
- S-037-6: With `[agents] identity = "host"` and no `app_id`, `shipmill gh pr create ...` runs `gh` with exactly its arguments and no `GH_TOKEN`, mints no token, prints nothing extra, and exits with `gh`'s code
- S-037-7: `[agents] identity` set to a string other than `"app"` or `"host"`, or to a non-string, makes `shipmill gh` and `AgentsConfig.load` exit 2 naming `[agents] identity` and both values; absent, it reads as `"app"`
- S-037-8: `[agents] identity = "host"` together with `app_id` exits 2 naming both keys, and `shipmill gh` runs no `gh`; `identity = "app"` with `app_id` parses
- S-037-9: With no `app_id`, `shipmill gh --as-host pr create ...` runs `gh` with the arguments after `--as-host` and no `GH_TOKEN`, and the next call without it is refused; `--as-host` and `--app-key` are read in either order before the first `gh` argument, an `--as-host` after it reaches `gh` untouched, and `--as-host` with `--app-key` exits 2
- S-037-10: With `app_id` set, `shipmill gh --as-host <any args>` exits 2 naming `[agents] app_id` and runs no `gh`; without `--as-host`, reads and writes run as the App and token failures exit 2 exactly as S-012-2 and S-012-3 say
- S-037-11: `hooks/delivery.py` gives the same exit code and output for every spec 026 fixture whether or not the config's `[agents]` section sets `identity`
- S-037-12: The six skills' "Write as the App" rules name the refusal without `app_id`, `[agents] identity = "host"`, that the exit 2 is never retried with plain `gh`, and that `--as-host` is passed only for a write a person approved in the chat; `SUSPECT_CLOSE`, `OFF_MILESTONE`, and `MILESTONE_OVERTAKEN` name `shipmill gh` only with `[agents] app_id` set; `docs/install.md` documents the refusal, `identity`, and `--as-host`, and `docs/release-lanes.md` lists `[agents] identity`

## Out of scope

- Plain `gh`: the delivery hooks (spec 026, and spec 033's availability rule) decide what
  a plain `gh` write may do; a plain `gh` write in a repo without an App still runs as
  the host, and D-19's rows report that repo's missing App
- Minting tokens differently, or another App per repo: spec 012's token path is unchanged
- Changing D-19's reports for a repo with `identity = "host"`: setup still reads it as
  unfinished; a later spec may read the key as the maintainer's choice
- An environment variable or any other per-call switch beside `--as-host`
- Rewriting the author of what was already posted

## Decisions relied on

- D-4: `[agents] identity` lives in `.github/shipmill.toml`
- D-14: agent writes go as the App or not at all where the App is set, so `identity =
  "host"` with `app_id`, and `--as-host` with `app_id`, exit 2, and behaviour with
  `app_id` set doesn't change
- D-19: a gate without an App is unfinished setup; the refusal's first fix is an App, and
  `identity = "host"` doesn't change D-19's reports
- D-54 (superseding D-40): the hooks fail open and act only in repos
  with `[agents]`; `shipmill gh` fails safe, and `--as-host` turns off no hook rule
- D-54 (spec 033): a plain `gh` write runs as the
  person where the App isn't available; this spec leaves that case to it

## Issues

- shipmill/shipmill#700: S-037-1, S-037-2, S-037-3, S-037-4, S-037-5, S-037-6, S-037-7, S-037-8, S-037-9, S-037-10, S-037-11, S-037-12

## Verification

- S-037-1: `pr create -R owner/name` and `issue comment` in a checkout with no config raise the three-line refusal (repo, the missing file and `app_id`, `identity = "host"`, `shipmill gh --as-host` with the shell-quoted arguments, `shipmill` written as `cli_command()` names it, per #236) with no gh call, token, or signature, and `python -m shipmill` exits 2 with no gh run (`tests/test_gh_refuses_without_app.py`), pass
- S-037-2: the same writes with only `[release]` and with `[agents]` without `app_id` give the first line `.github/shipmill.toml sets no [agents] app_id`; outside any checkout, and in one without a GitHub origin, the message names the folder or the checkout's path, pass
- S-037-3: `pr view 1`, `issue list`, `api user --jq .login`, and `api -X GET search/issues -f q=x` in all four configs, with `GH_TOKEN` unset and empty, run the gh on `PATH` with exactly their arguments, no `GH_TOKEN`, no token minted, no output, gh's exit 7; end to end through the fake gh too, pass
- S-037-4: `is_read` on every listed read (with `--help` on a read), every group and subcommand of `hooks/delivery.py`'s `GH_WRITES` (with and without `--help`), and unlisted commands (`gist create`, `project item-add`, `codespace create`, `pr create --help`, a flag before the subcommand, `--` first, an alias), pass
- S-037-5: `gh api` reads (no method, `-X GET`, `-XGET`, `--method=get`, `-X HEAD` with and without fields, an inline graphql query) and writes (`POST`, `PATCH`, `PUT`, `DELETE`, each field flag and `--input` without a method, a graphql mutation, `-F query=@file`, `--input` to graphql), pass
- S-037-6: with `identity = "host"`, `pr create` runs gh with exactly its arguments, no `GH_TOKEN` (an empty one dropped), no token, no output, gh's code, pass
- S-037-7: six bad values (other strings, an integer, a boolean, an array) make `AgentsConfig.load` and `shipmill gh` exit 2 naming `[agents] identity` and `"app"` and `"host"`, with no gh run; absent reads as `"app"`, pass
- S-037-8: `identity = "host"` with `app_id` exits 2 naming both keys from `shipmill gh` (no gh run) and `AgentsConfig.load`; `identity = "app"` with `app_id` parses, pass
- S-037-9: `--as-host pr create` runs gh with the arguments after it and no `GH_TOKEN`, the next call without it is refused; `--as-host` with `--app-key` in either order and in the `=` form exits 2; an `--as-host` after gh's first argument reaches gh and allows nothing; `--as-host` twice exits 2, pass
- S-037-10: with `app_id`, `--as-host` with a write, a read, or no arguments exits 2 naming `[agents] app_id` with no gh run or token; without it a write and a read run as the App, and a missing key still exits 2 as S-012-3 says; spec 012's tests (`tests/test_app_gh.py`) pass, S-012-4's now with a read
- S-037-11: every fixture in `tests/fixtures/hooks` (pre and post) answers with the same exit code, stdout, and stderr in the app and agents repos with and without `identity` set (`tests/test_delivery_hooks.py`), pass
- S-037-12: the six skills' rules name the refusal, `identity = "host"`, the exit 2 as a stop never retried with plain `gh`, and `--as-host` only for a write a person approved in the chat; the `SUSPECT_CLOSE`, `OFF_MILESTONE`, and `MILESTONE_OVERTAKEN` rows, and the rename `shipmill milestones` prints, name `shipmill gh` only with `app_id` set; `docs/install.md` and `docs/release-lanes.md` document the refusal, `identity`, and `--as-host` (`tests/test_app_gh_docs.py`, `tests/test_milestone_status.py`), pass
