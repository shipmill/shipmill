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
- **"tag X"** adds the release: readiness check, tag, and registry check; shipmill posts no notice on the fixed issues (D-69)

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
| Release | "tag <X>" | Readiness check, tag, publish |
| Which issues a release fixed | `python3 $S/github-pr-triage/scripts/shipped.py <owner/repo> <prev> <tag> [--json]` | Prints them; posts nothing (D-69) |
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
- **A goal ends; a measure is held** (spec 105). A goal is written `<outcome>. Check: <check>. By: <date or release>` and ends when its check passes; a standing measure is written `Held: <statement>. Threshold: <threshold>. Source: <source>` and is held for good. Product intake proposes a goal plan for a goal nothing serves (`no-work`), with `Check:` and `By:` in its Goal section; a measure is planned only on request (a `goal-plan` issue you open naming it), with `Threshold:`, `Source:`, and `Measure:`. A goal written in neither form plans as before, with `Measure:` alone

## Goals, plans, and projects

A goal, its plan, and the projects the plan files each have a state (spec 106), read by product intake's `intake_state.py` (`--goals`, `--plans`, `--projects`) from the direction and the repository's issues. The watch lists each state that needs a session on its PLANS row, so the gate starts one; `shipmill status --item G-3`, or `--item N` on a plan issue or a project's head, names the state, who holds it, and what moves it.

**A goal** (only a goal of kind goal; a standing measure and a goal of kind none have no state):

| State | Read when | Holder | Moved by |
|---|---|---|---|
| proposed | an open issue labelled `goal-proposal` by a trusted author or the App | the maintainer | writing it into the direction and closing the issue, or closing it as not planned |
| written | in the direction, with no `Met:` or `Dropped:` sentence, and not planned | an agent (a plan is due), or the maintainer (a plan waits for the answer) | an accepted plan |
| planned | an accepted plan of the goal is open, or a project head of one of its plans | its projects | its last project closing, when its check is read again |
| met | its text ends `. Met: <YYYY-MM-DD>` | nobody | nothing |
| dropped | its text ends `. Dropped: <YYYY-MM-DD>: <reason>` | nobody | nothing |

A written or planned goal past its horizon (its date has ended, or its release is tagged) reads GOAL_OVERDUE until the App's `goal-review` issue for that goal and horizon exists; its session asks you to extend, rewrite, or drop it, and opens the direction edit as a pull request only you merge (D-34).

**A plan** waits for your answer until a date: seven days after its newest revision, or the date a trusted `answer by YYYY-MM-DD` reply sets. Past that date it reads PLAN_OVERDUE, your overdue decision, and while any plan of the product is overdue no `no-work` plan is proposed and no held project starts; work already started goes on. A goal has one open plan: a newer plan of the same goal (proposed for a `requested in #N` request or an accepted opportunity) replaces the older, which reads PLAN_REPLACED until its session closes it. A held plan (spec 098) has no answer date until it reads PLAN_OPEN again.

**A project** is a head issue labelled `project`, its check issue the head's sub-issue titled `Check: ` with a `## Check`, and its parts the other sub-issues, two levels deep. `[agents] projects = N`, set in the product's home, limits how many of the product's projects are active at once:

| State | Read when | Holder |
|---|---|---|
| held | the head is open and has no check issue, or is labelled `held` | its start: a free slot, its turn, no overdue plan |
| active | the head and its check issue are open, and a part is open or none is filed yet | agents and your steps |
| in focus | active and labelled `focus` | your steps first |
| closing | the check issue is open and every part is closed | someone other than the builder, who runs the check |
| closed | the head closed as completed | nobody |
| stopped | the head closed as not planned with the App's stop record | nobody |

