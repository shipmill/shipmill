# S-051: Write as the decider

status: approved
serves: G-8

## Problem

Once a repo is connected, the App authors nearly everything that lands: the issues it files,
the pull requests it opens, and the commits it merges. GitHub credits each to
`shipmill-<owner>[bot]`, so the profiles of the people who decided the work show almost none of
it (#793). On one maintainer's 14 active repositories over 2026-10-28, GitHub credited them 75
contributions while the App opened 44 issues and 52 pull requests and authored 42 commits on
default branches. Spec 049's `Co-authored-by` trailer credits the merged commit, not the issue
or the pull request, and only when a repo turns `[agents] credit` on.

Practice elsewhere (2026-10-29): an agent in a person's editor writes as the person, with the
agent as co-author; a delegated coding agent writes as its bot, with the person who assigned
the work as co-author. This spec lets a repo's owner choose the first convention for delegated
work, with the App visible, and only for people who agreed to it.

### What the spike found

From GitHub's documentation for an App acting on a user's behalf (read 2026-10-31):

- A request made with an App's user access token is attributed to the user; GitHub shows the
  user's avatar with the App's badge, and the audit log records the user as the actor with a
  user-to-server token
- The token reaches only what both the user and the App's permissions reach, and only in
  accounts where the App is installed
- The user must authorize the App themselves; in an organization, each member authorizes it.
  An owner installing the App authorizes nobody
- A profile counts the issues a person opened, the pull requests they proposed, and the commits
  they authored or co-authored

Not settled by the documentation, and checked live before the build's first release (Out of
scope names the person's step): that `performed_via_github_app` names the App on an issue,
pull request, and comment made with a user access token, and who GitHub makes the author of a
squash merge made with one. The design below does not depend on the second: the merge names
its author with `--author-email`.

## Behaviour

### The modes

The owner chooses whose account an agent's issue, pull request, and merge commit go out as:

| Mode | Config | Author of an agent's issue, pull request, and merge commit | `Co-authored-by` on the merge commit |
|---|---|---|---|
| Autonomous | `[agents] app_id` with `author = "app"` | The App | The decider (spec 049) |
| Assisted | `[agents] app_id` with `author = "decider"` | The decider, when they authorized the App; else the App | The App, or the decider when the App wrote it |
| Operator | no `app_id`, `identity = "host"` (spec 037) | The host's `gh` login | As today |

`[agents] author` in `.github/shipmill.toml`, read by `src/shipmill/agents.py`, takes `"app"`
or `"decider"`; any other value fails the config load with exit 2 naming the key and both
values, and so does `author` without `app_id`. Operator mode is unchanged.

### `[agents] credit` folds into the mode (D-63)

- A config that sets `author` names the decider in `Co-authored-by` whenever the App authors
  the merge, as `credit = "decider"` does today; `credit` is then ignored, and `shipmill
  doctor` WARNs that `author` replaces it
- A config that sets neither key merges exactly as today, with no trailer: upgrading shipmill
  changes no repo (D-63)
- A config that sets `credit` and not `author` keeps spec 049's reading, and `shipmill doctor`
  WARNs that `credit` is deprecated, naming `author = "app"` (the same as `credit =
  "decider"`) and saying that a repo that wants no trailer leaves both unset

### A person's consent

`shipmill app-login` (`src/shipmill/app_login.py`) runs GitHub's device flow for the App named
by `[agents] app_id`: it prints the verification URL and the one-time code, and the person
enters the code on github.com in their own browser, signed in as themselves. On success it
stores the user access token and its refresh token in
`~/.config/shipmill/user-<app_id>-<login>.json` with mode `0600`, prints the login it
stored, and exits 0. `shipmill app-logout <login>` deletes that file and revokes the token
(`DELETE /applications/<client_id>/token` is the App's; when it can't, it deletes the file
and says the person can revoke the App under their GitHub settings). The App's client id is
read from `GET /app`; device flow must be on in the App's settings, and when it isn't,
`app-login` exits 2 naming the setting.

The owner turning `author = "decider"` on is no one's consent: a person takes part only once
a token of their own is stored on the host. No other way stores one.

### Who is the decider

The decider of a write is the first trusted person spec 049's sources name, in its order, for
the record the write follows from, with spec 049's and D-62's limits (never a bot, the App, an
untrusted account, or a record carrying the agent marker):

- `shipmill gh pr merge <n>`: the pull request's deciders (spec 049)
- `shipmill gh pr create`: the deciders of the issues its body closes (spec 049's sources 2 to
  4 on those issues)
- `shipmill gh issue create`: the deciders of the issue or pull request named by shipmill's own
  `--decided-in <n>` flag, removed before gh runs; without it the issue has no decider

### The write

In assisted mode, `shipmill gh` (`src/shipmill/app_gh.py`) runs `issue create`, `pr create`,
and `pr merge` with the decider's user access token when one is stored for them, refreshing
it first when it has expired, and with the App's installation token otherwise:

- A write with no decider, a decider with no stored token, or a token GitHub refuses or can't
  refresh goes as the App, exactly as autonomous mode writes it, after one stderr line saying
  why, the login in a code span (D-61), such as ``author: the App; `@octocat` has not run
  shipmill app-login``. A refused refresh deletes the stored file
- A write as a person prints one stderr line before gh runs, such as ``author: `@octocat`,
  who approved the pull request``
- An issue or pull request written as a person keeps the agent marker (D-62) and gets one
  more line at the end of its body: `Opened by an agent through shipmill, on `@<login>`'s
  decision.`
- A merge written as a person passes `--author-email <id>+<login>@users.noreply.github.com`
  for the decider, and its body ends with one `Co-authored-by` trailer for the App's bot,
  `<slug>[bot] <<bot id>+<slug>[bot]@users.noreply.github.com>`, the bot id read from
  `GET /users/<slug>[bot]`; spec 049's trailers name every other decider
- Comments, labels, reviews, edits, closes, needs-decision questions, relayed decisions, and
  every `shipmill gh api` call stay the App's: assisted mode changes the author of those three
  commands only
- No mode approves a pull request on a person's behalf: a branch that requires a review still
  needs a person's

### What counts as a decision

Nothing in this spec changes it: a record carrying the agent marker is never a person's
decision, whoever authored it (D-62). `AGENT_AS_PERSON` (`src/shipmill/agent_as_person.py`,
spec 012) skips a record whose `performed_via_github_app` names the repo's App, so assisted
mode's own writes
don't read as agents writing as a person; a marked record a person's own token made without
the App still does.

### Doctor and the docs

`shipmill doctor` (`src/shipmill/doctor.py`) prints an `author` row: `author: app, the App
writes and names the decider (spec 051)`, `author: decider, N people authorized (spec 051)`
listing their logins in code spans, or `author: unset` with the deprecated `credit` reading
when the config sets it. The shipmill-setup skill (`skills/shipmill-setup/SKILL.md`, the
`[agents]` keys), `docs/flow.md`, and `README.md` name the three modes, `author`, `shipmill
app-login`, that each person opts in, and that the decider sources are who assigned or
approved the work, never an outside author of a request.

## Acceptance criteria

- S-051-1: A config whose `[agents] author` is neither `"app"` nor `"decider"`, or that sets `author` without `app_id`, fails to load with exit 2 naming the key and both values
- S-051-2: A config that sets neither `author` nor `credit` merges through `shipmill gh pr merge` with gh's arguments unchanged and every write as the App, as before this spec
- S-051-3: With `author = "app"`, `shipmill gh pr merge` names the decider in `Co-authored-by` as `credit = "decider"` does, whatever `credit` says, and `shipmill doctor` WARNs that `author` replaces `credit` when both are set
- S-051-4: A config that sets `credit` and not `author` merges by spec 049, and `shipmill doctor` WARNs that `credit` is deprecated, naming `author = "app"`
- S-051-5: `shipmill app-login` stores the user access token and refresh token from GitHub's device flow in `~/.config/shipmill/user-<app_id>-<login>.json` with mode `0600`, prints the login and exits 0, and exits 2 naming the setting when the App has device flow off
- S-051-6: `shipmill app-logout <login>` deletes the stored file and revokes the token, and says how to revoke it in GitHub's settings when the revoke fails
- S-051-7: With `author = "decider"`, `shipmill gh pr merge`, `pr create`, and `issue create --decided-in <n>` run gh with the decider's stored user access token, the decider taken from spec 049's sources in its order for the record each names, and `--decided-in` never reaches gh
- S-051-8: With `author = "decider"`, an expired token is refreshed before the write, and a refused refresh deletes the stored file and writes as the App
- S-051-9: With `author = "decider"`, a write with no decider, a decider with no stored token, or a refused token goes as the App with autonomous mode's trailer, after one stderr line naming why, the login in a code span
- S-051-10: An issue or pull request written as a person carries the agent marker and ends with `Opened by an agent through shipmill, on `@<login>`'s decision.`
- S-051-11: A merge written as a person passes `--author-email` with the decider's noreply address and ends its body with a `Co-authored-by` trailer for the App's bot, and other deciders keep spec 049's trailers
- S-051-12: With `author = "decider"`, every `shipmill gh` command other than `issue create`, `pr create`, and `pr merge` runs with the App's installation token
- S-051-13: An issue or pull request written as a person carries the agent marker, so `triage_state.py`, `watch_state.py`, and `credit.py` never read it as that person's decision, filing, or answer
- S-051-14: `AGENT_AS_PERSON` skips a marked record GitHub made through the repo's App and still flags a marked record a person's token made without it
- S-051-15: `shipmill doctor` prints an `author` row naming the mode, spec 051, and in assisted mode the logins with a stored token
- S-051-16: The shipmill-setup skill, `docs/flow.md`, and `README.md` name the three modes, `[agents] author`, `shipmill app-login`, each person's opt-in, and that the decider is who assigned or approved the work, never an outside author

## Out of scope

- The live check of the two points the documentation leaves open (`performed_via_github_app`
  on a user access token's records, and a squash merge's author through one): it needs a
  person to authorize the App, so it is filed at the split as a `role:maintainer` step with a
  `## Check`, and the build's first release waits on it
- Commits an agent pushes to a pull request's branch: their author is the session's git
  identity, and the squash merge's author is what reaches the default branch
- How a commit reaches the default branch (D-33)
- Writing as a person in operator mode, or any mode that hides shipmill's traces
- A person's token on any host but the one running the gate, or shared between hosts

## Decisions relied on

- D-14
- D-33
- D-54
- D-61
- D-62
- D-63
- D-64

## Issues

## Verification
