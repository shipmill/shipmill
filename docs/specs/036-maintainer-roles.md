# S-036: Steps an agent can't do go to the maintainer; roles for the rest

status: approved
serves: G-1, G-4

## Problem

Spec 017 gives a step an agent can't do (a DNS record, a new repository, a provider key, a
sign-off) the `human` label. With an assignee, a gate session posts the hand-off, waits for
`done`, and checks the result; with none, the item reads NO_ASSIGNEE and the session asks
the maintainer, through needs-decision, who does it (#534, the maintainer's decision).

That question is almost always answered "me". On one connected repo, three of the ten
items waiting on needs-decision on a single day were steps of this kind (check a mail
domain's DNS, issue a staging provider's keys, create a repository and a key) and needed no
decision, only "assign the maintainer". And `human` names the wrong thing: a step belongs to
a role, which one person, several, a team, or later an agent may fill.

## Behaviour

### The config: `[agents.roles]`

Roles live in `.github/shipmill.toml` (D-4) as a subtable of `[agents]`, the layer whose
sessions hand the steps off, parsed in `src/shipmill/agents.py` (a new `roles` key in
`AgentsConfig`, reached from `src/shipmill/policy.py` and `AgentsConfig.load`):

```toml
[agents.roles]
maintainer = ["octocat"]           # the default for every step an agent can't do
infra = ["octocat", "hubot"]       # DNS, secrets, new repositories
legal = ["@example-org/legal"]     # a team: mentioned, since a team can't be assigned
accounting = []                    # nobody yet: falls back to the maintainer
```

Each key is a role name, matching `[a-z0-9][a-z0-9-]{0,44}` (its label, `role:<name>`,
stays within GitHub's 50 characters). Each value is an array of fillers: a GitHub user login
(`[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}`) or a team as `@<org>/<team-slug>`.
The table is optional; with none, the only role is `maintainer`.

Validation is strict and fails fast. Any load of the config (`shipmill doctor`, the gate's
tick, `shipmill roles`) exits 2 naming `[agents.roles]` and the key for:

- `roles` that isn't a table, or a role name outside the pattern
- a value that isn't an array of strings (a string, a number, an inline table such as
  `{ agent = "..." }`; the message says agent-filled roles aren't supported yet)
- a filler that is neither a login nor `@org/team`, a login ending `[bot]`, or a filler
  listed twice in one role (logins and team slugs compared case-insensitively)
- `maintainer` set to a non-empty list that names no user (teams only): the maintainer's
  steps are assigned at once, and a team can't be assigned

An empty array is valid and means nobody fills the role yet: it resolves to the
maintainer, as an undefined role does.

### Who the maintainer is

The maintainer role resolves to the users (and teams) `[agents.roles] maintainer` lists.
When that key is unset or empty, it resolves to the host's gh login, `gh api user`, read as
`src/shipmill/gate.py`'s `host_login` reads it: the person a gate session's needs-decision
comment already mentions (spec 005). The repo's owner is never used: an organization can't be
assigned. When the key is unset and the login can't be read, resolving the roles exits 2,
as the gate does today when it can't read the login.

### `shipmill roles`

A new command in `src/shipmill/cli.py`, backed by a new `src/shipmill/roles.py`, prints the
resolved roles of the checkout's config: one line per role, `maintainer` first, with its users
and teams, and `fallback` on a role that resolved to the maintainer. `--json` prints them as
one object `{"roles": {"<name>": {"users": [...], "teams": [...], "fallback": bool}}}`.
`--flags` prints the `--role` arguments below, for a session or a person running
`triage_state.py` by hand. It exits 0, or 2 on a malformed config or an unreadable login.

### Roles reach the state scripts as flags

The state scripts stay config-free (their docstrings say so today), so the package resolves
the roles and passes them on. `skills/github-issue-triage/scripts/triage_state.py` gains
`--role NAME=FILLER[,FILLER...]`, repeatable, one per role, already resolved (an empty role
arrives as the maintainer's fillers). It exits 2 naming the flag for a malformed name or
filler, an empty filler list, a name given twice, or `--role` given without
`maintainer`.

`gate.py`'s `StateRead` carries the resolved roles and adds the flags, as it adds
`--bot-login`; `skills/github-ship-watch/scripts/watch_state.py` accepts the same flags and
passes them to `triage_state.py`; `src/shipmill/status.py`'s `read_issues` passes them too.
The gate's session prompt gains a line next to `bot_line`, telling the session to pass the
same `--role` flags when it reads the state again (a change to the gate's session paragraphs,
so D-37's evals apply).

### A person's item, by role

An open issue is a person's item when it carries `human` or a label `role:<name>` (label names
compared case-insensitively). Everything spec 017 says of a `human` item holds for it
unchanged: no implementer, no PR state, triaged from the start, its holds, `## Check`, the
hand-off and done markers, VERIFY_DUE, VERIFY_CLOSED, and `--wip` never counting it.

Its roles are its `role:<name>` labels, and `human` counts as `role:maintainer`. A label
naming a role no `--role` flag gives (undefined, or a name outside the pattern) resolves to
the maintainer's fillers, and the note says `role:<name> undefined`. Several role labels
resolve to the union of their fillers. An item's assignees, once it has any, are who does it:
a person chose them, and nothing reassigns it.

With `--role maintainer=...` given, `triage_state.py` reads a person's item, after
UNTRUSTED, NEEDS_DECISION, DECIDED, and OFF_MILESTONE and before its holds, as:

| State | Means | The session |
|---|---|---|
| ASSIGN_DUE | No assignee, and its roles resolve to at least one user | Assigns those users (`gh issue edit --add-assignee`), no comment; an assignment GitHub refuses goes to the maintainer through needs-decision (D-21) |

and otherwise as spec 017 reads it (BLOCKED, HANDOFF_DUE, WITH_PERSON, VERIFY_DUE).
ASSIGN_DUE is read while the item is still blocked, so the step is assigned the moment it is
filed or labelled; once assigned, the gate hands it off on the first tick its holds have all
closed. The note reads `assign @a @b (role:infra)`, and the `--json` line carries an
`assign` list. A role resolved to teams only assigns nobody, so its item goes straight to its
holds and then HANDOFF_DUE.

The hand-off mentions every assignee and every team its roles resolve to: HANDOFF_DUE's note
reads `for @a @example-org/legal`, and HANDOFF_DUE's and WITH_PERSON's `--json` lines carry a
`teams` list next to `assignees` (which may now be empty). A done report still counts from an
assignee or a trusted author (D-16): a team member who is an organization member is a MEMBER,
so their `done` counts; an outside team member's does not.

**What NO_ASSIGNEE becomes.** With no `--role maintainer=` flag (an older gate, or a session
that didn't pass the flags), the script knows no maintainer, and an unassigned person's item
reads NO_ASSIGNEE as spec 017 says, `role:<name>` items included. With the flag, which the
gate always passes, NO_ASSIGNEE is never read: the maintainer always resolves to a user. So
NO_ASSIGNEE is left for "the roles weren't given", and needs-decision is never asked who does
a step.

### Existing `human` items

Nothing is relabelled. `human` stays a person's item and reads as `role:maintainer`, so an
existing assigned `human` item reads exactly as before, and an unassigned one reads
ASSIGN_DUE on the gate's next tick and is assigned to the maintainer. Skills file new items
with `role:<name>` only; `human` is read, not written.

`skills/github-ship-watch/scripts/watch_state.py`'s `TRIAGE_ACTION` gains ASSIGN_DUE, and its
WITH_PERSON row lists the teams after the assignees. `src/shipmill/status.py` lists
ASSIGN_DUE to triage and accepts a WITH_PERSON line whose `assignees` is empty when it has
`teams`. `triage_state.py` exits 1 on ASSIGN_DUE.

### Chains

`skills/github-issue-triage/scripts/chains.py` treats a `role:<name>` item as a person's item
like a `human` one. `chains.py show` can't read another repo's roles, so its executor column
reads `person: @login,...` from the assignees as today, and `role:<name>` for a person's item
with none.

### Choosing the role when filing

A session filing a step only a person can do (`skills/github-issue-triage/references/spec-gate.md`,
A step only a person can do) runs `shipmill roles`, picks the role whose name fits the step,
labels the issue `role:<name>`, and assigns that role's users at once; with no role that
clearly fits, `role:maintainer`. A team-only role is labelled and left unassigned: the
hand-off mentions the team. It never asks who does it.

### Setup and docs

`skills/shipmill-setup/scripts/setup_state.py` wants `role:maintainer` wherever it wants
`needs-decision`, and `role:<name>` for each role `[agents.roles]` defines (read as it reads
the rest of the config, tomllib on 3.11+ and its fallback on 3.10); it still wants `human` for
the items that carry it. `skills/shipmill-setup/SKILL.md` documents `[agents.roles]` and
creates the labels.

`skills/github-issue-triage/SKILL.md` (Chains), `references/triage-rubric.md` (A person's
item and its flags table), `references/comments.md` (A person's item: the hand-off mentions
teams), `references/spec-gate.md`, and `references/needs-decision.md` describe role labels,
ASSIGN_DUE, the fallback, and the filing rule; `docs/flow.md` and `docs/install.md` call the
item a role's item.

## Acceptance criteria

- S-036-1: a config whose `[agents.roles]` maps role names to arrays of logins and `@org/team` entries loads, and `shipmill roles --json` prints each role's `users`, `teams`, and `fallback`, with `maintainer` present even when the table doesn't name it
- S-036-2: `shipmill doctor` and `shipmill roles` exit 2 naming `[agents.roles]` and the key when `roles` isn't a table, a role name is outside the pattern, a value isn't an array of strings (an inline table's message saying agent-filled roles aren't supported yet), a filler is neither a login nor `@org/team`, a login ends `[bot]`, a filler is listed twice in one role, or `maintainer` lists only teams
- S-036-3: a role set to `[]` resolves to the maintainer's fillers and `shipmill roles` marks it `fallback`
- S-036-4: with `maintainer` unset or empty, the maintainer resolves to the host's `gh api user` login; with it unset and the login unreadable, `shipmill roles` exits 2
- S-036-5: `shipmill gate` passes one `--role` flag per resolved role, `maintainer` included, to `watch_state.py`, which passes them to `triage_state.py`; `shipmill status` passes them too; and the session prompt carries the line telling the session to pass them
- S-036-6: `triage_state.py` exits 2 naming `--role` for a malformed role name or filler, an empty filler list, a name given twice, or `--role` flags with no `maintainer`
- S-036-7: an open issue labelled `role:<name>` is a person's item exactly as a `human` one: it counts as triaged with no triage comment, reads no PR state, follows HANDOFF_DUE, WITH_PERSON, VERIFY_DUE, and VERIFY_CLOSED, and `--wip` doesn't count it
- S-036-8: with `--role maintainer=a`, an unassigned person's item whose roles resolve to a user reads ASSIGN_DUE, even while a hold is open, with the note `assign @a (role:<name>)` and an `assign` list in `--json`, and `triage_state.py` exits 1
- S-036-9: an unassigned `human` item reads ASSIGN_DUE naming the maintainer's users, and an assigned `human` item reads as it did before this spec
- S-036-10: a `role:<name>` label no `--role` flag gives resolves to the maintainer's fillers and the note says `role:<name> undefined`; two role labels resolve to the union of their fillers
- S-036-11: an unassigned item whose roles resolve to teams only never reads ASSIGN_DUE; it reads HANDOFF_DUE once its holds close, with the team in the note and a `teams` list in `--json`, then WITH_PERSON with an empty `assignees` and the `teams` list
- S-036-12: with no `--role` flags, an unassigned `human` or `role:<name>` item reads NO_ASSIGNEE; with `--role maintainer=...`, no item reads NO_ASSIGNEE
- S-036-13: `watch_state.py` counts ASSIGN_DUE as a triage action and lists a WITH_PERSON item's teams; `shipmill status` lists ASSIGN_DUE to triage and reads a team-only WITH_PERSON line without error
- S-036-14: `chains.py show` lists a `role:<name>` item as a person's item, its executor `person: @login,...` from its assignees or `role:<name>` when it has none
- S-036-15: `setup_state.py` reports `role:maintainer` missing wherever it reports `needs-decision` missing, and `role:<name>` missing for each role `[agents.roles]` defines, and still reports `human`
- S-036-16: github-issue-triage's SKILL.md, triage-rubric.md, comments.md, spec-gate.md, and needs-decision.md describe role labels, ASSIGN_DUE, the maintainer fallback, the team mention, and filing a step with `role:<name>` assigned at once; shipmill-setup's SKILL.md documents `[agents.roles]` and its labels

## Out of scope

- A role filled by an agent: how it receives a hand-off (a gate session with another prompt, another App, or another repo's gate) is a design of its own, with its own trust question (D-16) and identity (D-14). The config refuses an inline table now, so the shape stays free for that spec
- Whom a needs-decision question mentions: it stays the host's gh login (spec 005); with `maintainer` unset the two are the same person
- Items already parked on needs-decision with spec 017's "who does it" question: they read NEEDS_DECISION first, and the maintainer answers or removes the label as today
- Checking that a listed user can be assigned or a team exists in the repo's organization: GitHub refuses the assignment, and the session asks then
- Relabelling existing `human` items, or deprecating the label: it stays readable
- A description per role to guide the choice: role names are the guide until filing picks wrong
- Reminders for a role's item: one mention per unblock, as spec 017 chose (#335)

## Decisions relied on

- D-3
- D-4
- D-14
- D-16
- D-19
- D-21
- D-37

## Issues

- shipmill/shipmill#638: S-036-1, S-036-2, S-036-3, S-036-4
- shipmill/shipmill#639: S-036-6, S-036-7, S-036-8, S-036-9, S-036-10, S-036-11, S-036-12
- shipmill/shipmill#640: S-036-5, S-036-13
- shipmill/shipmill#641: S-036-14
- shipmill/shipmill#642: S-036-15
- shipmill/shipmill#643: S-036-16

## Verification
