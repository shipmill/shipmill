# S-030: A decision policy

status: draft
serves: G-1

## Problem

An agent's right to decide is spread over six places, and none of them says which
decisions are the agent's (shipmill/shipmill#486):

- `[autonomy]` sets observe, propose, or act for the release side's stages: release,
  deploy, rollback, intake, and upgrade (`src/shipmill/autonomy.py`)
- The needs-decision protocol (D-21) says how a gate session asks, not when
- The design gate asks on a departure from a `D-n`, on two designs users would tell
  apart, and on a breaking change; the spec gate makes a merged spec the approval
- `pr_gate.py` hard-codes D-34: a pull request that edits `docs/product.md` waits on the
  maintainer, as does one matching a `REVIEW.md` Protected areas glob (spec 024)
- The delivery hooks (spec 026, D-40) refuse a handful of irreversible writes
- D-10 keeps accepting an opportunity with the maintainer; D-39 keeps a breaking stable
  release with a person's hand start

Everything else is left to the session's judgment, so an agent that is unsure asks. On
2026-10-18 the maintainer settled 9 questions across specs 025 to 029 and pull requests
#429, #434, #435, and #436, and every one was settled by taking the agent's
recommendation; the one override was about the maintainer's own repositories. Each such
question costs a gate tick and a human step, against G-1: a connected repository goes from
a new issue to an announced release with no human step but the maintainer's decisions.

This spec makes those decisions an explicit, checkable list. Every decision an agent meets
falls in a **zone** with a stable id, and each zone has one **level**: the agent decides,
decides and tells, asks, or never decides. shipmill ships the zones and their defaults; a
repo's maintainer changes the levels. N-3 stays: what is the maintainer's is written down,
and a level change is the maintainer's own decision.

The maintainer asked for this in chat on 2026-10-19. The levels below are proposals: the
maintainer settles them when approving this spec, and a `D-n` records the result.

## Behaviour

### Levels

Four levels, ordered from the least to the most human involvement:

| Level | The agent | Recorded as | Waits |
|---|---|---|---|
| `act` | decides and goes on | the work's own history: the commit, the pull request's plan, the triage comment | no |
| `notify` | decides, says so on the item, and goes on; the maintainer may veto | a `decided` marker comment and the `decided` label, or a `D-n` when the decision sets a rule | no |
| `ask` | asks with the needs-decision protocol and leaves the item | the needs-decision question and its answer | yes, until a trusted reply |
| `never` | may prepare the change (an issue, a pull request, a draft) but never takes the decision: never merges, accepts, closes, or answers it, even when the maintainer approves in chat | the item assigned to the maintainer | yes, until the maintainer acts by hand |

When a decision falls in several zones, the strictest level among them applies. A session
that can't place a decision in a zone treats it as the zone `unknown`.

### Zones

Zones are ordered by reversibility first: a one-way door (a published contract, a release
users installed, a direction others plan against) sits above a two-way door (an internal
design a later pull request can change). Blast radius, how many people a wrong decision
reaches, orders zones of the same reversibility.

| Zone | Covers | Default | Floor | Code detects |
|---|---|---|---|---|
| `direction` | an edit of `docs/product.md` or `docs/product/`: the mission, users, goals, non-goals, quality bar (D-34) | `never` | `ask` | a changed path |
| `decision-policy` | the `[decisions]` section of `.github/shipmill.toml` | `never` | `never` | a changed key in that section |
| `scope` | accepting or declining an opportunity (D-10), approving a spec, accepting a goal plan (spec 028), creating or editing a milestone | `ask` | `ask` | a spec whose status line becomes `approved`; the `planned` label |
| `rule-departure` | a change that departs from an active `D-n` or an approved spec's `S-NNN-k` (Q-5) | `ask` | `ask` | candidates only: `decisions.py find` on the changed paths |
| `contract-change` | changing or removing a command, flag, argument, exit code, env var, output or file format, default, limit, public API, or stored state an upgrade reads | `ask` | none | an added changelog entry under a `major` heading of `[bump]` |
| `contract-addition` | adding one of those while every existing use behaves as before; a new runtime dependency | `notify` | none | no |
| `security` | `.github/**` (workflows, CODEOWNERS, the config outside `[decisions]`), a secret or credential, a token's or a workflow's permissions, the delivery hooks' rules, the gate's tool allowlist | `ask` | `notify` | a changed path |
| `protected` | a file matching a `REVIEW.md` Protected areas glob (spec 024) | `ask` | none | a changed path |
| `interpretation` | choosing between readings of an approved spec, a `D-n`, or an issue, where each reading meets the criteria | `notify` | none | no |
| `triage-verdict` | won't fix, duplicate, postpone, or close as done on an issue | `notify` | none | no |
| `implementation` | work order, how a change splits into pull requests, internal design, refactors, tests, docs of existing behaviour | `act` | none | no |
| `unknown` | a decision no other zone covers | `ask` | `ask` | no |

