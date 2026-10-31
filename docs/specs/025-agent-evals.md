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
      bin/shipmill, bin/uvx            send `shipmill gh` to the stub, else the real program
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
  the run needs an Anthropic token, so as with unattended sessions (D-16) the job runs only
  for a head in the repository. A fork's pull request gets no OIDC token from GitHub anyway,
  and the refusal below comes before any token step. On a fork's pull request the job fails, never skips, with the
  line `evals: a fork's pull request runs only by hand: gh workflow run evals.yml -f
  pr=<N> -f sha=<head SHA>`, the number and the event's head SHA filled in, so the change
  can't land unevaluated; the maintainer
  dispatches that run once they have read the change, and its green result for that head
  is the check that counts (D-37)

### A dispatched run is pinned to the head the maintainer read

The maintainer reads a fork's change at one commit and dispatches the run some time later.
If the run took the pull request as it is when it starts, the fork's author could push in
between, and the commit nobody read would run with an Anthropic token (shipmill/shipmill#545).
So a dispatched run names the commit it is for:

- `.github/workflows/evals.yml` gains a `sha` input beside `pr`. A dispatch with `pr` needs
  `sha`, the full 40-character head SHA the maintainer read: `gh workflow run evals.yml -f
  pr=<N> -f sha=<head SHA>`. A dispatch with `pr` and no `sha`, with a `sha` that is not 40
  hexadecimal characters, or with `sha` and no `pr` exits 1 naming the input; a plain
  dispatch without either stays the baseline run
- **Before any checkout, and before the step that mints the Anthropic token**, the run
  reads the pull request's current head SHA (`gh api repos/<repo>/pulls/<N>`, with the
  job's own token) and compares it with `sha`. When they differ it runs no case and exits 1 with `evals: the
  head of #<N> is <current SHA>, not <sha>; read the new commits and dispatch again with
  -f sha=<current SHA>`, written as the job's error and to its summary
- **After the checkout**, the run confirms that the head parent of the checked-out
  `refs/pull/<N>/merge` (`HEAD^2`) is `sha`, and exits 1 with the same line naming both
  commits when it isn't, still before the step that mints the Anthropic token: a push between
  the read and the checkout is refused too
- **The run records what it measured:** the job summary's first line is `evals: measured
  <sha> of #<N>`, and the run's `meta.json` in its artifact holds `"pr"` and `"head"` beside
  the model and commit it holds today. A green dispatched run counts for a fork's pull
  request only while that SHA is still its head: a push after the run needs a new dispatch,
  and `skills/github-pr-triage/SKILL.md` says so beside its rule on a red `evals` check

The job runs `claude plugin eval . --trust-plugin --scaffold --allow-tools <the case's
tools> --ablation none --no-publish --model <pinned> --runs 3 -j 4 --max-cost-usd 15
--json <out>`, authenticated through Workload Identity Federation (below) and with no GitHub
token in the run's environment, uploads the JSON and the HTML report as the run's
artifact, and writes the summary below to the job's summary. `--ablation none` skips the
no-plugin arm, which would double the cost to measure something the gate doesn't use.

### The Anthropic token comes from Workload Identity Federation

The job stores no Anthropic credential: it trades GitHub's OIDC token for a short-lived
Anthropic one through Anthropic's Workload Identity Federation (shipmill/shipmill#442). No
step of `evals.yml` reads `secrets.ANTHROPIC_API_KEY`, and no API key secret is used, not
even as a fallback when federation fails.

- **The permission:** the `evals` job gets `permissions: id-token: write`, the job and not
  the workflow, beside the permissions it has today
- **The ids, in `env`:** the workflow names the organization (`ANTHROPIC_ORGANIZATION_ID`),
  the service account `shipmill-evals` (`ANTHROPIC_SERVICE_ACCOUNT_ID`), and the federation
  rule (`ANTHROPIC_FEDERATION_RULE_ID`) as plain values in `env`, never as a repository
  secret or variable: they are not secrets, since a token is minted only for a GitHub OIDC
  token the rule matches. Both rules cover the Default workspace only, so the job sets no
  `ANTHROPIC_WORKSPACE_ID`
- **The rule is chosen by the event:** the schedule and every `workflow_dispatch` on the
  default branch, a fork's pinned `pr` and `sha` run included, use `shipmill-evals-main`
  (`fdrl_01Pk7bGkjpHPcaWhVmDNMffp`, subject `repo:shipmill/shipmill:ref:refs/heads/main`);
  a same-repo `pull_request` run uses the pull-request rule of shipmill/shipmill#846
  (subject `repo:shipmill/shipmill:pull_request`), whose id the workflow writes once #846
  posts it
- **The step that mints the Anthropic token** runs after the S-025-20 and S-025-21 checks
  and after `shipmill evals check`, where "Check the API key" ran. It requests GitHub's
  OIDC token with audience `https://api.anthropic.com` (from `ACTIONS_ID_TOKEN_REQUEST_URL`
  with `ACTIONS_ID_TOKEN_REQUEST_TOKEN` as the bearer, as Anthropic's GitHub Actions guide
  shows), writes it to a file in `$RUNNER_TEMP`, never in the checkout the cases clone, and
  exchanges it once at `POST /v1/oauth/token` with the rule, organization, and service
  account ids, so a rule that doesn't match shows before any case runs
- **The eval run** gets `ANTHROPIC_IDENTITY_TOKEN_FILE` pointing at that file and the three
  ids; Claude Code selects federation credentials when `ANTHROPIC_FEDERATION_RULE_ID` and
  `ANTHROPIC_ORGANIZATION_ID` are both set and exchanges the file's token itself. Its
  environment holds neither `ANTHROPIC_API_KEY` nor `ANTHROPIC_AUTH_TOKEN`, which outrank
  federation, nor `ACTIONS_ID_TOKEN_REQUEST_URL` and `ACTIONS_ID_TOKEN_REQUEST_TOKEN`, which
  would let a case mint a GitHub OIDC token for any audience; every other command that runs
  the checkout's code drops those two as well, as the GitHub token is kept out today
- **The file stays fresh:** GitHub's OIDC token expires about 5 minutes after it is issued,
  the minted Anthropic token lasts the rule's 10 minutes, and each identity token is
  single-use (its `jti`), while a run takes far longer. Anthropic's guide says the client
  re-reads `ANTHROPIC_IDENTITY_TOKEN_FILE` on each refresh, so the file must hold a new
  token before each one: the run step writes a fresh OIDC token to the file in the
  background, from a process outside the eval run's environment, for as long as the run
  lasts

When there is no OIDC token (the request variables are unset, or the request fails) or the
exchange fails, the job runs no case and writes one line, `evals: no Anthropic token from
Workload Identity Federation (<reason>), so no case ran`, to its summary: on a pull request
while the gate is off as a warning with exit 0, else as its error with exit 1, the rule
"Check the API key" follows today. The reason says which part failed and the HTTP status
of a refused exchange, never a token. A run the runner stops with `partialReason:
auth_failed` writes the same line, its reason naming the runner, and compares nothing.

A fork's pull request still fails before any token step with the S-025-18 line. The
accepted trade-off of the pull-request rule (#846): a same-repo branch's own `evals.yml`
runs on its pull request, so anyone who can push a branch here, collaborators and the App,
can mint a 10-minute Developer token that spends from the Default workspace's budget. The
`--max-cost-usd 15` cap holds for the workflow as written; a branch that edits `evals.yml`
can drop it, so the workspace's spend limit is the bound that holds.

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

- `evals/`: the cases, `cases.toml`, `scaffold.sh`, `bin/gh`, and its `bin/shipmill` and `bin/uvx` shims
- `src/shipmill/evals.py` and `src/shipmill/cli.py`: `shipmill evals check` and
  `shipmill evals compare`
- `.github/workflows/evals.yml`: the runs and their federation ids; `.github/workflows/ci.yml`:
  `shipmill evals check`
- `docs/evals.md`: how to run a case locally, record one, and read a failing gate
- `docs/postmortems/TEMPLATE.md` and the skills' "Improve the skill" sections
- `skills/github-pr-triage/SKILL.md`: a red `evals` check blocks the merge (D-37), and a
  fork's dispatched run counts only for the head SHA it recorded
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
- S-025-13: dropped in #603, see S-025-18: the command the fork refusal prints names the head SHA
- S-025-14: A run that reaches `--max-cost-usd` fails the gate with `evals: budget reached after <n> of <m> runs` and compares nothing
- S-025-15: `docs/postmortems/TEMPLATE.md` has an `## Eval case` section, and the "Improve the skill" section of every skill under `skills/` says to add a failing case under `evals/` with the lesson
- S-025-16: `shipmill evals check --gate` exits 1 naming the kinds short of the first suite's counts (8 `verdict`, 4 `decision`, 4 `finding`, 4 `fix`), and while it does, the evals pull request job reports the comparison and exits 0
- S-025-17: `skills/github-pr-triage/SKILL.md` says a red `evals` check is never proven unrelated and blocks the merge unless the maintainer accepts that run
- S-025-18: On a pull request from a fork the evals job runs no case and fails, never skips, with the line `evals: a fork's pull request runs only by hand: gh workflow run evals.yml -f pr=<N> -f sha=<head SHA>`, the pull request's number and the event's full head SHA filled in, as its error and in its summary
- S-025-19: `.github/workflows/evals.yml`'s `workflow_dispatch` takes a `sha` input beside `pr`; a dispatch with `pr` and no `sha`, with a `sha` that is not 40 hexadecimal characters, or with `sha` and no `pr` exits 1 naming the input before any checkout, and a dispatch with neither runs as the baseline
- S-025-20: A dispatched run with `pr` reads the pull request's current head SHA before any checkout and before the step that mints the Anthropic token (S-025-26), and when it differs from `sha` runs no case and exits 1 with `evals: the head of #<N> is <current SHA>, not <sha>; read the new commits and dispatch again with -f sha=<current SHA>` as the job's error and in its summary
- S-025-21: After its checkout of `refs/pull/<N>/merge` and before the step that mints the Anthropic token (S-025-26), a dispatched run whose `HEAD^2` is not `sha` runs no case and exits 1 with the S-025-20 line naming both commits
- S-025-22: A dispatched run with `pr` writes `evals: measured <sha> of #<N>` as the first line of its job summary, and its `meta.json` in the uploaded artifact holds `pr` and `head` set to that number and SHA
- S-025-23: `skills/github-pr-triage/SKILL.md` says a fork's dispatched `evals` run counts only while the head SHA it recorded is the pull request's current head, and a push after the run needs a new dispatch naming the new SHA
- S-025-24: When the evals job gets no GitHub OIDC token or the Anthropic token exchange fails, it runs no case and writes `evals: no Anthropic token from Workload Identity Federation (<reason>), so no case ran` to its summary, as a warning with exit 0 on a pull request while the gate is off and as its error with exit 1 otherwise; a run the runner stops with `partialReason: auth_failed` writes the same line and compares nothing
- S-025-25: No step of `.github/workflows/evals.yml` reads `secrets.ANTHROPIC_API_KEY`, and the `evals` job has `permissions: id-token: write`
- S-025-26: The step that mints the Anthropic token requests GitHub's OIDC token with audience `https://api.anthropic.com`, writes it under `$RUNNER_TEMP` and never in the checkout, and exchanges it with the federation rule chosen by the event (`shipmill-evals-main`, `fdrl_01Pk7bGkjpHPcaWhVmDNMffp`, for the schedule and every `workflow_dispatch`; the pull-request rule of #846 for a same-repo `pull_request` run), the organization and service account ids written in the workflow's `env`; the eval run gets `ANTHROPIC_IDENTITY_TOKEN_FILE` and those ids, and holds no `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ACTIONS_ID_TOKEN_REQUEST_URL`, or `ACTIONS_ID_TOKEN_REQUEST_TOKEN`

## Out of scope

- Cases other repositories add for their own agents: this spec covers shipmill's own
  suite only; a later spec can ship `evals.yml` as a reusable workflow once the format
  has held here
- A sandbox repository on GitHub that runs cases end to end: the offline stub replaces it,
  and the App identity and API calls stay the scripts' tests' job
- A command grader that reruns a fix's test in the run's workspace: the runner has none
  today; `fix` cases check the order of tool calls and the files written instead, and gain
  it if the runner adds one
- The federation issuer, service account, and rules in the Claude Console: the
  maintainer's steps (shipmill/shipmill#442, shipmill/shipmill#846), since the gate's App
  has no access to the Console
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
- shipmill/shipmill#442: S-025-24, S-025-25, S-025-26
- shipmill/shipmill#443: S-025-8, S-025-9, S-025-14
- shipmill/shipmill#448: S-025-10, S-025-11, S-025-12, S-025-13, S-025-16
- shipmill/shipmill#449: S-025-7
- shipmill/shipmill#545: S-025-18, S-025-19, S-025-20, S-025-21, S-025-22, S-025-23

## Verification