A held project's turn reads PROJECT_START_DUE (its session files the check issue first), a project whose tree had no update for 14 days PROJECT_IDLE (its session asks you to continue, hold, or stop), and a trusted `stop: <reason>` PROJECT_STOP_DUE (its session closes the parts, records the stop, and sets its spec to `stopped`). A held project's `status --item` names what it waits for: `plan #P overdue`, `a free slot: K of N active`, or `held by the maintainer`.

**An accepted opportunity** names the goal it serves (`accept G-<n>`, or the one goal its `Serves:` line names): it reads ACCEPTED_INTO that goal, whose next plan takes it; `accept new goal` reads GOAL_PROPOSAL_DUE until the App's `goal-proposal` issue holds it; one that names no open goal reads NEEDS_GOAL, whose session asks you once which goal it serves. `fleet.py queue` lists a PLAN_OVERDUE plan as an overdue `PLAN` row and a NEEDS_GOAL opportunity as an `OPPORTUNITY` row.

| Label | On | Means |
|---|---|---|
| `project` | an issue | it is a project's head |
| `held` | a project's head | held: it starts only in its turn |
| `focus` | an active project's head | your steps on it come first |

A session makes your moves on these with one command each (spec 108), writing a relay that names you and then the label: `shipmill project add|focus|unfocus|hold|resume <n> --by <login>`, `shipmill project check <head>` for the check issue, and `shipmill opportunity accept <n> G-<n>|new` or `decline <n> --reason "<why>"`. Each refuses a move its reader wouldn't count and prints the item's state after it.
| `goal-proposal` | an issue | a proposed goal, not yet in the direction |
| `goal-review` | the App's issue | a goal past its horizon, waiting for your extend, rewrite, or drop |

| Marker (a comment's or issue's first line, by the App) | Records |
|---|---|
| `<!-- shipmill:goal-overdue G-<n> by=<horizon> -->` | the goal-review issue of a goal past that horizon |
| `<!-- shipmill:plan-replaced #<new> -->` | a plan closed for the newer plan of its goal |
| `<!-- shipmill:project-stopped -->` | a stopped project, its reason in the body |

## Who decides

Every decision an agent meets falls in a **zone**, and each zone has one **level** (spec 030, D-48): `act` (the agent decides and goes on), `notify` (it decides, posts a decided comment and the `decided` label, and goes on; you may veto with a comment starting `veto`), `ask` (it asks through the needs-decision protocol and waits), or `never` (it may prepare the change but never takes the decision, even after your yes in chat). shipmill ships the zones and their defaults; you change a level in `[decisions]` of `.github/shipmill.toml`, never below its floor:

| Zone | Covers | Default | Floor |
|---|---|---|---|
| `direction` | an edit of `docs/product.md` or `docs/product/` | `never` | `ask` |
| `decision-policy` | the `[decisions]` section itself, and a raise of an `[autonomy]` stage's level (D-99) | `never` | `never` |
| `scope` | accepting an opportunity, approving a spec not in `accepted-spec`, accepting a goal plan, a milestone | `ask` | `ask` |
| `accepted-spec` | approving the spec of work you already accepted: an opportunity you planned or an issue you filed (spec 067) | `ask` | `notify` |
| `rule-departure` | a change that departs from a `D-n` or an approved spec's criterion | `ask` | `ask` |
| `contract-change` | changing or removing a command, flag, exit code, format, default, limit, public API, or stored state | `ask` | none |
| `contract-addition` | adding one of those while every existing use behaves as before; a new runtime dependency | `notify` | none |
| `security` | `.github/**`, secrets, permissions, the delivery hooks' rules, the gate's allowlist | `ask` | `notify` |
| `deploy-step` | a change to a deploy workflow's job that no run named on the `Proof:` line ran (spec 063) | `ask` | none |
| `protected` | a file a `REVIEW.md` Protected areas glob covers | `ask` | none |
| `area-record` | a change that touches an area a failed release raised, until `[decisions] clean_releases` clean releases clear it (spec 083) | `act` | none |
| `interpretation` | choosing between readings of a spec, a `D-n`, or an issue that all meet it | `notify` | none |
| `triage-verdict` | won't fix, duplicate, postpone, or close as done | `notify` | none |
| `implementation` | work order, how a change splits into pull requests, internal design, refactors, tests | `act` | none |
| `unknown` | a decision no other zone covers | `ask` | `ask` |

