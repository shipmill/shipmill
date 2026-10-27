# GitHub issue-to-ship flow

Three skills cover the path from a new issue to a published release, and a fourth watches it, in any GitHub repo with the `gh` CLI:

| Skill | Job |
|---|---|
| `product-intake` | Feedback: groups requests and discussions, including the ones triage hands over, into opportunity issues the maintainer accepts or declines |
| `github-issue-triage` | The backlog: a verdict on every issue (implement, feature, postpone, clarify), comments and labels, one PR per fix; a user's request for a new capability goes to product intake |
| `github-issue-resolve` | One issue in depth: verify, fix with a regression test, open a PR |
| `github-pr-triage` | Landing: review, CI gate, rebase, merge, and the release |
| `github-ship-watch` | The routine: a stuck release run, a missing upload, unannounced fixes, waiting issues |

Before the first release, a new package goes through `shipmill-setup`: package checks, CI and publish wiring, and shipmill's release policy. In a repo that runs shipmill (`.github/shipmill.toml`), shipmill tags; the skills here only start its Release workflow and never tag by hand. The `oss-package-engineer` skill is retired: its release path is github-pr-triage's "tag X" or shipmill, and its package checks live in shipmill-setup.

Start each one with its slash command or with plain wording. The words you use set how far it goes. Below, `<owner/repo>` is the GitHub repo, `<X>` the version to release, and `<prev>` the previous tag.

## Everything in one message

```
/shipmill:github-issue-triage <owner/repo> — triage the new issues, merge the PRs when they're green, then tag <X>
```

- **"triage"** runs github-issue-triage: verdicts, comments and labels, and a PR for each "implement"
- **"merge when green"** hands the PRs to github-pr-triage, which merges each one only when every CI job passes
- **"tag X"** adds the release: readiness check, tag, registry check, and the "Released in" notices on fixed issues

Plain wording works the same, and the repo can be left out inside its checkout: "triage the new issues, merge when green, then tag 2.4.0".

## One stage at a time

`$S` below is the `skills` folder of this repo; run the scripts with `uv run --no-project python` or plain `python3` (3.10+).

| Stage | Say | Stops at |
|---|---|---|
| Status only | `python3 $S/github-issue-triage/scripts/triage_state.py <owner/repo>` | A list of each issue's state; nothing changes |
| Feedback status | `python3 $S/product-intake/scripts/intake_state.py <owner/repo>` | Each opportunity's state and the requests no opportunity groups yet; nothing changes |
| Group feedback | `/shipmill:product-intake <owner/repo>` or "group the feature requests" | Opportunity issues opened or updated; the accept or decline is yours |
| Triage the backlog | `/shipmill:github-issue-triage <owner/repo>` or "triage the new issues" | Comments, labels, and open PRs; nothing merged |
| One issue | `/shipmill:github-issue-resolve 57` or "fix #57" | One PR and the issue comment |
| Triage one issue only | "triage #57, don't fix" | The verdict comment |
| Review PRs | `/shipmill:github-pr-triage` or "review open PRs" | Verdicts and local fixes, no pushes |
| Merge | "merge #75" or "merge the PRs when they're green" | Merged on green CI |
| Release | "tag <X>" | Readiness check, tag, publish, notices |
| Tell reporters only | `python3 $S/github-pr-triage/scripts/shipped.py <owner/repo> <prev> <tag> --install '<install cmd>'` | Prints the plan; add `--post` to comment |
| Release check only | `python3 $S/github-pr-triage/scripts/release_ready.py <owner/repo> <sha> <X>` | A pass/fail report |

## Other stacks

| Situation | Flag |
|---|---|
| Version in a file other than `pyproject.toml`, `Cargo.toml`, or `package.json` | `release_ready.py --manifest <file>` |
| Version only in the tag (Go) | `release_ready.py --no-manifest` |
| No Keep a Changelog file | `release_ready.py --no-changelog` |
| Tags aren't `vX.Y.Z` (CalVer, `release-1.2`) | `triage_state.py --stable-tag-regex '<regex>'` |
| Triage comments use another prefix, or deferrals another label | `triage_state.py --marker '<prefix>' --postponed-label <label>` |

The bump, registry, and install commands per ecosystem (Python, Node, Rust, Go, none) are in `github-pr-triage/references/landing.md`, under Ecosystems. GitLab and other hosts aren't supported: every script calls `gh`.

## Plan, goal, and release policy

Three layers decide what ships when. Each lives in its own place and has its own writer, and they meet at one point: a milestone's title is the version it releases as.

