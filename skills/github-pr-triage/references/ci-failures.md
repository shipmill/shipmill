# Red CI

## Read the failure

A run's logs exist only once the whole run has completed; `--log-failed` refuses while jobs are still running. Then:

```bash
scripts/failed_tests.py <run-id>        # failing tests, assertion lines, and the summary, per job
gh run list --branch <branch> --limit 3 --json databaseId,conclusion,headSha
```

## Classify each failure

**Caused by the PR** when any of these holds:
- The failing test exercises code the PR changed (grep the test for the changed symbols)
- It fails on every OS, or on the rerun too
- It passes on the default branch and on other PRs' runs

**Unrelated** when both of these hold:
- The PR doesn't touch the tested code; a docs-only PR can't break a unit test
- The failure is timing- or race-shaped: counts of periodic events, `elapsed` comparisons, timeouts, concurrent processes, a file replace or read on Windows

A history of the same test failing on the default branch or on unrelated PRs (search their failed runs with `failed_tests.py`) makes the case stronger, but a first occurrence can still be unrelated. One rerun decides: green means merge and note it; red again on the same test means treat it as caused by the PR until shown otherwise.

Classify each failed job separately: two red jobs can have two different causes.

Since the evals stopped (D-74), no pull request gets an `evals` check, a fork's included, so none is waited on and a PR touching the agents' instructions lands without one. D-37's gate is retired, so a run someone dispatched by hand blocks nothing and is never a reason to hold a PR.

## Act

- **Caused by the PR:** it's a finding. Fix it or send it back to the author, and don't merge.
- **Unrelated:** `gh run rerun <id> --failed`, then merge on a green rerun. In the report, name the test and why it's unrelated.
- **Rerun only the current head's run.** A PR's CI often cancels in-progress runs in its concurrency group (`cancel-in-progress` on `pull_request`). If the PR is rebased and pushed after you rerun a failed job on the old head, the stale rerun can cancel the new head's run, and the gate then sees CANCELLED jobs on the current head. Before rerunning, check that the run's `headSha` is the PR's `headRefOid`. If a stale rerun is going, cancel it (`gh run cancel <id>`), then rerun the current head's run in full (`gh run rerun <id>`).
- **A recurring flake (seen twice or more):** open an issue before it blocks a release. Include:
  - a table of runs (link, branch, the exact assertion or exit codes)
  - what's unknown; if the test swallows the child's stderr, the first step is printing it on failure
  - a lead from reading the code under test, labeled "not verified" until reproduced
  - a checkbox plan
- **Read the code before calling it a test problem.** Two flakes in one session were real bugs:
  - A heartbeat scheduler that advanced `due += interval` from the old due time sent a burst of beats with equal timestamps after a stall
  - A Windows `os.replace` over a file another process had open raised `PermissionError`, as did an open during a replace
- **Merging over red:** only when the user accepts the red run. Say so in the report.

## Gate details

`scripts/pr_gate.py` counts a check as green only when its status is COMPLETED and its conclusion SUCCESS (or NEUTRAL or SKIPPED). An empty rollup right after a push counts as pending, not green. Pass `--wait` to poll until every check has finished; it gives up after `--timeout` (30 min by default) with exit 3. If that happens, report which jobs are still running and ask the user rather than merge. A docs-only PR gets no exemption from the gate: wait for its slow jobs too.

Run the gate in the background (Monitor, or Bash with `run_in_background`), not as a foreground sleep loop.

A label added after the PR opens (`full-ci`) starts a second run that cancels the first. The gate then counts the first run's CANCELLED jobs as failed and exits 1 while the new run is still pending. Before calling the PR red, check `gh pr checks <n>`: if each cancelled job has a passing or pending twin from the newer run, wait on that run (`gh run watch <id>`) and treat it as the gate. Better, add the label in `gh pr create --label`, which starts one run.

## A red default branch

No pull request lands on a red default branch, save the one that repairs it (D-75). `scripts/pr_gate.py` reads the checks on the base branch's head commit, newest run per check, and a completed one there that failed makes the verdict FAILED (exit 1) with a line `base: red: <check> failed on <base>@<sha>`, however green the PR's own checks are. A base check still queued or running is not red, nor is a cancelled, skipped, neutral, or stale one. Read the failure as above, then:

- **Caused by the code:** the PR that fixes it carries a body line `Repairs: <URL of the failed run>`: the workflow run's URL (`https://github.com/<owner>/<repo>/actions/runs/<id>`) covers each of its jobs, a job's URL (`.../actions/runs/<id>/job/<id>`) only that job, and a commit status is named by its exact target URL. The gate then prints `base: repairs: ...` instead of `base: red: ...`; check that the PR does fix that failure before merging it. A URL naming another run doesn't pass. Other PRs wait until it lands and the base reads green
- **Caused outside the code** (a 504 on a download, a connection limit, a runner lost): no PR repairs it. Re-run the failed run on the default branch, `gh run rerun <id> --failed`, through `shipmill gh` when `[agents] app_id` is set (as the App), and landing resumes once that run is green; a fresh pass of the gate reads it again

## Platform-only test bugs

When PR CI covers one OS (Ubuntu-only, as treaty's does), a new test that builds a path or glob from platform-dependent state (a uid suffix, a temp-dir name, a separator) passes on the PR and fails only in the release's full matrix. In treaty, a glob `cf-*/out/*` missed Windows's `cf` session directory and skipped the rc17 release until a follow-up PR. When a reviewed PR adds such a test, or touches cleanup, paths or permissions, put the `full-ci` label on it before merging.
