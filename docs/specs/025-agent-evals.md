# S-025: Evals for the agents' instructions

status: approved
serves: G-2

## Problem

shipmill changes its own skills, briefs, and references often, and nothing checks that the
agents work as well afterwards. The tests in `tests/` prove the scripts a skill runs
(`triage_state.py`, `pr_gate.py`, `shipped.py`), never the judgment the skill's prose asks
for: a rewording in the reviewer brief or a triage rule can turn a **feature** into an
**implement**, drop a finding a reviewer used to raise, or make a headless session guess
where it used to ask, and that shows only as a bad verdict or a bad merge in a real repo.
Model updates change the same behaviour with no change in the repo at all. Asked for by
the maintainer in chat, in shipmill/shipmill#380.

What is missing is a suite of real cases the agents run when their instructions change,
with a gate that refuses a change that makes them worse and names the cases it broke.

## Behaviour

### The runner is Claude Code's

Claude Code ships an eval runner for plugins, `claude plugin eval`: it loads a plugin,
runs each case's prompt in a throwaway workspace with a fresh config and only that plugin,
`runs` times per case (3 by default), scores each run with the case's graders, and writes
`aggregate-result.json` and an HTML report. shipmill is a plugin (`.claude-plugin/`,
source `./`), so its suite is a `claude plugin eval` suite and shipmill writes no runner.
What shipmill adds is what the runner lacks for this repo: offline fixtures for GitHub,
a manifest that ties each case to the history it came from, and the comparison against
the default branch that makes the result a gate.

### Where the cases live

The suite is `evals/` at the repository's root, the runner's default eval dir, one case per
directory, grouped by the skill it exercises:

    evals/
      cases.toml                       the manifest
      scaffold.sh                      materialises a case's fixture
      bin/gh                           the offline gh stub
      github-issue-triage/feature-maintainer-filed/
        prompt.md                      the task, as a gate session would get it
        case.yaml                      schema_version "1.1", scaffold_script: ../../scaffold.sh
        fixture/                       the case's recorded GitHub state
        graders/verdict.md             a deterministic grader
      results/                         run output, ignored by git

`prompt.md` uses the runner's frontmatter only (`name`, `tags`, `runs`, `max_turns`,
`timeout_seconds`, `allowed_tools`), with `tags` holding the skill's name, and a body that
is the prompt a gate session would get, `Headless:` paragraph included where the case is
about a headless session. Everything shipmill needs beyond the runner's format sits in
`evals/cases.toml`, one entry per case:

```toml
[[case]]
path = "github-issue-triage/feature-maintainer-filed"
skill = "github-issue-triage"
kind = "verdict"                       # verdict | finding | decision | fix
source = "shipmill/shipmill#380"       # the issue, PR, or postmortem it came from
commit = "f8c08ec"                     # the repository state the case is set at
```

`shipmill evals check [--repo DIR]` validates the suite without a model and exits 1 naming
the case and the rule it breaks: a case directory missing from the manifest or a manifest
entry with no directory, a `skill` that is not a directory under `skills/`, a `tags` list
that does not name it, a `source` not of the form `owner/repo#N` or a
`docs/postmortems/` path, a `kind` outside the four, a `commit` that does not resolve, and
a case with no deterministic grader unless its kind is `finding`. CI runs it on every pull
request (`.github/workflows/ci.yml`), so a malformed case never waits for an eval run to
show.

### Offline fixtures, not a sandbox repo

Every case runs offline: no session reaches GitHub, and none needs a token.

- **The repository** is this repository at the case's `commit`: `evals/scaffold.sh`
  makes a shared clone of the checkout the run starts from into the workspace and checks
  out that commit, then copies the case's `fixture/` to `.eval/` in it
- **GitHub** is `evals/bin/gh`, a stub put first on `PATH` for the whole run (the
  workflow sets it; the runner passes `PATH` through). It is a Python 3.10 script with no
  dependencies, like the skills' scripts. It finds `.eval/` by walking up from its working
  directory, answers each read (`gh issue view`, `gh pr view`, `gh pr diff`, `gh api`,
  `gh api graphql`) from `.eval/gh/`, keyed by its arguments, so the skills' state scripts
  read the recorded state too, and answers each write (`issue comment`, `issue edit`,
  `label`, `pr create`, `pr review`, `pr merge`, `issue close`, `release`) with a
  plausible success. Every call, read or write, appends one JSON line to `.eval/gh.jsonl`
  with its kind (`read`, `write`, or `miss`), its arguments, and any `--body-file` content
