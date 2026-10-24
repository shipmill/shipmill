# Changelog

All notable changes to shipmill, named release-lanes before 0.3.0. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/). shipmill releases itself with its own
bot.

## [Unreleased]

## [0.66.0] - 2026-10-24

### Added

- `chains.py link` reads the checkout's `[product]` table (spec 038): in a component (`[product] home`) it exits 2 before any write when a reference names another repo than its own, and the coordinator's new `link --product P --child C` writes through `shipmill gh --product <P's repo>`, exiting 2 without `[product] repos` or for a reference outside the listed repos and the home repo (#587)
- The coordinator's view of upstream reports (spec 038, D-47): github-issue-triage's `upstream_state.py <owner/home>`, run in the home repo's checkout, reads every open `upstream` report of the home repo (through gh) and of each repo `[product] repos` lists (through `shipmill gh --product`) as ROUTE_DUE, ASKED, ANSWERED, ROUTED, CLOSE_DUE, or UNTRUSTED, counting a report's sub-issues and `Depends on` lines as its children and never reading an untrusted author's report past its author (D-16); in a checkout with `[product] repos`, github-ship-watch's `watch_state.py` reports UPSTREAM_DUE as an agent's row, so the gate starts the coordinator's session, UPSTREAM_ASKED, UPSTREAM_UNTRUSTED, and a failing run as one UPSTREAM_UNREADABLE row (#588)

## [0.65.0] - 2026-10-24

### Added

- The coordinator's token (spec 038, D-47): in the product's home repo, `shipmill app-token OWNER/NAME --product` and `shipmill gh --product OWNER/NAME` use a second App token over the repos `[product] repos` lists under OWNER, asking contents read, issues write, pull requests read, and metadata read; a token GitHub grants wider than asked is refused, it is cached apart in `app-token-product-<owner>.json`, `gh --product` refuses the commands that write code or pull requests, the home repo's gate checks the App on every listed repo before it starts a session, and a `[product]` naming the checkout's own repo exits 2 (#585)

## [0.64.0] - 2026-10-24

### Added

- Config: an optional `[product]` table (spec 038, D-47), `home = "owner/name"` in a component repo or `repos = [...]` in the product's home repo, read strictly by `shipmill plan` and the gate alike; `repos` needs `[agents] app_id`, and in a component `shipmill gh -R` and `shipmill app-token` for any repo but the checkout's origin exit 2 naming D-47 before a token is minted (#584)
- An open issue labelled `upstream`, a report of a fault another repo owns, reads UPSTREAM in `triage_state.py`, right after UNTRUSTED and before every other state, and is never an action; a new `--home OWNER/NAME` words its note (`routed by OWNER/NAME`, else `no coordinator: waits for the maintainer`, plus `asks the maintainer` while its needs-decision question has no reply), and a closed one never reads SUSPECT_CLOSE. `watch_state.py` passes the config's `[product] home` as `--home` and lists the reports in ISSUES_OPEN as `UPSTREAM #N`, so the gate starts no session for one, and `setup_state.py --fix` creates the `upstream` label wherever it creates `needs-decision` (spec 038) (#586)

## [0.63.0] - 2026-10-24

### Changed

- D-47 supersedes D-45: the role that owns delivery across a product's repos is the coordinator, which routes `upstream` reports, closes stand-ins and builds the queue, and never plans the product; `docs/design/product-layer.md` says so (#580)

## [0.62.0] - 2026-10-24

### Added

- `docs/design/product-layer.md` gains an Across repos section: components stay in their repo while the product's manager owns every cross-repo step, a bug found in another repo's module reported in the agent's own repo, the manager as a role on a home repo rather than a store, the forge's own cross-repo objects, why no external tracker is needed, and decisions D-45 and D-46 (#338)

## [0.61.0] - 2026-10-21

### Removed

- `[agents] plugin_update` (spec 031): a config that sets it, whatever its value, now exits 2 with `[agents] plugin_update was removed (spec 031); delete it`, and `doctor` fails the policy with that line instead of warning; delete the key (#553)

## [0.60.0] - 2026-10-21

### Deprecated

- `[agents] plugin_update` (spec 031): gate sessions load the installed plugin and report its lag, so the gate ignores the key whatever its value and runs no `claude plugin update`; `doctor` warns naming it, and the next minor release refuses it. `shipmill upgrade` no longer offers `plugin-update`, `shipmill init` no longer writes it, and a release closes an open `plugin-update` upgrade issue as withdrawn; `gate --json` drops the `plugin` field of the daily update (#552)

### Changed

- The install guide, the policy reference, and the shipmill-setup and github-ship-watch skills describe the pinned CLI, the marketplace serving release tags, gate sessions loading the installed plugin, `requires`, and the `plugin_update` deprecation, and no longer describe a gate paused on a stale plugin (#552)

## [0.59.1] - 2026-10-21

### Fixed

- A gate held because PyPI doesn't serve the plugin version sessions load no longer reads healthy: `shipmill status` reads the gate's last `PYPI_WAIT` tick as a wait on you (`paused: plugin <version> waits for PyPI`), and `doctor` asks PyPI for that version itself, a WARN on 404 or when PyPI doesn't answer; each names the fix, the release's `publish.yml` run, or a new one with `gh workflow run publish.yml --repo shipmill/shipmill -f tag=v<version>` (#569)
- A gate whose launchd job runs a pinned `--tool` or the pre-org `@v0` source is told to rewrite its job with `uvx shipmill@latest --repo <checkout> launchd <repo>` when its CLI lags, not `uv tool upgrade shipmill`, which never changes the job; a job on `shipmill@latest` is told to run now with `launchctl kickstart` (#570)

## [0.59.0] - 2026-10-21

### Changed

- `shipmill gate` no longer pauses on a lagging plugin: `PLUGIN_STALE` is gone, and the tick starts the session and reports, each on one line with its fix, every install of `shipmill@shipmill` older than the latest release (with `claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope <scope>`), an install keyed on the gate's linked worktree that no session loads (delete its entry in `~/.claude/plugins/installed_plugins.json`; shipmill never writes that file), the gate's own CLI when it lags (`uv tool upgrade shipmill`, or `uvx shipmill@latest --repo <checkout> launchd <repo>` for a launchd job on the old `@v0` source), and a config whose `requires` the version sessions load doesn't meet; with `[agents] notify = true` the first gate on a host to find a lagging install sends one desktop notification per release (marker `~/.cache/shipmill/plugin/<version>.notified`). The one plugin hold left is PyPI answering 404 for the version sessions load: the tick reads `PYPI_WAIT: plugin <version> waits for PyPI` and the next tick tries again. `doctor` and `shipmill status` report the same as WARNs and rows, with no line saying a gate starts no session, and `shipmill launchd` writes jobs that run `shipmill@latest` unless `--tool` names another source (spec 031) (#551)

## [0.58.0] - 2026-10-20

### Added

- `shipmill downstream collect` finds each downstream run `downstream start` dispatched by the `shipmill-id` in its run-name, links it as the check's details URL, and concludes the check: `success`, `failure` naming the run's conclusion, or `timed_out` for a required downstream, always `neutral` with the result in the title for a report-only one, and a failure naming the run-name rule when no run shows within 2 minutes; the summary names the tested SHA, links the run, and lists its failed jobs, never a log line (#511)
- The weekly retro passes `--goals`, adds a Goals section to its tracking comment, and proposes `Direction: G-n met for N weeks` and `Direction: G-n stalled for N weeks` issues, at most one open per goal; it never edits the direction itself (#512)
- `intake_state.py --plans` reads each goal plan issue's state from the maintainer's reply: PLAN_OPEN, PLAN_ANSWERED (`decline` or `edit`), PLAN_ACCEPTED until every `feature` and `fix` item is filed (and in the named milestone), PLAN_FILED, PLAN_MALFORMED naming the line, and PLAN_DECLINED with the reason; only an OWNER, MEMBER, or COLLABORATOR other than the `--bot-login` answers, a `plan-revised` comment makes an earlier answer stale, and an accept older than the body's last edit reads PLAN_OPEN (#514)
- `watch_state.py` reports a PLANS row, from `intake_state.py --plans`, listing the goals whose plan is due and the plan issues that are malformed, answered, or accepted, and `shipmill gate` starts a session for it; with `--trusted-only` a plan issue the `--bot-login` didn't open is UNTRUSTED and starts none. Intake never reads a `goal-plan` issue as feedback, and triage reads a plan carrying intake's `Triage: **plan**` comment as TRIAGED (#515)
- `shipmill doctor` checks downstream tests for a policy with `[downstream]`: a FAIL naming `shipmill init --downstream --force` for a caller workflow missing a trigger, the reusable call, `actions: write`, or `checks: write`, a FAIL for a missing `SHIPMILL_DOWNSTREAM_KEY` secret, a line per downstream on its workflow's inputs and run-name (a WARN when your login can't read it), and, with the App's key on the host (`--app-key`), a FAIL for a downstream the App isn't installed on; `docs/release-lanes.md` gains a "Downstream tests" section, and the setup and landing skills cover them (#516)
- `requires = ">=X.Y"` at the top of `.github/shipmill.toml` names the oldest shipmill the config is written for: an older CLI, `watch_state.py`, or `setup_state.py` exits 2 with the bound, its version, and how to update, before it refuses a key it doesn't know; `shipmill init` writes it, and `shipmill upgrade --apply` raises a lower one (#549)

### Fixed

- `shipmill gate` with `[agents] prs = true` starts a session when a push lands on an open pull request a session already looked at, instead of waiting out `retry_hours`: `watch_state.py --json` adds each listed pull request's head SHA to its `PRS_OPEN` row, and the gate's fingerprint counts it (#546)

### Changed

- The plugin pins its CLI: the skills, their scripts, and the hooks run `uvx shipmill==<the version in the plugin's plugin.json>` from PyPI instead of the `@v0` tag's source or a `shipmill` on PATH, and a missing or malformed `plugin.json` exits 2 naming it; the wheel ships `shipmill/.claude-plugin/plugin.json`. The marketplace entry names the release tag, which each release's stamp moves with `plugin.json` and every pinned line, and the gate, `doctor`, `status`, and `watch_state.py` read the latest release from that ref instead of `gh release view` (spec 031) (#548)

## [0.57.0] - 2026-10-20

### Added

- An `evals` workflow that runs the agents' eval suite with `claude plugin eval` on a pull request touching the skills, the plugin, `evals/`, or the gate's session paragraphs, weekly, and by hand, and compares a pull request's run against the default branch's baseline (or its merge base's when the baseline is missing, stale, or another model's); a fork's pull request fails naming `gh workflow run evals.yml -f pr=<N>`, and `shipmill evals check --gate` names the kinds short of the first suite's counts; until the suite holds them, the pull request job reports and exits 0 (#448)
- `shipmill product measure <G-n> "<metric> <comparison> <target>"` writes or replaces a goal's measure line and `--clear` removes it, leaving every other line as it was, also in a Goals section moved to `docs/product/`; shipmill-setup offers each goal a measure from the registry and writes only the ones the maintainer gives (#506)
- `shipmill downstream start` writes a `downstream: <name>` check per `[downstream]` repository on a pull request's head and dispatches each one's workflow with a token minted for the App and limited to that repository, then dispatches the collect run; a fork's pull request waits for a person's `workflow_dispatch`, and the reusable `.github/workflows/downstream.yml` runs it from the default branch's checkout, never the pull request's code (#508)
- `retro.py gather --goals` reports per goal of `docs/product.md`: the issues and pull requests that served it this week and the week before (by the latest trusted verdict's `Serves:`, a spec's `serves:`, or a plan's `Serves:`), whether its measure is met with the weeks in a row, and whether it stalled; then the `quality bar` row, the verdicts postponed for no goal or declined for a non-goal with the most-cited one, and the agent pull requests whose plan names no goal; a checkout off `origin/HEAD` or a direction `shipmill product show` refuses exits 2 (spec 027) (#509)
- product-intake's `intake_state.py --plans` reports PLAN_DUE for a goal with no open plan: `no-work` when no draft or approved spec, triaged issue, pull request plan, open opportunity, or plan item serves it and its newest plan wasn't declined, and `requested in #N` for a trusted `goal-plan` request; with `--wip N` a `no-work` plan waits for room (PLAN_WAITS) and a request never does (#510)
- `shipmill init --downstream` writes `.github/workflows/downstream.yml`, the workflow that runs the `[downstream]` repositories' tests on each pull request through shipmill's reusable `downstream.yml`; it refuses a policy without `[downstream]` and an existing file without `--force` (#513)

### Fixed

- An interactive gate session (`claude --bg`) that `claude agents` lists as `failed`, or as `done` within 60 seconds of its launch, no longer counts as an attempt toward `retry_hours`: the next tick reads `SESSION_DEAD`, names the session and its state with `claude logs <id>` as the fix, starts another, and holds the same findings for `retry_hours` after 3 dead in a row, as a headless one does (#500)
- github-issue-triage's `chains.py link` writes as the App: run from a checkout whose `.github/shipmill.toml` sets `[agents] app_id`, the native blocked-by or sub-issue relation and the `Depends on` line it adds to the body go through `shipmill gh` (from PATH, else through uvx), and a `shipmill gh` exit 2 stops the link with its message, never retried with plain `gh`; reads stay on plain `gh`, and without app_id nothing changes. Before, both writes ran as the maintainer's gh login (D-14) (#526)

## [0.56.0] - 2026-10-20

### Added

- A stable release that promotes an rc names in its plan reason how many of the issues the rc fixed have a requester who confirmed its pre-release notice, such as `2 of 3 requesters confirmed`; the count is reported only and never makes a lane due or holds one (S-021-8) (#395)
- `shipmill evals compare --base <main.json> --head <pr.json>` gates a pull request's eval run against the default branch's (spec 025, D-37): it reads the runner's `aggregate-result.json` (`schemaVersion` 1), counts a run as passed only when every scored grader passed and a run that errored, aborted, or skipped its paid graders as failed, exits 1 when the suite's pass rate drops more than 0.05 (`--tolerance`), a case falls from 3 of 3 to at most 1 of 3, or a new or `--changed` case passes fewer than 2 of 3, prints each regressed, new failing, improved, and removed case and both pass rates, fails with `evals: budget reached after <n> of <m> runs` on a run stopped at its budget, and exits 2 on a missing or malformed `aggregate-result.json` (#443)
- Delivery hooks: the PreToolUse hook refuses a `git push` to the default branch (`default-branch-push`, off with `[hooks] default_branch = false`) and a `cp`, `mv`, or `rsync` of a `[hooks] private` path out of the repo (`private-paths`) (#444)
- The docs name the delivery hooks: github-pr-triage's rule 8 and landing reference say which forms a hook refuses, shipmill-setup asks for `[hooks] private` paths and reads `doctor`'s hooks block, `docs/release-lanes.md` documents the `[hooks]` keys, and `docs/install.md` says the hooks come with the plugin, need `uv`, and what happens when one can't start (#447)
- `docs/direction.md`, a guide for the maintainer to the product's direction (`docs/product.md`): what it holds, what the agents do with it, its structure, and the `shipmill product` commands that change it; linked from the README, `docs/flow.md`, shipmill-setup, and `shipmill doctor`'s direction FAIL line (#498)
- The policy reads an optional `[downstream]` section: the App id, a run timeout, and one table per downstream repository (`repo`, `workflow`, `ref`, `report_only`, `timeout_minutes`), refusing a malformed one with exit 2 naming the key; nothing runs on it yet (#503)
- Tests prove the PR gate reads a `downstream: <name>` check like any check: `FAILURE`, `TIMED_OUT`, and `ACTION_REQUIRED` fail it, a running one keeps it pending, and `NEUTRAL` and `SUCCESS` count as green (#504)
- A goal in `docs/product.md` may carry one measure on the line under it, `  measure: <metric> <comparison> <target>`, naming a metric from a fixed registry (`deploy_frequency`, `lead_time_median`, `human_touch`, ...) and a target in its unit: `shipmill product check` refuses an unknown metric or comparison, a target in the wrong unit, and a misplaced or second measure line with its file, line, and rule; `shipmill product show --json` gives every goal a `measure` key, and the PR gate and `specs.py check` accept the line (spec 027) (#505)
- product-intake's `plans.py`: `check` holds a goal plan's body to its grammar (marker, goal, headings, Work items, Milestone), naming the line and rule for each problem, and `items` lists a plan's items with the issue filed for each (#507)

### Removed

- `[lanes.stable] min_soak_days`, deprecated in 0.53.0: a policy that sets it, whatever its value, exits 2 with `[lanes.stable] min_soak_days was removed (spec 029); delete it, or run shipmill upgrade --apply stable-every-batch`, and `shipmill doctor` reports that as its policy failure. `shipmill upgrade --apply stable-every-batch` still reads and fixes such a config. `promote_from = "rc"` promotes the newest rc once a stable trigger is due, whatever its age, and its reason says how old the rc is, `promotes v1.5.0rc2, cut 1 day(s) ago`, instead of `soaked 1 day(s)` (#464)

### Fixed

- CI now runs `shipmill product check` and `shipmill review check`, as spec 024 says, so a malformed `docs/product.md` or `REVIEW.md` can no longer reach main (#493)
- An eval case's write through `shipmill gh`, or `uvx ... shipmill gh` headless, now reaches the offline `gh` stub instead of failing for want of the App's token: `evals/bin` gains `shipmill` and `uvx` shims that send `shipmill gh` to the stub, logged with `"via": "shipmill"` so a grader still catches a plain `gh` write, and pass every other command to the real program (#494)
- A release proposal, an issue, a comment, or release notes too long for one command-line argument no longer fails with `Argument list too long`: shipmill passes every body to `gh` on stdin, and one over GitHub's limit (65,536 characters for an issue or comment, 125,000 for release notes) is cut to fit and ends with a line linking the changelog that holds the full text (#499)
- Gate: a lost Claude Code login no longer burns the retry window. Before a launch the gate runs `claude auth status --json`, and when Claude Code isn't logged in it starts no session and reports `CLAUDE_AUTH` with the fix (`claude auth login`), sending one desktop notification per failure episode with `[agents] notify = true`; `doctor` checks the login too. A headless session whose log holds an authentication failure, or that ended within 60 seconds of its launch (by its log's last write) with no result in its log, doesn't count toward `retry_hours`: the next tick launches again and reads `SESSION_DEAD`, naming the dead session, how many died in a row, and its log's last line; after 3 dead sessions in a row the same findings wait for `retry_hours` again. `shipmill status` reports both, and github-ship-watch's `watch_state.py` reports a gate whose sessions end dead as `GATE_SESSIONS_DEAD` (#500)

### Changed

- shipmill-setup no longer edits a repo's CLAUDE.md, AGENTS.md, or CONTRIBUTING.md when it turns changelog fragments on: `setup_state.py`'s new `CHANGELOG_RULES` warning names each line there that mentions Unreleased as file and line, and leaves the change to the maintainer (D-42) (#496)

## [0.55.0] - 2026-10-19

### Added

- A deployment tells its fixed issues: after a tag's first successful deployment to an environment of `[environments]`, read from GitHub deployments, the watch reports UNANNOUNCED for each closed issue whose fix the tag holds and the environment didn't run before, and `shipped.py --environment <name> --post` comments `Deployed to <environment> in <tag>.` under a `<!-- shipmill:available: <environment> <tag> -->` marker, once per issue and environment (spec 021) (#393)
- The watch reads the requester's answer to a pre-release notice: REQUESTER_CONFIRMED when the issue's author reacted 👍 to it, and REQUESTER_REPORT when they commented after it or reacted 👎, for a session to hand to triage as a possible regression; anyone else's reaction gives no row, an issue a bot opened has no requester, and neither row is an action or labels, holds, or reopens anything (spec 021) (#394)
- `shipmill milestones` (`--json` for one object) prints spec 022's MILESTONE_WAITING and MILESTONE_OVERTAKEN rows, the overtaken one with its number, the version to rename it to, and the rename through `shipmill gh api`; github-ship-watch's `watch_state.py` runs it when a lane sets `milestone = true`, so `shipmill status --rows` and `--json` show both rows, MILESTONE_OVERTAKEN is an action (exit 1), and under "watch" a pass renames an overtaken milestone (#475)

### Changed

- Product intake reads the direction's Goals and Non-goals: each opportunity issue says `Serves: G-n` or `Serves no goal`, the accept question to the maintainer says the same, and an opportunity serving no goal is never proposed for acceptance on demand alone (#488)

## [0.54.0] - 2026-10-19

### Changed

- Docs: no stable release is described as a soaked rc. `docs/release-lanes.md` shows a stable lane that releases main's head after every green batch, the fix-forward, revert, hotfix, and rollback order for a bad batch, and a "Stable releases" section on the breaking hold, `promote_from = "rc"` with no age, and `min_soak_days`, deprecated in 0.53.0 and refused from the next minor, with `shipmill upgrade --apply stable-every-batch` as the migration; `README.md`, the site, shipmill-setup's lane table, and the triage rubric's "a breaking release waiting for the maintainer" row follow (#463)

### Fixed

- Plugin: the fix printed for a stale shipmill@shipmill install (the gate's `PLUGIN_STALE` tick, `doctor`, `status`, the setup checklist, and github-ship-watch's `SHIPMILL_OUTDATED`) runs `claude plugin marketplace update shipmill` before the update or reinstall, and the gate's daily update with `plugin_update = true` refreshes the marketplace once before updating its checkout's installs, reporting a failed refresh and still trying the update; `claude plugin update` alone left an install behind when Claude Code's copy of the marketplace predated the release (#477)

## [0.53.0] - 2026-10-18

### Added

- `shipmill status` reports MILESTONE_WAITING, with its reasons, while a lane with `milestone = true` has a milestone with no open issues whose specs aren't built or shipped, and MILESTONE_OVERTAKEN, with the rename to the version the lane cuts next, when a stable tag of an open milestone's version exists while the milestone has open issues; both are read with the release's own planner, which no milestone changes the bump of (spec 022) (#398)
- Skills: the agents work toward `docs/product.md` (spec 024, D-34). github-issue-triage's verdict on new behaviour names the goal it serves (`Serves: G-n`), gives won't fix for a non-goal and postpone for a feature serving no goal, still hands a user's request serving none to product intake, and leaves bug fixes alone; github-issue-resolve writes the pull request's `## Plan` (Serves, Files, Order, Proof) before the code and updates it before a push that departs from it; the reviewer brief carries the `REVIEW.md` rubric, the direction's Goals, Non-goals, and Quality bar, and the plan, with nits capped; github-pr-triage never merges an edit to the direction on its own judgment; shipmill-setup asks the maintainer for the direction when it connects `[agents]`, never inventing a goal. A repo without `docs/product.md` triages, plans, and reviews as before (#408)
- Delivery hooks: after an edit of `docs/product.md`, a file under `docs/product/`, or a `REVIEW.md`, the PostToolUse hook runs `shipmill product check` or `shipmill review check` and shows a failed check's output to the model (#445)
- Hooks: `shipmill doctor`, for a repo with `[agents]`, prints a line per delivery-hook rule, on or off and why, and self-tests the hook of the plugin install a session would load on a refused `gh pr merge 1 --rebase`, failing with the fix when it doesn't refuse, the install has no `hooks/hooks.json`, `uv` isn't on PATH, or a settings file sets `disableAllHooks`; it warns when it can't read what a session loads (the plugin listing, a settings file) and when `origin/HEAD` is unset. A headless gate runs the same self-test before a launch and, when it fails, starts no session and reads `HOOKS_FAILED`; an interactive gate reports it and starts the session (#446)
- A breaking stable candidate gets its `Ready to release` issue, with the breaking entries listed first, even in a run that releases rc or dev, and only a person's hand start releases it: `shipmill plan --actor` (from `$GITHUB_TRIGGERING_ACTOR`) skips stable for a `[bot]` login or a run naming no actor, and land closes the issue once the release is tagged (#462)

### Fixed

- Hooks: when uv is missing, can't find or install a Python 3.11 or newer, or `hooks/delivery.py` is missing, the hook prints one line naming `shipmill doctor` and exits 1, so the command runs unchecked instead of every shell command being refused (#458)

### Changed

- A trigger never releases a breaking change on stable: when quiet time, a window, or a milestone makes the stable lane due and its pending entries (at the rc's base, for a promotion) sit under a `major` heading, `shipmill plan` proposes it with the cause "a breaking change waits for the maintainer's decision" under `act` too; starting the stable lane by hand still releases it (#459)
- `shipmill init` writes a stable lane that releases after every batch of merges (`quiet_minutes = 30`), with no `promote_from`, `min_soak_days`, `schedule`, or `milestone`, and the rc lane only as comments, so the `release.yml` it derives has no schedule; `shipmill upgrade --apply stable-every-batch` takes `min_soak_days` out of `[lanes.stable]`, keeps `promote_from`, and adds `quiet_minutes = 30` only to a table with no trigger, every other byte left as it was (#461)

### Deprecated

- `[lanes.stable] min_soak_days`: still honoured for this minor release, with a `shipmill doctor` WARN naming spec 029 and `shipmill upgrade --apply stable-every-batch`; the next minor release refuses it. `shipmill doctor` also warns about a prepare or land job lacking `issues: write` for a config whose stable lane can hold a breaking change (`[bump] major`), in the one warning per job it already gives (#460)

## [0.52.0] - 2026-10-18

### Added

- Evals: `shipmill evals check [--repo DIR]` validates the agents' eval suite, `evals/`, without a model, exiting 1 with one line per case naming the rule it breaks (an unlisted case or a listed one with no directory, a skill not under `skills/`, tags not naming it, a malformed source, an unknown kind, a commit that does not resolve, no deterministic grader outside a finding case, `max_turns` above 40 or `timeout_seconds` above 900); a repository with no case under `evals/` passes, and CI runs it on every pull request (#437)
- Evals: eval cases run offline with no token: `evals/bin/gh` answers reads from a case's recorded fixture, logs every read, write, and miss to `.eval/gh.jsonl` without contacting GitHub, and records reads with `EVAL_GH_RECORD=1`; `evals/scaffold.sh` sets a case's workspace at its commit with its fixture at `.eval/`, and the shared `no-miss` grader fails a run that read anything unrecorded (#438)
- The policy reads an optional `[hooks]` section in `.github/shipmill.toml`: `default_branch` (true or false, default true) and `private` (a list of globs, default none), refusing any other key or a wrong type with exit 2 naming the key (#440)
- Plugin hooks: in a repo whose `.github/shipmill.toml` has `[agents]`, a PreToolUse hook refuses a plain `gh` write while `app_id` is set, a rebase merge, and a force push without a lease pinned to a commit, each with the command to run instead (#441)

### Changed

- Every skill's "Improve the skill" section says a lesson comes with a case under `evals/` that fails without it, in the same pull request; the postmortem template gains an `## Eval case` section; and github-pr-triage never counts a red `evals` check as unrelated: it blocks the merge unless the maintainer accepts that run (#439)

## [0.51.0] - 2026-10-18

### Added

- The notices on fixed issues name their stage: a dev or rc tag posts `Released in <tag> (pre-release).` with the pin command and that a plain install gets it with the next stable release, a stable promotion of an rc tells every issue the rc fixed, and each notice starts with a `<!-- shipmill:available: <stage> <tag> -->` marker so a rerun posts nothing; a new optional `[notices]` section in `.github/shipmill.toml` sets the `pin` and `install` commands, with `{version}`, `{tag}`, and `{name}` (spec 021) (#392)
- `specs.py split NNN --milestone <title>` puts every proposed build issue in the feature issue's milestone, as a `milestone:` line and a `milestone` key in `--json`, and the spec gate files each with `gh issue create --milestone` (#399)
- `triage_state.py` reports OFF_MILESTONE, an action, for an open build issue whose feature issue (its sub-issue parent in the repo) is in a milestone the build issue isn't in, so a goal's milestone holds every build issue the release lane reads (spec 022) (#400)
- `shipmill product add|edit|retire` and `shipmill review add-rule|protect|set-cap|retire`
  (`--dir DIR` for a subdirectory's `REVIEW.md`) edit one structured line of
  `docs/product.md` or a `REVIEW.md` and print it: an added id is one above any the file's
  git history held, a missing section is written in its fixed place, a moved section's file
  is edited, every other line stays byte for byte, and a file its check refuses exits 2
  without a write (#404)
- `shipmill doctor` fails a repo whose config has `[agents]` and no `docs/product.md`, or one
  `shipmill product check` refuses, naming the fix; a repo without `[agents]` gets no direction
  line (#405)
- `specs.py check` refuses a spec that isn't built without a `serves:` line naming the goals of `docs/product.md` it serves (or `quality bar`), or naming a goal the direction doesn't list, sections moved to `docs/product/` included; a repo without a direction is checked as before (#406)
- PR triage: `pr_gate.py` reads the direction and `REVIEW.md` from the default branch (spec 024). It refuses an agent's pull request (authored by `--bot-login`, or any named with `--agent`) whose body has no `## Plan` with `Serves:`, `Files:`, `Order:`, and `Proof:`, or whose `Serves:` names a goal `docs/product.md` doesn't list (exit 6, REFUSED); a repo without `docs/product.md` and a person's pull request skip the check. A pull request whose files match a `REVIEW.md` Protected areas glob, or that edits `docs/product.md` or `docs/product/`, waits on the maintainer (exit 5, NEEDS_DECISION) until `--maintainer-accepted`. It reads them at the checkout's `origin/HEAD`, or at `origin/<base branch>` when that isn't set; outside a checkout, or when the default branch holds neither file, it gates exactly as before (#407)

### Changed

- `milestone = true` makes a lane due only once the milestone's goal is built: every spec whose Issues section names one of its issues, or whose file one of its issues links, says `status: built` at main's head, and each of their build issues closed by a merged pull request in the candidate's base (the rc's base, for a promotion), closed as not planned, or confirmed by a trusted close-confirmed comment; the plan names what holds it, and a milestone no spec belongs to is due as before (spec 022) (#397)
- `shipmill gate` starts no session while the `shipmill@shipmill` install a session in its
  checkout would load is older than the latest release (D-35, superseding D-23's "the
  session still starts"). It reads that install at any scope, user scope included, as
  Claude Code picks it (the most specific scope installed for the checkout's project: local,
  project, user, then managed; a linked worktree's project is its main checkout), after the
  daily `plugin_update` when that is on. The tick reads `PLUGIN_STALE: ...` with the
  install's version and scope, the latest release, and the command that updates it, stops
  and starts no session, and the next tick with a current install launches; a failed read
  is printed and the session starts. `gate --json` adds `loaded`. `shipmill status` shows a
  paused gate as waiting on you with that command, and github-ship-watch's
  `SHIPMILL_VERSION` (so `status`, `doctor`, and the setup checklist) names the install a
  session loads, warning when it is behind (#417)

### Fixed

- `triage_state.py` links a PR to an issue by a closing keyword only in the PR's title outside backticks or at the start of a body line outside a code fence, the rule `shipped.py` reads, so a PR that quotes "Closes #N" mid-line no longer reads as the issue's fix or makes DONE_NOT_CLOSED close it (#416)

## [0.50.0] - 2026-10-18

### Fixed

- Shipped notices: a PR's closing keyword counts only at the start of a body line, in its title, or as GitHub's closing link, never quoted mid-line or in backticks, and a number with no issue behind it is skipped with a note instead of stopping the watch and the gate with exit 2 (#368)
- github-issue-triage: post the close-confirmed comment once the issue is closed, never with `gh issue close --comment`, which posts it before the close so it never counts (D-29); specs 005 and 014 note D-30's trusted upgrade issues (#369)

### Deprecated

- Config: `[roadmap]` is deprecated (D-32). A config with it still loads and the policy validates it, but nothing reads it, and `doctor` warns that the work-in-progress limit is now `[agents] wip`; the next minor release refuses `[roadmap]` (#377)

### Added

- Config: `[agents] wip = N` (1..100) is the work-in-progress limit github-issue-triage reads (`triage_state.py --wip N`): at most N issues in progress at once; without it there is no limit (D-32) (#377)
- `shipmill product check|show|ids` reads the product's direction, `docs/product.md` (spec 024): check exits 1 naming the file, line, and rule each broken heading, item, id, or moved section breaks; show prints it, or only `--section` sections, as Markdown or `--json`; ids lists every id with its text, moved sections in `docs/product/` resolved (#402)
- `shipmill review check` exits 1 naming the file, line, and rule when a `REVIEW.md`'s Important, Nits, or Protected areas section breaks its format, at the root or in a subdirectory, and passes free sections and a repo without one; `shipmill review show [--path FILE ...] [--json]` prints the rubric for the changed files, the root's and their directories' merged, each item with its file and the smallest cap (#403)

### Removed

- Product intake: the roadmap plan is gone (D-32). The skill no longer proposes, ranks, or creates milestones; `roadmap_state.py` and the milestone-proposal template are removed, and a milestone is the maintainer's own list of what a version must hold. Grouping requests into opportunities stays (#377)

## [0.49.0] - 2026-10-17

### Changed

- github-pr-triage lands a pull request with a squash merge, and the base of a stack with a merge commit, instead of matching the repo's history; it never rebase-merges (D-33) (#378)

## [0.48.0] - 2026-10-10

### Changed

- A headless gate now asks the config-upgrade question: with `--trusted-only`, `triage_state.py` trusts an issue the release workflow opened as the Bot `github-actions[bot]` when it carries both the `shipmill-upgrade` label and the `<!-- shipmill-upgrade: <id> <version> -->` marker as its first line, so `watch_state.py` reports it as UPGRADE_PENDING instead of UNTRUSTED; any other `github-actions[bot]` issue stays UNTRUSTED (D-30) (#314)
- shipmill.dev: the tab icon is the gear mark from the page and its preview image, and the preview's source, `site/og.html`, sits next to `og.png` to redraw it (#361)

### Added

- Triage: a right close can end SUSPECT_CLOSE. `triage_state.py` reads each recently closed issue's last 5 comments (paging back to the close only when all 5 came after it) and drops the SUSPECT_CLOSE row when a comment after the last close has `<!-- shipmill:close-confirmed -->` as its first line and comes from an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` App; an outsider's marker never counts, and a reopen and a new close re-arm it. The skill's step 7 and `references/comments.md` give the comment (#332)

### Fixed

- Triage: `triage_state.py` no longer reads SUSPECT_CLOSE for an issue closed by a commit that names it only mid-line when a same-repo merged pull request closes it, by GitHub's link or a closing keyword in its title or body; a commit with no such pull request, or one that only mentions the issue or never merged, still reads SUSPECT_CLOSE (#363)

## [0.47.0] - 2026-10-10

### Added

- Triage: an issue labelled `human` is a person's item, triaged from the start and never dispatched; with every hold closed it reads HANDOFF_DUE until a trusted `<!-- shipmill:handoff -->` comment, WITH_PERSON until an assignee or trusted author replies `done`, then VERIFY_DUE, and NO_ASSIGNEE with no assignee; one closed as completed by a person with a `## Check` section reads VERIFY_CLOSED (never SUSPECT_CLOSE) until a trusted `<!-- shipmill:verified -->` comment, and `--wip` never counts a person's item (#342)
- Triage: `chains.py show <owner/repo#N>` prints the chain an issue belongs to, every issue it waits on and every issue that waits on it (natively or as its parent), recursively and each once across repos, with its executor (`agent`, or `person: @login` for a `human` item) and its state (CLOSED, BLOCKED with the open holds, READY); a READY item in a repo whose `.github/shipmill.toml` has no `[agents]` table reads NO_GATE and the command exits 1. With `--trusted-only` it never reads or follows an untrusted author's issue, and on a forge without issue relations it walks the `Depends on` lines alone. github-ship-watch reports each such item in a chain of the repo's open issues as a `CHAIN_NO_GATE` row, and a walk that fails as one `CHAIN_UNREADABLE` row, both actions for a person (#343)
- Watch and setup: github-ship-watch lists a person's item waiting on its assignees in ISSUES_OPEN as `WITH_PERSON #N (@login ...)` (triage_state.py's `--json` line for WITH_PERSON now carries an `assignees` list), and shipmill-setup's `setup_state.py` wants the `human` label wherever it wants `needs-decision` and `--fix` creates both (#344)
- Triage: the skill documents chains of work, in a Chains section and its references: the two link forms (`Depends on` lines and GitHub's blocked-by and sub-issue relations) and `chains.py link`, a person's item (the `human` label, each of its states, and what a session does for it, from the hand-off comment to checking the done report against its `## Check`, with the needs-decision question when the check can't run), a parent's close, and `chains.py show`; the spec gate links build issues with `chains.py link`, and `docs/flow.md` walks a chain across three repos with a person's step in it (#345)
- shipmill.dev: a link preview image (`og.png`, 1200×630) with `og:image` and `twitter:card`, so a shared link shows the page's headline and conveyor instead of text only (#351)

### Fixed

- `chains.py show --trusted-only`, the watch's chain walk, judges an issue's author by the repo the walk started from (D-16), not by the issue's own repo, where an outsider owns their own: an issue in another repo is followed only when its author is the starting repo's owner or collaborator (one `gh api repos/<repo>/collaborators/<login>` per login, cached) or the `--bot-login`, so an outsider's issue linked to a public one no longer makes every watch tick report CHAIN_UNREADABLE (#355)
- `shipmill status` knows spec 017's person's-item states: HANDOFF_DUE, VERIFY_DUE, and NO_ASSIGNEE are listed to triage, WITH_PERSON is parked with the logins it waits on (`(@login ...)`), and VERIFY_CLOSED is a closed item to check on its own `verify close` line, no longer counted among the open issues; CHAIN_NO_GATE and CHAIN_UNREADABLE wait on you on a `chain` line with their fix instead of under "other" (#358)

## [0.46.0] - 2026-10-10

### Added

- `docs/design/product-layer.md` maps the product layer (feedback, opportunities, specs, build items, decisions, milestones, releases), who moves each object, and the gaps ranked, starting with #334, #336, #337 and #338
- Triage: a GitHub issue dependency (blocked by) or a sub-issue holds a triaged issue as a "Depends on" line does, in any repo, listed once with its text holds and marked `(native)` or `(child)`; a parent's note starts with `children K/N closed`, and a forge that can't read the relations falls back to the text holds with one note (#340)
- Triage: `chains.py link <owner/repo#N> --blocked-by <owner/repo#M>` and `--child <owner/repo#C>` write a dependency both as GitHub's native relation (blocked by, or sub-issue) and as a `Depends on` line in the issue's body, adding only the half that is missing; when the forge refuses the relation it writes the line alone and says `text only:` (#341)

### Changed

- shipmill.dev: a new landing page with the run of #312 to 0.41.2 as its proof, the seven stages, per-stage control, release lanes, and a contact address, `hello@shipmill.dev` (#346)

## [0.45.0] - 2026-10-09

### Changed

- `shipmill init` derives `release.yml`'s schedule from the policy (spec 015): the hourly tick
  only when a lane sets `milestone` or the stable lane promotes with `quiet_minutes`, one cron
  per UTC window time when the lanes are schedule-only, and no `schedule:` at all when every
  run starts from a push or by hand, so a private repo stops paying for idle hourly runs. The
  starting policy still gets the hourly tick. `shipmill init --caller` rewrites only
  `release.yml` from the existing policy (with `--ci` and `--runs-on`), and `shipmill doctor`
  warns on a `schedule` check naming each cron the policy needs that `release.yml` lacks (#324)

### Added

- Self-hosted runner docs: `docs/release-lanes.md` gains "Self-hosted runners" (the `runs-on` input, `init --runs-on`, what the runner needs, and the settle wait holding it) and "The schedule in `release.yml`"; shipmill-setup asks for the runner on a private repo, warns when a self-hosted runner also runs deploys, and rewrites `release.yml` with `init --caller --force` after editing the policy; `setup_state.py` warns with `RUNNER_SHARED` when a deploy or dispatch workflow runs on shipmill's runner labels while a lane sets `quiet_minutes` (#325)

### Fixed

- With `[agents] app_id` set, a gate session's prompt names the App's `<slug>[bot]` login and
  tells the session to pass `--bot-login '<slug>[bot]'` to `triage_state.py` and
  `watch_state.py`, and github-issue-triage's steps 1 and 7 say so too, so a session's own
  reads no longer show an App question the maintainer answered as NEEDS_DECISION, or, with
  `--trusted-only`, an issue the App opened as UNTRUSTED; a repo without an App gets the same
  prompt as before (#329)

## [0.44.0] - 2026-10-09

### Fixed

- A stable promotion skips when `.github/workflows/` changed since the rc it would promote, since the release's CI runs main's workflows on the rc's code, and the same run cuts the next rc instead, which carries the new CI and soaks before it is promoted (#317)

### Added

- The reusable `prepare.yml` and `land.yml` take a `runs-on` input, a runner label or a JSON
  list of labels, that every one of their jobs runs on; it defaults to `ubuntu-latest`, so a
  caller that passes nothing runs as before. `shipmill init --runs-on <runner>` writes it
  into `release.yml`'s `prepare` and `land` jobs, a label bare and a list as compact JSON in
  single quotes, and exits 2 naming the value for one that isn't a runner label or a
  non-empty JSON list of labels, writing no file; without the flag `release.yml` is the one
  `init` wrote before (spec 015) (#323)

## [0.43.0] - 2026-10-09

### Fixed

- `shipmill status --rows` and `--json`, and the summary after a failed App check, read with the App's `--bot-login` when the config sets `[agents] app_id` and its key is on this host, so an App question the maintainer answered no longer reads NEEDS_DECISION (#311)
- `shipmill settle-minutes` prints 0 when the policy's mode is `off`, so the settle job no longer sleeps billed runner minutes after every push for a run that then skips; the release lanes reference adds the cost on private repositories, and shipmill-setup reads the repo's visibility and, on a private repo, offers the cheaper setups with rough monthly figures before choosing lanes (#318)

### Changed

- shipmill's site is at `https://shipmill.dev/`, and its health URL is
  `https://shipmill.dev/health.json`; the old `shipmill.github.io/shipmill` addresses
  redirect there. The package homepage and the plugin's homepage point at it (#315)

## [0.42.0] - 2026-10-09

### Added

- Config upgrades are asked about and carried out: `watch_state.py` reports an open `shipmill-upgrade` issue as `UPGRADE_PENDING` (or in NEEDS_DECISION while its question waits), github-ship-watch asks the maintainer through the needs-decision protocol under `[autonomy] upgrade = "propose"` and opens the upgrade pull request as the App on `shipmill/upgrade-<id>`, github-pr-triage merges it only on an accepting answer from an owner, member, or collaborator or under `act`, and `shipmill upgrade --propose` takes the `shipmill-upgrade-later` ("not now") label off only once a newer shipmill release changes the upgrade (#281)

### Fixed

- An answered needs-decision issue reads DECIDED in `triage_state.py`, an action the gate starts a session for on the next tick instead of after its retry window, and a hold word in one sentence of a comment line no longer holds the issue on a link another sentence names (#309)

## [0.41.2] - 2026-10-09

### Fixed

- A headless gate session no longer stops on a chained Bash call whose commands are all on
  the allowlist (`cd <dir> && git push`): the skills and the implementer and reviewer briefs
  run one allowlisted command per Bash call (`git -C <dir>`, no `;` or `&&` chains or pipes
  into unlisted tools) and rerun a denied chain as separate calls; a command that isn't on
  the list is still a needs-decision (#312)

## [0.41.1] - 2026-10-08

### Fixed

- github-pr-triage no longer tells a reviewer to reword an Unreleased entry after a rebase in
  a repo with changelog fragments, which `changelog_guard.py check` fails: stale wording is
  fixed in the fragment that holds the entry, and an entry still under Unreleased stays or
  moves into a fragment in the same PR (#304)
- `shipmill upgrade --apply changelog-fragments` writes `changelog.d/README.md` with an
  example in the config's `[changelog] style`, as `shipmill init` does, instead of always
  the keep-a-changelog one; it refuses a style it doesn't know, and still leaves an existing
  `README.md` alone (#305)

## [0.41.0] - 2026-10-08

### Changed

- `shipmill gate --json`'s `plugin` changes shape: it was `installed`, `latest`, `updated`,
  and `error`, and is now `latest`, `installs` (each `scope`, `installed`, `updated`), and
  `error`, one entry per install keyed on the gate's checkout (#240)

### Fixed

- The package metadata names its author as Roman Medvedev instead of the handle Romamo
- The LICENSE names the copyright holder as Roman Medvedev instead of the handle Romamo
- With `[agents] plugin_update = true`, the gate now updates every shipmill plugin install
  keyed on its checkout, at local scope as well as project scope, so a gate whose checkout
  has a local install (shipmill's own) no longer stays on an old release (D-23). After the
  update it reads the installs again and reports a failure, not an update, when an install
  stayed behind or an install in another folder changed; the session still starts (#240)

### Added

- `shipmill upgrade --propose` opens one issue labelled `shipmill-upgrade` per pending
  config upgrade, with `<!-- shipmill-upgrade: <id> <version> -->` on its first line, and
  updates it in place on later runs; under `[autonomy] upgrade = "observe"` it opens none.
  An upgrade whose issue was closed while the config lacks its key is declined: never
  proposed again, and no longer listed by `shipmill upgrade`, which now reads the
  `shipmill-upgrade` issues when one is pending. A config that sets the key closes its open
  issue as completed. The reusable `land.yml` runs it in its own `upgrade` job after a
  release lands, with the `issues: write` the caller's land job already grants, so no
  caller workflow changes, and a failure there names the upgrade and fails that job only,
  never the release; a dry run proposes nothing. `shipmill doctor` lists each pending
  upgrade with its fix, never failing on one, and warns about a land job without `issues:
  write` only when `upgrade` is propose or act and an upgrade is pending (D-9); `shipmill
  status` lists each pending upgrade with its
  issue's link or the `--apply` command as its fix (spec 014) (#280)
- Changelog fragments are on by default: `shipmill init` sets `[changelog] fragments =
  "changelog.d"` and writes `changelog.d/README.md`, and `shipmill init --no-fragments`
  writes neither; in a repo with fragments, `changelog_guard.py check` fails a pull request
  that adds a line under Unreleased, naming the fragment to write, or a fragment that
  doesn't read; the skills add a fragment instead of editing `CHANGELOG.md`, and shipmill's
  own pull requests do too (spec 013) (#274)

## [0.40.0] - 2026-10-08

### Changed

- Decision D-27: with `[changelog] fragments` set, a revision whose tree has no fragments
  folder and whose own config doesn't set the key has no fragments; spec 013 gets
  S-013-17 for it (#291)

### Fixed

- A repo that turns on `[changelog] fragments` mid-cycle can plan and release the stable
  promotion of an rc cut before the folder existed, and run `shipmill notes` and proposals
  against an older tag or base: a revision whose tree has no fragments folder, and whose
  own `.github/shipmill.toml` doesn't set the key, reads as no fragments, and the stable
  stamp applies that to the base it releases; HEAD when planning, and a revision whose
  config sets the key, still exit 2 naming the folder. Only `[changelog] fragments` is
  read from that revision's config, so an older config's retired keys don't block it;
  malformed TOML or a `fragments` that isn't a string fails (D-27) (#291)

## [0.39.0] - 2026-10-08

### Changed

- Decision D-26: when a stable release folds its rc sections, prose before an rc
  section's first `### ` heading is dropped, and any other text outside an entry still
  fails the fold (#283)

### Fixed

- A stable promotion folds rc sections that open with prose, such as "The 34th 1.0 release
  candidate: 2 breaking changes, ...": the prose before an rc section's first `### `
  heading is dropped, in both styles, so `shipmill plan` and `prepare` no longer fail with
  `text outside a '- ' entry` (D-26); any other text outside an entry, or a list item
  before the first heading, still fails the fold (#283)
- `shipmill plan` no longer stops at a stable lane that can't work out its candidate,
  such as an rc section it can't fold: it goes on to rc and dev, names the stable lane's
  error in the reason when one of them releases or proposes, and exits 2 with that error
  only when none does; `--lane stable` fails as before. An rc, dev, or hotfix `prepare`
  never reads the fold (#296)

## [0.38.0] - 2026-10-08

### Added

- Changelog fragments on the hotfix lane (spec 013): a hotfix's section holds the
  Unreleased entries and the fragment entries its merges added (each merge's added or
  modified fragments against those it deleted or modified, by `git diff` with its first
  parent, so a renamed fragment adds nothing), and the merges' fragment files stay off
  the release branch, as `CHANGELOG.md` does; a merge that adds neither still fails. `shipmill sync`,
  after a hotfix or a stable release cut off a moved main, deletes on main each fragment
  whose every entry the section holds, and exits 2 naming the entry when the section
  holds one that is in neither Unreleased nor a fragment on main. Without `[changelog]
  fragments` nothing changes (#273)

### Changed

- Spec 011, a fix on every non-OK status row, is built: each of its 20 criteria is checked
  against main under its Verification section (#242)

### Fixed

- `shipped.py --post` (its "Released in" notices) and `setup_state.py --fix` (its labels)
  write as the App through `uvx --from git+https://github.com/shipmill/shipmill@v0
  shipmill gh` when the checkout's `.github/shipmill.toml` sets `[agents] app_id`, as spec
  012 asks of every write, instead of as the person running them; without `app_id` they
  use plain `gh` as before. A `shipmill gh` exit 2 stops the script with nothing retried,
  and a config that can't be read, or an `app_id` outside a readable `[agents]` table,
  exits 2 before anything is written. The config is the checkout's, so a run from a
  subfolder still writes as the App. Reads stay on plain `gh` (#290)

## [0.37.0] - 2026-10-08

### Changed

- `shipmill gate`'s QUIET line names the pull requests it leaves for a person: with no
  work and pull requests in `PRS_OPEN` while `[agents] prs` isn't true, it reads `QUIET:
  nothing needs an agent; N pull request(s) wait to land, landing off ([agents] prs =
  false)`; with none waiting it reads as before. A row's `fix` from `watch_state.py --json`
  enters neither the gate's fingerprint nor its session prompt, so a new fix starts no
  session (#260)
- The six skills that write to GitHub run every `gh` call that writes as `shipmill gh`
  when the repo's config sets `[agents] app_id`, in every session, gated or started by
  hand, and stop on its exit 2 instead of retrying with plain `gh`; a decision a person
  gives in the session is posted with the first line `Decision by @<login>, relayed by
  <agent>`; `docs/install.md` and shipmill-setup document `shipmill gh`, the no-checkout
  token cache, and that the App's identity covers the sessions a person starts. Spec 012
  is built (#263)

### Added

- Changelog fragments, the core of spec 013: `[changelog] fragments = "<folder>"` in
  `.github/shipmill.toml` makes each `<folder>/<name>.md` pending alongside Unreleased.
  `shipmill plan` reads them at the planned revision through git and bumps by their
  headings; `propose`, `notes`, and a pre-release's GitHub release list them; a stable
  `prepare` writes Unreleased, then the fragments in file-name order, then the version's rc
  sections into one section and deletes the released fragments in the release commit,
  keeping `README.md`; dev and rc releases leave the folder alone. A missing folder or a
  malformed fragment exits 2 naming it, and `shipmill doctor` counts fragments and names
  one a released section already holds, with the `git rm` that removes it. Without the
  key nothing changes (#272)
- Spec 011: github-ship-watch's `watch_state.py` and `shipmill status` run a `gh` read that
  fails on an `HTTP 5xx`, a timeout, or a reset or refused connection once more after 5
  seconds; when it fails again, the error line ends `transient GitHub API error: rerun`. An
  auth, not-found, or any other failure still fails at once, and no write is ever rerun
  (#261)
- `shipmill upgrade` lists the config upgrades a repo hasn't decided (`--json` for
  scripts): `changelog-fragments` until `[changelog] fragments` is set to any value, and
  `plugin-update` for a config with an `[agents]` section and no `plugin_update` key.
  `shipmill upgrade --apply <id>` adds the upgrade's line at the end of its table, keeping
  every other byte of `.github/shipmill.toml`, creates the files it owns
  (`changelog.d/README.md`), and commits nothing; an unknown id, one that doesn't apply, or
  one already decided exits 2 naming it. `[autonomy] upgrade` takes observe, propose (the
  default), or act, and an open hold reads act as propose; doctor's autonomy row names it
  (spec 014) (#279)

### Fixed

- A failing `shipmill plan` no longer stops github-ship-watch's `watch_state.py`, so the
  gate reads a repo's issues and pull requests again: the failure is a new `BOT_PLAN_FAILED`
  row on the release workflow, with the planner's error line and the plan to run to see it, an
  action for a person (exit 1, not an agent's), read as no release due; `shipmill status`
  reads it as STUCK (#276)

## [0.36.0] - 2026-10-08

### Added

- Spec 014: config upgrades. shipmill proposes a feature that needs an opt-in in a repo's
  config (changelog fragments, `plugin_update`) as an issue, asks the maintainer through
  the needs-decision protocol, and opens the pull request once they accept;
  `[autonomy] upgrade` picks observe, propose, or act, and a declined upgrade is never
  proposed again (#277)
- Spec 013: changelog fragments. With `[changelog] fragments = "changelog.d"`, each pull
  request adds its entry as its own file instead of editing `CHANGELOG.md`, so PRs stop
  conflicting on it; a stable release writes the fragments into its section and deletes
  them, and `shipmill init` turns them on by default (#256)
- github-ship-watch's `watch_state.py` gives each row that needs a person or an agent a
  fix, the one line that clears it: `gh run rerun <id> --failed -R <repo>` for a failed
  bot, operate, or publish run, the lane to start for a stalled bot, the `git -C` commands
  for a stale worktree, the close command for a hold, the skill to run for issues,
  incidents, and untrusted items, and for open pull requests no gate lands, the
  `[agents] prs` setting. `--json` adds it as `fix` (a string or null) beside the
  unchanged keys, and the table prints it on an indented `fix:` line; a fix names its repo
  and checkout and never quotes an issue's or a pull request's title. `fleet.py` reads
  the new key (#258)
- `shipmill gh <args>` runs the `gh` on `PATH` with exactly those arguments, as the repo's
  App when `[agents] app_id` is set (a token limited to gh's `-R`/`--repo`, else origin's
  repo; any failure to get it exits 2 and never runs `gh`), else as the host's login with
  no empty `GH_TOKEN`; and `shipmill app-token` works outside a checkout, caching under
  `$XDG_CACHE_HOME/shipmill/<owner>/<repo>/` with mode 0600 (spec 012) (#262)
- `AGENT_AS_PERSON`: with `[agents] app_id` set, `shipmill status` prints a WARN row and
  `shipmill doctor` a WARN check when an issue, pull request, or issue comment of the last
  7 days carries an agent's marker but a person's login wrote it, naming the count, up to
  three URLs, and the fix (`shipmill gh`); one GraphQL search, and no request without an
  `app_id` (#264)

### Changed

- `shipmill status` shows the fix for every reason it is STUCK or WAITS ON YOU, on an
  indented `fix:` line after the line it clears: the gate's launchd job, the App, the CLI
  update for the form installed, and landing pull requests when no gate does. Its item lines
  say what acting on them needs: a pull request behind or in conflict with its base, the
  pull requests covering an issue in progress, what a parked issue waits on, how to ready a
  draft, and the `git -C <checkout> pull --ff-only` for a branch behind (`fetch origin
  <branch>:<branch>` when another branch is checked out) (#259)

## [0.35.0] - 2026-10-08

### Added

- Spec 011: every row and summary line of `shipmill status` that waits on you or is stuck
  ends with its fix, an exact command scoped to where it runs or the decision to make;
  `--json` carries it as a `fix` field, and a test fails on a row without one (#242)
- Spec 012: every agent session writes to GitHub as the repo's App, not only gated ones:
  `shipmill gh` runs `gh` with the App's token and never falls back to a person's login,
  `shipmill app-token` works with no checkout, and `status` and `doctor` flag agent text
  posted under a person's name (#250)

## [0.34.0] - 2026-10-08

### Changed

- Decision D-23, superseding D-22: with `[agents] plugin_update = true` the gate updates
  every install of the plugin keyed on its checkout, local scope as well as project
  (#240)
- Decision D-24, superseding D-12: a worktree whose tip is, or was before a force-push,
  the head of a merged pull request on its branch counts as landed, so the gate's prune
  removes it (#244)
- Decision D-25: a stable promotion folds its version's rc sections in the CHANGELOG into
  the stable section, and never skips as nothing pending while they hold entries (#243)

### Fixed

- A repo that moved to shipmill with `[X.Y.ZrcN]` sections in its CHANGELOG, written by
  an earlier release bot, could never promote X.Y.Z: the stable lane skipped with "nothing
  pending under Unreleased". A stable release now counts the rc sections of its version
  (newer than the last stable section) as pending together with Unreleased, writes the
  X.Y.Z section with all their entries merged under their headings (Unreleased first, then
  the rc sections newest first, each entry once), and removes the rc sections and their
  compare links; the GitHub release notes and a release proposal list the same entries.
  When a promotion still skips, the reason names the rc sections it found or says there
  were none. An rc section holding text that is not an entry (prose, a `####` heading, a
  numbered list) stops the release with an error naming it rather than lose that text. A
  CHANGELOG without rc sections releases as before (#243)
- `shipmill worktrees` and the gate's prune no longer keep a worktree forever as
  `<N> commit(s) not landed` when review force-pushed its pull request before a squash
  merge: a branch also landed when its tip is, or was before a force-push, the head of a
  pull request merged into the default branch from that branch or its upstream, matched by
  commit SHA; commits made
  after that head still keep it, counted alone. The merged pull requests come from one
  `gh api graphql` read per run, and a failed read exits 2 and removes nothing (#244)

## [0.33.2] - 2026-10-07

### Fixed

- A headless gate session no longer loses its background subagents 10 minutes after its
  last turn: the gate starts `claude -p` with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` in
  its environment unless the gate's own environment sets the variable, and
  github-issue-triage and github-pr-triage run their agents in the foreground when
  headless (#246)
- The factory stalled when a gate session left the gate's own checkout
  (`tmp/shipmill-gate`) on a branch: every tick refused it and told you to create a
  worktree that already existed. A `--refresh` tick now detaches a clean linked worktree
  on a branch to the default branch's head, keeping the branch and its commits, and
  prints `detached <path> from <branch>` (`detached` in `gate --json`); a dry run moves
  nothing. `launchd` and a tick in the main working tree still refuse a checkout on a
  branch, now with `git -C <path> switch --detach origin/<default>` as the fix, and a
  checkout with tracked changes is refused with the files named. github-issue-resolve and
  github-pr-triage now tell a gate session to work in a new worktree and never switch
  branches or commit in the checkout it started in (#247)

## [0.33.1] - 2026-10-07

### Fixed

- Gate sessions could run a working copy of a skill instead of the released plugin: every
  prompt shipmill writes or recommends (its own `[agents] prompt`, shipmill-setup's, and
  the docs' prompts and `/loop` commands) named the skills without the plugin's prefix, so
  a link or copy in `~/.claude/skills` or `~/.agents/skills` answered them. They now call
  `/shipmill:<skill>`. github-ship-watch (and so `shipmill status`) and the setup checklist
  report each such link or copy of a shipmill skill as `SKILL_SHADOWED`, with its fix
  (remove it, or call the skill with the prefix); a link into the plugin's cache isn't
  one. It is an action for a person, never an agent's. The checklist also reads an
  `[agents] prompt` that calls a shipmill skill without the prefix as `AGENTS_UNPREFIXED`,
  and a home folder with neither as `SKILLS_OK` (#236)

## [0.33.0] - 2026-10-07

### Added

- `[agents] plugin_update` (default `false`: the gate changes no install). With `true`, a
  gate tick about to start a session checks at most once per 24 hours whether its
  checkout's own project install of `shipmill@shipmill` is behind the latest release and,
  when it is, runs `claude plugin update` in the checkout first; a failed update is printed
  on the tick (and in `gate --json`'s `plugin`) and the session starts anyway (D-22).
  shipmill's own gate sets it, and `shipmill init`'s template shows it with its default
  (#233)

### Changed

- Decision D-22: the gate updates its checkout's plugin at most once a day, and only when
  `[agents] plugin_update = true`; otherwise status, doctor, and setup report the behind
  install with a fix that works in its folder (#233)
- The docs and skills recommend installing the CLI from PyPI with `uv tool install
  shipmill` (upgraded with `uv tool upgrade shipmill`) and running a plain `shipmill
  <command>`, keeping `uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill` for
  when it isn't installed and for headless gate sessions; each uvx call resolves git again,
  which took minutes and filled uv's cache. The hints the CLI prints name a plain `shipmill`
  when the `shipmill` on PATH is the running install, and the uvx form otherwise.
  `docs/install.md` gains a "Clean up old builds" section on `uv cache prune` and the plugin's
  old versions under `~/.claude/plugins/cache` (#236)

### Fixed

- `shipmill status` (github-ship-watch's `SHIPMILL_OUTDATED`) reports a stale plugin
  install in the gate's checkout (`tmp/shipmill-gate`) as its own row, and for the repo's
  own install prints a fix that works: an uninstall and install at that scope, since
  `claude plugin update` in the repo picks the nested gate install (a Claude Code bug).
  shipmill-setup's checklist reads the installs too and reports `PLUGIN_OUTDATED` (not
  done) for each one behind the release, instead of `PLUGIN_OK`, and `shipmill doctor`
  reports them with the same rows and fix text: a `plugin` WARN for each install behind
  the release, a PASS when none is, and a WARN, never a crash, when they can't be read (#233)

## [0.32.2] - 2026-10-07

### Fixed

- shipmill-setup no longer calls a stalled factory healthy: `setup_state.py` adds a
  landing row, `LANDING_OFF` (exit 1) when `[agents]` has `prs = false` (or no `prs` key)
  and open non-draft pull requests wait, listing them; setup then asks whether the gate
  should land them, and checks `shipmill status`, calling the setup healthy only when the
  verdict is IDLE or WORKING (#234)

## [0.32.1] - 2026-10-07

### Fixed

- `shipmill status` shows the open pull requests waiting to land: a `to land` line lists
  each with its link, a `landing` line says whether the gate lands them (`[agents] prs`),
  and when no gate does (`prs = false`, or no `[agents]`), the verdict is WAITS ON YOU,
  naming the pull requests and the fix, instead of IDLE while the gate logs QUIET (#231)

## [0.32.0] - 2026-10-07

### Changed

- The README now says what shipmill is, why to use it, and how to start, with a
  quickstart and links that work on PyPI; the release reference (lanes, policy,
  environments, operate, autonomy, versions, CLI, limits) moved to
  `docs/release-lanes.md`. The PyPI metadata gains keywords, classifiers, and homepage,
  documentation, and issue links, and the GitHub Pages site becomes a landing page

## [0.31.1] - 2026-10-07

### Fixed

- github-ship-watch no longer reads a version tag cut before the package's first PyPI upload
  as NOT_PUBLISHED, which started a gate session with nothing to repair: such a tag reads
  PREDATES_PUBLISH, a report-only row, while a later missing release stays NOT_PUBLISHED
  (#228)

## [0.31.0] - 2026-10-07

### Added

- `.github/workflows/publish.yml` builds the release tag it is given, checks that the tag is
  `vX.Y.Z` and matches `pyproject.toml`, runs `shipmill --help` from the wheel in a fresh
  environment and checks the wheel holds the skills' state scripts, then uploads with `uv
  publish` through trusted publishing in the `pypi` environment. The stable and hotfix lanes
  dispatch it, and `docs/install.md` says shipmill is on PyPI and needs Python 3.14 (#224)

### Changed

- shipmill's own gate runs headless: `[agents] mode = "headless"`, so each gated session
  is a detached `claude -p` that asks on GitHub and ends

### Fixed

- The CLI's own hints name the full `uvx --from git+https://github.com/shipmill/shipmill@v0
  shipmill` form instead of a bare `shipmill <command>`: the `next:` line after `init`,
  doctor's workflow and operate details, the launchd error off macOS, the status picture's
  launchd reason, `app-create`'s closing line, and the operate note in the config `init`
  writes. A test fails on a bare command in any string the package prints, raises, or
  writes (#223)

## [0.30.0] - 2026-10-07

### Added

- Spec 010: each stable and hotfix release publishes shipmill to PyPI through a new
  `publish.yml`, with trusted publishing and a smoke test of the built wheel (#216)

### Fixed

- The README, `docs/install.md`, and the github-ship-watch and github-pr-triage skills no
  longer tell you to run a bare `shipmill <command>`, which nothing puts on `PATH`: they
  use `$CR` or the full `uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill`
  form. `docs/install.md` shows an alias for the short name that keeps tracking `@v0`,
  and says why `uv tool install` drifts; the github-ship-watch description, always in an
  agent's context, says how to run the CLI. A test fails on a bare command in the README,
  the top-level docs, or a skill (#215)

## [0.29.0] - 2026-10-07

### Changed

- Decision D-21: every gate session, interactive or headless, asks its questions through
  the needs-decision protocol, so a question nobody answers waits on GitHub instead of
  holding the gate (#206)
- Every `shipmill gate` session asks through the needs-decision protocol, interactive
  too: the interactive prompt ends with a `Gate session:` paragraph naming your `gh`
  login, so the session posts its question as a marked comment with the `needs-decision`
  label before it asks in the session, and an unattended question waits on GitHub instead
  of reading as work. An answer given in the session is posted on the item and the label
  comes off. An interactive launch now reads your login with `gh api user` and starts
  nothing when that fails. With `app_id` set, an interactive gate checks the App before it
  reads the state, as headless does, and reads it with `--bot-login <slug>[bot]`, so a
  reply on GitHub to the bot's question wakes the item. `setup_state.py` wants the
  `needs-decision` label whenever the config has an `[agents]` section (D-21) (#206)
- `shipmill status` prints a short linked summary instead of blocks: a heading with the
  repo, its link, and the verdict, with no list of reasons, since each reason is a line of
  its own; then the repo (in sync, at which version, release ok or the problem), every
  issue and pull request waiting on a decision or listed by state with its own link
  instead of a label search, the open issues and pull requests counted with the list's
  link, the gate as `OK, launchd every N min` or its problem, the mode, the GitHub App
  (`active`, `not active`, or the problem), and shipmill's version (`up to date` or the
  update commands); empty lines are dropped, and `--rows`, `--json`, and the exit code
  are unchanged (spec 009, #212)

### Fixed

- `specs.py` honours a dropped criterion, one whose text starts `dropped in #N`:
  `coverage` prints it as dropped instead of demanding a test, `split` leaves it out of
  new build issues, and `check` needs no Issues line for it, so a built spec that drops
  criteria can pass (#219)

## [0.28.0] - 2026-10-07

### Added

- `shipmill status` says whether the factory works or is stuck: a verdict (STUCK, WAITS ON
  YOU, WORKING, IDLE) with its reasons, then the local `main` against GitHub's and the
  version each is at, the open issues and pull requests (waiting on you with a GitHub link,
  to triage, to build), the gate's job, last run, last decision, mode and App, and one
  shipmill line with the CLI and plugin versions; `--rows` prints the old table (spec 009)

## [0.27.0] - 2026-10-07

### Changed

- A gate without a GitHub App is unfinished setup (D-19): shipmill-setup makes the App step
  required before it schedules the gate, `setup_state.py` reads `AGENTS_NO_APP` for any
  `[agents]` prompt without `app_id`, in either mode, and exits 1 on it (it was headless
  only and counted as done), and github-ship-watch's `watch_state.py`, and so `shipmill
  status`, reports a new `GATE_NO_APP` row, an action for a person that never starts a
  gate session. The gate and `launchd` still run without one (#204)
- shipmill-setup asks for the gate's `[agents] mode` every time, with the App question, and
  writes `mode = "interactive"` or `mode = "headless"` (D-20); `setup_state.py` reads a new
  `AGENTS_NO_MODE` row, exit 1, for a prompt with `app_id` and no `mode` key (after
  `AGENTS_NO_APP`, one row for the section). The config's default stays interactive, and
  shipmill's own config now says `mode = "interactive"` (#205)
- Decisions D-19 and D-20: a gate set up without an App, or without an explicit
  `[agents] mode`, is unfinished setup and reads as an action, never as done (#204, #205)

## [0.26.0] - 2026-10-06

### Added

- `shipmill status` prints github-ship-watch's report for the checkout's repo, as a table or
  with `--json` its JSON lines, and exits 1 when a row needs action, so a person without an
  agent or a CI job can ask "is anything stuck?" (spec 008)

### Changed

- `shipmill gate` reads a crashed `watch_state.py` (exit 1, no rows) as a failure with the end
  of its stderr, where it read it as QUIET
- Spec 008 after a second review: status needs a checkout even with a named repo, shows the
  script's whole stderr and passes it through on success, and the gate shares the guard
  that reads a crashed `watch_state.py` as a failure, not as QUIET
- Spec 008 settled after review: `status` exits 2, not 1, when `watch_state.py` crashes
  without printing a row; `watch_command` gains a `json` parameter for the table; the
  origin and the repo check reuse `_origin_repo` and `check_checkout`

## [0.25.0] - 2026-10-06

### Added

- Spec 008 for `shipmill status`, which prints github-ship-watch's report for the checkout's
  repo and exits 1 when something needs action
- github-ship-watch compares the host's `shipmill@shipmill` plugin (`claude plugin list`)
  with the latest shipmill release: SHIPMILL_VERSION lists the installs that apply to the repo (user scope, the
  checkout, and the gate's working directory) and a marketplace on an old repo name, and
  SHIPMILL_OUTDATED names an install behind the release with the command that updates it.
  The gate's checkout was found pinned at 0.14.0 while 0.24.0 was out (#196)
- github-ship-watch reports BRANCH_DELETE_OFF when the repo's `delete_branch_on_merge` is
  off, with the command that turns it on: merged branches piled up unnoticed after a repo
  move, since only setup checked it. An action for a person, never an agent's (#194)

### Fixed

- github-ship-watch's SHIPMILL_OUTDATED no longer reports a plugin install keyed on a linked
  git worktree, such as the gate's checkout: Claude Code loads the main checkout's install
  there, so the leftover entry was never used and its update command couldn't clear it (#198)

## [0.24.0] - 2026-10-06

### Added

- `[agents] mode = "headless"` for `shipmill gate` (D-17): a launch runs `claude -p` with
  `--permission-prompts none`, the `HEADLESS_TOOLS` allowlist, `--disallowedTools
  AskUserQuestion`, and a new `--session-id`, and its prompt ends with a paragraph that sends
  a decision for your `gh` login to the needs-decision protocol. The session runs detached,
  its output in `sessions/<uuid>.log` under the state directory, and the gate tracks it in
  `gate.json` by pid and process start time: RUNNING while it runs, never WAITING. The state
  read passes `--trusted-only` (D-16), and with `app_id` set `--bot-login <slug>[bot]`; a
  headless gate refuses `--claude-arg` flags that would bring prompts back or break the
  tracking. `mode` defaults to `"interactive"`, which launches exactly as before, and
  `shipmill launchd` now writes `AbandonProcessGroup` (run it once more for an installed
  job) (S-005-1, S-005-2, S-005-3, S-005-5, S-005-6, S-005-11, S-005-19, S-005-20, S-005-21)
  (#162)
- A headless `shipmill gate` without `app_id` notifies you of each item that waits on your
  needs-decision reply, since GitHub doesn't notify you of a comment under your own login:
  on a tick that reads the state, at once and then every `remind_hours`, recorded in
  `needs-decision.json` beside `waiting.json` and under its rules. With `app_id` the bot's
  mention notifies on GitHub and the gate sends nothing; a headless launch without it says
  so. `--json` gains `mode` and a `decisions` list (S-005-12, S-005-13, S-005-14,
  S-005-15) (#163)
- shipmill-setup's checklist knows headless mode: with `[agents] mode = "headless"` it wants
  the `needs-decision` label (`--fix` creates it, color `d876e3`), and without `app_id` the
  agents row reads `AGENTS_NO_APP`, counted as done, saying GitHub won't notify you of a
  question posted as your own login. Interactive and no-`[agents]` setups see no new row,
  and an `[agents]` `mode` no longer reads as the release mode. agent-modes.md, the
  shipmill-setup skill, and install.md document headless mode: `HEADLESS_TOOLS` and how to
  widen it (`--claude-arg=--allowedTools --claude-arg "Bash(npm *)"`), the trust filter, the
  label, and notifications with and without an App (S-005-16, S-005-18) (#164)

### Changed

- Spec 005's S-005-8 counts a `needs-decision` question only from a trusted author: an
  owner, member, or collaborator, or with `--bot-login` the bot's own marker comment. An
  outsider's marker comment can no longer re-park an answered item, and a maintainer's
  question after a bot's triage comment no longer reads as its reply. The code follows in
  #184

### Fixed

- `shipmill launchd` writes each `--claude-arg` into the job as `--claude-arg=<flag>`. It
  wrote `--claude-arg` and the flag as two arguments, which the job's gate refused ("expected
  one argument") on every tick, since a separate value that starts with a dash reads as an
  option. Run `shipmill launchd` once more for a job installed with `--claude-arg` (#192)
- A `needs-decision` question now counts only from a trusted author, in `triage_state.py`
  and the pull requests `watch_state.py` reads: a comment whose first line is the marker,
  by an owner, member, or collaborator, or with `--bot-login` by the bot. An outsider's
  marker comment no longer re-parks an answered item, a bot comment without the marker is
  no question, and with `--bot-login` a maintainer's marker question newer than the bot's
  leaves the item labelled with no question, so it waits instead of reading as answered
  (S-005-8) (#184)
- github-ship-watch no longer reports `WORK_BRANCH_STALE` for a work branch whose run is
  still alive behind ten or more newer runs: with a work branch on origin, it asks GitHub
  for the release workflow's unfinished runs by status (queued, in progress, waiting,
  pending, requested), as `prepare` does, instead of reading the newest ten, and a failed
  query stops the watch (exit 2) rather than reading as no owner. The row's re-check before
  deleting the branch asks by status the same way. A pass with no work branch makes no
  extra calls (#185)

## [0.23.0] - 2026-10-06

### Added

- The needs-decision protocol for headless sessions: a question for the user becomes a
  comment whose first line is `<!-- shipmill:needs-decision -->` and a `needs-decision`
  label, and the item waits on GitHub (`references/needs-decision.md`, linked from a headless
  rule in github-issue-triage, github-issue-resolve, and github-pr-triage).
  `triage_state.py` reads such an issue as NEEDS_DECISION, no action, until an OWNER,
  MEMBER, or COLLABORATOR replies, and gains `--bot-login` and `--trusted-only` (an outside
  author's issue reads UNTRUSTED). `watch_state.py` passes both through, leaves waiting
  issues and pull requests out of ISSUES and PRS_OPEN, and lists them in a NEEDS_DECISION
  row (an action, `agent: false`) and, with `--trusted-only`, outsiders' issues and fork pull
  requests in an UNTRUSTED row, so `shipmill gate` reads a repo whose only work waits as
  QUIET (S-005-7, S-005-8, S-005-9, S-005-10, S-005-17) (#161)
- D-18: a Release run that finds a work branch no active run owns deletes it and pushes its
  own, given `actions: read`; without it, the stop stays but is reported (#175)
- github-ship-watch reports what else is going on in the repo, and every status report lists
  it: the open issues triage owes nothing on yet, by state (ISSUES_OPEN); each queued or
  running workflow run (RUNS_ACTIVE); the gate's triage mode from `[agents]` (TRIAGE_MODE);
  the Claude Code sessions on the host working the repo (AGENT_SESSION); and the gate's
  launchd loop with its last decision (LOOP). All are report-only, so the exit code and the
  gate's fingerprint are unchanged (#182)

### Fixed

- A work branch left on origin by a Release run cancelled before its cleanup job got a
  runner no longer stalls the lane: the next run's `prepare` deletes it and pushes its own
  when no other queued or in-progress run of the Release workflow could own it (D-18). This
  takes `actions: read` on the caller's prepare job, which `shipmill init` now writes; the
  reusable prepare job takes the caller's grant instead of setting its own, so a caller
  without it still runs. Every stop at a held work branch is now visible: a warning
  annotation and a run-summary line naming the branch and its commit, saying to grant
  `actions: read` when that is the cause; the run stays green. github-ship-watch reports
  `WORK_BRANCH_STALE` for a `shipmill/v*` branch no active run owns, and deletes it and
  starts the lane (#175)

## [0.22.0] - 2026-10-06

### Changed

- `docs/design/agent-modes.md` records the #160 probe of a headless `claude -p` session on
  Claude Code 2.1.291: it outlives the launchd job that started it, a call outside the
  allowlist is denied with no prompt, AskUserQuestion is absent, and it exits on its own
  even when its last reply asks a question (S-005-4)

## [0.21.0] - 2026-10-06

### Changed

- github-issue-triage asks a design question on the issue too, as a **Decision needed**
  block at the top of its verdict comment: the question in one plain sentence, the options
  numbered with the recommended one first and what each means for users, and how to answer
  (reply with a number). A reply on the issue counts as the answer, so the maintainer
  doesn't have to attach to the gate session; a held PR's decisions are asked the same way
- Spec 005 now runs headless gate sessions as `claude -p` instead of `claude --bg`, after
  the #160 probe found a `--bg` session reads `blocked` whenever its last reply asks for
  something: the gate starts the session detached, logs its output under the state
  directory, tracks it by pid, and never reads it as waiting; `shipmill launchd` sets
  `AbandonProcessGroup` so a session outlives its tick (D-17)

## [0.20.0] - 2026-10-06

### Added

- `shipmill app-install [owner/name ...]` guides installing the gate's App on more repos:
  for each repo the App doesn't cover it opens the App's Install App page and says per
  account whether to click Install or Configure and which repos to pick, then waits until
  each is covered; it never installs or adds anything itself. `shipmill app-create`'s
  install step uses the same guide (#172)
- Spec 007 for `shipmill app-install`, which guides installing the gate's App on more repos
  and accounts, and checks that it took

### Changed

- shipmill's own gated sessions write as the `shipmill-romamo` GitHub App (`[agents] app_id`)
- `shipmill app-create` makes the App yours by default (your personal account), private
  unless a gated repo is in an org, then public so it installs there; an interactive run
  asks who should own it, your account first, and `--owner` picks an org you administer
  (#167)
- `shipmill app-create` names the App `shipmill-<owner>` by default (`shipmill-agent` under
  the `shipmill` account), falling back to `shipmill-<login>`, so each account's bot is told
  apart on its pull requests; when both are taken it exits 2 naming free alternatives

### Fixed

- `shipmill app-create` sets the App's homepage to `https://github.com/shipmill/shipmill`,
  not the first gated repo's URL

## [0.19.0] - 2026-10-06

### Added

- Spec 006 for `shipmill app-create`, which makes the gate's GitHub App in one click and
  picks its owner and visibility from where the gated repos are
- `shipmill app-create` makes the gate's GitHub App in one click: it finds the accounts your
  `gh` login administers and the repos in them holding `.github/shipmill.toml`, plans a
  private App when they are all in one account and a public one when they span several
  (`--owner`, `--public`, `--private`, `--name`, `--repos` change it; `--dry-run` prints the
  plan), opens GitHub's create page with the permissions filled in, saves the key to
  `~/.config/shipmill/app-<app_id>.pem` with mode `0600`, waits for the installations, and
  prints the `app_id` line to commit; exit 1 names a repo still missing the App. The setup
  skill and `docs/install.md` use it first, the manual steps as the fallback (#155)
- Spec 005 for headless gate sessions: `[agents] mode = "headless"` starts sessions that
  can't prompt, a decision for the user becomes a `needs-decision` comment and label the
  gate waits on, and headless work is limited to trusted authors' items, with D-16 (#134)
- Spec 005's build issues: #160 to #164 (#134)

### Fixed

- D-15's `Decided` line names the issue it was decided in (#147), so `specs.py check`
  accepts a spec that cites it
- `shipmill app-create` prints each line as it happens, so a piped or backgrounded run shows
  the plan and the URL at once; its local page no longer posts to GitHub by itself, which
  lost the manifest when GitHub asked to sign in first (*We didn't find an App Manifest*),
  but shows the plan and each permission with its use and a **Create on GitHub** button to
  click again after signing in; and a taken default name moves to a free variant, while a
  taken `--name` exits 2 naming the free ones (#157)

## [0.18.0] - 2026-10-06

### Added

- `shipmill gate` prunes on each tick as `shipmill worktrees --prune` does, held or not:
  after the waiting step and before the hold check, it removes each worktree that provably
  landed with the local branch it held, prints `pruned <path> (<branch>)` for each, and
  lists their paths under a new `pruned` key in `--json`. `--dry-run` removes nothing,
  prints `would prune <path> (<branch>)`, and lists them under `pruned`. A prune error
  (`claude agents --json` or `gh pr list` failing, or git refusing a removal) exits 2 and
  starts no session; the gate's own checkout is never a candidate (#124)
- Spec 004's build issues: #141 to #144 (#136)
- `[agents] app_id` names the GitHub App gated sessions write as, and `shipmill gate
  --app-key <path>` its private key (default `~/.config/shipmill/app-<app_id>.pem`). On a
  launch with `app_id` set, the gate checks the key's mode, signs the App's JWT with
  `openssl`, and checks the App is installed on the repo with every permission spec 004
  lists, exiting 2 naming what failed (D-14) (#141)
- github-ship-watch's `watch_state.py` reports a `WORKTREE_STALE` row, report-only
  (`agent: false`, never an action), for each worktree under `.claude/worktrees/` or
  `tmp/wt-*` that `shipmill worktrees` keeps and that is over 7 days old, naming its path
  and why it is kept. It runs `shipmill --repo <repo-dir> worktrees --json` for a shipmill
  bot, so the watch needs `claude` on `PATH` there, and a failing command exits 2 as a
  failing plan does. shipmill-setup's gate section documents the prune and `shipmill
  worktrees`, and github-issue-resolve, github-pr-triage, and github-issue-triage say that
  the worktrees a session leaves behind once it exits are the gate's prune's to remove.
  Spec 002 is built (#125)
- `shipmill app-token <owner/repo> --app-id <id> [--app-key <path>]` prints a GitHub App
  installation token limited to that one repository and spec 004's permissions. It caches
  the token in `$(git rev-parse --git-common-dir)/shipmill/app-token.json` (mode `0600`,
  replaced atomically), reuses it while it has at least 10 minutes left, and exits 2 on a
  malformed cache, naming it. `--git-credential get` answers git's credential protocol for
  `https://github.com` with `username=x-access-token`; another host gets no answer, and
  `store`, `erase`, and other operations print nothing. `python -m shipmill` now runs the
  CLI, and the session's `gh` and `git-credential-shipmill` helpers, which hold no token,
  can be written for the gate's launch (#142)
- With `[agents] app_id` set, `shipmill gate` starts its session as the App's bot. After
  the App's checks it reads the bot account's id, writes the `gh` and git credential
  helpers to `$(git rev-parse --git-common-dir)/shipmill/bin/`, and launches `claude --bg`
  with `--settings` env that puts that folder first on `PATH`, makes `<slug>[bot]` and
  `<id>+<slug>[bot]@users.noreply.github.com` the git author and committer, and, through
  `GIT_CONFIG_*`, replaces the host's github.com credential helpers with the App's and
  sends `git@github.com:` and `ssh://git@github.com/` remotes over https. The env holds no
  token, and the gate's own reads keep the host's `gh` login. Any failure exits 2 before a
  session is stopped or started. The decision line ends ` as <slug>[bot]`, `--json` gains
  `identity` (`null` without an App), and `--dry-run` runs the checks, writes nothing, and
  prints `would launch as <slug>[bot]`. With `app_id` unset the launch is unchanged.
  `shipmill launchd --app-key <path>` passes the key, made absolute, to the job's gate,
  and refuses it when `app_id` is unset or the key is missing or readable by others (#143)
- shipmill-setup's gate section and `docs/install.md` give the GitHub App's setup: creating
  it with no webhook and spec 004's permission table, installing it only on the repos the
  gate works on, the private key at `~/.config/shipmill/app-<app_id>.pem` with `chmod 600`
  (or `--app-key` on `gate` and `launchd`), `app_id` in `[agents]`, the token cache and
  helpers, the dry run that proves it, and that without `app_id` sessions launch as before.
  `docs/design/agent-modes.md` describes the session's identity, `--settings` env, and the
  `app-token.json` and `bin/` state, and github-ship-watch says the App's `<slug>[bot]`
  counts as a bot in the metrics. Spec 004 is built (#144)

### Changed

- `[agents] max_wait_hours` is now `max_wait_minutes` (0..10080) and defaults to 15, so
  `shipmill gate` stops a session that has waited on you for 15 minutes unless the config
  says otherwise (D-15, superseding D-13); 0 still never stops one. A config that still
  sets `max_wait_hours` is refused naming the key. Waits read in minutes under an hour
  (`stopped <id> after 15m waiting`), and `--json` reports `waited_minutes` in place of
  `waited_hours` (#147)

## [0.17.0] - 2026-10-06

### Added

- Spec 003 for notifying when a gated session waits on you, and stopping it after an
  optional `max_wait_hours`, with D-13: a hold doesn't keep the gate from stopping a stuck
  session (#119)
- Spec 003's build issues: #128 to #130 (#119)
- The `[agents]` section takes `notify` (default true), `remind_hours` (1..168, default 4),
  and `max_wait_hours` (0..168, default 0), refusing a bad value naming the key; the gate
  doesn't act on them yet (#128)
- `shipmill gate` sends a desktop notification when a session it started waits on you
  (`osascript` on macOS, `notify-send` elsewhere), and again every `remind_hours` while it
  waits; `notify = false` turns it off. The wait is kept in `waiting.json` next to
  `gate.json`, a failed send prints `notify failed for <id>: <error>` without changing the
  decision, notifying runs on held ticks too, `--dry-run` prints `would notify <id>`, and
  `--json` lists each blocked session under `waiting`. A tick with a blocked session now
  reads the `[agents]` section (#129)
- `shipmill gate` stops a session that has waited on you for `max_wait_hours` (when not 0)
  with `claude stop`, prints `stopped <id> after <N>h waiting: <name>`, sends a last
  notification, and decides the rest of the tick without it, held or not (D-13); a failed
  `claude stop` exits 2 and launches nothing, and `--dry-run` prints `would stop <id>`.
  Spec 003 is built (#130)
- `shipmill worktrees [--json]` lists every worktree of the repository as REMOVABLE, once
  its branch provably landed on the default branch (by ancestry, patch id, or a squash of
  its whole diff), or KEPT with the first check it fails: the main or current checkout, not
  under `.claude/worktrees/` or `tmp/wt-*`, missing, locked, detached, on the default
  branch, under a day old, a live Claude Code session in it, another worktree inside it,
  uncommitted changes, commits not landed, or an open pull request (#122)
- `shipmill worktrees --prune` removes each REMOVABLE worktree with `git worktree remove`
  (never `--force`) and then the local branch it held, printing those rows as REMOVED (also
  the `verdict` in `--json`); no other worktree or branch, local or remote, is touched.
  `--prune --dry-run` prints them as WOULD_REMOVE and removes nothing, and `--dry-run` alone
  exits 2. The first removal or branch deletion git refuses stops the prune with exit 2,
  naming the worktree and git's error and what it removed before (#123)
- Spec 004 for gated sessions writing as a GitHub App (`[agents] app_id`), with D-14:
  with an App set, a session starts as the App or not at all (#137)

## [0.16.0] - 2026-10-05

### Added

- shipmill-setup's `setup_state.py` reports whether GitHub deletes a pull request's branch
  when it merges: `BRANCH_DELETE_ON`, or `BRANCH_DELETE_OFF` (exit 1), which `--fix` turns
  on through the repo setting `delete_branch_on_merge`. github-pr-triage's stacked merges
  rely on it to retarget a stacked PR. github-issue-triage now deletes the branch of a PR
  it closes because the new plan dropped it (#117)
- Spec 002 for pruning landed worktrees, and D-12: whoever creates a worktree removes it,
  and `shipmill gate`'s prune owns what an exited session left (#116)
- Spec 002's build issues: #122 to #125 (#116)

### Changed

- shipmill's own `.github/shipmill.toml` has an `[agents]` section, so `shipmill gate` triages
  this repo's new issues and lands its green pull requests

## [0.15.0] - 2026-10-05

### Added

- `docs/install.md`: the full installation, from prerequisites through the skills, release
  lanes, and the gate, to pausing and removing shipmill. The README keeps a short Install
  section and links to it; its Quick start and Where the agents run sections moved there
- A one-line setup: `claude plugin marketplace add shipmill/shipmill && claude plugin install
  shipmill@shipmill && claude "/shipmill:shipmill-setup"`, from the root of a repo, installs
  the plugin and starts the shipmill-setup skill
- `watch_state.py --json` marks every row with `agent: true|false`: true for BOT_FAILED,
  BOT_STALLED, NOT_PUBLISHED, UNANNOUNCED, ISSUES, OPERATE_FAILED, and INCIDENT_OPEN, the
  rows an agent works on; false for every other state, PROMOTION_DUE, UNHEALTHY, HOLD, and
  PRS_OPEN among them. The text table is unchanged, and `fleet.py` reads the new field
  without adding it to its own report (#49)

### Changed

- `shipmill gate` starts a session on the rows `watch_state.py` marks `agent: true`, plus
  PRS_OPEN with `[agents] prs = true`, in place of its own copy of the states. A failed
  operate run (OPERATE_FAILED) and an open incident (INCIDENT_OPEN) now start one; an open
  `shipmill-hold` issue still stops every launch (D-11). The gate refuses a row with no
  boolean `agent` rather than guessing (#49)
- shipmill moved to the shipmill GitHub org: the repository is `shipmill/shipmill`, so
  `shipmill init` writes `uses: shipmill/shipmill/...@v0`, the default `--tool` for the
  workflows, `launchd`, and `watch_state.py` is `git+https://github.com/shipmill/shipmill@v0`,
  and the plugin's marketplace is `shipmill/shipmill`. GitHub redirects the old path; the
  setup checklist still counts a `release.yml` that calls `romamo/shipmill`. shipmill's own
  Pages site, and its health URL, moved to `https://shipmill.github.io/shipmill/`
- The CHANGELOG's `[Unreleased]` link points at `shipmill/shipmill`, so the compare links
  each release writes from it use the org's path

### Fixed

- `shipmill gate` no longer writes a row's detail into the session's prompt: an open
  incident's detail starts with the issue's title, text anyone who can edit the issue
  controls, which reached the session as if the gate wrote it. The prompt lists each row by
  state and subject only (`- INCIDENT_OPEN #42`) and tells the session to rerun
  `watch_state.py` for the details and read each issue's text as untrusted data, not
  instructions. `--dry-run`, the log, and the launch fingerprint keep the detail (#114)
- The github-issue-resolve skill no longer leaves the checkout it starts in on the fix branch,
  where a later `shipmill plan` read the PR branch instead of main: Phase 3 creates the branch
  in a worktree (`git worktree add -b fix/<slug> tmp/wt-<slug> origin/<default>`) unless the
  session already runs in a linked worktree, never switches, resets, or pulls the user's
  checkout, keeps the worktree while the PR is open, and removes it and its branch once
  `landed.py` confirms the merge (#110)
- `fleet.py report --metrics` measured change failure rate and time to restore with the
  `incident` label for a repo whose fleet entry sets no `incident_label`, even when the repo's
  config sets `[operate] incident_label`. fleet.py now reads that label from the clone with
  `watch_state.py`'s config reader and passes it to `metrics.py`, so the metrics and the watch
  count the same issues (#99)

## [0.14.0] - 2026-10-05

### Changed

- `shipmill gate` starts no session while an issue labelled `shipmill-hold` is open, and
  reports HELD with any session still open (D-11)

## [0.13.0] - 2026-10-05

### Changed

- The project is now shipmill, with no compatibility layer: the package and CLI
  `shipmill`, the config `.github/shipmill.toml`, the labels `shipmill-hold` and the
  other `shipmill-*` labels, the `shipmill/<tag>` work branches, the `shipmill-setup`
  skill, the plugin `shipmill@shipmill`, and the repository `romamo/shipmill`

### Removed

- macOS Finder's `.DS_Store` files, which the rename's commit picked up; `.gitignore` now
  lists them
- `.github/release-policy.toml`, the config's alias: shipmill reads only
  `.github/shipmill.toml`, and `init --force` no longer removes the alias

## [0.12.0] - 2026-10-05

### Added

- github-ship-watch reports a fleet (spec S-001): `fleet.py report --fleet <file>` runs
  `watch_state.py` for every repo the fleet file lists, each on a fresh blobless clone,
  and prints one table with the repo named on each row, the action rows of all repos
  first. It exits 1 when any repo has an action row; a repo whose check fails (not
  found, no access, a gh error) gets one REPO_ERROR row with the error's first line, the
  rest are still reported, and the run exits 2. `--metrics` adds each repo's
  `metrics.py` measures over one shared 30-day window, side by side with one column per
  repo, "no data" kept as no data. `--json` prints the report as one object, each repo
  with its rows (and its metrics with `--metrics`). The skill's new Fleet section
  documents the fleet file, the report, and a routine prompt that runs it. The fleet
  file is `[[repos]]` tables naming each repo as `owner/name`, with an optional
  `incident_label`, refused (exit 2, naming the file and the problem) when it is
  missing, isn't TOML, has no repos, has an entry without `repo` or with an unknown key,
  names a repo not in owner/name form, or lists a repo twice.
  `watch_state.py --incident-label` takes the place of the config's
  `[operate] incident_label`, so a fleet entry's label is the one its watch reads (#91)

## [0.11.0] - 2026-10-04

### Added

- A merged spec becomes a task graph: `specs.py split NNN` proposes its build issues,
  one per `--group` of criteria, each with a title, a body naming its `S-NNN-k`
  criteria, and `Depends on` lines (`--after B:A`) to fill in as the issues get numbers
  (`--json` for the same as one object). `specs.py check` reads the Issues section as
  `- owner/repo#N: S-NNN-1, S-NNN-2` and holds every criterion of an approved or built
  spec to exactly one build issue there. `triage_state.py` reads a `Depends on
  owner/repo#N` (or same-repo `#N`) line in an issue's body as a hold: BLOCKED while the
  dependency is open, UNBLOCKED once it closes, and UNFILLED (an action state) while a
  `#{Bk}` placeholder from `split` is left unfilled; `--wip N` reports the room left
  under a WIP limit. The triage skill files the build issues as sub-issues of the
  feature issue, dispatches them in dependency order within `[roadmap] wip` once the
  config has it (#70), stacks a
  dependent PR on its dependency's open one, and verifies the whole spec when the last
  build issue closes (#71)
- github-ship-watch learns from failures. `watch_state.py` reports POSTMORTEM_DUE (an
  action) for an issue labelled `[operate] incident_label` (default `incident`) closed as
  completed, not as not planned or a duplicate, that no `docs/postmortems/*.md` on the
  default branch names in an `Incident:` line (`owner/repo#N`, the issue's URL, or `#N`),
  read through the GitHub contents API. The skill drafts the postmortem from the
  incident's comments and deployment statuses as a pull request the maintainer merges,
  from the new `docs/postmortems/TEMPLATE.md` (timeline, cause, what caught it, what would
  have caught it sooner, actions); after the merge each rule becomes a `D-n` entry through
  `decisions.py` and each other action an issue. A weekly retro, run only when the user
  schedules it, compares this week's metrics with last week's, reads the refused and
  reworked PRs, recurring review findings, and stuck states, and posts a short comment on
  the roadmap issue with at most three proposals, each opened as an issue. The new
  `scripts/retro.py` gathers the retro (`gather`) and checks proposal titles against the
  open issues (`dedupe`), and `metrics.py --until` ends the window at a date or time, so
  the week before can be measured (#72)
- A `product-intake` skill groups product feedback (open issues triage left to it, open
  discussions when Discussions are on, and their thumbs-up reactions) into one
  `opportunity` issue per outcome, with the problem, who is affected, the evidence, and
  what success looks like. The maintainer accepts one with the `planned` label or declines
  it by closing it as not planned with the reason in a comment; a later request for a
  declined outcome is linked into that opportunity's Evidence, never proposed again, and an
  accepted one goes to github-issue-triage's spec gate as a feature. Its
  `scripts/intake_state.py` reports NEW_FEEDBACK, OPPORTUNITY_OPEN, ACCEPTED, HANDED_OFF,
  DECLINED, NO_REASON, DONE, MERGED, and OVERLAP; an issue labelled `bug`, `roadmap`, or
  one of shipmill's own labels isn't feedback, and `--skip-label` adds more. `[autonomy] intake` sets how far it
  goes: `propose` (the default) or `observe`; `act` is refused, and `doctor` prints it (#69)
- The `product-intake` skill plans the roadmap: milestones are the roadmap, and it
  proposes the next one from accepted opportunities, ranked by evidence (requests and
  thumbs-up) per load (the opportunity plus its spec's build issues), within a new
  `[roadmap]` config section: `wip`, the issues open at once across the open milestones
  (default 5), and `cadence`, the weeks between milestone due dates (default 2). The
  proposal is a `milestone-proposal` issue the maintainer approves by closing it with an
  "approve" comment. Its `scripts/roadmap_state.py` reports MILESTONE, OVERDUE, WIP_OVER,
  UNPLANNED, PROPOSAL_OPEN, APPROVED, UNREADABLE, and NEXT. `doctor` validates
  `[roadmap]` and prints it when present (#70)
- A deploy gets its first health check right after it succeeds, not at the next scheduled
  `shipmill operate` run up to 10 minutes later: the deploy workflow in the README and the
  shipmill-setup skill ends with an `operate` job that runs `gh workflow run operate.yml -f
  dry-run=false` with `actions: write`, and the 10-minute schedule stays the backstop.
  `doctor` notes when an environment's deploy workflow starts the operate caller, and warns
  when it doesn't for an environment with `from` or `health` (#84)

### Changed

- github-issue-triage sends a user's request for a new capability to product intake
  instead of the spec gate: the new **opportunity** verdict (`Triage: **opportunity**`,
  the marker intake uses) hands it over, `triage_state.py` reads it TRIAGED and
  `intake_state.py` reads it NEW_FEEDBACK until an opportunity groups it. A spec is
  written only for an accepted opportunity (label `planned`), a request one already
  covers (held on that opportunity), or an issue the maintainer filed; bugs, contract
  tweaks, and small additive features keep their verdicts. The rubric, the comment
  templates, the spec gate, github-issue-resolve, product-intake, and `docs/flow.md`
  say so, and tests hold both scripts to the new templates (#78)

### Fixed

- `changelog_guard.py move` no longer leaves an entry headless when a union kept the
  PR's `###` heading line above the other side's lines: an entry right under a release
  heading goes under the nearest `###` heading above it, joining that heading in
  Unreleased or creating it in Keep a Changelog order, and `move` refuses a bullet with
  no `###` heading anywhere above it instead of moving it as a block (#82)
- `triage_state.py` no longer reads an incident closed as completed by hand as
  SUSPECT_CLOSE: an incident closes once the environment is healthy again, and
  github-ship-watch's POSTMORTEM_DUE follows it up. The label is `incident` by default;
  the script can't read the shipmill config, so pass `[operate] incident_label` with the
  new `--incident-label` when it differs (#83)
- A deploy workflow started by hand without `--ref <tag>` recorded its deployment under the
  branch, which names no release tag, so `shipmill operate` couldn't tell what ran there.
  The deploy workflow in the README and the shipmill-setup skill now starts with a `ref`
  job that fails such a run, with the right `gh workflow run ... --ref <tag>` command, and
  `doctor` warns when an environment's deploy workflow has no step comparing `github.ref`
  with `refs/tags/<tag>` (#80)

## [0.10.1] - 2026-10-04

### Fixed

- Spec and metrics follow-ups: `specs.py check` and `coverage` report "no specs" and
  exit 0 when `docs/specs/` doesn't exist yet, and `check` refuses the template's
  placeholder text left in an `approved` spec (Problem through Out of scope) or a
  `built` one (any section); `triage_state.py` reads a plain `#N` right after a hold
  phrase ("waits on #N") as the same repo; `metrics.py` pages an issue's comments back to its first "Released
  in" notice, so a notice from before the window keeps a later one out of issue to
  release, and its docstring and SKILL.md name the backport shape lead time misreads
  (#68)

## [0.10.0] - 2026-10-04

### Added

- `shipmill operate` rolls back an environment that fails `[operate] rollback_after`
  health checks in a row (default 3) to the previous tag that reached `success` there,
  under `rollback` autonomy and the hold: act dispatches, propose (or the hold) has the
  incident propose it for `operate --approve-rollback <environment>`, observe reports.
  It opens one issue per environment and bad tag, labelled `[operate] incident_label`
  (default `incident`), with the failing check and the rollback, and comments on it
  when the environment is healthy again or when the rollback fails its checks too, where
  it stops. An open incident holds the `[gates] blocker_lanes` like the blocker label.
  A failed check now writes a `failure` status each time, up to `rollback_after` in a
  row, to count them. `doctor` validates `[operate]` and wants `issues: write` on the
  operate job once an environment has `health` (#31)
- github-ship-watch reports what `shipmill operate` found, for a repo whose config has
  `[environments.<name>]` tables: OPERATE_FAILED (the operate caller's latest run failed;
  the watch reruns a flaky one once), UNHEALTHY (an environment's newest `shipmill health`
  status is a failure), PROMOTION_DUE (an open "Ready to promote" proposal, with its
  approve command, or a promotion operate would make or propose if it ran on a schedule),
  and INCIDENT_OPEN (an open issue labelled `[operate] incident_label`, default
  `incident`, with its age and the PRs linked to close it). Every repo with a shipmill
  config also gets a HOLD row for an open `shipmill-hold` issue, with who opened it and
  when; a hold alone doesn't make the watch exit 1. Incidents and holds lead the report,
  and the watch never deploys or rolls back itself (#33)
- Under `release = "propose"`, the land workflow closes the lane's "Ready to release"
  issue once the release is tagged, with a comment naming the tag and the run, and says so
  when the issue proposed another version. A new `close-proposal` job takes the caller's
  grant: add `issues: write` to the land job in `.github/workflows/release.yml` (`shipmill
  init` writes it, and `doctor` warns under `release = "propose"` until it is there).
  `shipmill operate` closes a "Ready to promote" or "Ready to deploy" issue once the
  environment runs its tag or a later one, whoever deployed it (#40)
- github-ship-watch's `metrics.py` measures a repo over a window (`--days 30` by
  default) from GitHub alone: deploy frequency (successful deployments per environment,
  or stable releases for a repo without deployments), lead time for changes (a merged
  PR's first commit to the first stable release that shipped its merge commit, median
  and p90), change failure rate (incidents per deploy, or `release-blocker` issues and
  hotfix releases per release), time to restore (an incident to operate's "healthy
  again" comment or its close), issue to release (an issue to its "Released in" notice),
  human touch (merges a person merged or approved; an agent merging with a person's
  token counts as the person), and agent share (merged PRs whose body carries Claude
  Code's footer or whose commits carry a `Co-Authored-By: Claude` or `Claude-Session:`
  trailer, and how many of those a person approved in a review). An empty measure reads
  "no data", never 0. A table by default, `--json`, and `--markdown` for a weekly post on
  the roadmap issue, which the user schedules (#56)
- A spec gate in github-issue-triage: an issue asking for new behaviour gets the verdict
  **feature** and a spec file `docs/specs/NNN-<slug>.md` (template in
  `docs/specs/TEMPLATE.md`) with numbered acceptance criteria `S-NNN-k`, merged through
  its own PR before any implementer starts. `specs.py` writes the next spec (`new`),
  validates them (`check`), lists the specs a path or area touches (`find`), and prints a
  spec's criteria for the implementer brief (`criteria`). `triage_state.py` reads a hold
  on a pull request of the same repo: BLOCKED while it is open, UNBLOCKED once it
  merges, and the new action state SPEC_REFUSED (exit 1) once it closes unmerged, until
  a newer triage comment decides again (#54)
- Acceptance tests from specs: a test proves a spec's criterion by naming it,
  `test_s007_2_...` (Go `TestS007_2...`) or a `proves: S-007-2` comment line, and
  `specs.py coverage [--spec NNN]` lists each criterion of the built specs with the
  Python, JS/TS, Go, and Rust tests that prove it, exiting 1 when one has none. A spec
  carries `status: draft|approved|built` and a Verification section; `check` refuses a
  built spec that lists no issues or leaves a criterion out of Verification. CI runs
  `check` and `coverage`, and the reviewer brief checks that each listed test really
  asserts its criterion (#55)

### Fixed

- The triage skills keep an implementer's or reviewer's worktree until its PR merges, not
  just until it's pushed: a revision goes back to the same agent through SendMessage, and
  an agent whose worktree was removed can't be resumed
- `doctor` accepts the repository hosting shipmill calling its own `operate.yml` locally:
  there `.github/workflows/operate.yml` is the reusable workflow, so the operate check
  reads the workflow that `uses: ./.github/workflows/operate.yml` instead. A blank line no
  longer hides what follows it: a later job's `environment:`, or a workflow input (#53)
- `shipmill propose` and `shipmill operate` no longer open a duplicate proposal issue in
  a repo with more than 500 open issues: every release or deploy proposal carries a
  `shipmill-proposal` label, created on first use, and is found among the open issues with
  it (refusing, rather than guessing, at 100 of them). A proposal opened before the label
  is found once by the old scan and labelled on that update.
  github-ship-watch finds proposals by the label too, falling back to its title search
  while none has it (#41)
- A config error for an unknown key in `[lanes]`, `[bump]` or `[autonomy]` lists the allowed
  keys as the values the file accepts (`'dev', 'hotfix', 'rc', 'stable'`), not as enum
  reprs like `<Lane.DEV: 'dev'>` (#59)
- Proposal follow-ups: `land` leaves open a release proposal for a later version than the
  one it released, as `operate` does for a deploy proposal; github-ship-watch always runs
  its title search beside the label lookup, so an unlabelled deploy proposal shows while a
  labelled one exists; and a `shipmill-proposal` label another run created meanwhile no
  longer fails the run (#65)

## [0.9.0] - 2026-10-04

### Added

- `shipmill gate <owner/repo>` starts a Claude Code background session (`claude --bg`)
  for a repo only when its state needs one: it reads the state with code, skips while a
  session it started is still working or waits on you, skips findings unchanged since
  the last launch, and passes the findings in the prompt. The prompt, whether open PRs
  count as work, and the retry window come from a new `[agents]` section of
  `.github/shipmill.toml`. `--refresh` moves a dedicated, detached checkout to the
  default branch first. The wheel now bundles the skills
- `shipmill launchd <owner/repo>` runs the gate from launchd every few minutes on a
  Mac, with a PATH built from where claude, gh, git, and uvx live outside temporary
  folders. Each pass is a new session, and a quiet tick makes no model call
- shipmill-setup connects the agent side: `setup_state.py` reports releases, the
  `[agents]` section, the plugin in `.claude/settings.json`, and the labels the skills
  read, and `--fix` enables the plugin and creates the labels. The gate on launchd is a
  new choice for where agents run
- `shipmill operate`, run every 10 minutes by the new reusable `operate.yml` through a
  caller that `shipmill init --operate` writes: for each environment it reads the current
  deployment from GitHub, checks its `health` URL (2xx within 10 s; a JSON body's `version`
  must name the deployed release), and records the result as deployment statuses, written
  only when the state changes. It promotes a `from` environment once its source has been
  healthy on a tag for `bake_minutes`, and redeploys a `lane` environment that missed its
  lane's newest tag, each at most once per tag (a deployment of it or a run of the
  workflow on it counts) and under `deploy.<environment>` autonomy:
  act dispatches, propose (or the hold) opens a "Ready to promote" issue that `operate
  --approve <environment>` deploys once, observe reports. `land` now starts environment
  workflows on the tag, so each deployment's ref names it. `doctor` checks the operate
  caller and its permissions once an environment uses `from` or `health` (#30)

## [0.8.0] - 2026-10-04

### Added

- Environments: an `[environments.<name>]` table in `.github/shipmill.toml` names a deploy
  `workflow` and exactly one of `lane` or `from`, plus an optional `health` URL and, with
  `from`, `bake_minutes`; a `from` chain must end at a `lane` environment. `land` starts the
  workflow of each environment whose `lane` is the release's, with `tag` and `environment`
  inputs, and lists it as `deploy.yml@staging`; `from` environments wait for promotion.
  `doctor` checks each workflow takes both inputs and that a job sets `environment:`, so
  GitHub records a deployment; `init` writes a commented example (#29)
- `[autonomy]` in `.github/shipmill.toml` sets each stage to `observe`, `propose`, or `act`
  (`release`, `deploy.<environment>`, and `rollback`, all `act` by default), and an open
  issue labelled `shipmill-hold` turns every `act` into `propose`. Under `release =
  "observe"` a due lane is only reported; under `"propose"`, or while a hold is open, the
  new `propose` job of `prepare.yml` opens or updates one "Ready to release vX on <lane>"
  issue per due lane instead of releasing. A lane started by hand still releases under
  propose; under a hold only a hotfix started by hand does. `doctor` prints the effective
  autonomy per stage and warns on an open hold. Proposing needs `issues: write` on the
  prepare job of the calling workflow, which `shipmill init` now writes; `doctor` warns
  about it only once a stage is set to propose or a hold is open. Each `deploy.<name>` must
  name an environment in `[environments]`. Deploy and rollback autonomy take effect once
  shipmill deploys (#32)

## [0.7.0] - 2026-10-04

### Fixed

- `changelog_guard.py move` carries each entry a rebase dropped into a released section
  under its own `###` heading in Unreleased, creating the heading in Keep a Changelog
  order, and leaves the released section as the base has it; it no longer leaves a bullet
  with no heading. `check` also fails on such a headless bullet and on a duplicate heading
  under Unreleased, and `union` keeps a blank line between a release heading and the
  heading it meets. The landing loop runs `move`, `check`, and the planner's dry run after
  every rebase, and prints the Unreleased section for the lander to read (#25)
- `triage_state.py` reads a busy repo such as pypa/pip: a page GitHub rejects for its
  resource limits is asked again at half the size, down to 10 issues, and one still
  rejected there fails with one error line instead of gh's line per node (#24)

### Added

- `.github/shipmill.toml`, the one config file every shipmill layer will read: `shipmill
  init` writes it, and `doctor` names the file it read. `.github/release-policy.toml` keeps
  working as an alias with the same keys, and `doctor` warns to rename it with `git mv`; a
  repo with both files fails. `init` refuses when either file exists, and `--force` replaces
  the alias with `shipmill.toml`. ship-watch finds either file. Rename to `shipmill.toml`
  only once the shipmill CLI your Release workflow runs (the `tool` input of `prepare.yml`
  and `land.yml`, default `@v0`) is this release or newer (#28)

## [0.6.0] - 2026-10-04

### Added

- "Where the agents run" in the README, and a last hand-over step in `shipmill-setup`
  that asks whether the skills run on demand, on a `/loop`, or as a cloud `/schedule`
  routine, and whether a routine may merge

### Changed

- The `release-lanes-setup` skill is now `shipmill-setup`: `/shipmill-setup` (or
  `/shipmill:shipmill-setup` from the plugin) replaces `/release-lanes-setup`. A checkout
  linked into `~/.agents/skills` re-runs the link loop from the README and removes the
  dangling `release-lanes-setup` link. "Set up release lanes" and "add a release bot"
  still find it

### Fixed

- The design gate finds an open decisions PR by the log file it changes, not by
  `DECISIONS` in its title, which missed a PR titled "Record D-1 and D-2"
- `triage_state.py` pages past the caps of its GitHub query instead of reading a capped
  list as complete: open issues beyond the newest 100, an issue's comments beyond the
  newest 50 (an older verdict or "On hold" line), cross-references beyond the oldest 50
  (a later linked PR), and tags back to the newest stable one. An issue with more than 100
  labels exits 2 as bad input. A repo under the caps still takes one query (#19)

## [0.5.2] - 2026-10-04

### Fixed

- `doctor`'s `work branch` check asks origin for a `shipmill` branch, as `prepare` does,
  instead of reading the clone's fetched refs: a shallow or single-branch clone (such as a
  CI checkout) passed while origin had the branch, and a stale `origin/shipmill` failed
  after it was deleted. It warns when there is no origin or origin can't be reached

## [0.5.1] - 2026-10-04

### Fixed

- A scheduled or hand-started run of the prepare workflow no longer cancels a push run
  waiting out `quiet_minutes`: only a newer push shares the settle job's concurrency
  group, and any other run gets a group of its own (#6)
- `prepare` names a branch `shipmill` on origin that blocks the `shipmill/<tag>` work
  branch, instead of failing with git's raw `cannot lock ref` error, and `doctor` checks
  for it as `work branch` (#7)
- `github-pr-triage` launches reviewer agents from the repo's root and has each confirm
  its remote: from a nested clone, worktree isolation copied the wrong repository and a
  reviewer's fix commits were lost with its worktree
- `triage_state.py` reads an issue's newest triage comment, not its oldest, so a
  re-decision changes NEEDS_PR and clears REVISIT. It compares comment and tag times as
  instants, so a tag date with a UTC offset no longer misorders against a comment's `Z`
  time
- The triage skills record a pass's decisions in one docs PR opened before dispatch, not
  in each implementing PR: decision ids are sequential, so two PRs that each added an
  entry both took the same `D-n`. github-pr-triage renumbers a colliding entry when it
  lands a batch

## [0.5.0] - 2026-10-03

### Added

- A design gate and a decisions log for the triage skills. An issue that changes a flag,
  a format, a default, a public API, or stored state gets its design written into the
  issue and checked against the repo's settled decisions before an implementer starts;
  a departure waits for the user. `decisions.py` keeps the log (`DECISIONS.md` or
  `docs/decisions.md`): `add` numbers and links entries, `find` lists the rules a diff's
  paths touch, `check` validates it. Implementer and reviewer briefs carry the matching
  rules, and github-pr-triage holds a PR that departs from one

## [0.4.0] - 2026-10-03

### Added

- The `github-ship-watch` skill: one pass reports a failed or stalled release bot, a
  release missing from PyPI, fixed issues not yet told which version shipped them, and
  issues triage owes, then finishes what the policy already decided. Its
  `watch_state.py` exits 1 when anything needs action, for `/loop` and `/schedule`

### Fixed

- `shipped.py` fetches tags with `--force`, so it no longer fails once the bot has moved
  a major tag such as `v0`

## [0.3.1] - 2026-10-03

### Fixed

- `github-pr-triage` starts a shipmill bot by naming the lane: a hand-started
  `lane=policy` run cancels the push run's quiet wait and then skips (#6)

## [0.3.0] - 2026-10-03

### Breaking

- release-lanes is now shipmill: the package, the CLI (`shipmill init`, `shipmill doctor`,
  and the rest), and the repository `romamo/shipmill`. In a repository already set up,
  replace `romamo/release-lanes` with `romamo/shipmill` in `.github/workflows/release.yml`,
  or run `shipmill init --force` and restore your policy. A release commit now waits on a
  `shipmill/` work branch

### Added

- The GitHub workflow skills join `release-lanes-setup`: `github-issue-triage`,
  `github-issue-resolve`, and `github-pr-triage`, with the whole flow in `docs/flow.md`.
  `github-pr-triage` starts a shipmill bot after its last merge
- A Claude Code plugin and marketplace in `.claude-plugin`: `/plugin marketplace add
  romamo/shipmill`, then `/plugin install shipmill@shipmill`. Each release sets the
  plugin's version

## [0.2.1] - 2026-10-03

### Fixed

- A rejected push now reports git's error, and a rejected tag push is retried: the first
  release by the bot (0.2.0) landed on main, but its tag push was refused and the
  reason was lost. The `land` step also fails when the tool fails, where a pipe through
  `tee` hid the failure and reported success

## [0.2.0] - 2026-10-03

### Added

- `doctor` fails a `[tool.uv.sources]` entry taken from a local path or installed
  editable, and the setup skill covers a Python package's build and smoke test

## [0.1.0] - 2026-10-01

### Added

- Release lanes driven by a hand-written CHANGELOG: `dev` and `rc` pre-releases cut from
  main without touching it, `stable` releases promoted from an rc that soaked without a
  blocker, and `hotfix` releases of chosen pull requests from `release/X.Y`
- Triggers per lane (quiet time after merges, schedule windows in any time zone, a finished
  milestone) and gates (a `release-blocker` label, freeze windows); every lane can be
  started by hand
- Version bumps from the pending entries' headings or from the paths changed since the last
  stable tag
- Reusable `prepare.yml` and `land.yml` workflows that run the caller's CI on the release
  commit before tagging, then sync a stable release made off main back into main
- `init` and `doctor` commands, and a setup skill for agents

[Unreleased]: https://github.com/shipmill/shipmill/compare/v0.66.0...HEAD
[0.66.0]: https://github.com/shipmill/shipmill/compare/v0.65.0...v0.66.0
[0.65.0]: https://github.com/shipmill/shipmill/compare/v0.64.0...v0.65.0
[0.64.0]: https://github.com/shipmill/shipmill/compare/v0.63.0...v0.64.0
[0.63.0]: https://github.com/shipmill/shipmill/compare/v0.62.0...v0.63.0
[0.62.0]: https://github.com/shipmill/shipmill/compare/v0.61.0...v0.62.0
[0.61.0]: https://github.com/shipmill/shipmill/compare/v0.60.0...v0.61.0
[0.60.0]: https://github.com/shipmill/shipmill/compare/v0.59.1...v0.60.0
[0.59.1]: https://github.com/shipmill/shipmill/compare/v0.59.0...v0.59.1
[0.59.0]: https://github.com/shipmill/shipmill/compare/v0.58.0...v0.59.0
[0.58.0]: https://github.com/shipmill/shipmill/compare/v0.57.0...v0.58.0
[0.57.0]: https://github.com/shipmill/shipmill/compare/v0.56.0...v0.57.0
[0.56.0]: https://github.com/shipmill/shipmill/compare/v0.55.0...v0.56.0
[0.55.0]: https://github.com/shipmill/shipmill/compare/v0.54.0...v0.55.0
[0.54.0]: https://github.com/shipmill/shipmill/compare/v0.53.0...v0.54.0
[0.53.0]: https://github.com/shipmill/shipmill/compare/v0.52.0...v0.53.0
[0.52.0]: https://github.com/shipmill/shipmill/compare/v0.51.0...v0.52.0
[0.51.0]: https://github.com/shipmill/shipmill/compare/v0.50.0...v0.51.0
[0.50.0]: https://github.com/shipmill/shipmill/compare/v0.49.0...v0.50.0
[0.49.0]: https://github.com/shipmill/shipmill/compare/v0.48.0...v0.49.0
[0.48.0]: https://github.com/shipmill/shipmill/compare/v0.47.0...v0.48.0
[0.47.0]: https://github.com/shipmill/shipmill/compare/v0.46.0...v0.47.0
[0.46.0]: https://github.com/shipmill/shipmill/compare/v0.45.0...v0.46.0
[0.45.0]: https://github.com/shipmill/shipmill/compare/v0.44.0...v0.45.0
[0.44.0]: https://github.com/shipmill/shipmill/compare/v0.43.0...v0.44.0
[0.43.0]: https://github.com/shipmill/shipmill/compare/v0.42.0...v0.43.0
[0.42.0]: https://github.com/shipmill/shipmill/compare/v0.41.2...v0.42.0
[0.41.2]: https://github.com/shipmill/shipmill/compare/v0.41.1...v0.41.2
[0.41.1]: https://github.com/shipmill/shipmill/compare/v0.41.0...v0.41.1
[0.41.0]: https://github.com/shipmill/shipmill/compare/v0.40.0...v0.41.0
[0.40.0]: https://github.com/shipmill/shipmill/compare/v0.39.0...v0.40.0
[0.39.0]: https://github.com/shipmill/shipmill/compare/v0.38.0...v0.39.0
[0.38.0]: https://github.com/shipmill/shipmill/compare/v0.37.0...v0.38.0
[0.37.0]: https://github.com/shipmill/shipmill/compare/v0.36.0...v0.37.0
[0.36.0]: https://github.com/shipmill/shipmill/compare/v0.35.0...v0.36.0
[0.35.0]: https://github.com/shipmill/shipmill/compare/v0.34.0...v0.35.0
[0.34.0]: https://github.com/shipmill/shipmill/compare/v0.33.2...v0.34.0
[0.33.2]: https://github.com/shipmill/shipmill/compare/v0.33.1...v0.33.2
[0.33.1]: https://github.com/shipmill/shipmill/compare/v0.33.0...v0.33.1
[0.33.0]: https://github.com/shipmill/shipmill/compare/v0.32.2...v0.33.0
[0.32.2]: https://github.com/shipmill/shipmill/compare/v0.32.1...v0.32.2
[0.32.1]: https://github.com/shipmill/shipmill/compare/v0.32.0...v0.32.1
[0.32.0]: https://github.com/shipmill/shipmill/compare/v0.31.1...v0.32.0
[0.31.1]: https://github.com/shipmill/shipmill/compare/v0.31.0...v0.31.1
[0.31.0]: https://github.com/shipmill/shipmill/compare/v0.30.0...v0.31.0
[0.30.0]: https://github.com/shipmill/shipmill/compare/v0.29.0...v0.30.0
[0.29.0]: https://github.com/shipmill/shipmill/compare/v0.28.0...v0.29.0
[0.28.0]: https://github.com/shipmill/shipmill/compare/v0.27.0...v0.28.0
[0.27.0]: https://github.com/shipmill/shipmill/compare/v0.26.0...v0.27.0
[0.26.0]: https://github.com/shipmill/shipmill/compare/v0.25.0...v0.26.0
[0.25.0]: https://github.com/shipmill/shipmill/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/shipmill/shipmill/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/shipmill/shipmill/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/shipmill/shipmill/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/shipmill/shipmill/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/shipmill/shipmill/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/shipmill/shipmill/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/shipmill/shipmill/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/shipmill/shipmill/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/shipmill/shipmill/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/shipmill/shipmill/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/romamo/shipmill/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/romamo/shipmill/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/romamo/shipmill/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/romamo/shipmill/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/romamo/shipmill/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/romamo/shipmill/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/romamo/shipmill/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/romamo/shipmill/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/romamo/shipmill/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/romamo/shipmill/compare/v0.5.2...v0.6.0
[0.5.2]: https://github.com/romamo/shipmill/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/romamo/shipmill/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/romamo/shipmill/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/romamo/shipmill/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/romamo/shipmill/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/romamo/shipmill/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/romamo/shipmill/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/romamo/shipmill/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/romamo/shipmill/releases/tag/v0.1.0
