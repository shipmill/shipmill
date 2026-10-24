# Design: the product layer

Status: map and direction, 2026-10-10 (shipmill 0.45.0). Nothing here is new behaviour; specs
carve the gaps below into buildable pieces, the first being shipmill/shipmill#334, specified
in [spec 017](../specs/017-work-chains.md). Where this note and a merged spec differ, the
spec wins. D-32 (2026-10-17) later removed product intake's roadmap plan and `[roadmap]`:
a milestone is the maintainer's own list, and the work-in-progress limit is `[agents] wip`;
the tables below say so, and the gaps keep their 2026-10-10 wording.

shipmill's product layer is the part of the factory that decides **what** gets built and
**when** it ships: feedback, opportunities, specs, the task graph, milestones and releases.
Each stage was built on its own (#69, #54, #71, #70), and each works. What is missing is the
connective tissue: work done by people rather than agents, links the forge already holds,
the step after a milestone ships, and a view across repos. This note names the stages and
the objects that move through them, says who moves each one, and ranks the gaps, so the
layer grows on purpose rather than issue by issue.

## What stays true

- **The forge is the state.** Every object below is an issue, a label, a milestone, a marker
  comment, a file or a tag. shipmill keeps nothing of its own (#26, rule 1; D-6's spirit for
  product data: no external tracker)
- **Scripts answer facts, agents judge.** Each stage has a `*_state.py` that says where every
  object stands and exits 1 when one needs action; a skill decides what to do about it
- **The maintainer decides what and when, the spec decides how.** Accepting an opportunity
  (D-10) and merging a spec (D-5) are the human approvals on the path from feedback to
  release, and a milestone is the maintainer's own list (D-32). Agents propose the first two
  and never take them; they propose no milestone
- **Questions wait on the forge.** Anything an agent can't decide becomes a `needs-decision`
  item (D-21), not a stalled session
- **Forge-neutral by capability.** A relation the forge holds natively is read through the
  code host port (#322) as a capability; text conventions work on every forge

## Objects

| Object | On the forge | Created by | Done when |
|---|---|---|---|
| Request | An issue or discussion asking for an outcome | A user | Grouped into an opportunity, or left as a bug |
| Opportunity | An issue labelled `opportunity`; its `## Evidence` section lists the requests | Product intake | The maintainer labels it `planned` (accepted) or closes it as not planned (declined) |
| Feature | The accepted opportunity, or an issue the maintainer filed, carrying a spec | Triage's **feature** verdict | Its last build issue closes (`Fixes #feature` on the last build PR) |
| Spec | `docs/specs/NNN-<slug>.md`, `status: draft`, `approved`, `built` | Triage's spec gate | Its PR merges (approved), then its build verifies it (built) |
| Build item | An issue holding a group of the spec's criteria, with `Depends on` lines, a sub-issue of the feature | `specs.py split` | Its PR merges |
| Fix | An issue triaged **implement** (a bug or a contract tweak) | Triage | Its PR merges |
| Decision | A `needs-decision` marker comment and label on any item | Any agent session | A trusted person replies; the next session removes the label |
| Human item | (missing) An item only a person can do: a deploy, a credential, a payment, a vote | Today: by hand, assigned to the person | Today: the person closes it, if they remember |
| Milestone | A forge milestone named after the version it releases | The maintainer, by hand (D-32) | Its last issue closes |
| Release | A tag and a CHANGELOG section cut on a lane | The release workflow, by policy | Published; fixed issues told by shipped notices |

The feature issue is already an epic in all but name: it has sub-issues, `Depends on` lines on
each build item, and closes with the last one. What it lacks is a life outside the spec gate
(below, gap 5).

## States and who moves them

Four actors move objects: **users** (anyone filing), **agents** (intake, triage, resolve, PR
triage, ship-watch sessions), **people with authority** (the maintainer and trusted
collaborators, D-16), and **shipmill's code** (the release planner and the gate).

| Stage | States (script) | Agent moves | Person moves | Code moves |
|---|---|---|---|---|
| Feedback | NEW_FEEDBACK, OVERLAP, OPPORTUNITY_OPEN, ACCEPTED, DECLINED, NO_REASON, HANDED_OFF, DONE, MERGED (`intake_state.py`) | Groups requests, opens and updates opportunities | Accepts (`planned`) or declines with a reason | Nothing |
| Spec | The feature reads BLOCKED on its spec PR, then UNBLOCKED or SPEC_REFUSED (`triage_state.py`); the spec's status line (`specs.py check`) | Writes the spec, opens its PR, splits it | Merges the spec PR, or closes it | `specs.py check` and `coverage` in CI |
| Build | NEEDS_PR, IN_PROGRESS, BLOCKED, UNFILLED, UNBLOCKED, DONE_NOT_CLOSED (`triage_state.py`) | Implements, reviews, lands within `[agents] wip` | Nothing, unless asked | Merges on green under the repo's autonomy |
| Decisions | NEEDS_DECISION, then DECIDED (`triage_state.py`, `watch_state.py`) | Asks, then takes up the answer | Answers | The gate starts no session while it waits |
| Release | A lane is due when a trigger fires and no gate holds it; `milestone = true` fires when the version's milestone has closed issues and none open (`planner.py`) | Watches, reruns, tells reporters | Holds or starts a lane by hand | Cuts the release |

Read end to end, the path is:

```text
request ──intake──▶ opportunity ──maintainer: planned──▶ feature ──triage──▶ spec PR
   ──maintainer: merge──▶ build items (Depends on, sub-issues) ──agents──▶ merged PRs
   ──maintainer: lists──▶ milestone "X.Y.0"
   ──last issue closes──▶ lane due ──planner──▶ release X.Y.0 ──ship-watch──▶ shipped notices
```

## How it is used today

Checked on 2026-10-10 across the five repos the maintainer runs shipmill in:

- No repo sets `[roadmap]`, and no repo but shipmill has an opportunity issue; the roadmap
  plan has never run outside its tests
- Two repos set `milestone = true` on their stable lane. In one, the version shipped and its
  milestone is still open with no next milestone, so the lane has no milestone trigger left;
  in the other, the last open issue in the milestone is a question to the maintainer, and
  "close the milestone" is a step the maintainer has to remember after a soak ends. The
  milestone works as a manual hold, not as a plan
- In a third repo, three of the maintainer's own steps (a key rotation, a web server change,
  a pricing call) were filed as issues assigned to the maintainer, with nothing to say when they
  became doable and nothing to start the next step once they were done

## Gaps, ranked

Ranked by how often the gap costs the maintainer a step today, then by how much else waits
on it. Forge-specific work waits for the code host port (#322), which has priority until
2026-10-26; until then this is design work.

| # | Gap | Why it ranks here | Tracked in |
|---|---|---|---|
| 1 | **Human items have no lifecycle.** UNBLOCKED always means "dispatch an implementer"; an item only a person can do is never announced when it unblocks, never verified, and its close starts nothing | Seen in two repos in two days; every chain with a deploy, a credential or a decision in it stops here | #334 |
| 2 | **A milestone's loop doesn't close.** Nothing closes a milestone once its version ships, opens the next one, or moves leftover issues; the roadmap plans only accepted opportunities, so fixes and maintainer-filed features reach a milestone only by hand | Both repos that use `milestone = true` show it; small: one milestone write on the port beside the read it has | #336 |
| 3 | **No single queue for the maintainer.** Decisions, human items, opportunities awaiting a call, milestone proposals and spec PRs to merge are spread across repos; `fleet.py report` lists watch rows, and `shipmill status` covers one repo | Every approval in the layer is the maintainer's, so the layer moves only as fast as they are found | #337 |
| 4 | **Native relations aren't read.** Forge dependencies and sub-issues hold nothing; sub-issues are written by `specs.py split` and never read back | Links set in the forge's UI silently do nothing; GitHub first in spec 017, other forges behind the port (spec 016) | #334 |
| 5 | **No epic outside the spec gate.** A parent whose children are fixes, human items or items in other repos has no state, progress or close | Comes almost free once gaps 1 and 4 land | #334 |
| 6 | **Planning stops at the repo.** A chain, a milestone or a roadmap for a product that spans repos has no home; the gate and triage see one repo | Real (one product spans three repos) but rare among users so far; it needs gaps 1 to 4 first | Chains: #334; a plan across repos: #338 |
| 7 | **The layer is configured nowhere.** Setup never offers `[roadmap]`, the `opportunity` and `planned` labels, or `milestone = true` with a first milestone | Not a missing feature; until it is fixed, gaps 2 and 3 have no users | #336, under Success |

## Direction for each gap

These are the shapes the specs should start from, not the specs.

**1. Human items.** Settled in spec 017: an issue labelled `human` is a person's item, done
by its assignees. Its body may carry a `## Check` section: what proves it done. On unblock,
a triage session mentions the assignees once with what to do. "Done" is the person
commenting `done` or closing it; a session then runs the check where it can and either
closes or confirms the item, or hands it back with what failed. Its close unblocks the next
item like any other. There are no reminders yet; a repeat mention can come later behind its
own option.

**2. Closing the milestone loop.** When a lane with `milestone = true` releases version X,
the same run closes milestone X and moves any issue left in it (there should be none) to the
next one. The roadmap plan then reads a missing next milestone as NEXT even with no accepted
opportunity, so fixes triaged **implement** can be proposed into it too, ranked after the
opportunities. A hold stays a hold (D-8): an open issue parked in a milestone to stop a
release reads as a hold in `watch_state.py`, with its reason, instead of as unfinished work.

**3. The maintainer's queue.** `fleet.py report --queue` (or `shipmill queue` over the same
fleet file) lists only what waits on a person, across repos, oldest first: NEEDS_DECISION
items, human items assigned to the reader, OPPORTUNITY_OPEN, PROPOSAL_OPEN, open spec PRs,
and NO_REASON declines. It reads the state scripts that already exist and adds no state.

**4. Native relations.** Settled in spec 017 for GitHub: `triage_state.py` reads issue
dependencies and sub-issues as holds, the same as a `Depends on` line; both count, and the
item waits until every one is closed. `chains.py link` writes the relation and the text line
together. GitLab's linked issues (`blocks`, `is_blocked_by`) and epics come through the code
host port (#322) later, behind the same reading.

**5. Epics.** Settled in spec 017: an issue with sub-issues is a parent; `triage_state.py`
reports its progress (`children K/N closed`) and reads it UNBLOCKED, to close, when the last
child closes. The spec gate's feature issue is then one kind of parent, not a special case.

**6. Across repos.** Chains first: each repo's triage already parses `owner/repo#N` holds,
so a cross-repo chain advances as long as every repo in it runs a gate, and D-16 applies in
each. A plan across repos (one milestone name in several repos, released together) is a
later question, and depends on the queue (gap 3) to be visible at all.
Chains shipped in spec 017; the plan across repos is under [Across repos](#across-repos).

## Across repos

Added 2026-10-24 (shipmill 0.61.0), after chains across repos shipped in spec 017. It answers
gap 6: how repos work together, and whether that takes another product.

The repo stays the unit of execution: its gate, policy, lanes, milestones and the App's
identity are per repo. The fleet becomes the unit of planning. Working across repos needs
no new product and no new store, because the forge already holds everything the fleet
needs; what it needs is one access rule, one role, and the forge's own cross-repo objects.

### Read anywhere, change at home

- Every change to code stays in its own repo: its branch, its pull request, its CI, its
  gate. A session may read other repos of the fleet and file an issue there, nothing more
  (D-45)
- A cross-repo effect happens on the side that waits: the downstream item names its
  upstream (`Depends on owner/repo#N`, or a native relation), and the downstream repo's
  gate reads the upstream's state on its tick and takes the item up when it closes. The
  upstream repo knows nothing about its dependents. This is built for chains (spec 017),
  which reads an upstream item's state and never its text
- A person is told from the repo where their item waits, by that repo's gate
- A release that needs another repo's change holds a stand-in issue in its own milestone
  with `Depends on owner/repo#N`, so the milestone empties only when the other repo's change
  closes. GitHub milestones are per repo, so this needs no cross-repo milestone; GitLab's
  group milestones can come later through the code host port
- The App's token covers only the gate's repo today (`src/shipmill/app.py`), so an upstream
  in another private repo reads UNREADABLE in `chains.py show`. D-45 adds a second token
  over the fleet with read access and issues write only; an installation token carries the
  same permissions on every repo it lists, so its permissions keep code changes at home

### A bug found in another repo

An agent working an issue finds that the fault is in a module another repo owns:

1. **It reports what it can.** A coding agent usually can't run another repo's services, so
   the report is how to reproduce the bug and, when it found the cause in the module's
   source (a dependency's code it can read), the suspected place in the code. A guess it
   could not trace is said to be one
2. **It files the report in the module's repo** with the fleet token (D-45), linking back to
   its own issue, and names that issue on a `Depends on` line of its own when its work
   can't go on without the fix. That repo's triage judges the report like any other issue
3. **It never fixes the module from its own repo:** no vendored copy, no patch of an
   installed dependency, no pull request in the other repo. A workaround in its own code
   is fine when it is a real change there (a check, an error handled on its side), said to
   be temporary in its pull request

A plan's items still reach other repos only through the maintainer's marker (D-46): a plan
is the maintainer's choice of work, a bug report is a fact the other repo's triage weighs.

### The manager is a role, not a store

Someone has to look across repos: gather what waits on the maintainer, watch chains, and
put together the plan for a product that spans repos. Today the maintainer does it from
memory. The role fits a fleet-level playbook, run by a gate on the product's home repo (the repo
whose `docs/product.md` describes the product as a whole, with or without code of its own),
with the fleet's read token:

- It builds the maintainer's queue (#337) and reports where chains stall (`chains.py show`,
  CHAIN_NO_GATE)
- It proposes a plan across repos from each repo's goal plans (spec 028) for the maintainer
  to accept (D-10, D-34); the plan, its stand-in issues and its milestone live in the home
  repo
- It changes nothing outside the home repo; an accepted plan reaches the other repos
  through a trusted marker the maintainer posts, and each repo takes up its part (D-46)

### Cross-repo objects the forge already has

| Need | GitHub | GitLab |
|---|---|---|
| A board or plan over many repos | Projects (fields, iterations, a roadmap view) | Group boards |
| A parent over many repos | Sub-issues in other repos (spec 017 reads them) | Group epics |
| A milestone over many repos | None: a stand-in issue in each repo's milestone | Group milestones |
| Dependencies | Issue dependencies across repos (spec 017) | Linked issues, `blocks` |

They are read and written through the code host port as capabilities, like the relations
in spec 017. A GitHub Project belongs to a user or an organization and needs its own App
permission, and one maintainer's repos often span several owners: whether one Project can
hold them is to be checked before anything relies on it.

### Linear and Jira

Neither is needed as a system of record: a shipmill-owned tracker or an external one would
be state outside the forge, which every layer avoids (D-6's spirit). A person's step that
has no repo of its own is a `human` item (spec 017) in the repo where it waits, or in an
operations repo. An external tracker fits only as an intake source, behind its own config
section and never required, for a team that already works there or for work no repo holds.

### Decided

The maintainer settled the three questions on 2026-10-24, in #338:

- Gates read the fleet and may file issues there, with a second token that has no write
  access to code or pull requests; every change stays in its own repo (D-45, refining D-14)
- A plan accepted in the home repo reaches the other repos through a trusted marker the
  maintainer posts, and each repo's own session takes up its part (D-46)
- The home repo is the one whose `docs/product.md` describes the product as a whole, code or
  no code; each component repo keeps a `docs/product.md` for its own scope, such as an API
  (D-46, D-34)

## Questions for the maintainer

- Whether a release may close its milestone by itself, or proposes the close (gap 2)
- Whether fixes belong in the roadmap plan, or milestones stay for features only (gap 2)
- The plan across repos: decided, see [Across repos](#across-repos) (gap 6)