- **A read with no recording** is a `miss`: the stub exits 1 with `gh: no recording for
  <args>`, as the real `gh` would for a missing object, and the line it logs fails the run
  (every case carries the shared `no-miss` grader), so a fixture that drifts from what
  the skills read shows as a failing case naming the call, never as a silent pass
- **Recording a case** is `EVAL_GH_RECORD=1`: the stub then forwards reads to the real
  `gh` and saves the answers into the case's `fixture/gh/`, and still never forwards a
  write. A case taken from history is recorded once and edited back to the moment it is
  set at (later comments removed, the state reopened), which is why it names its `commit`

A sandbox repository on GitHub was the alternative: it would exercise the real API and the
App identity end to end, but every run would write real issues and comments, need a token
in CI, race with itself across pull requests, and drift as GitHub changes. Offline
fixtures run in parallel, cost nothing but the model, and replay the same state every
time; the App identity and the API are the scripts' tests' job already.

### What a case asserts

Deterministic graders first, over what the agent did rather than how it phrased it. The
runner's graders cover them:

- **The writes** (`regex` with `target: {source: file, path: .eval/gh.jsonl}`): the
  verdict comment's first line (`Triage: **feature**.`), the labels added, a needs-decision
  question asked (the marked comment and the `needs-decision` label), and what must never
  happen, as `match: not_contains`: a `pr merge` by an implementer, a write as a person
  where the fixture's config has `[agents] app_id` (a plain `gh` write instead of
  `shipmill gh`), a guess where the case's answer is a question
- **The tools** (`tool_used`, `tool_order`): a skill loaded (`tool: Skill`), a state
  script run before a verdict, the failing test run before the fix's edit and again after
  it, `AskUserQuestion` never called in a headless case (`min: 0, max: 0`)
- **The files** (`file_exists`, `regex` on a file): a regression test added under
  `tests/` that names its issue, a spec file with a `serves:` line, a changelog fragment