```toml
[decisions]
veto_hours = 24                   # the notify window, 1 to 168
contract-addition = "act"         # a zone id = a level; an absent zone keeps its default

[decisions.paths.security]
".github/workflows/**" = "notify" # a part: these paths take their own level, never below the floor
```

The three zones code detects from a changed path, `direction`, `security`, and `protected`, take parts (spec 057): under `[decisions.paths.<zone>]`, a glob of the zone's paths gets its own level, above or below the zone's, never below its floor. A part never adds a zone to a change; it only sets the level of a path the zone already covers, and the strictest level among a change's paths wins, so a change to a workflow (`notify` above) and to `.github/CODEOWNERS` (no part: `ask`) reads `ask`. `shipmill decide levels` and `shipmill doctor` list every part.

A pull request may earn a lower level in two zones (spec 083). Under `[decisions.earned]`, `protected` and `security` each take a bound, the lowest level a pull request may earn there (never below the zone's floor), and `max_lines` (default 200) caps its size. A path that puts either zone in lands at the bound instead of the zone's level only when all four pieces of evidence hold: `checks` (the default branch requires a status check that proves, by `shipmill merge-checks`' reading), `size` (its added plus deleted lines are at most `max_lines`), `record` (it touches no area the `area-record` zone raised), and `kind` (it touches no path of a ceiling kind). The three ceiling kinds never earn, whatever the evidence: `controls` (shipmill's config, `CODEOWNERS`, `REVIEW.md`, `CLAUDE.md`, `AGENTS.md`, the decisions log, `.claude/**`, `.claude-plugin/**`, and every workflow and action), `infrastructure` (Terraform, Dockerfiles, compose files, migrations, `infra/`, `deploy/`, `k8s/`, `helm/`), and `dependencies` (manifests and lockfiles, and `.github/dependabot.yml`). A path at `never` never earns, a change given as `--files` earns nothing, and without the table nothing earns. `shipmill decide classify --pr <n>` prints the landing level and each piece of evidence, and `shipmill decide record` the production record behind `area-record`.

The release side's stages keep their levels in `[autonomy]` ([release-lanes.md](release-lanes.md#autonomy-and-the-stop-switch)), which `[decisions]` can't set, and so do the agent stages `triage`, `fix`, and `land` (spec 040): `release`, `deploy`, `rollback`, `intake`, `upgrade`, `triage`, `fix`, and `land` read `act` for `act`, `ask` for `propose` (the proposal issue is the question), and no level for `observe`, and `breaking-release` is always `ask`, since a breaking stable release waits for a person's hand start (D-39). `shipmill decide levels` shows both: every zone with its level, its floor, and where the level comes from. `shipmill decide classify`, given a pull request's number, names the zones code detects in its change, read from the default branch's config, so a pull request can't lower its own levels. A session asks the code first, then places what code doesn't see itself, and the strictest level among a decision's zones wins: the sessions' steps are in github-issue-triage's [needs-decision.md](../skills/github-issue-triage/references/needs-decision.md#who-decides).

An agent's text is told from a person's by its marker, never by its author (spec 050, D-62): `shipmill gh` ends every body it writes with `<!-- shipmill:agent -->`, and a record carrying it is never a reply, a veto, a decider's credit, or the maintainer's filing.

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
| RELAY_REFUSED | The `needs-decision` label is off and a relay by the App after its question is out of the relay grammar (D-93), so it isn't counted; its note is `relay not counted: <reason>` | Ask again by the needs-decision protocol, with `<!-- shipmill:relay-refused <reason> -->` and its visible `Relay not counted` line under the zone line; record the next answer with `uvx shipmill decision answer` (spec 107), which writes only a relay its reader counts |
| POSTPONED | Labelled `postponed` | Skip it |
| REVISIT | Postponed before the newest stable release | Decide again |
| TRIAGED | Triaged, with nothing pending: a request handed to product intake (`opportunity`) reads this too | Nothing; intake groups the handed-over requests: once one has waited 24 hours (`FEEDBACK_AFTER`), the watch reports FEEDBACK_DUE and, under `[autonomy] intake = "propose"`, the gate starts an intake pass. An opportunity you accept (`planned`) reads SPEC_DUE in the watch, and the gate hands it to triage's spec gate (spec 074) |
| ASSIGN_DUE | A role's item (labelled `role:<name>`, or the older `human`, which counts as `role:maintainer`) nobody is assigned to, even while it is held | The session assigns the role's users from `[agents.roles]`, or the maintainer's when nobody fills the role |
| NO_ASSIGNEE | A role's item nobody is assigned to, read without the `--role` flags the gate passes | The session reads the state again with them; it never asks who does a step |
| HANDOFF_DUE | A person's item whose holds all closed, not yet handed off | The session mentions its assignees and its role's teams with what to do |
| WITH_PERSON | A person's item handed off, no done report yet | Nothing: it waits on the person |
| STALE_HANDOFF | A person's item whose sub-issue parent closed, with no `<!-- shipmill:still-waits -->` comment since | The session closes it, or posts the still-waits comment saying why it still waits on its person; `shipmill gh issue close` refuses to close a parent over a person's open sub-issue |
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

`github-ship-watch` is the routine: each pass checks the release runs, the newest releases, and the issue intake, finishes what the policy already decided (a stalled lane, a flaky release job), and hands flagged issues to triage when asked.

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

### How a pull request lands

`[agents] merge` (spec 072, D-96) picks the method an agent's merge takes:

```toml
[agents]
merge = "merge"   # or "squash", the default
```

- **`"squash"`, or no key:** each pull request lands as one commit with its number in the subject, as before
- **`"merge"`:** a merge commit, so each of the branch's commits reaches the default branch and counts on its author's contribution graph. That includes an agent's in-between commits, such as "fix lint" or "address review", so squash stays the default while agents don't shape their commits
- **A stack's base** lands with a merge commit under either value, so its child retargets and rebases clean; under `"squash"` in a repo that doesn't allow merge commits, it lands with a squash and its child is rebased. No pull request is rebase-merged
- **A method the repo doesn't allow fails, never falls back.** Where the repo's settings (`allow_squash_merge`, `allow_merge_commit`, Settings > General > Pull Requests) don't allow the method the setting names, `shipmill gh pr merge` exits 2 naming both, and `shipmill doctor`'s `merge` row warns. The plugin's delivery hook refuses `--squash` under `"merge"` (its `merge-method` rule) as it refuses a rebase merge

### Who the work is credited to

A merge the App makes is authored by its bot, so your contribution graph doesn't show the change you decided to land. `[agents] author` (spec 051) picks whose account an agent's issue, pull request, and merge commit go out as. Every write still goes through the App (D-54); only those three commands change author, and comments, labels, reviews, edits, closes, and `shipmill gh api` calls stay the App's:

| Mode | Config | Author of the issue, pull request, and merge commit | `Co-authored-by` on the merge commit |
|---|---|---|---|
| **Autonomous** | `app_id` with `[agents] author = "app"` | The App | The decider |
| **Assisted** | `app_id` with `[agents] author = "decider"` | The decider, when they ran `shipmill app-login`; else the App | The App's bot, or the decider when the App wrote it |
| **Operator** | no `app_id`, `identity = "host"` (spec 037) | The host's `gh` login | Unchanged |

- **Who decides.** The decider is who assigned or approved the work, never an outside author of a request: the first trusted person a record shows decided it (an approving review, an answer to a needs-decision question, the issue it closes, or the `planned` label on its opportunity), never a bot, the App, an untrusted account, or a record carrying the agent marker. A merge takes the pull request's decider, `pr create` the deciders of the issues its body closes, and `issue create` those of the record shipmill's `--decided-in <n>` flag names
- **Each person's consent.** Each person opts in by running `shipmill app-login` themselves (`uvx shipmill app-login` without the install), on the host that runs the gate: it prints a URL and a code, and they enter the code on github.com signed in as themselves. Turning `author = "decider"` on authorizes no one; `shipmill app-logout <login>` deletes the stored token and revokes it
- **What a person-written record shows.** An issue or pull request written as a person keeps the agent marker, so it is never read as their own words, and ends with ``Opened by an agent through shipmill, on `@<login>`'s decision.``; a merge written as a person has them as its author, through their token, and adds a `Co-authored-by` trailer for the App's bot. A write with no decider, or a decider who hasn't run `shipmill app-login`, goes as the App and says why on stderr. No mode approves a pull request on your behalf
- **`credit` is deprecated.** `[agents] credit = "decider"` (spec 049) is what autonomous mode does: `shipmill gh pr merge` adds a `Co-authored-by` trailer for each trusted person a record shows decided the change. The trailer means the person decided the change, not that they wrote it. The default is `"off"`: with neither `author` nor `credit` set, every merge is written as GitHub writes it, as before. Set `[agents] author = "app"` in place of `credit = "decider"`; `shipmill doctor` warns while `credit` is set and shows the mode in its `author` row

## Safeguards

- A change to a flag, format, default, public API, or stored state is designed in its issue first and checked against the repo's decisions log (`DECISIONS.md` or `docs/decisions.md`); what you settle is recorded there, so it isn't asked again
- A user's request for a new capability goes to product intake first: triage comments `Triage: **opportunity**` and intake groups it with the requests for the same outcome into one opportunity issue. Nothing is specified until you accept the opportunity (the `planned` label); declining it closes it with your reason, and later requests for the same outcome are recorded against that decline. Bugs, contract tweaks, and small additive features skip intake
- With `[agents] outcomes = N` (spec 101), at most N opportunities are open across the product at once. At the limit intake opens no new one: it comments on each request that would start a new outcome with a held comment (first line `<!-- shipmill:intake-held -->`), and `intake_state.py` reads the request HELD, which needs nothing from you. What clears it: an open opportunity closes (accepted work done, declined, or merged), and the held requests are proposed oldest held first; or you reply `propose` on the request (as an owner, member, or collaborator), and intake proposes it past the limit
- A feature (new behaviour beyond a bug fix or a contract tweak: an accepted opportunity, a request one covers, or an issue you filed) gets a spec first: a file `docs/specs/NNN-<slug>.md` with numbered acceptance criteria, merged through its own PR before any implementer starts. Merging the spec is your approval, and the issue reads BLOCKED until then. Each criterion is proven by a test that names it (`test_sNNN_k_...` or a `proves: S-NNN-k` comment), and `specs.py coverage` fails CI when a built spec has a criterion without one
- A merged spec splits into build issues, one PR each (`specs.py split`), linked as sub-issues of the feature issue with `chains.py link`, with `Depends on #N` lines that hold each one until its dependency closes. Every criterion belongs to exactly one build issue, which `specs.py check` verifies in CI, and `[agents] wip` in the config (D-32), when set, caps how many are in progress at once
- Scope is read narrowly: "triage" never merges, and "merge" never tags, unless you say so
- A change that departs from a spec, breaks existing users, or belongs to a held PR stops and asks you, whatever the scope
- When another session works the same repo, the skills message it first, and your word in the current session wins
- Mark a held issue with a comment line like `On hold: <why>, decided in owner/repo#N`, or the `blocked` label, so the script can report BLOCKED and later UNBLOCKED