| Layer | Answers | Where it lives | Written by | Read by |
|---|---|---|---|---|
| Release policy | When each lane releases, and what holds it | `[lanes.*]`, `[gates]`, `[bump]`, `[environments]` in `.github/shipmill.toml` | The maintainer, first through `shipmill-setup` | `src/shipmill/policy.py` (validates), `src/shipmill/planner.py` (decides), `src/shipmill/ticks.py` (the cron); run by the Release workflow (`release.yml` → `prepare.yml`, `land.yml`) |
| Plan | What a version must hold | GitHub milestones, one per future version: the maintainer's milestones, their own list of the issues that version needs | The maintainer, by hand (D-32); no skill proposes, ranks, or creates one | A lane with `milestone = true`; triage, which works through a milestone's issues |
| Goal | What makes a milestone's version | The feature issue in the milestone, the spec `docs/specs/NNN-*.md` its body links (criteria, build issues, status), and the build issues | `github-issue-triage` (spec gate, split); implementers; the spec reaches `status: built` once its criteria are verified | Triage (holds and chains) |

```
the maintainer ──lists───► milestone "1.5.0" ◄── feature issue ──links──► docs/specs/NNN-*.md
                                   ▲                                          │
                                   │ looked up by version name                └─ build issues ─► PRs ─► main
[lanes.stable] milestone = true ───┘                                                                     │
        └── planner: due when milestone "1.5.0" has no open issues ── cuts 1.5.0 from main (or its rc) ◄─┘
```

- **The name is the link.** A lane with `milestone = true` looks up the milestone titled with its candidate's version, so the maintainer names a milestone after the version it should release as
- **The due date doesn't release anything.** Only the lane's triggers and gates cut a release
- **Only the milestone lane waits on the plan.** Other triggers (`quiet_minutes`, `schedule`, by hand) release what is merged, so `dev`, `rc`, and fixes never wait for a goal; a stable release cut by them can take a milestone's version before its goal is done
- **Today a milestone is done when it has no open issues** and at least one closed (`planner.py`), which says nothing about whether its spec is built
- **Above all three sits the product's direction**, `docs/product.md`: its goals (`G-n`) decide whether new behaviour is built at all, and its non-goals what is declined. [direction.md](direction.md) explains it for the maintainer who writes it

## Who decides

Every decision an agent meets falls in a **zone**, and each zone has one **level** (spec 030, D-48): `act` (the agent decides and goes on), `notify` (it decides, posts a decided comment and the `decided` label, and goes on; you may veto with a comment starting `veto`), `ask` (it asks through the needs-decision protocol and waits), or `never` (it may prepare the change but never takes the decision, even after your yes in chat). shipmill ships the zones and their defaults; you change a level in `[decisions]` of `.github/shipmill.toml`, never below its floor:

| Zone | Covers | Default | Floor |
|---|---|---|---|
| `direction` | an edit of `docs/product.md` or `docs/product/` | `never` | `ask` |
| `decision-policy` | the `[decisions]` section itself | `never` | `never` |
| `scope` | accepting an opportunity, approving a spec, accepting a goal plan, a milestone | `ask` | `ask` |
| `rule-departure` | a change that departs from a `D-n` or an approved spec's criterion | `ask` | `ask` |
| `contract-change` | changing or removing a command, flag, exit code, format, default, limit, public API, or stored state | `ask` | none |
| `contract-addition` | adding one of those while every existing use behaves as before; a new runtime dependency | `notify` | none |
| `security` | `.github/**`, secrets, permissions, the delivery hooks' rules, the gate's allowlist | `ask` | `notify` |
| `protected` | a file a `REVIEW.md` Protected areas glob covers | `ask` | none |
| `interpretation` | choosing between readings of a spec, a `D-n`, or an issue that all meet it | `notify` | none |
| `triage-verdict` | won't fix, duplicate, postpone, or close as done | `notify` | none |
| `implementation` | work order, how a change splits into pull requests, internal design, refactors, tests | `act` | none |
| `unknown` | a decision no other zone covers | `ask` | `ask` |

```toml
[decisions]
veto_hours = 24                   # the notify window, 1 to 168
contract-addition = "act"         # a zone id = a level; an absent zone keeps its default
```