A model-graded rubric (`type: llm`, judged by the runner's default judge) is used only
where the outcome is prose no pattern can check: a reviewer's finding (`kind = "finding"`)
or the substance of a question. Its `criteria` name the one fact to check ("names the
unbounded retry in `land.py` as a blocking finding"), never "a good review". A `finding`
case still carries its deterministic graders where it has any (the verdict, no merge).

A run passes when every scored grader passes. A case's pass rate is its passing runs over
its runs, and the suite's is passing runs over all runs. shipmill computes both itself
from the per-run grader results in `aggregate-result.json`, so the gate never depends on
how the runner folds runs into a case score.

### The first cases

The suite starts with at least 20 cases from shipmill's own issues, pull requests, and
postmortems, each recorded at its `commit`, and the gate turns on only once it holds them:
until then `evals.yml` runs on the triggers below and reports, and its pull request job
always exits 0. `shipmill evals check --gate` exits 1 while the suite has fewer cases of a
kind than the table asks, and `evals.yml` fails a pull request on a regression only when
it passes:

| Kind | At least | Examples |
|---|---|---|
| `verdict` | 8 | implement, feature (maintainer-filed), opportunity (a user's request), postpone, clarify; a feature written as a spec PR with "Spec for #N" and a hold line |
| `decision` | 4 | a headless session asks through needs-decision instead of guessing: a contract change against a `D-n`, a pull request touching a Protected area, a denied tool call |
| `finding` | 4 | a reviewer raises the bug a later fix or postmortem named |
| `fix` | 4 | an implementer runs the failing test first, writes the `## Plan`, opens the PR as the App, and never merges |

### When it runs

`.github/workflows/evals.yml` runs the suite:

- **On a pull request** that touches `skills/**`, `.claude-plugin/**`, `evals/**`, or
  `src/shipmill/gate.py` (the gate's `Gate session:` and `Headless:` paragraphs are part
  of every session's instructions). Skills have no `agents/**` at the root; each skill's
  `agents/openai.yaml` is under `skills/**` already
- **On a schedule**, weekly, and by hand (`workflow_dispatch`), on the default branch: a
  model update changes behaviour with no change here, and this run is the baseline the
  pull requests compare against
- **Not for a pull request from a fork:** a case's scaffold runs the repository's bash and
  the run needs the API key, so as with unattended sessions (D-16) the job runs only for a
  head in the repository. On a fork's pull request the job fails, never skips, with the
  line `evals: a fork's pull request runs only by hand: gh workflow run evals.yml -f
  pr=<N>`, so the change can't land unevaluated; the maintainer dispatches that run once
  they have read the change, and its green result is the check that counts (D-37)

The job runs `claude plugin eval . --trust-plugin --scaffold --allow-tools <the case's
tools> --ablation none --no-publish --model <pinned> --runs 3 -j 4 --max-cost-usd 15
--json <out>`, with the API key from the repository secret `ANTHROPIC_API_KEY` and no GitHub
token in the run's environment, uploads the JSON and the HTML report as the run's
artifact, and writes the summary below to the job's summary. `--ablation none` skips the
no-plugin arm, which would double the cost to measure something the gate doesn't use.

The pinned model is the one the gate's sessions run, written once in `evals.yml` as the
`EVALS_MODEL` value, so the suite measures the agents as they work; every case runs 3
times, 4 runs at once. A dispatched run may pass another `model` input to compare, and
its result never becomes the baseline.

### The gate against the default branch

`shipmill evals compare --base <main.json> --head <pr.json>` reads two runner results,
compares the cases both hold, and exits 1 when any of these holds, 0 otherwise:

- **The suite got worse:** the head's suite pass rate is below the base's by more than
  the tolerance, 0.05 (`--tolerance` changes it for a dispatched run, never in the pull
  request job)
- **A case regressed:** it passed 3 of 3 runs on the base and at most 1 of 3 on the head
- **A new or changed case fails on its own:** a case the base lacks, or whose directory
  the pull request changed, passes fewer than 2 of its 3 runs on the head; it is judged
  against itself, since the base can't run it

It prints one line per case that moved (`regressed`, `improved`, `new failing`), then the
two pass rates, so the failing check names the cases that broke. The base is the
`aggregate-result.json` of the latest successful scheduled or dispatched run on the
default branch, fetched from its artifact. When there is none, or it is older than 14 days,
or its pinned model differs from the head's, the job first runs the suite on the pull
request's merge base and compares against that. Cases the base and the head both hold are
compared by `path`; a case removed by the pull request is listed as `removed` and never
fails the gate.

A failing `evals` check is a red check like any other: github-pr-triage's `pr_gate.py`
merges only on a green rollup, so a pull request that regresses the agents does not land
until it is fixed (D-37). `skills/github-pr-triage/SKILL.md` says so beside hard rule 2:
a red `evals` check is never "proven unrelated", since it is the measure of the change
itself; only the maintainer accepting that run lets it land.

### What it costs

A pull request's run is bounded three ways: each case's `max_turns` (at most 40) and
`timeout_seconds` (at most 900), which `shipmill evals check` enforces, and the run's
`--max-cost-usd` budget. A run that hits the budget exits 2 with partial results, and the
gate then fails with `evals: budget reached after <n> of <m> runs`, never compares partial
results. The job summary reports the run's spend, turns, and wall time per skill, from
the runner's result, so the number exists before spec 023 measures the gate's sessions.

### The suite grows from mistakes

A mistake that was caught becomes a case, so a fixed class of error stays fixed:

- `docs/postmortems/TEMPLATE.md` gains a `## Eval case` section: the path of the case
  that would have caught the fault, or `none:` and why no agent's instructions were
  involved
- The "Improve the skill" sections of `skills/github-issue-triage/SKILL.md`,
  `skills/github-pr-triage/SKILL.md`, `skills/github-issue-resolve/SKILL.md`,
  `skills/github-ship-watch/SKILL.md`, `skills/product-intake/SKILL.md`, and
  `skills/shipmill-setup/SKILL.md` say: when a lesson goes into the skill, add a case under
  `evals/` that fails without it, in the same pull request

### Where it lives

- `evals/`: the cases, `cases.toml`, `scaffold.sh`, `bin/gh`
- `src/shipmill/evals.py` and `src/shipmill/cli.py`: `shipmill evals check` and
  `shipmill evals compare`
- `.github/workflows/evals.yml`: the runs; `.github/workflows/ci.yml`: `shipmill evals check`
- `docs/evals.md`: how to run a case locally, record one, and read a failing gate
- `docs/postmortems/TEMPLATE.md` and the skills' "Improve the skill" sections
- `skills/github-pr-triage/SKILL.md`: a red `evals` check blocks the merge (D-37)
- `docs/decisions.md`: D-37
- `.gitignore`: `evals/results/`

## Acceptance criteria

- S-025-1: `shipmill evals check` exits 0 on a well-formed suite and 1 naming the case and rule for each of: a case directory missing from `evals/cases.toml` or an entry without a directory, a `skill` not under `skills/`, `tags` not naming the skill, a malformed `source`, an unknown `kind`, a `commit` that does not resolve, no deterministic grader in a case whose kind is not `finding`, `max_turns` above 40 or `timeout_seconds` above 900
- S-025-2: `.github/workflows/ci.yml` runs `shipmill evals check` on every pull request
- S-025-3: `evals/bin/gh` answers a recorded read from the case's `.eval/gh/`, answers a write with success without contacting GitHub, and appends a `read`, `write`, or `miss` line with the arguments and any `--body-file` content to `.eval/gh.jsonl`
- S-025-4: `evals/bin/gh` exits 1 with `gh: no recording for <args>` on an unrecorded read, and the shared `no-miss` grader fails that run
- S-025-5: With `EVAL_GH_RECORD=1`, `evals/bin/gh` forwards reads to the real `gh` and saves their answers into the case's `fixture/gh/`, and never forwards a write
- S-025-6: `evals/scaffold.sh` leaves the workspace holding this repository at the case's `commit` with the case's fixture at `.eval/`
- S-025-7: `evals/` holds at least 20 cases from shipmill's own history, at least 8 `verdict`, 4 `decision`, 4 `finding`, and 4 `fix`, and every one passes at least 2 of 3 runs on the default branch when the spec's build ends
- S-025-8: `shipmill evals compare` exits 1 when the head's suite pass rate is more than 0.05 below the base's, when a case that passed 3 of 3 base runs passes at most 1 of 3 head runs, or when a new or changed case passes fewer than 2 of 3 head runs, and prints one line per regressed, improved, new failing, or removed case and both pass rates; it exits 0 otherwise
- S-025-9: `shipmill evals compare` computes pass rates from the per-run grader results in `aggregate-result.json`, counting a run as passed only when every scored grader passed
- S-025-10: `.github/workflows/evals.yml` runs on a pull request touching `skills/**`, `.claude-plugin/**`, `evals/**`, or `src/shipmill/gate.py`, weekly on the default branch, and by `workflow_dispatch`, and on no other pull request
- S-025-11: The evals job runs `claude plugin eval` with `--ablation none`, `--no-publish`, `--model` set to the gate sessions' model, `--runs 3`, `-j 4`, and `--max-cost-usd 15`, with `evals/bin` first on `PATH` and no GitHub token in the run's environment, uploads the JSON result and the HTML report, and writes the moved cases, both pass rates, and the spend to the job summary
- S-025-12: The pull request job compares against the latest successful default-branch run's result, and runs the suite on the merge base first when that result is missing, older than 14 days, or from a different model
- S-025-13: On a pull request from a fork the evals job runs no case and fails, never skips, naming the `gh workflow run evals.yml -f pr=<N>` command
- S-025-14: A run that reaches `--max-cost-usd` fails the gate with `evals: budget reached after <n> of <m> runs` and compares nothing
- S-025-15: `docs/postmortems/TEMPLATE.md` has an `## Eval case` section, and the "Improve the skill" section of every skill under `skills/` says to add a failing case under `evals/` with the lesson
- S-025-16: `shipmill evals check --gate` exits 1 naming the kinds short of the first suite's counts (8 `verdict`, 4 `decision`, 4 `finding`, 4 `fix`), and while it does, the evals pull request job reports the comparison and exits 0
- S-025-17: `skills/github-pr-triage/SKILL.md` says a red `evals` check is never proven unrelated and blocks the merge unless the maintainer accepts that run

## Out of scope

- Cases other repositories add for their own agents: this spec covers shipmill's own
  suite only; a later spec can ship `evals.yml` as a reusable workflow once the format
  has held here
- A sandbox repository on GitHub that runs cases end to end: the offline stub replaces it,
  and the App identity and API calls stay the scripts' tests' job
- A command grader that reruns a fix's test in the run's workspace: the runner has none
  today; `fix` cases check the order of tool calls and the files written instead, and gain
  it if the runner adds one
- Gating on cost, or reporting the gate's real sessions' spend: spec 023
- Choosing models per stage from eval results: the suite runs one pinned model; comparing
  models is a dispatched run with `--model`, read by a person

## Decisions relied on

- D-3: prose calls the release automation shipmill
- D-5: the spec is a file in `docs/specs/`, and the issue links it
- D-14: a case whose fixture sets `[agents] app_id` asserts writes go through `shipmill gh`
- D-16: a fork's pull request starts no unattended run, so its evals run only by hand
- D-34: cases replay the direction (`docs/product.md`) the skills read at their `commit`
- D-37: a change to the agents' instructions lands only when the evals don't regress

## Issues

- shipmill/shipmill#437: S-025-1, S-025-2
- shipmill/shipmill#438: S-025-3, S-025-4, S-025-5, S-025-6
- shipmill/shipmill#439: S-025-15, S-025-17
- shipmill/shipmill#443: S-025-8, S-025-9, S-025-14
- shipmill/shipmill#448: S-025-10, S-025-11, S-025-12, S-025-13, S-025-16
- shipmill/shipmill#449: S-025-7

## Verification
