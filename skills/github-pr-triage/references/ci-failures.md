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

`scripts/pr_gate.py` counts a check as green only when its status is COMPLETED and its conclusion SUCCESS (or NEUTRAL or SKIPPED). An empty rollup right after a push counts as pending, not green. Each pending check's line says whether it waits or runs: `pending: <name> (queued)`, `(running since HH:MM UTC)`, or `(pending)` for a commit status; a check queued behind another's job on the one self-hosted runner waits, it isn't stalled. Pass `--wait` to poll until every check has finished; it gives up after `--timeout` (30 min by default) with exit 3. If that happens, report which jobs are still running and ask the user rather than merge. A docs-only PR gets no exemption from the gate: wait for its slow jobs too.

Run the gate in the background (Monitor, or Bash with `run_in_background`), not as a foreground sleep loop.

A label added after the PR opens (`full-ci`) starts a second run that cancels the first. The gate then counts the first run's CANCELLED jobs as failed and exits 1 while the new run is still pending. Before calling the PR red, check `gh pr checks <n>`: if each cancelled job has a passing or pending twin from the newer run, wait on that run (`gh run watch <id>`) and treat it as the gate. Better, add the label in `gh pr create --label`, which starts one run.

## A red default branch

No pull request lands on a red default branch, save the one that repairs it (D-75). `scripts/pr_gate.py` reads the checks on the base branch's head commit, newest run per check, and a completed one there that failed makes the verdict FAILED (exit 1) with a line `base: red: <check> failed on <base>@<sha>`, however green the PR's own checks are. A base check still queued or running is not red, nor is a cancelled, skipped, neutral, or stale one. A base check queued or running whose previous attempt on that head failed is a rerun of the failure, not yet green: it reads `base: pending: <check> rerunning on <base>@<sha7>` and makes a PR that would read READY read PENDING (exit 3) until the rerun finishes, red again or green (#1310). Read the failure as above, then:

- **Caused by the code:** the PR that fixes it carries a body line `Repairs: <URL of the failed run>`: the workflow run's URL (`https://github.com/<owner>/<repo>/actions/runs/<id>`) covers each of its jobs, a job's URL (`.../actions/runs/<id>/job/<id>`) only that job, and a commit status is named by its exact target URL. The gate then prints `base: repairs: ...` instead of `base: red: ...`; check that the PR does fix that failure before merging it. A URL naming another run doesn't pass. Other PRs wait until it lands and the base reads green
- **Caused outside the code** (a 504 on a download, a connection limit, a runner lost): no PR repairs it. Re-run the failed run on the default branch, `gh run rerun <id> --failed`, through `shipmill gh` when `[agents] app_id` is set (as the App), and landing resumes once that run is green; while it reruns the gate prints `base: pending:` and reads PENDING, and a fresh pass of the gate reads it again

### The watch's BASE_RED row

github-ship-watch reports a red default branch as a BASE_RED row from `scripts/base_red.py`'s reading (spec 079). What a session handed that row does depends on the default branch's `[autonomy] revert` (`observe` when unset; an open `shipmill-hold` issue reads `act` as `propose`, D-15). Under `observe` it reports the row and changes nothing: landing waits as above. Under `propose` or `act` it reads the branch itself, `scripts/base_red.py <owner/repo> --bot-login '<slug>[bot]' --json` (without `--json` for the lines), and takes the first of these steps that applies, every write through `shipmill gh` (D-54) and every shipmill command in the pinned form, as the skill's hard rules run them, then leaves; the next reading judges what it did:

1. **RERUN_DUE: re-run once.** Re-run each run a `rerun: <run URL>` line names, once, `gh run rerun <id> --failed` through `shipmill gh`, and leave: a flaky test or a failure outside the code clears here before any merge is blamed. While it reruns, the reading is PENDING (the row's `rerun running`): wait for it, never re-run it again
2. **CANDIDATES with a run to re-run: re-run the unjudged candidates' cancelled runs.** Re-run every run a candidate's `unjudged, rerun: <run URL>` part names, the cancelled run of the failed check's workflow on that commit, `gh run rerun <id>` through `shipmill gh`, and leave; the next reading has fewer candidates. A candidate that is only `unjudged` has no run to re-run
3. **CULPRIT, or CANDIDATES with no run left to re-run, at most three and every one `revertable`: revert.** From an up-to-date checkout of the repo, open the revert with the CLI's `revert open <PR>... --run <failed run URL>` (`shipmill revert open`), naming each candidate's pull request and the failed check's run (`--json`'s `failed`, each `url`). It checks first and exits 2 with nothing written when a check fails; otherwise it pushes `revert/<N>-<sha7>`, opens the revert pull request as the App, labelled `revert`, its body holding a `Reverts #N` line per pull request, the `Repairs: <URL>` line, and a `## Plan`, reopens each issue a reverted pull request closed, and prints the pull request's URL and each reopened issue. That pull request is the repair: the next reading has `repair: #R`, and the gate hands it to tier 3. Under `propose`, `pr_gate.py` reads it BLOCKED with a `revert: [autonomy] revert is propose; a person merges it` line; under `act` it lands like any pull request, with its review record and its zones. A `revert open` that exits 2 for any reason but a conflict is a stop: report its message
4. **Anything else: ask on one issue per branch.** A candidate `not revertable` (`no pull request`, `merged by a person`, `released in <tag>`), more than three candidates, NO_GREEN, a `revert open` that exits 2 on a conflict, or a revert pull request whose own head fails the check it repairs: no revert. Close such a revert pull request (`gh pr close <R> --comment "<why>"` through `shipmill gh`), then file one issue as the App, its body's first line `<!-- shipmill:base-red <branch> -->`, naming the failed run, the candidates, and why none was reverted, and ask the maintainer on it with the [needs-decision protocol](../../github-issue-triage/references/needs-decision.md) (D-21): the question is its comment, with the `needs-decision` label. One such issue is open per branch at a time: a reading with an `asked: #Q` line (the row's `asked in #Q`) waits on its answer, which tier 4 takes up, and no second issue is filed. Once the branch reads green, the row reads `green again, close #Q`: close it with a comment naming the head, `gh issue close <Q> --comment "<branch>@<sha7> is green again"` through `shipmill gh`

## Platform-only test bugs

When PR CI covers one OS (Ubuntu-only, as treaty's does), a new test that builds a path or glob from platform-dependent state (a uid suffix, a temp-dir name, a separator) passes on the PR and fails only in the release's full matrix. In treaty, a glob `cf-*/out/*` missed Windows's `cf` session directory and skipped the rc17 release until a follow-up PR. When a reviewed PR adds such a test, or touches cleanup, paths or permissions, put the `full-ci` label on it before merging.
