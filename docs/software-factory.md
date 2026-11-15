# shipmill as a software factory

The `mattpocock/skills` repository has an in-progress skill, `software-factory`, that gives a
shared language for designing a software factory: "a system of agents that turns tickets,
PRs and schedules into merged code". This page maps its terms to the parts of shipmill that
fill them, so a reader who designs in those terms can find their way around this repo.

The skill is in progress, so this page reads it at one commit, `5863806`:
[SKILL.md](https://github.com/mattpocock/skills/blob/5863806/skills/in-progress/software-factory/SKILL.md)
and its
[EXAMPLE-TASKS.md](https://github.com/mattpocock/skills/blob/5863806/skills/in-progress/software-factory/EXAMPLE-TASKS.md).
A later version may say something else. The skill's words appear in the left column only;
shipmill keeps its own (it says "session" where the skill says "run", for one).

## Services

The skill calls each service a slot to fill with a product.

| Slot | What the skill says it is | What fills it in shipmill |
|---|---|---|
| Ticket tracker | "Where tickets live, and the factory's human interface" | GitHub issues, with their comments and labels; a question for the maintainer is a comment and the `needs-decision` label ([needs-decision.md](../skills/github-issue-triage/references/needs-decision.md)) |
| Ticket source | "Anything outside the factory that creates tickets": a feedback button, a monitor, an error tracker, an inbox | People filing issues and discussions, which [product-intake](../skills/product-intake/SKILL.md) groups into opportunities; `shipmill operate`, which opens an incident issue when a deploy fails and rolls back ([release-lanes.md](release-lanes.md#operate-health-bake-promotion-and-rollback)). No counterpart for a feedback button or an error tracker |
| Git host | "Where branches, PRs and reviews live" | GitHub |
| Orchestrator | "Receives triggers, starts runs on runners, and records which runs are queued, in flight or finished" | `shipmill gate` for the agents: on each tick it reads the repo's state and starts a session only for an item that needs one, recording which item it handed to which session ([shipmill-setup](../skills/shipmill-setup/SKILL.md#the-gate)); GitHub Actions for the release side, through shipmill's reusable workflows |
| Runner | "The disposable machine a run executes on" | A Claude Code background session on the host that runs the gate, in its own git worktree, pruned once its commits land; the host itself is not disposable. The release side runs on GitHub Actions runners |
| Observability platform | "Where runners send logs, traces and status"; optional | No platform of its own: the gate's log, `shipmill status` and `shipmill factory`, the Actions run pages, and [github-ship-watch](../skills/github-ship-watch/SKILL.md)'s report |

Of the three designs the skill sets side by side, "All on GitHub" is the closest: GitHub fills
the ticket tracker and git host slots and, for the release side, the orchestrator and runner
slots, while the agents' orchestrator and runner are on the host that runs the gate. GitHub
holds the work's state: issues, labels, pull requests, tags, and deployments.

## Tasks and runs

| Skill term | What fills it in shipmill |
|---|---|
| Trigger | A gate tick (a launchd interval) that checks GitHub for a change since its last walk, then hands one item; for the release side, a lane's triggers in `.github/shipmill.toml` (a schedule, the default branch quiet for a set time after merges, a milestone done, or a start by hand) ([release-lanes.md](release-lanes.md)) |
| Run | One gate session, handed one item, or one workflow run. As the skill asks, a headless session never waits for a person: it asks through the needs-decision protocol and ends, and the answer reads DECIDED for a later session ([flow.md](flow.md#issue-states)) |
| Task | A skill, or a release workflow; the example tasks map below |

The skill's example tasks:

| Example task | What it does, per the skill | shipmill counterpart |
|---|---|---|
| Explore | "Checks the ticket's claims against the codebase", sorts the ticket into a category, and leaves its findings for the implementer; it never pushes | [github-issue-triage](../skills/github-issue-triage/SKILL.md): verifies each issue's claim against the current default branch, comments a verdict (implement, feature, postpone, clarify) with labels, and dispatches an implementer for each "implement" |
| Implementer | Builds the ticket until the automated checks pass, and opens a draft PR | [github-issue-resolve](../skills/github-issue-resolve/SKILL.md): one issue, fixed with proof that fails without the fix, as one pull request. It opens the pull request ready for review, not as a draft (D-67 in [decisions.md](decisions.md)) |
| Automated review | Reviews the diff against the codebase's standards and the ticket it came from | [github-pr-triage](../skills/github-pr-triage/SKILL.md): reviewer agents each rebase one pull request in its own worktree, run the checks, and review correctness, security, and the repo's rules |
| Rework | Fixes only what the automated review named, and pushes | github-pr-triage again, in the same pass as its review: a reviewer commits small fixes with regression tests |
| Decompose | Splits a spec into tickets, each recording which tickets it depends on | github-issue-triage's [spec gate](../skills/github-issue-triage/references/spec-gate.md): a merged spec splits into build issues with `Depends on #N` lines, and an issue reads BLOCKED until its dependencies close ([flow.md](flow.md#safeguards)) |
| Ratchet | Takes one file a day off a stricter check's exception list and fixes it | No counterpart |
| Fix | Files a failed run's log as a ticket and attempts a fix as a PR | Partly [github-ship-watch](../skills/github-ship-watch/SKILL.md): a failed release or operate run is rerun once when the failure is flaky or transient, and otherwise reported with its failing step; it files no issue from the log and opens no fix |
| Architecture | Scans recent changes for refactoring candidates and files them as one ticket | No counterpart |
| Retro | Reads a merged PR, its ticket, reviews and run logs, and proposes changes to the factory's own instructions as a PR | Partly github-ship-watch's [weekly retro](../skills/github-ship-watch/SKILL.md#weekly-retro), a routine the user schedules: it reads the week's refused and reworked pull requests and their review comments, and proposes at most three changes as issues, never as a pull request |

## After the merge

The skill's tasks and slots stop at the merge: none releases, deploys, or rolls back.
shipmill goes on from there, and the skill has no slot for these stages:

| Stage | Done by | Where it is defined |
|---|---|---|
| Release | shipmill's release workflows cut a release on its lane (`dev`, `rc`, `stable`, `hotfix`) when the policy says one is due, run CI on that exact commit, tag, and publish | [release-lanes.md](release-lanes.md) |
| Deploy | `shipmill operate`: health checks, bake time, and promotion between environments | [release-lanes.md](release-lanes.md#operate-health-bake-promotion-and-rollback) |
| Rollback | `shipmill operate` rolls back a failing deploy and opens an incident issue | [release-lanes.md](release-lanes.md#operate-health-bake-promotion-and-rollback) |
| Watch | github-ship-watch reports a stalled release, a missing upload, an open incident, and the issues triage owes, finishes what the policy already decided, and drafts a postmortem for each closed incident | [github-ship-watch](../skills/github-ship-watch/SKILL.md) |

## shipmill terms the skill has no word for

| Term | What it is | Where it is defined |
|---|---|---|
| Gate | `shipmill gate` fills the orchestrator slot, but no event starts a session directly: each tick reads GitHub's state, walks the work in tiers, and starts a session only for the first item no session has taken | [shipmill-setup](../skills/shipmill-setup/SKILL.md#the-gate) |
| Lane | A release track (`dev`, `rc`, `stable`, `hotfix`) with its own triggers and gates, set in `.github/shipmill.toml` | [release-lanes.md](release-lanes.md) |
| Hold | An open issue labelled `shipmill-hold` turns every `act` into `propose`, for the agents and the release side alike, until it closes | [release-lanes.md](release-lanes.md#autonomy-and-the-stop-switch) |
| `needs-decision` | The label and marked comment an agent asks the maintainer with; the item waits until a trusted reply | [needs-decision.md](../skills/github-issue-triage/references/needs-decision.md) |
| `decided` | The label and comment of a decision an agent took at `notify`: it goes on, and the maintainer may veto | [flow.md](flow.md#who-decides) |
| Spec gate | A feature gets a spec with numbered acceptance criteria, merged through its own pull request before any build starts; the merge is the maintainer's approval | [spec-gate.md](../skills/github-issue-triage/references/spec-gate.md) |
| Decision zones | Every decision an agent meets falls in a zone, and each zone has a level (`act`, `notify`, `ask`, `never`) set in `[decisions]` | [flow.md](flow.md#who-decides), D-48 in [decisions.md](decisions.md) |

## The three brakes

The skill names three brakes for a factory's triggers: automated checks, automated review,
and human review, the last being "a human reads the PR before it merges". It advises adding
one automated trigger at a time, "with human review on every PR", and opening the throttle
as the brakes earn trust.

- **Automated checks: kept.** The repo's CI runs on every pull request, and github-pr-triage
  merges only when every job finished green (`pr_gate.py`). A release runs CI again on the
  exact commit it tags
- **Automated review: kept.** github-pr-triage's reviewer agents review each pull request
  before it lands, whoever wrote it
- **Human review: kept by default, replaceable by policy.** `[autonomy] land` in
  `.github/shipmill.toml` defaults to `propose` (D-51): github-pr-triage reviews, labels a
  pull request that passes every check `shipmill-ready`, and a person merges it. Set to
  `act`, the agents merge on green CI, and a written policy takes the place of a human read
  of every pull request: `[decisions]` sends each decision to the maintainer by its zone, so
  a change in an `ask` zone waits for their answer and one in a `never` zone, such as an
  edit of the direction, waits for their own merge

The `[autonomy]` levels (`observe`, `propose`, `act`) are the nearest thing to the skill's
throttle: each agent stage (`triage`, `fix`, `land`) and each release stage (`release`,
`deploy`, `rollback`) has its own level, so a repo opens one stage at a time. To bring a
human review back:

- Every pull request: `land = "propose"` under `[autonomy]`, or an open `shipmill-hold`
  issue while it lasts
- Some changes: raise a zone's level under `[decisions]` (such as `contract-addition =
  "ask"`), give a set of paths its own level under `[decisions.paths.<zone>]`, or list the
  paths in a `REVIEW.md` Protected areas glob, which the `protected` zone covers

[Who decides](flow.md#who-decides) lists every zone, its default, and its floor, and
[release-lanes.md](release-lanes.md#autonomy-and-the-stop-switch) every `[autonomy]` stage.
