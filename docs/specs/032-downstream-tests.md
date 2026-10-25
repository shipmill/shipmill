# S-032: Run downstream repositories' tests on a library's pull request

status: built
serves: G-2

## Problem

A library's change can break the repositories that depend on it, and today that shows only
after a release, when a downstream picks the release up (shipmill/shipmill#483). The rc soak
was meant to catch it; spec 029 (D-39) removed the time soak because nobody ran the rc, and
named this follow-up in its Out of scope: proof that moves before the merge. The check the
soak stood in for is a downstream's own test suite, run against the library's pull request
before it lands.

A library's maintainer today has two poor choices: read every downstream by hand before a
merge, or learn about the break from a downstream's red build after the release. Both cost
the trust G-2 asks for. The release side stays fast (G-1): the proof is spent before the
merge, so nothing waits after it.

shipmill decides and verifies; the platform executes (D-31). Here that means shipmill starts
each downstream's own test workflow, in the downstream's repository, on the downstream's
runners, and reads its result as a check on the library's pull request. It never runs a
downstream's tests itself, and never updates a downstream's dependency.

## Behaviour

### The config

A new optional section in `.github/shipmill.toml` (D-4), parsed by `src/shipmill/policy.py`
into a `DownstreamConfig` in `src/shipmill/downstream.py`, strictly as every section is: an
unknown key, a wrong type, or a value out of range fails with exit 2 naming the key.

```toml
[downstream]
app_id = 123456           # the App installed on each downstream with Actions: read and write
timeout_minutes = 30      # how long a downstream run may take, for every downstream (default 30)

[downstream.consumer-app]                   # the name is the check's: "downstream: consumer-app"
repo = "example-org/consumer-app"           # owner/name
workflow = "library-tests.yml"              # a workflow file in that repo's .github/workflows/
ref = "main"                                # the downstream's branch to run on (default: its default branch)
report_only = false                         # true: report the result, never hold the merge (default false)
timeout_minutes = 45                        # overrides the section's (optional)
```

- `[downstream]` holds two scalar keys, `app_id` (a positive integer, required) and
  `timeout_minutes` (an integer from 1 to 300, default 30), and one table per downstream.
  Any other scalar key exits 2 naming it; a section with no downstream table exits 2 with
  `[downstream] names no downstream repository`
- A downstream's name matches `[a-z0-9][a-z0-9-]{0,38}`, since it becomes a check's name
- In a downstream table: `repo` (required, `owner/name`, not the library's own repo when
  `shipmill` can tell it from `origin`), `workflow` (required, a file name ending in `.yml`
  or `.yaml`, no `/`), `ref` (optional, a non-empty branch name), `report_only` (a boolean,
  default false), `timeout_minutes` (1 to 300, default the section's). Any other key exits 2
- The same `repo` and `workflow` named twice exits 2 naming both names

A repo with no `[downstream]` section sees no change anywhere: no workflow, no check, no
`doctor` line (D-9).

### What a downstream offers

A downstream takes part by keeping one workflow the library's maintainer names in `workflow`.
shipmill needs only this interface from it; how it installs the library and which tests it
runs are the downstream's:

```yaml
name: Tests against the library
run-name: library ${{ inputs.library-ref }} (${{ inputs.shipmill-id }})
on:
  workflow_dispatch:
    inputs:
      library-repo: {required: true, type: string}   # owner/name of the library
      library-ref: {required: true, type: string}    # the full 40-character commit SHA to test
      shipmill-id: {required: true, type: string}    # an opaque id shipmill finds the run by
```

- `library-ref` is the pull request's head commit, which the downstream installs as it
  installs any git dependency (for a Python downstream, `uv add
  git+https://github.com/<library-repo>@<library-ref>` in the job, or an override). A head
  commit from a fork is reachable through the library's `refs/pull/<N>/head`, so the same
  install works for it
- `run-name` must contain `inputs.shipmill-id`: GitHub's dispatch call returns no run, so
  shipmill finds the run it started by that id among the workflow's `workflow_dispatch`
  runs created after the dispatch
- The run's conclusion is the result: `success` passes, every other conclusion fails

### The library's workflow

`shipmill init --downstream` writes the caller, `.github/workflows/downstream.yml`, into the
library (only that file; `--force` overwrites it), and refuses with exit 2 when the policy
has no `[downstream]` section:

```yaml
name: Downstream tests
on:
  pull_request_target:
    types: [opened, synchronize, reopened]
  workflow_dispatch:
    inputs:
      pr: {description: "pull request to test", required: true, type: number}
      sha: {description: "the head SHA you read; the run refuses any other", required: true, type: string}
      collect: {description: "set by shipmill: the head SHA to collect results for", type: string, default: ""}
permissions:
  actions: write          # start this workflow's collect run
  checks: write           # write one check per downstream on the pull request's head
  contents: read
  pull-requests: read
jobs:
  downstream:
    uses: shipmill/shipmill/.github/workflows/downstream.yml@v0
    with:
      pr: ${{ github.event.pull_request.number || inputs.pr }}
      sha: ${{ inputs.sha }}
      collect: ${{ inputs.collect }}
    secrets:
      downstream-key: ${{ secrets.SHIPMILL_DOWNSTREAM_KEY }}
```

The reusable workflow `.github/workflows/downstream.yml` in this repo (`workflow_call`)
checks out the library's default branch, never the pull request's code, so the config it
reads is the default branch's and a pull request can't switch off its own downstream run.
It writes the key to a file of mode 0600 outside the checkout and runs one of two commands
of a new `shipmill downstream` CLI group (`src/shipmill/cli.py`, `src/shipmill/downstream.py`):

- **`shipmill downstream start --pr <N> --app-key <file>`**, when `collect` is empty. It
  reads the pull request (its head SHA, and whether its head repository is the library's),
  and for each downstream, in config order:
  1. Writes the check `downstream: <name>` on the head SHA, or updates the one this
     workflow already wrote there with that name (found by name and app on the commit), so
     a rerun never adds a second
  2. Mints an installation token for `app_id` limited to the downstream's repo, through
     `src/shipmill/app.py` (the JWT and `mint` the gate already uses), and dispatches
     `workflow` on `ref` with `library-repo`, `library-ref` (the head SHA), and
     `shipmill-id`, `<library owner>/<library name>#<N>@<head SHA>/<name>`
  3. Records the `shipmill-id` and the dispatch time in the check's `external_id`, so the
     state lives on the forge, not in shipmill (N-2)

  Then it starts this workflow by `workflow_dispatch` on the default branch with `pr` and
  `collect` set to the head SHA, and exits 0. It exits 2 when the config doesn't parse, the
  pull request can't be read, or a check can't be written, and also, after writing every
  check with the reason, when the key file is empty or isn't a private key
- **`shipmill downstream collect --pr <N> --head <SHA> --app-key <file>`**, when `collect`
  is set. For each `downstream: <name>` check on that SHA that has no result yet, it finds
  the downstream run by its `shipmill-id`, links it as the check's details URL, and polls
  it every 30 seconds until it completes or the downstream's `timeout_minutes`, counted
  from the dispatch, passes; then it writes the result (below) and exits 0. It exits 2 when
  the config doesn't parse or a check can't be written

The collect run's job sits on the default branch's commit, not on the pull request's head,
so no job of the library's own waits as a check on the pull request: a report-only
downstream can be slow without holding the merge. Its job's `timeout-minutes` is the
longest downstream timeout plus 10. Each mode has a concurrency group per pull request
(`downstream-<N>` and `downstream-collect-<N>`) that cancels the older run; a collect run
started later picks up every check on its SHA still without a result.

### The check

One check run per downstream, named `downstream: <name>`, on the pull request's head SHA:

| Downstream | While it runs | Passed | Failed | Timed out | Couldn't start |
|---|---|---|---|---|---|
| Required (default) | `in_progress` | `success` | `failure` | `timed_out` | `failure` |
| Report-only | `completed`, `neutral` | `neutral` | `neutral` | `neutral` | `neutral` |

- The title says what happened in one line: `passed`, `failed: <the downstream run's
  conclusion>`, `timed out after <M> minutes`, `report-only: running`, `report-only:
  failed: <conclusion>`, and so on
- The summary names the library SHA tested, links the downstream run, and lists the names
  of the downstream run's failed jobs. It copies no log: a private downstream's logs stay
  in the downstream, where the library's contributors may not see them
- **Couldn't start** covers a dispatch GitHub refuses and a run never found. Its summary
  names the HTTP status and the fix: `the App <app_id> is not installed on <repo>, or lacks
  Actions: read and write`; `<workflow> doesn't exist on <ref> in <repo>, or has no
  workflow_dispatch trigger`; `no run of <workflow> has <shipmill-id> in its run-name within
  2 minutes of the dispatch; its run-name must contain inputs.shipmill-id`
- At the timeout the downstream run is left running; the check names it, and a later look
  at the downstream shows the result

### Report-only

`report_only = true` is for a downstream that is private (the library's contributors can't
read why it failed) or slow (a suite longer than the library's own CI). Its check is
`completed` with conclusion `neutral` from the moment it is written, and collect updates its
title and summary with the result, never its conclusion. The result is visible on the pull
request and holds nothing: `pr_gate.py` reads `NEUTRAL` as green.

### A pull request from a fork

A fork's head is code no maintainer has read, and a downstream's workflow would run it with
the downstream's secrets on its runners. So, as with unattended sessions (D-16) and a fork's
evals (D-37), it runs only once a person starts it:

- On a fork's pull request, `start` dispatches nothing. A required downstream's check is
  written `completed` with conclusion `action_required`, title `a fork's pull request runs
  downstream tests only by hand`, and the command in its summary: `gh workflow run
  downstream.yml -f pr=<N> -f sha=<head SHA>`, the head SHA it read filled in. A
  report-only one is written `neutral` with the same text
- A `workflow_dispatch` run with `pr` and an empty `collect` is the person's start:
  `start` dispatches every downstream for the head SHA the person named, fork or not,
  and updates the same checks (pinned as below). When `$GITHUB_TRIGGERING_ACTOR` (passed as `--actor`) ends
  in `[bot]` and the head is a fork's, `start` writes nothing and exits 2 with `a fork's
  downstream run is started by a person, not <login>`: an agent writing as the App can't
  decide to run a fork's code in another repository
- `pull_request_target` gives the run a token that can write checks on a fork's pull
  request, which a `pull_request` run from a fork can't; the reusable workflow never checks
  out or runs the pull request's code, so the token never meets it

### A dispatched start is pinned to the head the person read

The person reads a fork's change at one commit and starts the run some time later. If
`start` took the head it reads at dispatch, the fork's author could push in between, and
the commit nobody read would run in each downstream with its secrets, on a token that can
dispatch the downstream's workflows (shipmill/shipmill#545). So a person's start names the
commit it is for:

- The caller's `workflow_dispatch` gains a required `sha` input, the full head SHA the
  person read: `gh workflow run downstream.yml -f pr=<N> -f sha=<head SHA>`. The reusable
  `.github/workflows/downstream.yml` takes `sha` as an optional `workflow_call` input
  (default empty, so a caller written before it still starts) and passes it to `shipmill
  downstream start --sha <SHA>` on a `workflow_dispatch` run
- **Before it writes a check, mints a token, or dispatches anything**, `start` on a
  `workflow_dispatch` run compares `--sha` with the pull request's head SHA it reads. When
  they differ it writes nothing and exits 1 with `the head of #<N> is <current SHA>, not
  <sha>; read the new commits and start again with -f sha=<current SHA>`. The checks it
  wrote before keep their state, so a fork's stay `action_required`
- A `workflow_dispatch` start with no `--sha`, or one that is not 40 hexadecimal
  characters, writes nothing and exits 2 naming the missing input and the fix for an old
  caller, `shipmill init --downstream --force`. A `pull_request_target` start needs no
  `--sha`: its head is the event's, and a fork's is held as above
- The SHA the person named is the one tested: the downstream's `library-ref`, its
  `shipmill-id`, the checks' head, and the collect dispatch (`pr`, `sha`, and `collect` all
  set to it) carry it
- The hand-offs name the SHA: the fork hold's summary prints the command with the head SHA
  it read, and `skills/github-pr-triage/references/landing.md` gives the rerun of a flaky
  downstream as `gh workflow run downstream.yml -f pr=<N> -f sha=<head SHA>` (through
  `shipmill gh`)
- `shipmill doctor` FAILs a caller whose `workflow_dispatch` lacks the `sha` input or
  doesn't pass `sha` to the reusable workflow, naming `shipmill init --downstream --force`

### How `pr_gate.py` reads it

`skills/github-pr-triage/scripts/pr_gate.py` needs no new logic: a downstream check is a
CheckRun in `statusCheckRollup` like any job. A required downstream that failed, timed out,
or waits for a person's start (`FAILURE`, `TIMED_OUT`, `ACTION_REQUIRED`) is outside
`GREEN`, so the gate exits 1 and prints `failed: downstream: <name> (<conclusion>)`; one
still running exits 3 as pending; a report-only one (`NEUTRAL`) and a passed one count
green. Its docstring gains one line saying so. `skills/github-pr-triage/references/landing.md`
says a red downstream check is treated like any red job, that a downstream's flaky test is
rerun with `gh workflow run downstream.yml -f pr=<N> -f sha=<head SHA>` (through `shipmill
gh`), and that a
fork's `action_required` downstream check is the maintainer's to start.

### `shipmill doctor`

`src/shipmill/doctor.py`, for a policy with `[downstream]`, adds a `downstream` block:

- FAIL when `.github/workflows/downstream.yml` is missing, doesn't call
  `shipmill/shipmill/.github/workflows/downstream.yml`, lacks the `pull_request_target` or
  `workflow_dispatch` trigger, or lacks `actions: write` or `checks: write`; the fix is
  `shipmill init --downstream --force`
- FAIL when the library's repository secrets (`gh secret list`) don't include
  `SHIPMILL_DOWNSTREAM_KEY`
- Per downstream, reading through the maintainer's own `gh`: PASS when `workflow` exists on
  `ref` (or the default branch) in `repo`, declares `workflow_dispatch` with the inputs
  `library-repo`, `library-ref`, and `shipmill-id`, and has a `run-name` containing
  `inputs.shipmill-id`; FAIL naming the missing part; WARN when the maintainer's login
  can't read the downstream (a private repo of another owner), naming the repo and that
  the first pull request's check will show the result
- The App's installation on each downstream is read only when the App's key is on the
  host (`--app-key`, or the default path `src/shipmill/app.py` names); then FAIL when it
  isn't installed on a downstream or lacks Actions: read and write. Without the key, one
  WARN line says the installation is unchecked

### Docs and setup

- `docs/release-lanes.md`: a "Downstream tests" section with the `[downstream]` keys, the
  interface a downstream workflow offers, the check table, report-only, forks, the App and
  its secret, and `shipmill init --downstream`
- `skills/shipmill-setup/SKILL.md`: for a library, asks whether other repositories depend
  on it, and when they do, writes `[downstream]`, has the maintainer install the App on
  each downstream and add the secret, runs `shipmill init --downstream`, and reads the
  doctor block before it reports done
- `skills/github-pr-triage/references/landing.md`: as above

## Acceptance criteria

- S-032-1: `src/shipmill/policy.py` reads `[downstream]` with `app_id`, `timeout_minutes` (default 30), and one table per downstream with `repo`, `workflow`, `ref`, `report_only` (default false), and `timeout_minutes` (default the section's); a policy without the section loads with no downstreams
- S-032-2: The policy exits 2 naming the key for an unknown scalar key in `[downstream]`, an unknown key in a downstream table, a missing `app_id`, `repo`, or `workflow`, a `repo` that isn't `owner/name`, a `workflow` with a `/` or without a `.yml` or `.yaml` suffix, an empty `ref`, a non-boolean `report_only`, a `timeout_minutes` outside 1 to 300, or a name outside `[a-z0-9][a-z0-9-]{0,38}`; it exits 2 with `[downstream] names no downstream repository` for a section with no downstream table, and naming both names for the same `repo` and `workflow` twice
- S-032-3: `shipmill init --downstream` writes `.github/workflows/downstream.yml` with the `pull_request_target` and `workflow_dispatch` triggers, the `pr` and `collect` inputs, the four permissions, and the call to `shipmill/shipmill/.github/workflows/downstream.yml@v0` with the `SHIPMILL_DOWNSTREAM_KEY` secret; it writes no other file, refuses an existing file without `--force`, and exits 2 when the policy has no `[downstream]`; actionlint accepts the written file
- S-032-4: `.github/workflows/downstream.yml` in this repo is a `workflow_call` workflow that checks out the default branch and no ref from the pull request, runs `shipmill downstream start` when `collect` is empty and `shipmill downstream collect` otherwise, and passes actionlint
- S-032-5: For a pull request whose head is in the library's repository, `shipmill downstream start` writes one check named `downstream: <name>` per downstream on the head SHA (`in_progress` for a required one, `completed`/`neutral` titled `report-only: running` for a report-only one), dispatches each `workflow` on its `ref` with `library-repo`, `library-ref` set to the full head SHA, and `shipmill-id` `<owner>/<name>#<N>@<SHA>/<downstream>`, using a token minted for `app_id` and limited to that downstream's repo, records the id in the check's `external_id`, dispatches the library's `downstream.yml` with `pr` and `collect=<SHA>`, and exits 0
- S-032-6: A second `start` for the same head SHA updates the existing `downstream: <name>` checks instead of writing new ones
- S-032-7: When the dispatch is refused (404 or 403), a required downstream's check is `completed`/`failure` and a report-only one's `neutral`, its summary naming the status and the fix for a missing installation or a missing workflow; `start` still handles the other downstreams and exits 0
- S-032-8: `shipmill downstream collect` finds each downstream run by the `shipmill-id` in its run-name among the workflow's `workflow_dispatch` runs created after the dispatch, sets it as the check's details URL, and concludes a required check `success` for a run concluding `success`, `failure` with title `failed: <conclusion>` for any other conclusion, and `timed_out` once `timeout_minutes` from the dispatch has passed; a report-only check keeps conclusion `neutral` in every case with the result in its title
- S-032-9: When no run with the `shipmill-id` appears within 2 minutes of the dispatch, `collect` concludes a required check `failure` (a report-only one `neutral`) naming the run-name rule
- S-032-10: A check's summary names the tested SHA, links the downstream run, and lists the names of its failed jobs, and holds no line of the downstream's logs
- S-032-11: dropped in #603, see S-032-17: the command the fork hold prints names the head SHA
- S-032-12: A `workflow_dispatch` start with `--actor <person>` dispatches every downstream for a fork's pull request and updates its checks; with `--actor <name>[bot]` on a fork's pull request it writes nothing and exits 2 with `a fork's downstream run is started by a person, not <name>[bot]`; for a head in the repository a bot actor starts as a person does
- S-032-13: `start` and `collect` exit 2 when the config doesn't parse, the pull request can't be read, or a check can't be written; with an empty or malformed key file `start` writes every check with the reason (required `failure`, report-only `neutral`) and exits 2
- S-032-14: `pr_gate.py` on a pull request whose rollup holds a `downstream: <name>` CheckRun exits 1 printing `failed: downstream: <name> (FAILURE)` for `FAILURE`, likewise for `TIMED_OUT` and `ACTION_REQUIRED`; exits 3 for one `IN_PROGRESS`; and counts `NEUTRAL` and `SUCCESS` as green
- S-032-15: `shipmill doctor` with `[downstream]` FAILs naming `shipmill init --downstream --force` when the caller workflow is missing or lacks a trigger, the reusable call, `actions: write`, or `checks: write`; FAILs when `SHIPMILL_DOWNSTREAM_KEY` isn't a repository secret; per downstream PASSes for a readable workflow with the three inputs and a run-name containing `inputs.shipmill-id`, FAILs naming the missing part, and WARNs naming the repo when it can't read it; with the App's key on the host it FAILs for a downstream the App isn't installed on or lacks Actions: read and write, and without it WARNs once; a policy without `[downstream]` gets no downstream block
- S-032-16: `docs/release-lanes.md`, `skills/shipmill-setup/SKILL.md`, and `skills/github-pr-triage/references/landing.md` cover downstream tests as the Behaviour's Docs list says, and `pr_gate.py`'s docstring says a downstream check is read like any check
- S-032-17: On a pull request whose head repository isn't the library's, `start` dispatches nothing and writes each required check `completed`/`action_required` and each report-only one `neutral`, titled `a fork's pull request runs downstream tests only by hand` with `gh workflow run downstream.yml -f pr=<N> -f sha=<head SHA>` in the summary, the full head SHA it read filled in
- S-032-18: A `workflow_dispatch` start whose `--sha` differs from the pull request's head SHA writes no check, mints no token, dispatches nothing, and exits 1 with `the head of #<N> is <current SHA>, not <sha>; read the new commits and start again with -f sha=<current SHA>`; a fork's `action_required` checks are left as they were
- S-032-19: A `workflow_dispatch` start with no `--sha`, or a `--sha` that is not 40 hexadecimal characters, writes nothing and exits 2 naming the input and `shipmill init --downstream --force`; a `pull_request_target` start needs no `--sha`
- S-032-20: A `workflow_dispatch` start whose `--sha` is the head tests that SHA: each downstream's `library-ref` and `shipmill-id`, the checks' head SHA, and the collect dispatch's `pr`, `sha`, and `collect` inputs carry it
- S-032-21: `shipmill init --downstream` writes the caller with a required `sha` input on `workflow_dispatch` passed to the reusable workflow, and actionlint accepts it; the reusable `.github/workflows/downstream.yml` takes an optional `sha` `workflow_call` input and passes `--sha` to `shipmill downstream start` on a `workflow_dispatch` run
- S-032-22: `shipmill doctor` with `[downstream]` FAILs naming `shipmill init --downstream --force` when the caller's `workflow_dispatch` lacks the `sha` input or doesn't pass `sha` to the reusable workflow
- S-032-23: `skills/github-pr-triage/references/landing.md` gives the rerun of a downstream as `gh workflow run downstream.yml -f pr=<N> -f sha=<head SHA>` through `shipmill gh`, and says a fork's run is started only for the head SHA the maintainer read

## Out of scope

- A downstream's result as a release signal (D-31's "a dependent's CI" on a lane or a
  promotion): this spec proves a pull request before the merge; holding a release on a
  downstream is a later spec that can reuse the check
- Running a downstream's tests on the library's runners, or updating a downstream's
  dependency after a release: the platform's and the downstream's (D-31)
- Consumer-side cooldown (Renovate `minimumReleaseAge`, uv `exclude-newer`): the
  downstream's own tool for deciding when to take a release, as spec 029 says
- Testing the pull request's merge commit with the default branch instead of its head:
  its SHA moves whenever the default branch does, with no new run to match
- Finding downstreams on its own (GitHub's dependency graph "Used by"): the maintainer names
  them, since only they know which ones they promise not to break
- Copying a downstream's logs into the library's check
- Forges other than GitHub

## Decisions relied on

- D-4: the `[downstream]` section lives in `.github/shipmill.toml`
- D-9: `doctor` adds the downstream block and its permission checks only for a policy with `[downstream]`
- D-16: a fork's pull request starts no unattended run; its downstream run waits for a person
- D-31: shipmill starts the downstream's own workflow and reads its result as a signal, and never runs its tests or updates its dependency
- D-37: a fork's pull request runs a costly or secret-bearing check only when the maintainer dispatches it, the model for the by-hand start
- D-39: proof goes before the merge, so the soak this replaces adds no wait after it

## Issues

- shipmill/shipmill#503: S-032-1, S-032-2
- shipmill/shipmill#504: S-032-14
- shipmill/shipmill#508: S-032-4, S-032-5, S-032-6, S-032-7, S-032-11, S-032-12, S-032-13
- shipmill/shipmill#511: S-032-8, S-032-9, S-032-10
- shipmill/shipmill#513: S-032-3
- shipmill/shipmill#516: S-032-15, S-032-16

## Verification

- S-032-1: read `DownstreamConfig.parse` in `src/shipmill/downstream.py` and its call in `policy.py`, and ran `tests/test_downstream_policy.py`: the keys, the defaults (30, false, the section's timeout), config order, and no downstreams without the section hold
- S-032-2: ran `tests/test_downstream_policy.py`'s refusal table through `Policy.load` and the CLI: each bad key exits 2 naming it, `[downstream] names no downstream repository`, and a repeated `repo` and `workflow` names both tables
- S-032-3: ran `tests/test_downstream_init.py` and actionlint on the file `downstream_caller_text()` writes: only `.github/workflows/downstream.yml`, both triggers, `pr` and `collect`, the four permissions, the `@v0` call with `SHIPMILL_DOWNSTREAM_KEY`, refused without `--force`, exit 2 without `[downstream]`; actionlint printed nothing
- S-032-4: read `.github/workflows/downstream.yml` (`workflow_call`; every checkout is `github.event.repository.default_branch` with no pull request ref; `start` when `collect == ''`, `collect` otherwise) and ran actionlint on `.github/workflows/*.yml`: clean
- S-032-5: ran `tests/test_downstream_start.py`'s S-032-5 tests: one check per downstream (`in_progress`, or `completed`/`neutral` titled `report-only: running`), each dispatch with the full SHA and `<owner>/<name>#<N>@<SHA>/<downstream>`, a token per downstream limited to its repo, the id in `external_id`, the collect dispatch, exit 0
- S-032-6: ran `test_s032_6_a_second_start_updates_the_checks_it_wrote`: the second start updates the two checks and creates none
- S-032-7: ran the S-032-7 tests: a 404 or 403 dispatch, a missing installation, and one without Actions: write conclude `failure` (report-only `neutral`) naming the status and the fix, and the other downstream still starts
- S-032-8: ran `tests/test_downstream_collect.py`'s S-032-8 tests: the run is found by its id among `workflow_dispatch` runs created after the dispatch, linked as the details URL, and concluded `success`, `failure` titled `failed: <conclusion>`, or `timed_out`; a report-only check stays `neutral` with the result in its title
- S-032-9: ran the S-032-9 tests: no run within 2 minutes concludes `failure` (report-only `neutral`) naming the run-name rule, and a run found inside 2 minutes doesn't
- S-032-10: ran the S-032-10 tests and read `_result`: the summary names the SHA, links the run, lists failed jobs on one line each without a backtick, and copies no log
- S-032-11: dropped in #603
- S-032-12: ran the S-032-12 tests: a person's `--actor` dispatches a fork's head and updates its checks, a `[bot]` actor on a fork writes nothing and exits 2 with the message, and a bot starts a same-repository head
- S-032-13: ran the S-032-13 tests for `start` and `collect`: exit 2 on a bad config, an unreadable pull request, and a check that can't be written; an empty, malformed, or refused key writes every check with the reason and exits 2
- S-032-14: ran `tests/test_pr_gate.py`'s S-032-14 tests: exit 1 printing `failed: downstream: <name> (FAILURE)`, likewise `TIMED_OUT` and `ACTION_REQUIRED`, exit 3 for `IN_PROGRESS`, `NEUTRAL` and `SUCCESS` green
- S-032-15: ran `tests/test_downstream_doctor.py`'s S-032-15 tests against fake readers and GitHub, and `GhReader` read only against GitHub (a workflow on its default branch, a missing file, a repo the login can't read): the caller and secret FAILs, the per-downstream PASS, FAIL, and WARN, the App's FAIL with the key and one WARN without it, and no block without `[downstream]`
- S-032-16: read the "Downstream tests" section of `docs/release-lanes.md`, setup's "Downstream tests", landing's "Downstream checks", and `pr_gate.py`'s docstring, and ran the S-032-16 tests: each covers what the Docs list names
