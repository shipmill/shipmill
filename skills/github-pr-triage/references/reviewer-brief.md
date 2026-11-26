# Reviewer brief

Fill in the `{...}` fields and send one brief per PR, all in one message so the agents run in parallel (`subagent_type: general-purpose`, `isolation: "worktree"`). Don't hand the reviewer a verdict; hand it the PR's specific risks.

**The rubric, the direction, the plan (spec 024), and the history (spec 073).** Read them in a checkout at `origin/<default>` after `git fetch`, never on the PR's branch, which could rewrite its own rules; run each as `uvx shipmill==0.179.3 <command>`, the release this plugin pins, in every session:

- `{review_rubric}`: `shipmill review show --path <file> ...` with every file of `gh api repos/{owner}/{repo}/pulls/<N>/files --paginate --jq '.[].filename'` (gh fills in `{owner}/{repo}`; `gh pr diff --name-only` fails with HTTP 406 past 300 files), which merges the root `REVIEW.md` with those of the directories the diff touches: Important rules (`I-n`, a subdirectory's cited as `skills/I-2`), the nit cap, Protected areas, and the free sections as they are. Without a `REVIEW.md`, drop the field
- `{direction}`: `shipmill product show --section goals --section non-goals --section quality`. In a component, whose config sets `[product] home`, it also holds the product's goals and non-goals, under `## Product goals (<owner/home>)` and `## Product non-goals (<owner/home>)` (spec 071). When it exits 2 on the home's direction (it can't read it, or it breaks the grammar), no finding or verdict on new behaviour is given until the maintainer fixes it: name the problem in the report, leave each PR that adds new behaviour unreviewed, and go on with the rest; never fill the field with `--local`, which leaves the product's non-goals out. Without `docs/product.md`, drop the field
- `{cap}`: the most nits a review raises, the merged rubric's `cap:` (5 when its files set none); without a `REVIEW.md`, drop the clauses that name it
- `{plan}`: the PR body's `## Plan` section as written (`gh pr view <N> --json body`); without one, drop the field
- `{history}`: `shipmill review history <N>`, the touched area's history pack: the reverts, settled decisions, incidents, and other open pull requests on the files the PR touches, each item with an id `H-n`. When it prints `none` for every kind, drop the field and its step 3 check and the History part of the final report
- `{base}`: the PR's base branch, its `baseRefName` (`gh pr view <N> --json baseRefName`): the default branch for a PR on it, and for a stacked PR its base PR's branch, so the rebase and the test proof read the PR's own commits, never its base PR's

Without a `REVIEW.md`, a `docs/product.md`, and a plan, the brief is as before: drop the lines that hold the dropped fields.

## Open PR

```text
Review GitHub PR #{N} of {owner/repo} ("{title}", fixes #{issue}). The repo is at {repo_path}, and you are in an isolated worktree of it. Goal: a merge-or-refuse verdict. Do NOT push, comment on GitHub, or merge.
{In a headless gate session:} Run one allowlisted command per Bash call: `git -C <dir>`, not `cd <dir> &&`; no variable assignments, `;` or `&&` chains, or pipes into tools not on the list. Set a variable by writing its `VAR=value` lines to a file under `tmp/` with the Write tool, then running `uv run --env-file tmp/<name>.env <command>`, whose command is still one the delivery hook allows (D-82); never a `VAR=value uv run` or `env VAR=value` prefix, nor `uv run env`, which the hook refuses, and import the package through the project's install (`uv run pytest`), not `PYTHONPATH=.`. A chained call is denied whole when any part isn't on the list; rerun its commands as separate calls. A command that isn't on the list at all is a finding: stop that step and report it (github-issue-triage's needs-decision.md, A denied tool call is a decision).

{context: what the PR claims, what it's stacked on, whether the default branch has moved, and any peer session working near it (don't touch its worktree)}

{When the repo has a REVIEW.md:} The repo's review rubric, from the default branch (root and the touched directories):
{review_rubric}

{When the repo has docs/product.md:} The product's direction, its Goals, Non-goals, and Quality bar:
{direction}

{When the PR body has a ## Plan section:} The PR's plan:
{plan}

{When review history lists an item:} The touched area's history, from the default branch:
{history}

1. `git fetch origin`, `git fetch origin pull/{N}/head:review-{N}`, `git checkout review-{N}`, then {for a PR whose head branch is in {owner/repo}, not a fork:} `git branch --set-upstream-to=origin/{head_branch} review-{N}` (the PR's `headRefName`), so `shipmill worktrees` finds the PR by its head branch once it merges, as it does by the number in `review-{N}` (D-91). Rebase onto origin/{base} locally and report which files conflicted and how you resolved each:
   - CHANGELOG: keep every entry from both sides, and check that new entries sit under Unreleased, not inside a released section. {When `.github/shipmill.toml` sets `[changelog] fragments`: the PR adds its entry as a new fragment in that folder and leaves `CHANGELOG.md` alone; `changelog_guard.py check --base origin/{default}` must exit 0, and on a line added under Unreleased move the entry into the fragment it names}. On a Breaking entry it refuses, move the entry under the `[bump] major` heading it names; never drop the marker
   - A count or version both sides changed: recompute it from each side's baseline and confirm by running the test
2. Run the project's fast checks and the tests of the files the PR touches: {check_commands}. Leave the full suite to the PR's CI, which `pr_gate.py --wait` waits on before any merge{, unless the repo's CI doesn't run it: then run `{suite_command}` once, in the foreground (timeout 600000 ms), through the machine-wide queue}. Known flaky tests: {flakes}. For any other failure, say whether it also fails on origin/{default}.
   {When the brief's plan has a `Kind:` line:} Test proof (spec 076): after the rebase and before any fix of your own, write the PR's body (`gh pr view {N} --json body`) to `tmp/pr-{N}-body.md` with the Write tool and run `{test_proof_script} <kind> --base origin/{base} --plan-file tmp/pr-{N}-body.md -- <the touched files' test command>`, `<kind>` being the plan's `Kind:` (`fix` or `refactor`) and `{tests}` in the command standing for the first commit's test files (`uv run pytest -q {tests}`). `UNPROVEN` is a finding quoting its `fail:` lines; `NO_TEST` on a `Kind: fix` plan is a finding, since the plan claimed a test; `BASELINE_RED` is the base's failure, reported as such and not a finding against the PR (D-75 already holds landing on a red default branch). Still judge what the script can't: that the first commit's test fails for the issue's reason (read the run's output it prints), and that each `Tests changed:` reason holds.
3. Read `git diff origin/{default}...HEAD` and the linked issue (`gh issue view {issue}`). Look for:
   - Correctness: {pr_specific_risks, for example: edge-case inputs to test, concurrent callers, platform-only paths, and the cases that must NOT change}
   - Invariants: when the plan or the linked issue lists invariants, find where the code holds each one and what could break it
   - Security: secrets reaching output, logs, error messages, or another concurrent caller's output; input validation on every entry path
   - Whether it resolves the issue fully or only partially
   - The repo's rules in {rules_files, e.g. AGENTS.md, CLAUDE.md}
   - The settled decisions the diff touches: run `{decisions_script} find $(git diff --name-only origin/{default}...HEAD)` and check the diff against each Rule. A departure is a finding unless the PR records a superseding entry the user approved. Also run `{decisions_script} check` if the PR edits the log
   - Whether the code matches the design in the issue's triage comment, for a contract change
   - For a PR that builds a spec (its issue links `docs/specs/NNN-<slug>.md`): run `{specs_script} coverage --spec NNN` and read each test it lists. Check the test really asserts its criterion: the script finds names, you judge substance. A criterion this PR delivers with no test, or a test whose assertions don't match its criterion's statement, is a finding. If the PR moves the spec to `status: built`, check that its Verification section says how each criterion was checked on the code, not just that the tests pass, and run `{specs_script} check`
   - Whether CHANGELOG, README, and docs agree with the code
   - {When the brief holds a plan:} Whether the diff departs from the plan (files it didn't name, steps it skipped, proof it doesn't hold) without the plan saying why: a finding
   - {When the brief holds a plan:} A PR whose linked issue or title calls it a bug fix with a new or changed test, or a refactor, while its plan has no `Kind:` line: a finding (spec 076)
   - {When the brief holds the direction:} A change that hits a non-goal (cite `N-n`), or breaks a quality-bar item (cite `Q-n`): a finding. A change that hits a non-goal of the product, listed under `## Product non-goals (<owner/home>)`, is a finding too, citing `<owner/home> N-n`
   - {When the brief holds the history:} For each `H-n`, whether the PR contradicts it: `contradicts`, `consistent`, or `unrelated`, with one line of reason. A `contradicts` the PR's body or plan doesn't explain (why the revert, the answer, or the incident no longer holds) is a finding citing the `H-n`
   - {When the brief holds a rubric:} A change that breaks an Important rule: a finding citing its id (`I-n`, or `skills/I-2` for a subdirectory's). A nit never blocks the verdict: report at most {cap} nits, the rubric's `cap:`, and drop the rest
4. Reproduce each real bug before fixing it. Commit each small fix with proof that fails on the old code, by github-issue-resolve's [test gate](../../github-issue-resolve/references/test-gate.md) (a new regression test only when no existing test, type check or boundary model catches it), on review-{N}, and rerun the affected checks. Leave larger problems as findings.
5. Final report, under 250 words: verdict (MERGE / MERGE AFTER SMALL FIX / REFUSE), rebase status, test results, {when the plan has a `Kind:` line: a "Test proof" line with `test_proof.py`'s verdict (`PROVEN`, `UNPROVEN`, `NO_TEST`, or `BASELINE_RED`), which goes into the review record,} the findings you fixed with file:line, then each finding you did not fix as `F-1`, `F-2`, and so on: its file and line, the claim in one sentence, and `blocking` when the verdict stands on it or `nit`{ and the `I-n`, `N-n`, `Q-n`, or `H-n` each cites}{, at most {cap} nits}{, a History part with one line per `H-n` and its word, `contradicts`, `consistent`, or `unrelated`, which goes into the review record}, and the HEAD SHA of review-{N}, the head you reviewed: the landing session pushes it and records your verdict on it with `shipmill review record`, and `pr_gate.py` reads an agent's code PR UNREVIEWED until that record covers its head. A REFUSE names at least one blocking finding: a report whose REFUSE names none is sent back to you, and a second reviewer checks each blocking finding before the refusal is recorded (spec 075).
```

## Post-merge review

Use this for a PR that merged before anyone reviewed it. Same shape, but the branch starts from the default branch:

```text
Post-merge review of GitHub PR #{N} of {owner/repo} ("{title}"). It is already merged. Your job is to find bugs the merge shipped. Do NOT push, comment on GitHub, or open PRs.

1. `git fetch origin`, then `git checkout -B review-{N} origin/{default}`. Find what landed: `gh pr view {N} --json commits,mergeCommit,body`, plus any follow-up commits touching the same code ({follow_ups}).
2. {pr_specific_risks}. Also check it composes with PRs that merged next to it and touched the same code ({neighbours}).
3. Run the project's checks, then fix each real bug on review-{N} with proof by the test gate (the CHANGELOG entry goes under Unreleased → Fixed, or in a new fragment under `### Fixed` when `.github/shipmill.toml` sets `[changelog] fragments`).
4. Final report, under 250 words: CLEAN / BUGS FOUND, findings with file:line, test results, HEAD SHA.
```

## Verify a refusal

Use this for each PR whose reviewer reports REFUSE, before anything is recorded or handed back (spec 075). Send it to a fresh agent (`subagent_type: general-purpose`, `isolation: "worktree"`), never the first reviewer and never the landing session itself, all such agents in one message, and in the foreground in a headless session, as reviewers are. Give it the PR, the reviewed head, and each blocking finding's id, file and line, and claim, copied from the report; never the first reviewer's verdict or the rest of its report. Fill in `{base}`, the PR's `baseRefName`, and, for a PR whose head branch is in the repo, `{head_branch}`, its `headRefName`: the verifier's worktree holds a branch named for the PR, never a detached HEAD, because the gate's prune keeps a detached worktree forever (S-002-4) and finds a landed PR only by such a name or its upstream (D-91).

```text
Verify findings on GitHub PR #{N} of {owner/repo} ("{title}") at head {reviewed_head}. The repo is at {repo_path}, and you are in an isolated worktree of it. Goal: settle each finding below by the code. Do NOT push, comment on GitHub, merge, or fix anything.
{In a headless gate session:} the same one-command-per-Bash-call paragraph as the Open PR brief.

The findings:
{findings: one line each, `F-n`, file:line, the claim in one sentence}

1. `git fetch origin`, `git fetch origin pull/{N}/head`, then `git checkout -B review-{N}-verify {reviewed_head}`, your own branch (the first reviewer's worktree holds `review-{N}`), then {for a PR whose head branch is in {owner/repo}, not a fork:} `git branch --set-upstream-to=origin/{head_branch} review-{N}-verify`, so `shipmill worktrees` finds the PR once it merges (D-91). Read `git diff origin/{base}...HEAD` and the code each finding names.
2. Mark every finding with exactly one of:
   - `confirmed`, with the failure scenario: the input or steps, what happens, and what should; run it where it can be run (a failing test or command and its output), otherwise trace it through the code with file and line
   - `rejected`, with the file and line of the code that already handles it, or of the rule or test that shows the claim is wrong
   - `minor`, with one line saying why it is real and doesn't block: a note
3. Agree or reject by the code, never by default. A finding you can neither show failing nor show handled is not confirmed: mark it `minor` with the note starting `unproven:`. Save a security finding (a secret reaching output, a missing check on an entry path) you can't settle either way: mark it `confirmed`, with what you could not rule out.
4. Final report, under 250 words: one line per `F-n` with its mark and its scenario, handling code, or note, and the head you checked.
```

## Risks worth naming, by PR type

| PR changes | Ask the reviewer to check |
|---|---|
| Parsing or input types | Every input path (argv, JSON payload, stdin lines, tool calls, config and env, defaults); malformed values refused; schema matches what the parser accepts |
| Logging, errors, redaction | Secrets across concurrent callers and threads; secrets in the serialized form of a value object |
| Retry, locking, files | Platform-only branches; masking real errors; a no-op on other platforms; readers as well as writers |
| Audit or lint rules | False positives on already-compliant code; false negatives in nested types; suggested fixes that would themselves be rejected |
| Defaults or limits | Upgrade path for existing state; every doc and spec that names the old value |
| Charges, credits, quotas | Charge before or after the action; refund when it fails; a double charge or double refund; access granted without payment |
| Status fields | Every transition; a status a record can get stuck in; what the user sees in each |
| Several writes in one operation | A crash between two writes: what stays in the database, who repairs it, whether a transaction covers it |
| Handlers, jobs, webhooks | A repeated request, a double submit, a retried job, two workers on one record: idempotency and races |
| Queries and records | Access to another user's records; data written by the old code; the migration and its way back |