The release side's stages keep their levels in `[autonomy]` (below) and appear in
`shipmill decide levels` as zones that `[decisions]` can't set:

| Zone | Set by | Level for agents |
|---|---|---|
| `release` | `[autonomy] release` | `act` for `act`, `ask` for `propose` (the proposal issue is the question), none for `observe` |
| `breaking-release` | D-39, fixed | `ask`: a trigger only proposes, and the decision is a person's hand start that an App's run can't make |
| `deploy`, `rollback`, `intake`, `upgrade` | `[autonomy]` | mapped as `release` is; `intake` is never `act` (D-10) |

A zone's id is part of the contract: config keys, markers, and the retro's counts name it.
A new zone gets a new id; an id is never renamed or reused.

### The config

A new optional section of `.github/shipmill.toml` (D-4), parsed by `src/shipmill/policy.py`
into a `DecisionPolicy` in a new `src/shipmill/decide.py`:

```toml
[decisions]
veto_hours = 24                   # the notify window, 1 to 168 (default 24)
contract-addition = "act"         # a zone id = a level; an absent zone keeps its default
triage-verdict = "ask"
```

Each key besides `veto_hours` is a zone id and each value a level. The parse exits 2,
naming the key and the fix (Q-1), when:

- a key is no zone id: it lists the zone ids
- a value is not `act`, `notify`, `ask`, or `never`
- a level is below the zone's floor: `direction = "act" is below its floor ask: only the
  maintainer changes the direction (D-34)`
- the key is `decision-policy`, whatever its value: it is fixed at `never`
- the key is a release-side zone: `release is set in [autonomy] release`; for
  `breaking-release`, `a breaking stable release waits for a person's hand start (D-39)`
- `veto_hours` is not an integer from 1 to 168

Without the section every zone has its default. `[decisions]` in a config without
`[agents]` parses and is read by nothing; `doctor` warns about it.

### `[autonomy]` stays as it is

`[autonomy]` keeps its keys, defaults, and readers (the planner, `shipmill operate`,
product intake, `shipmill upgrade`), which run in CI without any agent (Q-6). `[decisions]`
is read by agent sessions and the tools they use. The two meet in one place, `shipmill
decide levels`, which shows the release-side zones mapped from `[autonomy]` beside the
agent zones. No existing config changes, so no spec 014 upgrade is needed.

### `shipmill decide`

A new command group in `src/shipmill/cli.py`:

- `shipmill decide levels [--repo DIR] [--ref REF] [--json]` prints every zone with its
  level, its floor, and where the level comes from (`default`, `config`, `autonomy`, or
  `fixed`), reading the config in the working tree, or at `REF` when given. JSON:
  `{"veto_hours": 24, "zones": [{"zone", "level", "floor", "source"}]}`
- `shipmill decide classify [--repo DIR] [--ref REF] (--pr N | --files PATH ...) [--json]`
  prints the zones code detects for a change, each with its level and the reason, the
  strictest level among them, and the `D-n` candidates. With `--pr N` it reads the pull
  request's files and diff through `gh`; with `--files` it reads paths only, so the
  changelog and status-line rules don't apply. The levels come from the config at `--ref`
  (default `origin/HEAD`), never from the change itself, so a pull request that edits
  `[decisions]` is judged by the levels it would replace. JSON: `{"level", "zones":
  [{"zone", "level", "reason"}], "candidates": [{"decision", "title"}]}`; no detected zone
  gives `"level": null` and an empty list

Code detects these zones from a change:

- `direction`: a path equal to `docs/product.md` or under `docs/product/`
- `decision-policy`: `.github/shipmill.toml` whose `[decisions]` table differs between the
  base and the head, compared parsed, so a comment or a reorder elsewhere doesn't count
