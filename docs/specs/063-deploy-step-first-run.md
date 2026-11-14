# S-063: A deploy step's first run is not in production

status: approved
serves: G-2

## Problem

A change to a deploy workflow is first run by the deploy itself. CI doesn't run those steps,
so a pull request can be green and reviewed while the step it changes has never run (#970,
grouped into #1053). Three cases in connected repos in two weeks:

- A notification job ran on the deploy runner with a plain `actions/checkout`, which removes
  ignored files, including the virtualenv the production workers run from; every deploy broke
  them for over a day
- A new `pip install -c` line failed on the first deploy with `Constraints cannot have
  extras`; three sessions had read the step and none had run it
- A canary step searched a page that never holds the value it looks for, so it failed on
  every run and blocked the release workflow for days, after a review that said MERGE

The sessions said these steps had not run, and nothing acted on that. In a repo with
`[agents]`, a change under `.github/` falls in the `security` zone (spec 030), whose floor is
`notify`: the question it asks, when it asks, doesn't say whether the changed step ever ran,
and a repo that set `security = "notify"` lands it on the agents' say alone.

This spec makes "the changed deploy job has a run" something code checks on the pull request,
and adds one `doctor` check for the known way a job breaks the deploy runner's checkout.
shipmill reads the workflow files, the pull request, and the forge's runs; it starts no run
and deploys nothing (N-1, D-31). Each deploy's own checks stay in the repos that own them.

## Behaviour

### A deploy workflow and its jobs

A **deploy workflow** is a file `.github/workflows/<name>.yml` or `.yaml` that either:

- an `[environments.<name>] workflow` of `.github/shipmill.toml` names, read at the base ref
  as `decide classify` reads the levels, or
- holds a job with an `environment:` key, at the base ref or at the pull request's head (the
  key GitHub records a deployment for, which `doctor`'s environment check already reads)

A workflow's **jobs** are read from its text, as `src/shipmill/doctor.py` reads them today
(`_JOB`), not by a YAML parse: under the top-level `jobs:` key, a job starts at a line
`  <id>:` (two spaces, the job id, a colon) and runs to the next such line or the next
top-level key. A job's **display name** is its `name:` value when that is a plain scalar
holding no `${{`, else its id. The shared reading lives in a new module,
`src/shipmill/workflows.py`, which `classify.py` and `doctor.py` both use.

### A changed deploy job

For each file of the pull request that is a deploy workflow (`src/shipmill/classify.py`), the
**changed jobs** are, from the file's patch as GitHub gives it:

- each job at the head whose lines hold an added line of the patch, or whose block at the base
  holds a removed line (a hunk header's `-a,b` numbers the base side)
- every job at the head, when an added or removed line sits outside every job (`on:`, `env:`,
  `permissions:`, `defaults:`, `concurrency:`, the workflow's `name:`), when the file is added
  or renamed, or when GitHub gives no patch for it
- no job for a removed file, nor for a job that exists at the base and not at the head

Granularity is the job, not the step: a step is not addressable in a run's record, while a
job's name is.

### A run of it

A **run of a changed job** is a GitHub Actions run named on a `Proof:` line of the pull
request's body (the plan's field, read as `pr_gate.py` reads it: after an optional list
bullet, outside a code fence) by its URL,
`https://github.com/<owner>/<repo>/actions/runs/<id>`, optionally followed by
`/attempts/<n>` (that attempt) or `/job/<job id>` (the run's latest attempt), such that:

1. `<owner>/<repo>` is the pull request's repo
2. the run's `path` is the deploy workflow's path
3. the workflow file's blob at the run's `head_sha` equals its blob at the pull request's
   head (the files API's `sha`): the run ran this content, from any commit, so a rebase that
   doesn't touch the file keeps the proof
4. at least one job of that attempt is the changed job, by name: equal to its display name,
   or starting with `<display name> (` (a matrix leg) or `<display name> / ` (a reusable
   workflow's job), and every such job concluded `success`; `skipped`, `failure`, a job still
   running, or no such job doesn't count

`classify` reads `GET repos/{repo}/actions/runs/{id}` (or `.../attempts/{n}`), the attempt's
jobs, and `GET repos/{repo}/contents/{path}?ref={head_sha}` through `GhCli`
(`src/shipmill/github.py`), one read each per named run, and the pull request's body with its
change (`PullChange` gains `body`). It never dispatches, reruns, or cancels a run: every
request it makes is a GET.

How a repo runs a deploy job off production (a `workflow_dispatch` on the branch with a
non-production environment input, a dry-run input, a staging runner) is the repo's own; this
spec only reads the run.

### The `deploy-step` zone

The zone table (`skills/github-issue-triage/scripts/decisions.py` `ZONES`, `Zone` in
`src/shipmill/decide.py`) gains `deploy-step`: a change to a deploy workflow's job that no run
covers. Default `ask`, no floor, placed after `security`. Like every zone, `[decisions]` may
set it, and only the maintainer edits `[decisions]` (the `decision-policy` zone).

`shipmill decide classify --pr N` detects `deploy-step` for each changed job no named run
covers, its reason `<path>: job <id> changed and no Proof: run ran it at this content`, plus,
for each run URL on a `Proof:` line that names the file but doesn't count, why
(`run <id> ran <other path>`, `run <id> ran another content of <path>`, `run <id> has no
successful job <display name>`, `run <id> is not in <repo>`), all joined with `; ` as
`_Found` joins reasons. `--files` (paths only) detects it for each deploy workflow path, read
at the ref, with the reason `<path> is a deploy workflow, and paths alone show no run`.

`pr_gate.py` needs no change: it reads the zone from `decide classify` as it reads every zone,
so at `ask` the pull request reads NEEDS_DECISION, exit 5, with
`  needs-decision: deploy-step: <reason>`, until `--maintainer-accepted`; at `notify` it lands
with a notice; at `never` it is MAINTAINER_ONLY. The `security` zone is detected beside it as
today. A repo without `[agents]` is judged as before (spec 030).

### The `deploy runner` doctor check

`shipmill doctor` (`src/shipmill/doctor.py`) reads every `.github/workflows/*.yml` and
`*.yaml` of the checkout. A **deploy job** is a job with an `environment:` key, or any job of
a workflow `[environments]` names. Its **runner labels** are its `runs-on` value: a scalar, a
flow list (`[self-hosted, linux]`), a block list, or a mapping's `labels:`; a `runs-on` that
holds `${{` or names only a `group:` is not compared. A deploy job runs on a **shared
runner** when none of its labels is a GitHub-hosted one (`ubuntu-*`, `windows-*`, `macos-*`):
a hosted runner starts clean for each job, a self-hosted one keeps its workspace.

A job J, in any workflow, **breaks the deploy runner's checkout** when, for some deploy job D
on a shared runner with J not D, J's runner labels are a subset of D's (so any runner that
takes D can take J) and J has a step `uses: actions/checkout@<ref>` whose `with:` sets no
`path:`. For each such J, doctor prints one WARN row named `deploy runner`:

`<J's file> job <J's id> runs actions/checkout without path: on [<J's labels>], a runner <D's file> job <D's id> deploys from; its checkout cleans the workspace the deploy left: set with: path: to a folder of its own, or run it on another runner`

With at least one deploy job on a shared runner and no such J, doctor prints one PASS row
`deploy runner` naming the deploy jobs it checked. With no deploy job on a shared runner it
prints no `deploy runner` row (D-9).

The row is a WARN, not a FAIL, in this build, so it leaves doctor's exit code as any WARN
does. Several connected repos can run CI and deploy jobs on the same self-hosted runner, and
a FAIL would turn doctor red in all of them on the upgrade, before anyone has looked at whether
their checkouts are affected.

### What the agents read

- `skills/github-issue-triage/references/needs-decision.md`, Who decides: the zone table lists
  `deploy-step` and what it covers
- `skills/github-issue-resolve/SKILL.md`, the plan: a change to a deploy workflow's job names,
  on its `Proof:` line, the URL of a run of each changed job off production, at the pull
  request's content of the file, started the repo's own way; when the repo has no way to run
  it off production, the `Proof:` line says so and the maintainer is asked
- `docs/specs/030-decision-policy.md`'s zone table gains the `deploy-step` row, pointing here

## Acceptance criteria

- S-063-1: `decisions.py`'s `ZONES` and `decide.py`'s `Zone` list `deploy-step` after `security`, default `ask`, no floor; `[decisions] deploy-step = "notify"` parses, and `shipmill decide levels` lists `deploy-step` at its level
- S-063-2: `shipmill decide classify --pr N --json` on a pull request that changes a job of a workflow `[environments]` names, with no `Proof:` run, prints the zone `deploy-step` at the base's level, its reason naming the file and the job id
- S-063-3: The same holds for a workflow no `[environments]` table names that has a job with an `environment:` key at the base or the head; a pull request that changes only a workflow with neither gets no `deploy-step` zone
- S-063-4: Changed jobs follow the patch: a change inside one job's block names that job alone; a change outside every job, an added or renamed file, or a file GitHub gives no patch for names every job at the head; a removed file or a removed job names none
- S-063-5: A `Proof:` line naming a run of the same repo whose `path` is the file, whose blob of the file at its `head_sha` equals the head's, and whose attempt has the changed job (by display name, a matrix leg, or a reusable workflow's job) all concluded `success` covers that job: no `deploy-step` reason names it, and every request classify makes for it is a GET
- S-063-6: A run doesn't cover the job, and the reason says why, when it ran another workflow path, another content of the file, has no job by that name, has that job `skipped`, `failure`, or not completed, or is in another repo; a run URL outside a `Proof:` line, or inside a code fence, isn't read
- S-063-7: `shipmill decide classify --files .github/workflows/<deploy workflow>` prints `deploy-step` with the reason `<path> is a deploy workflow, and paths alone show no run`
- S-063-8: `pr_gate.py` on a pull request of a repo with `[agents]` at default levels whose classify finds `deploy-step` reads NEEDS_DECISION, exit 5, with the line `  needs-decision: deploy-step: <reason>`, and READY on the same pull request with `--maintainer-accepted` and green checks
- S-063-9: `shipmill doctor` prints a WARN row `deploy runner` naming the file and job, for a job with `uses: actions/checkout@<ref>` and no `with: path:` whose `runs-on` labels are a subset of a deploy job's self-hosted labels, and never a FAIL row `deploy runner`, so with no other FAIL it exits 0
- S-063-10: `shipmill doctor` prints no WARN `deploy runner` row when that checkout sets `path:`, when the job's labels aren't a subset of any shared-runner deploy job's, when the deploy job runs on a GitHub-hosted label, or when either `runs-on` holds `${{`; it prints a PASS row when a deploy job runs on a shared runner and none breaks it, and no `deploy runner` row when no deploy job does
- S-063-11: `needs-decision.md`'s zone table lists `deploy-step`, github-issue-resolve's `SKILL.md` says a change to a deploy workflow's job names a run of each changed job on its `Proof:` line or says the repo has no way to run it off production, and spec 030's zone table has the `deploy-step` row

## Out of scope

- Starting a run: shipmill never dispatches, reruns, or cancels a deploy workflow (N-1, D-31); the repo or the implementer starts it, its own way
- A step-level proof: a run's record names jobs, and a step's default name is too fragile to match; the job that holds the changed step is what must have run
- A deploy that is neither an `[environments]` workflow nor a job with `environment:` (a deploy on `push` with no environment): GitHub records no deployment for it either; a repo that wants the check sets `environment:` on its deploy job
- Whether the named run touched production: shipmill can't tell a staging input from a production one in another repo's workflow; the run is the repo's choice, and the maintainer sees its URL
- Pull requests from forks, whose runs live in the fork
- Other ways a job breaks a shared runner (a `clean: false` checkout of another ref, a `rm -rf` in a step): the `deploy runner` check warns of the one known case, `actions/checkout` without `path:`
- Each deploy's own checks (a canary's expected value, a constraints file's rules): they stay in the repos that own them

## Decisions relied on

- D-4: the deploy workflows come from `[environments]` in `.github/shipmill.toml`
- D-9: the `deploy runner` row shows only where a deploy job runs on a shared runner
- D-31: shipmill reads runs and starts none
- D-34: the `Proof:` line of an agent's plan carries the run
- D-48: the zone's level comes from `[decisions]` at the base, and the maintainer alone edits it

## Issues

## Verification