The release side's stages keep their levels in `[autonomy]` ([release-lanes.md](release-lanes.md#autonomy-and-the-stop-switch)), which `[decisions]` can't set, and so do the agent stages `triage`, `fix`, and `land` (spec 040): `release`, `deploy`, `rollback`, `intake`, `upgrade`, `triage`, `fix`, and `land` read `act` for `act`, `ask` for `propose` (the proposal issue is the question), and no level for `observe`, and `breaking-release` is always `ask`, since a breaking stable release waits for a person's hand start (D-39). `shipmill decide levels` shows both: every zone with its level, its floor, and where the level comes from. `shipmill decide classify`, given a pull request's number, names the zones code detects in its change, read from the default branch's config, so a pull request can't lower its own levels. A session asks the code first, then places what code doesn't see itself, and the strictest level among a decision's zones wins: the sessions' steps are in github-issue-triage's [needs-decision.md](../skills/github-issue-triage/references/needs-decision.md#who-decides).

## Issue states

`triage_state.py` sorts every issue into one state and exits 1 when any need action.

| State | Meaning | Next step |
|---|---|---|
| NEW | No triage comment yet | Triage it |
| NEEDS_PR | Triaged "implement", no PR yet | Dispatch an implementer |
| IN_PROGRESS | An open PR fixes it | Wait, or review the PR |
| DONE_NOT_CLOSED | Its PR merged, the issue is still open | Close it, citing the PR |
| SUSPECT_CLOSE | Closed by a commit that only quoted "Fixes #N" | Check the fix landed; reopen if not |
| BLOCKED | Waiting on an open upstream issue, a spec PR not yet merged, or (a build issue) an issue its body says it depends on | Nothing, until it closes or merges |
| UNFILLED | A `Depends on` line of its body still names a `specs.py split` placeholder such as `#{B1}` | Put in the dependency's issue number |
| SPEC_REFUSED | The PR it waits on (its spec PR) closed without merging | Decide again: revise the spec in a new PR, postpone, or won't fix |
| UNBLOCKED | The upstream issue it waited on has closed, its spec PR merged, or its last dependency closed | Resume; a dependency noted `:not_planned` never landed, so decide again first |
| DECIDED | Labelled `needs-decision`, and a trusted person answered its question | Read the reply, remove the label, and act on it |
| POSTPONED | Labelled `postponed` | Skip it |
| REVISIT | Postponed before the newest stable release | Decide again |
| TRIAGED | Triaged, with nothing pending: a request handed to product intake (`opportunity`) reads this too | Nothing; intake groups the handed-over requests |
| ASSIGN_DUE | A role's item (labelled `role:<name>`, or the older `human`, which counts as `role:maintainer`) nobody is assigned to, even while it is held | The session assigns the role's users from `[agents.roles]`, or the maintainer's when nobody fills the role |
| NO_ASSIGNEE | A role's item nobody is assigned to, read without the `--role` flags the gate passes | The session reads the state again with them; it never asks who does a step |
| HANDOFF_DUE | A person's item whose holds all closed, not yet handed off | The session mentions its assignees and its role's teams with what to do |
| WITH_PERSON | A person's item handed off, no done report yet | Nothing: it waits on the person |
| VERIFY_DUE | A person's item whose assignee replied `done` | The session runs its `## Check` and closes it, or hands it back |
| VERIFY_CLOSED | A person's item closed by hand, its `## Check` not yet run; or a parent with a `## Check` closed by a PR, a commit, or the App before its check ran | The session runs the check, and reopens it if it fails |
| VERIFY_DUE (a parent) | A parent with a `## Check` whose children all closed | The session runs the check: it holds, the parent closes with the check and what came back; it fails, the check-failed comment |
| CHECK_FAILED | A parent's check failed after its last child closed | The session files the fix as a new child; the parent waits on it, then runs its check again |

## A chain across repos and people

Work that spans repos and people is a chain of issues, each waiting on the one before it through a `Depends on owner/repo#N` line or GitHub's own relations (blocked by, sub-issues); `chains.py link` writes both. Each repo's gate advances its own part, and a person's part is a role's item: an issue labelled `role:<name>` (such as `role:infra`), assigned at once to the people `[agents.roles]` lists for that role, or to the maintainer when nobody fills it. Issues labelled `human`, the label before roles, still read as `role:maintainer`. Building a page that a server change unhides, with a link to it from another site:

| # | Item | Repo | Done by | Waits on |
|---|---|---|---|---|
| 1 | Build the page | `acme/app` | an agent | nothing |
| 2 | Remove the rule that hides it | `acme/srv` | an agent | 1 |
| 3 | Reload the web server | `acme/app` | a person (`role:infra`, assigned) | 2 |
| 4 | Link to the new page | `acme/site` | an agent | 3 |

1. Item 1's PR merges and closes it: item 2 reads UNBLOCKED in `acme/srv`, and that repo's gate takes it up
2. Item 2 closes: item 3 reads HANDOFF_DUE, and the session posts the hand-off, mentioning the assignee with the issue's steps and its `## Check`. GitHub's mention is the notification
3. Item 3 reads WITH_PERSON, which needs no session, however long the person takes
4. The person does it and replies `done`: item 3 reads VERIFY_DUE, and a session runs the `## Check`. It holds: the session closes item 3. It fails: a new hand-off says what came back
5. Item 3 closes: item 4 reads UNBLOCKED in `acme/site`, and that gate takes it up

The person acts once, on item 3. `chains.py show acme/app#3` prints the whole chain with each item's executor and state, and NO_GATE on a ready item in a repo with no gate; `github-ship-watch` reports that as CHAIN_NO_GATE, since nothing would take it up.

A parent over such a chain can carry a `## Check` of its own: what must hold in production once the whole chain is in, and how to see it. After its last child closes it reads VERIFY_DUE, not UNBLOCKED, and a session runs the check, which only reads. It holds: the parent closes, with the check and what came back. It fails: a check-failed comment, then the fix filed as a new child, and the parent waits on that before it checks again. A check the session can't run goes to you as a needs-decision question. A feature issue whose build deploys gets one from the spec gate, and an `upstream` report may carry one for its coordinator (spec 042).

## Keeping it running

`github-ship-watch` is the routine: each pass checks the release runs, the newest releases, and the issue intake, finishes what the policy already decided (a stalled lane, a flaky release job, the shipped notices), and hands flagged issues to triage when asked.

- `shipmill gate` on launchd: a new background session on this machine only when the repo needs one, with the prompt from the config's `[agents]` section; quiet ticks make no model call (shipmill-setup, The gate)
- `/loop 30m /shipmill:github-ship-watch <owner/repo> — watch and triage`: every 30 minutes in this session
- `/schedule`: a cloud routine, with the prompt below that clones shipmill
- Status only: `python3 $S/github-ship-watch/scripts/watch_state.py <owner/repo>` (exit 1 when anything needs action)

The plugin is installed per person by default (`[agents] plugin = "host"`, spec 033). To enable it in every local session of a repo instead, a contributor's too, set `[agents] plugin = "repo"` and commit this to its `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "shipmill": { "source": { "source": "github", "repo": "shipmill/shipmill" }, "autoUpdate": true }
  },
  "enabledPlugins": { "shipmill@shipmill": true }
}
```

A cloud routine may not apply a repo's plugin keys ([plugins for organizations](https://code.claude.com/docs/en/plugins/org.md) lists where each surface reads them), so give the routine a prompt that doesn't depend on them:

```
Clone https://github.com/shipmill/shipmill into tmp/shipmill (or pull it if present), then follow
tmp/shipmill/skills/github-ship-watch/SKILL.md for <owner/repo> — watch and triage
```

## Safeguards

- A change to a flag, format, default, public API, or stored state is designed in its issue first and checked against the repo's decisions log (`DECISIONS.md` or `docs/decisions.md`); what you settle is recorded there, so it isn't asked again
- A user's request for a new capability goes to product intake first: triage comments `Triage: **opportunity**` and intake groups it with the requests for the same outcome into one opportunity issue. Nothing is specified until you accept the opportunity (the `planned` label); declining it closes it with your reason, and later requests for the same outcome are recorded against that decline. Bugs, contract tweaks, and small additive features skip intake
- A feature (new behaviour beyond a bug fix or a contract tweak: an accepted opportunity, a request one covers, or an issue you filed) gets a spec first: a file `docs/specs/NNN-<slug>.md` with numbered acceptance criteria, merged through its own PR before any implementer starts. Merging the spec is your approval, and the issue reads BLOCKED until then. Each criterion is proven by a test that names it (`test_sNNN_k_...` or a `proves: S-NNN-k` comment), and `specs.py coverage` fails CI when a built spec has a criterion without one
- A merged spec splits into build issues, one PR each (`specs.py split`), linked as sub-issues of the feature issue with `chains.py link`, with `Depends on #N` lines that hold each one until its dependency closes. Every criterion belongs to exactly one build issue, which `specs.py check` verifies in CI, and `[agents] wip` in the config (D-32), when set, caps how many are in progress at once
- Scope is read narrowly: "triage" never merges, and "merge" never tags, unless you say so
- A change that departs from a spec, breaks existing users, or belongs to a held PR stops and asks you, whatever the scope
- When another session works the same repo, the skills message it first, and your word in the current session wins
- Mark a held issue with a comment line like `On hold: <why>, decided in owner/repo#N`, or the `blocked` label, so the script can report BLOCKED and later UNBLOCKED