- `security`: any other path under `.github/`
- `protected`: a path a `REVIEW.md` Protected areas glob on the base covers, matched as
  `pr_gate.py` matches today
- `scope`: a `docs/specs/*.md` whose status line reads `approved` at the head and not at
  the base
- `contract-change`: an added line under a heading the config's `[bump] major` lists, in
  the changelog or a new fragment (spec 013)

`decisions.py find` on the changed paths gives the candidates: a `D-n` whose "Applies to"
covers the change. Code can't tell a departure from a change that keeps the rule, so a
candidate is not a zone; the session checks it, and calls the change a `rule-departure`
when it departs or when it can't tell.

Exit codes: 0 printed; 2 a malformed config, a ref the checkout lacks, or a `gh` failure.

### How a session decides who decides

Every agent session in a repo whose config has `[agents]`, gate session or not, places a
decision before it takes it. `skills/github-issue-triage/references/needs-decision.md`
gains a first section, "Who decides", that the other skills point to:

1. **Code first.** For a change on a branch or a pull request, run `shipmill decide
   classify`. Its zones hold whatever the session thinks of them
2. **Then the model.** For each decision code doesn't see (a verdict, a reading of a
   spec, a contract addition, a candidate `D-n`), pick the zone from the table. When two
   zones could fit, pick the one with the stricter level; when none fits, `unknown`
3. **The strictest level wins**, and the session follows it:
   - `act`: go on
   - `notify`: post the decided comment (below) and go on
   - `ask`: post the needs-decision question, as today, and leave the item
   - `never`: prepare what helps (a pull request, an issue with the evidence), assign it
     to the maintainer, label it `human` (a person's item, spec 017), say in one comment
     what the maintainer does by hand, and leave it. A reply never moves it: no answer in
     the session or on GitHub lets the agent take the step

A session a person started by hand still asks in the session for `ask`, as today; `never`
holds there too, even when the person says yes.

The needs-decision question gains the zone on its second line, so the retro can count asks
per zone; the first line stays the marker the scripts read:

```markdown
<!-- shipmill:needs-decision -->
<!-- shipmill:zone scope -->
@<login> Decision needed: ...
```

The session that takes up an answer edits that line to `<!-- shipmill:zone scope
answer=recommended -->`, or `answer=other` when the reply picked another option or its own
words.

The skills that decide today point to "Who decides" in place of their own rules:
`references/design-gate.md` step 3 ("Decide who decides"), `references/spec-gate.md` (a
spec's approval is `scope`), `references/comments.md` (the verdicts that are
`triage-verdict`), `skills/github-issue-resolve/SKILL.md` (product decisions and spec
departures), `skills/github-pr-triage/SKILL.md` and `references/implementer-brief.md`
(each item of "Decisions for you" names its zone), and `skills/product-intake/SKILL.md`
(accepting is `scope`).

### A `notify` decision and its veto window

The session posts one comment on the item the decision belongs to, through
`--body-file`, and adds the `decided` label:

```markdown
<!-- shipmill:decided zone=interpretation until=2026-10-20T14:00:00Z -->
@<login> Decided without waiting: <the decision, one sentence>

Why: <one or two sentences, naming the D-n or S-NNN-k it rests on>
Not taken: <the other option, and what it would have meant for users>

Reply with a comment starting with `veto` before 2026-10-20 14:00 UTC to reverse it,
adding what you want instead if you like. A later veto still counts and gets a follow-up.
```

`until` is the post time plus `veto_hours`, in UTC. `<login>` is the person the gate's
prompt names, as for a needs-decision question, so GitHub notifies them.

**The work doesn't wait.** The session goes on at once, and a pull request carrying a
`notify` decision merges when it is otherwise ready, inside the window too.

**A rule goes to the log.** When the decision sets something later work must respect (a
format chosen for a new output, a reading of a criterion the next pull request relies on),
the session also records it with `decisions.py add --zone <id>`, which writes a `- Zone:
<id> (notify, veto until <until>)` line under the entry; `decisions.py check` accepts
that field and refuses a zone id it doesn't know. One decisions pull request per pass
still holds (design-gate.md). A decision that sets no rule is recorded by the comment
alone.

**A veto** is a comment newer than the decided marker, by an OWNER, MEMBER, or
COLLABORATOR other than the `--bot-login`, whose first word is `veto` in any case. An
outsider's comment never counts (D-16), and neither does a marker or a veto in the
middle of a comment. `skills/github-issue-triage/scripts/triage_state.py` reads an item
labelled `decided` with a veto that no newer `<!-- shipmill:veto-handled -->` comment by
the bot answers as `VETOED`: an action, read right after `DECIDED` and before any other
state. It reads closed issues labelled `decided` too, those updated in the last 14 days,
since a veto comment updates the item; a closed issue reads `VETOED` or nothing.
`skills/github-ship-watch/scripts/watch_state.py` lists `VETOED` issues and pull
requests, open, closed, or merged, in a `VETOED` row that counts as work, so the gate
starts a session on the next tick.

The session that takes up a veto:

1. Reads it. When it says what to do instead, that is the maintainer's decision: do it.
   When it doesn't, the decision moves to `ask`: post the needs-decision question with the
   options, the vetoed one last
2. Undoes what it can. Not landed (a pull request open, an issue still open): revise or
   close the pull request, restore the issue's labels. Landed: open a revert pull request
   for a merged change (`implementation`, its plan citing the veto), reopen a closed issue.
   A release already published is never unpublished: file a follow-up issue to fix
   forward
3. Supersedes the `D-n` it recorded, if any, with `decisions.py add --supersedes`, the
   veto's comment as the source
4. Posts `<!-- shipmill:veto-handled zone=<id> -->` as the first line of a comment saying
   what it did, and removes the `decided` label

Without a veto the label stays, as the record the retro counts.

### `never` and `ask` in the merge gate

`skills/github-pr-triage/scripts/pr_gate.py` replaces its hard-coded direction check with
`shipmill decide classify --pr N --ref <the base it reads> --json`, run from PATH or
through `uvx` as the hooks run it, in a checkout whose config has `[agents]`:

- A `never` zone makes the pull request `MAINTAINER_ONLY`, a new verdict with exit 7,
  printed as `  maintainer-only: <zone>: <reason>`. `--maintainer-accepted` doesn't lift
  it: the maintainer merges it by hand. It ranks above `NEEDS_DECISION` and below
  `REFUSED`
- An `ask` zone makes it `NEEDS_DECISION` (exit 5), as the direction and protected areas
  do today, until `--maintainer-accepted`
- A `notify` zone leaves the verdict as it is and prints `  notify: <zone>: <reason>`; the
  skill posts the decided comment before it merges, unless one for that zone is already on
  the pull request
- Without `[agents]` in the base's config, `pr_gate.py` judges as it does today

`shipmill gh` (`src/shipmill/app_gh.py`), the only way a session writes when the config
sets `[agents] app_id` (D-40), refuses to merge a pull request whose classification has a
`never` zone: `shipmill gh pr merge <n>` and a `shipmill gh api` `PUT` to
`repos/<owner>/<repo>/pulls/<n>/merge` exit 2 naming the zone and saying the maintainer
merges it by hand. Approval in chat changes nothing, since the tool doesn't read the chat.
A repo without an App has only the skills and `pr_gate.py` between an agent and such a
merge, and `doctor` says so.

### The retro counts per zone

`skills/github-ship-watch/scripts/retro.py gather` gains `--decisions`, which reports per
zone over the retro's window: `notify` decisions (decided markers by the bot), vetoes
(veto-handled markers), asks (needs-decision questions with a zone line), and asks
answered with the recommended option. Two flags set when it proposes a change, as spec
027's thresholds are flags and not policy keys:

- `--raise-at N` (default 2): a zone at `notify` with N vetoes or more in the window is
  proposed one level up, to `ask`
- `--lower-after N` (default 4): a zone at `ask` whose questions over the last N windows
  number at least 5 and were all answered with the recommended option is proposed one
  level down, to `notify`; a zone at its floor is never proposed lower

The Weekly retro section of `skills/github-ship-watch/SKILL.md` adds a Decisions table to
its tracking comment and opens each proposal as an issue titled `Decision policy: <zone>
from <level> to <level>`, deduplicated with `retro.py dedupe`. The retro never edits
`[decisions]`, and a pull request that does is `decision-policy`, which only the
maintainer merges.

### `doctor` and setup

`src/shipmill/doctor.py`, for a config with `[agents]`, adds a `decisions` block:

- One PASS line per zone with its level and source, and the veto window
- WARN for each zone set below its default, naming both levels, so a lowered level is
  visible in every report
- WARN when `[agents] app_id` is unset: `never` holds by the skills and `pr_gate.py` only,
  since `shipmill gh` refuses the merge only for an App
- WARN when the repo lacks the `decided` label
- For a config without `[agents]`, WARN when it has `[decisions]`, which nothing reads

`skills/shipmill-setup/scripts/setup_state.py` adds `decided` to the labels it wants when
the config has `[agents]`, so `LABELS_MISSING` names it. A session that finds the label
missing creates it with `shipmill gh label create decided` before its first decided
comment. `skills/shipmill-setup/SKILL.md` shows the zone table and asks the maintainer
whether any level should differ from the default before it reports the agent side
connected.

### Upgrading

The section is optional, so no config fails and no spec 014 upgrade is needed. Three
things change for a repo with `[agents]` on the release that ships this spec, and the
changelog says so under `Changed`:

- An agent's pull request that edits `docs/product.md` or `docs/product/` is
  `MAINTAINER_ONLY` instead of `NEEDS_DECISION`. A maintainer who wants today's behaviour
  sets `direction = "ask"`
- Won't fix, duplicate, postpone, and close verdicts, and readings of a spec, carry a
  decided comment and the `decided` label
- An additive contract change goes on with a decided comment, where the design gate
  dispatched it with only the design in the triage comment

### Docs

- `docs/flow.md` gains a "Who decides" section with the zone table and the levels
- `README.md` names the policy where it describes what the maintainer keeps
- `docs/release-lanes.md` points to it from `[autonomy]`, for the mapping

## Acceptance criteria

- S-030-1: `Policy.parse` of a config without `[decisions]` gives every zone its default level from the zone table and `veto_hours` 24
- S-030-2: `Policy.parse` exits 2 naming the key and listing the zone ids for an unknown key in `[decisions]`, and naming the four levels for a value that isn't one
- S-030-3: `Policy.parse` exits 2 naming the floor for `direction = "act"`, `scope = "notify"`, `rule-departure = "notify"`, `security = "act"`, and `unknown = "notify"`, and accepts `direction = "ask"`
- S-030-4: `Policy.parse` exits 2 for a `decision-policy` key of any value, for `release`, `deploy`, `rollback`, `intake`, and `upgrade` naming `[autonomy]`, for `breaking-release` naming D-39, and for `veto_hours` of 0, 169, or a non-integer
- S-030-5: `shipmill decide levels --json` prints every zone with `level`, `floor`, and `source`, where a zone the config sets reads `config`, an absent one `default`, `decision-policy` and `breaking-release` `fixed`, and the release-side zones `autonomy` with `act` for `act`, `ask` for `propose`, and no level for `observe`
- S-030-6: `shipmill decide classify --files docs/product.md` reports `direction` at `never`; `--files docs/product/goals.md` the same; `--files .github/workflows/ci.yml` reports `security` at `ask`; `--files src/x.py` reports no zone and `"level": null`
- S-030-7: `shipmill decide classify --pr N` reports `decision-policy` when the pull request changes a key under `[decisions]`, `security` and not `decision-policy` when it changes only another section of `.github/shipmill.toml`, and neither for a change of a comment in `[decisions]`
- S-030-8: `shipmill decide classify --pr N` reports `scope` for a spec whose status line becomes `approved`, `contract-change` for a changelog line or fragment added under a heading the `[bump] major` list names, and `protected` for a path a base `REVIEW.md` Protected areas glob covers
- S-030-9: `shipmill decide classify` reads the levels from the config at `--ref` (default `origin/HEAD`), so a pull request that sets `direction = "ask"` is still classified `never` for its edit of `docs/product.md`
- S-030-10: `shipmill decide classify --pr N --json` lists under `candidates` each active `D-n` whose "Applies to" covers a changed path, and never as a zone
- S-030-11: `pr_gate.py` on a pull request with a `never` zone, in a checkout whose base config has `[agents]`, prints `MAINTAINER_ONLY` with a `maintainer-only:` line naming the zone and exits 7, with or without `--maintainer-accepted`
- S-030-12: `pr_gate.py` on a pull request with an `ask` zone and no `never` zone exits 5 without `--maintainer-accepted` and judges CI alone with it; with only a `notify` zone it keeps the CI verdict and prints a `notify:` line; without `[agents]` in the base config its output for a `docs/product.md` edit is what it was before this spec
- S-030-13: `shipmill gh pr merge <n>` and `shipmill gh api -X PUT repos/<o>/<r>/pulls/<n>/merge` exit 2 without running `gh` when pull request `n` has a `never` zone, naming the zone and the maintainer's hand merge, and run `gh` as before for a pull request without one
- S-030-14: `triage_state.py` reads an issue labelled `decided` whose bot decided marker is followed by a comment from a COLLABORATOR starting `Veto` as `VETOED`, an action read after `DECIDED`; a comment starting `veto` from a CONTRIBUTOR, a `veto` in the middle of a comment, or a newer bot `<!-- shipmill:veto-handled -->` comment leaves it in its usual state
- S-030-15: `triage_state.py` reads a closed issue labelled `decided` and updated in the last 14 days as `VETOED` when it holds an unanswered trusted veto, and reports nothing for it otherwise
- S-030-16: `watch_state.py` lists `VETOED` issues and pull requests, open, closed, or merged, in a `VETOED` row that counts as work, and leaves an item labelled `decided` without a veto out of every work row
- S-030-17: `decisions.py add --zone interpretation` writes a `- Zone: interpretation (notify, veto until <time>)` line; `decisions.py check` accepts an entry with it and fails one whose `Zone:` names no zone id
- S-030-18: `retro.py gather --decisions` reports per zone the window's decided markers, veto-handled markers, zoned needs-decision questions, and those whose zone line reads `answer=recommended`, and proposes `<zone> from notify to ask` at `--raise-at` vetoes and `<zone> from ask to notify` only when every question over `--lower-after` windows, at least 5, was answered `recommended`, never for a zone at its floor
- S-030-19: `shipmill doctor` on a config with `[agents]` prints a `decisions` block with one PASS line per zone, WARNs for each zone set below its default, for an unset `[agents] app_id`, and for a missing `decided` label; on a config with `[decisions]` and no `[agents]` it WARNs that nothing reads the section
- S-030-20: `setup_state.py` reports `LABELS_MISSING` naming `decided` for a config with `[agents]` whose repo lacks it, and doesn't want the label without `[agents]`
- S-030-21: `skills/github-issue-triage/references/needs-decision.md` opens with "Who decides", giving the code-first then model order, the strictest-level rule, `unknown` for a decision no zone covers, the four paths, the zone line under the needs-decision marker, the decided comment format, and the veto take-up steps; `design-gate.md`, `spec-gate.md`, `comments.md`, github-issue-resolve's, github-pr-triage's, and product-intake's SKILL.md point to it for who decides
- S-030-22: The eval suite (spec 025) holds cases where a session meets an `implementation` decision and goes on without a question, an `interpretation` decision and posts a decided comment and goes on, a `contract-change` and asks, and an approved `never` change in chat and still leaves the merge to the maintainer

## Out of scope

- Absorbing `[autonomy]` into `[decisions]`: the release side runs without agents (Q-6);
  if the maintainer chooses to absorb it, a spec 014 upgrade and the D-32 deprecation path
  come in a later spec
- A hook rule that classifies a merge: `shipmill gh` is the one write path with an App
  (D-40), so the refusal lives there; a repo without an App relies on `pr_gate.py`
- Per-path or per-label levels inside a zone (`contract-addition` at `act` for one
  module): a later spec, once the retro shows a zone that needs it
- Changing a level by itself: the retro proposes, the maintainer edits `[decisions]` and
  merges it by hand
- GitHub branch protection or rulesets that enforce `never` on the forge: the
  maintainer's settings, not shipmill's
- The cost of a decision in tokens or time (spec 023, deferred)
- Decisions outside the delivery loop (N-4)

## Decisions relied on

- D-4: `[decisions]` lives in `.github/shipmill.toml`
- D-10: accepting an opportunity is the maintainer's, so `scope` has the floor `ask` and `intake` is never `act`
- D-14: decided and veto-handled comments are written as the App
- D-16: only an OWNER, MEMBER, or COLLABORATOR's veto counts
- D-21: the `ask` level is the needs-decision protocol, unchanged but for the zone line
- D-29: a trusted marker comment is the model for the decided and veto-handled markers
- D-34: only the maintainer changes the direction, the zone `direction`
- D-39: a breaking stable release waits for a person's hand start, the fixed zone `breaking-release`
- D-40: `shipmill gh` is the write path with an App, where the `never` merge refusal lives

## Issues

## Verification
