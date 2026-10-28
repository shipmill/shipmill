---
name: shipmill-setup
description: Set up shipmill in a repository so releases are cut by policy on lanes (dev, rc, stable, hotfix) from its hand-written CHANGELOG. Use when the user asks to add a release bot, automate releases, set up release lanes, scheduled or nightly releases, release candidates, or hotfix releases, or to move a repo onto release lanes. Also connects the agent side, so the repo triages, fixes, and lands on its own: where the plugin loads (per person, or in the repo's settings), the labels the skills read, the config's [agents] section, and where the agents run, including `shipmill gate` on launchd. Use too when the user asks to "connect a repo to shipmill" or to make it "ship by itself", or to connect several repos as one product (a home repo and its components). Covers prerequisites, choosing lanes with the user, writing the policy, wiring CI and publishing, a dry run, and migration from hand-made or scripted releases.
---

# Set up shipmill

shipmill cuts releases from a hand-written CHANGELOG on lanes the project's policy
defines. Read [How a release works](https://github.com/shipmill/shipmill/blob/main/docs/release-lanes.md#how-a-release-works) once before starting:
pre-releases are tagged off main, stable releases ship every batch of merges whose CI
passed, and a breaking change waits for the maintainer's hand start.

Run the tool with:

```bash
CR="uvx shipmill==0.88.0"
```

the release this plugin pins, from PyPI (spec 031), in every session, a headless gate's
included, whose allowlist has `Bash(uvx *)`: the commands below are the ones this release
runs. uv keeps the release in its cache ([install.md](https://github.com/shipmill/shipmill/blob/main/docs/install.md#clean-up-old-builds)
says how to clean up old ones). For the user's own shell, recommend
`uv tool install shipmill` (upgraded with `uv tool upgrade shipmill`), which puts a bare
`shipmill` on PATH.

Work on a branch and finish with a pull request. Never set `mode = "release"` in the
first change: the bot starts in `dry-run`.

## 1. Inspect the repository

Collect these facts before asking the user anything; each one has a fixed answer in the
repo:

| Fact | Where to look | What the bot needs |
|---|---|---|
| Visibility | `gh repo view --json visibility` | `PRIVATE` or `INTERNAL`: GitHub bills its Actions minutes, so step 3 starts with [the cost](#on-a-private-repository) |
| Default branch | `git symbolic-ref refs/remotes/origin/HEAD` | the policy's `branch` |
| CHANGELOG style | `CHANGELOG.md` headings | `## [Unreleased]` with `## [X.Y.Z] - YYYY-MM-DD` and compare links (keep-a-changelog), or `## Unreleased` with `## X.Y.Z — YYYY-MM-DD` (dash) |
| Entry shape | the Unreleased section | keep-a-changelog: `- ` bullets under `### Category` headings, continuation lines indented; dash: one `### Title` block per entry |
| Version source | `pyproject.toml` `[project] version` | `version_files = "pyproject"`; a dynamic version or a non-Python project uses `"none"` plus `version_lines` |
| Other version strings | `git grep -n "<current version>"` | one `[[version_lines]]` entry each, a pattern matching exactly once |
| Stable tags | `git tag -l 'v*'` | at least one `vX.Y.Z`; the bot counts from the newest |
| CI workflow | `.github/workflows/*.yml` with the test jobs | must run on `workflow_call` with a `ref` input and check out `${{ inputs.ref }}` |
| Publish workflow | the one that uploads to PyPI, npm, or similar | must run on `workflow_dispatch` with a `tag` input and build `refs/tags/<tag>` |
| Existing release automation | release scripts, a release bot, tag-triggered workflows | replaced or disabled in the same pull request, so two tools never tag |
| Branch protection | `gh api repos/{owner}/{repo}/rulesets`, `.../branches/<branch>/protection` | `github-actions[bot]` must be able to push main, `release/*`, and `v*` tags |
| Python package basics | `pyproject.toml`, `src/`, the repo root | see [Python packages](#python-packages); a release ships whatever the build picks up |

## 2. Fix the prerequisites

Make each change the inspection showed missing, in the same branch:

- **No CHANGELOG**: create one in keep-a-changelog style with an empty `## [Unreleased]`
  and an `[Unreleased]: https://github.com/<owner>/<repo>/compare/v<latest>...HEAD` link
- **Entries the parser rejects**: `doctor` names the line; rewrite it into the entry shape,
  never loosen the policy around it
- **No stable tag**: ask the user which commit and version to tag; don't invent one
- **CI not callable**: add to its `on:`

  ```yaml
  workflow_call:
    inputs:
      ref:
        type: string
        required: true
  ```

  and pass `ref: ${{ inputs.ref }}` to its `actions/checkout` steps (empty outside a
  call, so pushes and pull requests keep checking out their own commit)
- **Publish workflow**: give it a `workflow_dispatch` `tag` input and build that tag. Remove
  any check that the tagged commit is on main: rc and promoted stable tags are off main
- **Tag-triggered publish** (`on: push: tags`): keep it only if it does not also run for
  the bot's tags; a workflow-token push starts no workflow, so the bot always dispatches
- **Python package**: make the fixes in [Python packages](#python-packages)

### Python packages

The bot publishes what `uv build` makes from the tag, so check the package once here.
`doctor` fails a `[tool.uv.sources]` entry with a `path` or `editable`: CI and users don't
have that checkout. Fix the rest by hand:

- `[project]` has a one-line `description`, `license`, `authors`, `requires-python`, and
  `[project.urls]` with `Repository` and `Issues` from `git remote get-url origin`. Take
  the author and license from the user's memory or earlier packages; never write a
  placeholder
- `LICENSE` and `README.md` exist; a typed package ships `src/<pkg>/py.typed`. A missing
  `README.md` is the user's to write (D-42): report it, never draft one
- `.gitignore` covers `.env`, `__pycache__`, `*.pyc`, and `.DS_Store`, and `git ls-files`
  lists none of them
- The sdist leaves out tooling: with hatchling, an explicit
  `[tool.hatch.build.targets.sdist]` `include` (`/src`, `/tests`, `/CHANGELOG.md`) or an
  `exclude` covering `/.github`, `/.agents`, `/.claude`, and `/uv.lock`
- The publish workflow builds the tag, checks the artifacts, and smoke-tests them before
  uploading. Add these steps after its checkout of the tag:

  ```yaml
  - run: uv build --out-dir dist
  - name: Check the sdist leaves out tooling
    run: |
      if tar -tzf dist/*.tar.gz | grep -E '^[^/]+/(\.github|\.agents?|\.claude|uv\.lock)(/|$)'; then
        exit 1
      fi
  - name: Smoke-test the wheel and the sdist
    run: |
      for dist in dist/*.whl dist/*.tar.gz; do
        uv run --isolated --no-project --with "$dist" python -c "import <pkg>"
      done
  ```

  A CLI checks its entry point too (`--with "$dist" <cli> --version`); a
  `tests/smoke_test.py` that calls one public function replaces the `import` line

## 3. Choose the lanes with the user

### On a private repository

Skip this for a public repo, which GitHub doesn't bill. On a private one, before proposing
lanes, tell the user what the default costs in billed Actions minutes on GitHub-hosted
runners ([Cost on private repositories](https://github.com/shipmill/shipmill/blob/main/docs/release-lanes.md#cost-on-private-repositories)),
and offer these setups, each with its rough figure. List them cheapest first, starting
from the cheapest that still gives what the user asked for:

| Setup | What to change | Rough cost |
|---|---|---|
| By hand only | remove `push` and `schedule` from `release.yml`'s `on:`, keep `workflow_dispatch` | nothing while idle; a few minutes per release |
| A fixed schedule, no quiet wait | lanes with `schedule` only, no `milestone`; `init --caller --force` in step 4 writes one cron per window time instead of the hourly tick | about 2 job-minutes per push and per tick; a lane held at its window releases on the next push or window tick |
| Release on every push | `quiet_minutes = 0`, the hourly cron | about 2 to 3 minutes per push, plus about 1,400 a month for the cron; a burst of merges cuts several releases |
| The default | `quiet_minutes = 30`, the hourly cron | about 30 minutes per push, plus about 1,400 a month |

`mode = "off"` sleeps no minutes, but releases nothing. Carry the user's choice into the
decisions below, and make any `release.yml` edit in step 4, after `init` writes the file.

**The runner.** On a private repo, ask with the decisions below where shipmill's release
jobs run: GitHub-hosted (the default, billed as above) or a self-hosted runner, named by
its labels (`self-hosted`, or a JSON list such as `["self-hosted", "linux"]`), which GitHub
doesn't bill. The runner needs `bash`, `git`, and `curl`, and network access to
`github.com`, `api.github.com`, `pypi.org`, and `files.pythonhosted.org`; `uv` comes from
the workflows' `astral-sh/setup-uv` step
([Self-hosted runners](https://github.com/shipmill/shipmill/blob/main/docs/release-lanes.md#self-hosted-runners)).
When the user picks a self-hosted runner and a lane uses `quiet_minutes`, ask whether that
runner also runs deploys. If it does, warn: a runner takes one job at a time, so the settle
wait holds it for up to `quiet_minutes` after each push, and a deploy started meanwhile
queues behind it. Offer the two fixes: give shipmill a runner of its own (another label or
another instance), or drop `quiet_minutes` for a `schedule`. Carry the labels into step 4's
`--runs-on`.

### The decisions

These are the user's decisions. Ask them together, with the defaults below as the
recommendation:

| Decision | Default | Notes |
|---|---|---|
| Lanes | `stable`, `hotfix` | add `rc` (and `dev`) only for people who try pre-releases |
| rc cadence | by hand, or `schedule = ["Mon-Fri 07:00 <their zone>"]` | the zone is an IANA name |
| Stable | `quiet_minutes = 30`, no `promote_from`, no soak | releases main's head after every batch of merges; a breaking change waits for the maintainer's hand start. `promote_from = "rc"` only when every stable release must be a pre-release people installed; it promotes the newest rc at any age |
| Milestones | `milestone = true` on stable | due once the milestone titled with the version has no open issues |
| Bump rule | `from = "headings"` for keep-a-changelog | `from = "paths"` when headings are topics, such as a spec |
| Where releases go | `github_release = true`; `dispatch = ["publish.yml"]` | per lane; pre-releases are marked pre-release |
| Holds | `release-blocker` holding `rc` and `stable` | create the label; add `freeze` ranges for holidays |
| Changelog fragments | on: `[changelog] fragments = "changelog.d"` | each PR adds its entry as a file `changelog.d/<issue>-<slug>.md` instead of editing `CHANGELOG.md`, so PRs stop conflicting on it; a stable release writes them into its section and deletes them. Off (`init --no-fragments`): each PR edits Unreleased |

This is what `shipmill init` writes. A policy whose `[lanes.stable]` sets the removed
`min_soak_days`, which shipmill refuses, migrates with `shipmill upgrade --apply stable-every-batch`.

### Environments

Ask whether releases deploy somewhere (a staging or production service), and skip this
for a library that only publishes. For each environment the user names, add a table to the
policy with exactly one of `lane` (deploy every release of that lane when it lands) or
`from` (promoted from another environment once it baked there), plus the
`workflow` that deploys and an optional `health` URL:

```toml
[environments.staging]
lane = "rc"
workflow = "deploy.yml"
health = "https://staging.example.com/health"
```

The deploy workflow is the repo's own. `land` starts it with `tag` and `environment`
inputs; it deploys that tag, and its job sets `environment:` so GitHub records a
deployment, the record of what runs where:

```yaml
on:
  workflow_dispatch:
    inputs:
      tag:
        type: string
        required: true
      environment:
        type: string
        required: true
jobs:
  ref:
    runs-on: ubuntu-latest
    steps:
      - name: Fail a run that isn't on the tag it deploys
        env:
          TAG: ${{ inputs.tag }}
          ENVIRONMENT: ${{ inputs.environment }}
        run: |
          if [ "$GITHUB_REF" != "refs/tags/$TAG" ]; then
            echo "::error::run it on the tag: gh workflow run deploy.yml --ref $TAG -f tag=$TAG -f environment=$ENVIRONMENT"
            exit 1
          fi
  deploy:
    needs: ref
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - uses: actions/checkout@v7
        with:
          ref: refs/tags/${{ inputs.tag }}
  operate: # with from or health: the first health check, right after the deploy
    needs: deploy
    runs-on: ubuntu-latest
    permissions:
      actions: write
    steps:
      - env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
        run: gh workflow run operate.yml -f dry-run=false
```

Turn an existing deploy workflow into this shape rather than writing a second one, and
remove its own trigger on tags or pushes, so one release deploys once. shipmill starts it on
the tag, so the deployment GitHub records names the tag as its ref. Keep the `ref` job: GitHub
records the run's ref, not the checked-out tag, so a run started by hand without `--ref <tag>`
would record a branch, and the job fails it first with the command to run instead (`doctor`
warns when a deploy workflow lacks it). The `operate` job matters once an environment has
`health` or `from` (and `init --operate` has written `operate.yml`): it starts operate as
soon as the deploy succeeds, so a bad deploy gets its first health check right away instead
of at the next 10-minute run. Keep it a separate job that needs the deploy job, so a failure
to start operate doesn't mark the deployment failed; drop it for an environment without
either.

If the environment already exists on GitHub with deployment protection, it must also allow
the release tags, since `land` starts the workflow on the tag (enabling GitHub Pages creates
`github-pages` allowing only `main`). Add a tag rule `v*` under Settings → Environments →
`<environment>` → Deployment branches and tags, or run
`gh api -X POST repos/<owner>/<repo>/environments/<environment>/deployment-branch-policies -f name='v*' -f type=tag`.

When an environment has `health` or `from`, also run `$CR init --operate` in step 4. It
writes `.github/workflows/operate.yml` and adds `rollback` and each `deploy.<env>` the
policy's `[autonomy]` doesn't set, at their default, `act`. operate.yml runs `shipmill operate` every 10 minutes:
it checks each `health` URL (2xx within 10 s; a JSON body's `version` must name the
deployed release), records the result as deployment statuses, and promotes a `from`
environment once its source stayed healthy for `bake_minutes`. An environment failing
`[operate] rollback_after` checks in a row (default 3) is rolled back to its last good tag
and gets an `incident` issue, which holds the rc and stable lanes until closed. Ask whether
production should deploy by itself after the bake (the default) or wait for approval
(`deploy.production = "propose"` in `[autonomy]`, approved with `gh workflow run
operate.yml -f approve=production -f dry-run=false`), and the same for rollbacks
(`rollback = "propose"`, approved with `-f approve-rollback=production`). Point the user at
`.github/workflows/operate.yml` as an extra scheduled workflow, and skip it for a
library with no environments.

### Downstream tests

For a library, ask whether other repositories depend on it and which of them the maintainer
promises not to break; skip this when none do. For each one, ask for its `owner/name`, the
workflow file in it that tests against the library, and whether it is report-only (private,
so contributors can't read why it failed, or slower than the library's own CI). Then:

1. Write `[downstream]` into the policy: `app_id` (the App below), and one
   `[downstream.<name>]` table per repository with `repo`, `workflow`, and, as needed,
   `ref`, `report_only = true`, and `timeout_minutes`; the keys are in
   [release-lanes.md](https://github.com/shipmill/shipmill/blob/main/docs/release-lanes.md#downstream-tests)
2. Point the maintainer at the interface the downstream's workflow must offer: a
   `workflow_dispatch` with the inputs `library-repo`, `library-ref`, and `shipmill-id`,
   and a `run-name` containing `${{ inputs.shipmill-id }}`. The downstream's workflow is its
   maintainer's; never edit it
3. Have the maintainer install the App on each downstream with Actions: read and write, and
   add its private key to the library as the repository secret `SHIPMILL_DOWNSTREAM_KEY`
   (`gh secret set SHIPMILL_DOWNSTREAM_KEY < <key file>`); the key never passes through you
4. Run `$CR init --downstream` in step 4, which writes only `.github/workflows/downstream.yml`
5. In step 5, read every `downstream` line of `$CR doctor` (with `--app-key <key file>` when
   the key is on this host) before reporting done: a FAIL names its fix, and a WARN that the
   maintainer's login can't read a downstream means the first pull request's check
   `downstream: <name>` shows the result

## 4. Write the files

```bash
$CR init --ci <ci-file>.yml
```

This writes `.github/shipmill.toml` (dry-run) and `.github/workflows/release.yml`, and,
for changelog fragments, `fragments = "changelog.d"` in the policy's `[changelog]` table
and `changelog.d/README.md`, which keeps the folder in git and is never read as a fragment.
When the user turned fragments off, run `$CR init --ci <ci-file>.yml --no-fragments`, which
writes neither. Tell the user that once fragments are on, every PR adds its entry as a new
fragment and leaves `CHANGELOG.md` alone. The repo's own docs are the maintainer's (D-42):
never edit CLAUDE.md, AGENTS.md, or CONTRIBUTING.md, nor draft text for them. Pass on each
`CHANGELOG_RULES` row of `scripts/setup_state.py` as its file and line
(`CONTRIBUTING.md:42 mentions Unreleased`), and leave the change to the user. Edit the
policy to the user's choices from step 3, then add `version_lines` and
`after_stamp` (for uv projects `["uv lock --check"]`; for a project with a docs check that
reads the version, that command too).

`init` wrote `release.yml`'s schedule from its starting policy, so once the policy is
edited, rewrite `release.yml` from it:

```bash
$CR init --caller --force --ci <ci-file>.yml
```

It writes only `release.yml`, with the schedule the edited policy needs (the hourly tick,
one cron per window time, or none). For a self-hosted runner chosen in step 3, add
`--runs-on <label>` or `--runs-on '<JSON list>'`, which puts every job of shipmill's
release workflows on it. `--force` replaces any hand edit, so make the private repo's
remaining `release.yml` edits (removing `push` and `schedule` for by hand only, per
[the setup chosen](#on-a-private-repository)) after it.

## 5. Verify

```bash
$CR doctor
```

Every line must be PASS; a WARN about the version is fine when the project is mid-series
(an rc on main). Then preview each lane locally (needs `gh auth status`):

```bash
$CR plan --lane rc --dry-run
$CR plan --lane stable --dry-run
```

Read the JSON: `version` must be what the user expects next. If it is not, the bump lists
or the tags are wrong; fix those, not the version.

## 6. Hand over

1. Open the pull request with the policy, the workflow, and the prerequisite changes
2. After it merges: run the Release workflow by hand (lane empty, dry-run on) and read the
   release commit in the run summary
3. Run the checklist: `uv run --no-project python <skill>/scripts/setup_state.py <owner/repo>`.
   It reports releases, the `[agents]` section, where the plugin loads, and
   the labels (`postponed`, `blocked`, `shipmill-hold`, the blocker label, and with an
   `[agents]` section, in either mode, `needs-decision`, `role:maintainer` and
   `role:<name>` for each role `[agents.roles]` defines, a role's item (spec 036), `human`,
   the older label for a person's item in a chain (spec 017), `shipmill-upgrade-later`, a config upgrade's "not now",
   `upstream`, a report for another repo, spec 038, and `decided`, a notify decision the
   maintainer may veto, spec 030), and
   whether GitHub deletes a pull request's branch when it merges (`BRANCH_DELETE_ON` or
   `BRANCH_DELETE_OFF`, the repo setting `delete_branch_on_merge`). That setting matters
   because github-pr-triage's stacked merges rely on GitHub retargeting a stacked PR when
   the branch under it is deleted, and without it merged branches pile up. `--fix`
   creates the missing labels and turns the setting on, all on GitHub at once, and with
   `[agents] plugin = "repo"` enables the plugin in `.claude/settings.json`, keeping every
   other key; commit the settings change in a follow-up PR. With
   `[agents] app_id` set it creates the labels as the App, through `shipmill gh` run by
   uvx at the version in the plugin's `plugin.json` (spec 012, spec 031); the setting stays on the host's `gh`, since the App has no
   Administration permission. A `shipmill gh` exit 2 stops `--fix`: report it, and never
   create the labels with plain `gh` instead.

   **Ask where the plugin loads** (spec 033): per person, the default `[agents] plugin =
   "host"` and the one to keep for a repo that takes outside contributions, or for
   everyone who opens the repo, `plugin = "repo"`, which commits it to
   `.claude/settings.json` so every contributor's Claude Code is offered it and its hooks.
   Write `plugin = "repo"` only when the user chooses it. With `host` the Plugin rows read
   the installs on this host: `PLUGIN_OK` names the install that applies to the repo's
   folder (user scope, or local or project scope keyed on its main checkout), and
   `PLUGIN_MISSING` gives the command, `claude plugin marketplace add shipmill/shipmill &&
   claude plugin install shipmill@shipmill --scope user`: run it on the maintainer's host
   after asking, since it changes their host, never with `--fix`. `PLUGIN_COMMITTED` (not
   done; `--fix` leaves it) says `.claude/settings.json` still enables the plugin while the
   key is `host`, as in a repo connected before spec 033: ask, then either set `plugin =
   "repo"` to keep it, or delete `shipmill@shipmill` from `enabledPlugins` (and the
   `shipmill` entry from `extraKnownMarketplaces` when no other plugin uses it), each in a
   pull request. With `host`, `--fix` never creates or changes `.claude/settings.json`. A
   plugin turned off on purpose
   (`PLUGIN_DISABLED`) is the user's call; ask before changing it. A host keeps one install,
   at user scope (spec 039): never install at project or local scope. In either mode, in
   place of a `PLUGIN_OK`, a user install behind the latest release reads `PLUGIN_OUTDATED`
   with its one update, run anywhere, `claude plugin marketplace update shipmill && claude
   plugin update shipmill@shipmill --scope user`, and the project- and local-scope installs
   keyed on the repo's checkout, its linked worktrees, or its gate checkouts (`shipmill
   factory` counts every one on the host) read as one `PLUGIN_SHADOWING` row whose fix is
   `uvx shipmill==<version> plugin-clean`, a dry run; the user removes them with `plugin-clean --apply` from their
   own terminal (both not done; `--fix` leaves them). Give the user the fixes. A link or
   copy of a shipmill skill in `~/.claude/skills` or `~/.agents/skills` reads
   `SKILL_SHADOWED`, one row each with its fix (not done; `--fix` leaves it): a prompt's
   bare `/<skill>` loads it in place of the plugin's. Give the user the fix (remove it, or
   call the skill as `/shipmill:<skill>`); never delete anything in their home folder
   yourself. A link into the plugin's cache is the plugin's own and isn't reported

   With an `[agents]` section, `AUTONOMY_IMPLICIT` follows the agents rows when the
   config's `[autonomy]` sets none of `triage`, `fix`, and `land` (spec 040): how far a
   gate session goes was never chosen, so it comes from the defaults or the prompt's
   words. Not done; `--fix` leaves it. Its fix is the Autonomy step, which writes all
   three keys, `land` among them: whether the gate works on open pull requests

   One Product row follows (spec 043). With `[agents] app_id` and no `[product]` table, the
   script lists the owner's unarchived repos with the host's `gh` and reads each one's
   `.github/shipmill.toml` from its default branch; a repo whose config sets the same
   `app_id` is a sibling. `PRODUCT_LISTED` (not done) names a sibling whose `[product]
   repos` lists this repo and the `[product] home = "<sibling>"` line to write;
   `PRODUCT_SIBLINGS` (not done) names the siblings, for the maintainer to say whether the
   repos make up one product, written as `home`, `repos`, or `standalone = true`;
   `PRODUCT_OK` is done: `[product]` is set in any form, there is no `app_id`, or no
   sibling exists. `--fix` leaves the row: each answer is a config change in a pull
   request. A sibling config the script can't read is named in the detail and skipped;
   it is that repo's to fix. The Product step under [The gate](#the-gate) answers both
   rows

   A warning row may follow: `RUNNER_SHARED` when `release.yml` passes a `runs-on` other
   than `ubuntu-latest`, a lane sets `quiet_minutes` above 0, and a workflow an
   environment's `workflow` or a lane's `dispatch` names has a job on the same runner
   labels (the same set, a subset, or a superset). It names the workflow and the fixes from
   step 3; it doesn't change the exit code, and `--fix` leaves it. Tell the user and let
   them choose

   Another warning row, `CHANGELOG_RULES`, follows once `[changelog]` sets `fragments`:
   one per line that mentions Unreleased in the root's CLAUDE.md, AGENTS.md, or
   CONTRIBUTING.md, or in `.github/CONTRIBUTING.md` or `docs/CONTRIBUTING.md`, as file and
   line. It doesn't change the exit code, and `--fix` leaves it: those files are the
   maintainer's (D-42). Pass each one on to the user

   The checklist reads the setup, not the factory. When checking an existing setup, also
   run `$CR status <owner/repo>` in the repo's checkout and report the verdict on its first
   line (`IDLE`, `WORKING`, `WAITS ON YOU`, or `STUCK`) and every line behind a waits-on-you
   or stuck verdict. Call the setup healthy only when the checklist exits 0 and the
   verdict is `IDLE` or `WORKING`. Use the plain report: `status --json` passes
   github-ship-watch's rows through and has no verdict
4. Ask the user to switch `mode = "release"` once the dry run looks right
5. Ask where the agents will run: releasing needs none of them, but triage, landing, and
   the shipped notices do. Recommend on demand to start, and offer the other two:

   | Option | Runs | Stops when |
   |---|---|---|
   | On demand | in the user's session, when they invoke a skill | the task is done |
   | `/loop 30m /shipmill:github-ship-watch <owner/repo> — watch and triage` | in this session | the session closes |
   | The gate (`shipmill gate` on launchd) | a new background session on this machine, only when the repo needs one, with its memory and repos | the job is removed |
   | A `/schedule` routine | in the cloud, with the user's computer off | the user deletes it |

   Recommend the gate over `/loop` for anything that runs for days: each pass is a fresh
   session, and a quiet tick makes no model call (see [The gate](#the-gate))

   A routine goes no further than `[autonomy]`, whatever its prompt says: it merges only
   under `land = "act"`, which the Autonomy step (in [The gate](#the-gate)) asks. Write the prompt so it clones shipmill rather than relying on the
   plugin, which a cloud routine may not load (docs/flow.md, Keeping it running), and offer
   to create it with `/schedule`

## The gate

`shipmill gate` is code that reads the repo's state and starts a Claude Code background
session (`claude --bg`) only when something needs an agent and no session it started is still
working or waiting on the user. Something needs an agent when github-ship-watch's
`watch_state.py` marks a row `agent: true` (github-ship-watch's SKILL.md lists them), plus
open PRs unless `[autonomy] land` is `observe` (spec 040; `[agents] prs` is deprecated, and
doctor warns while it is set). docs/design/agent-modes.md has the details.

A tick checks for change first (spec 046, D-58): one GraphQL query and one read of each
watched workflow's 10 newest runs (the release workflow and each `[operate]` workflow),
against the cursor of its last walk (`cursor.json` in the state directory). With nothing changed it reads nothing more and prints `QUIET: no change since
<cursor>`, a few seconds. On a change, or when a handed item's `retry_hours` ran out or the
last session ended dead, it walks the work tiers in order and stops at the first item no
session was handed within `retry_hours` (`handed.json`): 1 production (INCIDENT_OPEN,
OPERATE_FAILED), 2 the release lane, 3 open PRs to land, 4 vetoes and decided items, 5
upgrades and upstream reports, 6 the other issues triage owes, one item per triage state, 7
direction and plans, 8 notices. It reads a tier only when every tier above it is empty or
handed, and hands the session that one item, with its tier and its fix line, so a stuck
item never holds back the next. The timed sections (BOT_STALLED, UPGRADE_PENDING,
UPSTREAM_DUE, DIRECTION_PENDING, PLANS, UNANNOUNCED) come from a sweep every
`[agents] sweep_hours` (default 6, `sweep.json`), and a new release tag checks its own notices. The
decision line says how far the walk went (`read tiers 1-3`), and `--json` adds `walk` and
`item`. `--walk` walks and `--sweep` sweeps whether or not they are due, for a run by hand;
`--dry-run` writes none of these files. `shipmill status` still reads the full report.

Once a tick has its decision, held or not, it also prunes landed worktrees, every
`[agents] prune_hours` (default 6; 0: every tick; the last attempt is the state directory's
`prune.json`): it removes a worktree under `.claude/worktrees/` or `tmp/wt-*` and its local branch
once its commits landed on the default branch, it is clean and over a day old, and no
open PR or live Claude Code session holds it, and prints a `pruned <path> (<branch>)` line
for each, after the decision's lines (`would prune` under `--dry-run`, which judges every
time). A prune that fails prints `prune failed: <first line>` and fails no tick: the
decision and any launch stand, and `shipmill factory`'s `prune` line shows it failing since
when, with its fix, `shipmill worktrees --prune`, which `shipmill status` counts on its
`factory` line (spec 045). The worktrees a session leaves behind once it
exits are the gate's prune's to remove (D-12); never the main checkout, the gate's own
checkout, or a worktree elsewhere. `$CR --repo tmp/shipmill-gate worktrees` lists every
worktree as REMOVABLE or KEPT with why it is kept (`--json` for a record, `--prune
--dry-run` for what a prune would remove); `shipmill factory` lists a kept one older than 7
days with its fix, for a person to finish or remove.

`$CR factory` checks the gate's host for the repo, one line per check: the gate's launchd job
and log, its live sessions, the GitHub App, the shipmill installs, the local checkout, the
worktrees, and the gate's last prune, each run on its own (spec 044). `shipmill status` is the pipeline: what waits
on whom, from GitHub, with one `factory` line summing up those checks.

1. **Autonomy.** Ask once how far shipmill goes by itself, with AskUserQuestion (in a gate
   session through the needs-decision protocol), before you report the agent side
   connected (spec 040, D-51). Offer the profiles; each writes every stage key, so no level
   hides in a default:

   | Profile | triage | fix | land | release | deploy (production) | rollback |
   |---|---|---|---|---|---|---|
   | Watch first | propose | observe | observe | propose | propose | propose |
   | Recommended for the first weeks | act | act | propose | act | propose | act |
   | Ship by itself | act | act | act | act | act | act |
   | Custom | asked one stage at a time | | | | | |

   Recommend "Recommended for the first weeks". Under the question, show what each level
   means for each stage:

   - **triage:** `observe` reports the verdicts in the session and the gate log and writes
     nothing to GitHub; `propose` posts each verdict as a comment headed `Proposed verdict`,
     with no label, close, or dispatch, which you apply by hand or by replying `apply`;
     `act` posts the verdict, labels, closes, and dispatches
   - **fix:** `observe` writes no plan and no code; `propose` posts the implementation plan
     on the issue and opens no branch; `act` opens a branch and a pull request per implement
   - **land:** `observe` reviews in the session only, with no push and no comment; `propose`
     reviews, pushes small fixes with regression tests, posts the review, and labels a pull
     request that passes every check `shipmill-ready`, for a person to merge; `act` merges on
     green CI
   - **release, deploy, rollback:** `observe` reports only; `propose` opens an issue saying
     what it would do, and a person does it; `act` does it

   And the stop switch: one open issue labelled `shipmill-hold` turns every `act` into
   `propose`, for these stages and the release side alike, until it is closed; the gate
   starts nothing while it is open (D-15). Inside a stage at `act`, `[decisions]` still
   decides each decision by its zone.

   Write the answer into `[autonomy]` in the setup's PR, editing the section `shipmill
   init` wrote rather than adding a second one. Write `deploy.<env>` for each environment
   the config declares (the profile's production level for each; Custom asks per
   environment), and leave it out when there are none:

   ```toml
   [autonomy]
   triage = "act"
   fix = "act"
   land = "propose"
   release = "act"
   deploy.production = "propose"
   rollback = "act"
   ```

   Once that PR merges, run `$CR autonomy` and show the user its table. The prompt holds
   the task only, never the scope: `/shipmill:github-issue-triage {repo} triage the new
   issues`. Its words can lower a stage ("do not merge") but never raise one, so "merge
   when green" under `land = "propose"` merges nothing. Open PRs count as work unless
   `land` is `observe`. Name every shipmill skill with the plugin's prefix
   (`/shipmill:<skill>`): a skill of the same name in `~/.claude/skills` or
   `~/.agents/skills`, such as a link to a working copy, answers a bare `/<skill>` in place
   of the released plugin (#236). The checklist reads a bare one as `AGENTS_UNPREFIXED`
2. **Config.** Add the section to `.github/shipmill.toml` in a PR, and merge it before the
   job starts:

   ```toml
   [agents]
   prompt = "/shipmill:github-issue-triage {repo} triage the new issues"
   retry_hours = 24   # unchanged findings start a new session after this
   notify = true      # a desktop notification when a session waits on you
   remind_hours = 4   # repeat it while the session still waits
   max_wait_minutes = 15 # stop a session that waited this long; 0: never
   app_id = 123456    # replace with the App ID step 3 prints; sessions write as its bot
   mode = "interactive" # step 4's answer: sessions ask you; "headless": they ask on GitHub
   # wip = 3          # at most 3 issues in progress at once (1..100); unset: no limit
   ```

   Gate sessions load the installed plugin, which runs the CLI release it pins (spec 031,
   D-44); the gate never changes an install. When the user install is older than the
   latest release, or a project- or local-scope install applies to its checkout, the tick
   reports it with its fix and the session still starts. The setup checklist's
   `PLUGIN_OUTDATED` rows name the install a session loads with a `gate:` row when it lags. `[agents] plugin_update` was removed: never write it; in a config
   that has it, delete it, since each shipmill command that reads the config refuses it with exit 2

   The delivery hooks come with the plugin (spec 026), and need `uv` on PATH. In a repo
   whose config has `[agents]`, they refuse with exit 2 a plain `gh` write while `app_id`
   is set, a push to the default branch, a rebase merge, a force push without a lease
   pinned to a commit, and a copy of a `[hooks] private` path out of the repo. Ask whether
   the repo has paths whose files must never leave it (an `owner/` folder, for example),
   and list them as globs in `[hooks] private` in the same PR; `[hooks] default_branch =
   false` switches off the default-branch rule. Before you report the agent side
   connected, run `$CR doctor` and read its `hooks` block: one line per rule, on or off,
   and a passing self-test

   Every time you set up the gate, ask two questions together, before writing the
   section: who should own the gate's GitHub App (step 3), and whether anyone watches
   this machine, which picks `mode` (step 4); the Product step's question below joins
   that round. Write both answers into `[agents]`: `app_id`
   and `mode = "interactive"` or `mode = "headless"`, never left to the default (D-20).
   A session that waits on a question holds the repo, so by default the gate stops it
   after 15 minutes. Ask whether the user answers questions sooner or later than that; set
   `max_wait_minutes` (0..10080) to match, or 0 to never stop one. `app_id` is a
   placeholder until step 3 replaces it; never merge `123456` itself

   **Roles (spec 036).** A step an agent can't do (a DNS record, a new repository, a
   provider key, a sign-off) goes to a role, and the session files it labelled
   `role:<name>` and assigned that role's users at once, without asking who does it. Ask
   the user who receives such steps, and whether some go to someone else; write the answer
   as `[agents.roles]` in the same PR:

   ```toml
   [agents.roles]
   maintainer = ["octocat"]           # the default for every step an agent can't do
   infra = ["octocat", "hubot"]       # DNS, secrets, new repositories
   legal = ["@example-org/legal"]     # a team: mentioned, since a team can't be assigned
   accounting = []                    # nobody yet: falls back to the maintainer
   ```

   - Each key is a role name, `[a-z0-9][a-z0-9-]{0,44}`, and each value an array of
     GitHub logins and teams as `@<org>/<team-slug>`. The table is optional; with none,
     the only role is `maintainer`
   - With `maintainer` unset or `[]`, the maintainer is the host's `gh` login (`gh api
     user`), the person a needs-decision question mentions, never the repo's owner. A role
     set to `[]`, or a `role:<name>` label no role defines, falls back to the maintainer
   - A team is mentioned in the hand-off, never assigned, so `maintainer` must name at
     least one user when it is set
   - Every reader of the config (`$CR doctor`, the gate's tick, `$CR roles`) exits 2
     naming `[agents.roles]` and the key for a table that isn't one, a name outside the
     pattern, a value that isn't an array of strings (an inline table such as
     `{ agent = "..." }` too: agent-filled roles aren't supported yet), a filler that is
     neither a login nor `@org/team`, a login ending `[bot]`, a filler listed twice in one
     role, or a `maintainer` that lists only teams
   - `$CR roles` prints each role resolved, `maintainer` first, with `(fallback)` on one
     that resolved to the maintainer; `--json` prints them as one object, and `--flags`
     as the `--role` flags `triage_state.py` takes. The gate, `shipmill status`, and
     `watch_state.py` pass those flags on every state read. Show the user `$CR roles`
     before you call the section done
   - Labels: `setup_state.py --fix` creates `role:maintainer` and a `role:<name>` label
     for each role the table defines; a role added later needs `--fix` again. Existing
     `human` items keep their label and read as `role:maintainer`

   **The product's direction (D-34, spec 024).** A repo whose agents implement keeps its
   direction in `docs/product.md`, and the agents work toward it: triage names the goal an
   issue serves, implementers plan against it, and reviewers check the diff against it.
   When you connect `[agents]` and the default branch has no `docs/product.md`, ask the
   maintainer for its content, section by section: the mission (what the product is for),
   its users, the goals it works toward now, its non-goals, and its quality bar (what
   every change must hold). Point them to
   https://github.com/shipmill/shipmill/blob/main/docs/direction.md, which explains the
   file for people. Write their words into the file's fixed structure, each item
   one line with its id from 1 (`- U-1: ...`, `- G-1: ...`, `- N-1: ...`, `- Q-1: ...`),
   run `$CR product check` until it exits 0, and commit the file in the same pull request
   as the `[agents]` section. For each goal you write, offer a measure from the registry
   of spec 027, `<metric> <comparison> <target>` with a comparison of `<`, `<=`, `>`, or
   `>=`: `deploy_frequency` (`<n>/week`), `lead_time_median`, `lead_time_p90`,
   `time_to_restore_median`, `issue_to_release_median`, `issue_to_release_p90` (`<n>h` or
   `<n>d`), `change_failure_rate`, `human_touch`, `agent_share` (`<n>%`), such as
   `issue_to_release_median < 2d`. Write only the measures the maintainer gives, each with
   `$CR product measure G-n "<metric> <comparison> <target>"`, never by hand; a goal they
   give no measure gets none, and you never pick the metric or the target for them. Never invent a goal, a user, a non-goal, or a quality-bar
   item, and never fill one in from the README: what the maintainer didn't say stays out,
   and a section they can't answer yet (Users, Goals, and Quality bar each need at least
   one item; Non-goals may stay empty) is a question for them, not a guess. Show them the
   file before the pull request opens. Only the maintainer changes it later: the agents
   never merge an edit to it on their own. A repo without `[agents]`, where shipmill only
   cuts releases, needs none. Offer a starter `REVIEW.md` at the root too (Important
   rules, a `cap:` under Nits, Protected areas; `$CR review check`); it is optional

   **Product (spec 043).** A product may span several repos: a home, which holds planning
   and cross-repo work, and its components; the home's gate is their coordinator (D-47).
   Skip the question only when `.github/shipmill.toml` already has a `[product]` table in
   any form, `standalone = true` included. A first setup asks it too, though its config has
   no `[agents] app_id` yet: a product's repos meet through the App, so read the
   checklist's Product row (`setup_state.py <owner/repo>`, step 6's item 3) once the App's
   id is in this checkout's config, which the script reads; before that the row reads
   `PRODUCT_OK` with no sibling read. Then:

   - **`PRODUCT_LISTED`:** a sibling's `[product] repos` already lists this repo, so the
     maintainer answered in the home. Write the `[product] home = "<that sibling>"` line
     the row names, with no question. When two siblings list it, the row names both: ask
     which one is the home
   - **Otherwise ask, once,** in the same round as the App and mode questions (D-20), with
     AskUserQuestion, or through the needs-decision protocol in a gate session (D-21): "Is
     `<owner/repo>` one of several repos that make up one product?" On
     `PRODUCT_SIBLINGS`, list the siblings the row names as the likely other repos.
     Options: "No, it stands alone" (recommended when no sibling was found) and "Yes"
     (recommended when one was)
   - **On yes, ask for the home and the components.** The home is the repo whose
     `docs/product.md` describes the product as a whole (D-46); the components are the
     other repos. Offer the siblings found; the maintainer may name other repos, of any
     owner
   - **Write this repo's half** into `.github/shipmill.toml` (D-4), in the same pull
     request as the `[agents]` section:
     - In the home: `[product] repos = ["<owner/component>", ...]`, the components, which
       needs `[agents] app_id` in the same file
     - In a component: `[product] home = "<owner/home>"`
     - On "No, it stands alone": `[product] standalone = true`, alone in the table, so the
       question is not asked again. Joining a product later replaces it with `home` or
       `repos`
   - **Write only this checkout's config** (D-14): never another repo's config, its pull
     request, or a `$CR gh -R <other repo>` write. For each other repo of the product,
     print one line naming the table that repo needs and `/shipmill:shipmill-setup <repo>`
     to run in its checkout, and show the list to the maintainer before the pull request
     opens:

     ```
     acme/api: [product] home = "acme/product"  run /shipmill:shipmill-setup acme/api in its checkout
     acme/product: [product] repos = ["acme/api", "acme/web"]  run /shipmill:shipmill-setup acme/product in its checkout
     ```

     Run in a component once the home's `repos` has merged, the checklist reads
     `PRODUCT_LISTED` and this step writes its `home` with no question
   - **The App on every repo:** for each component the App doesn't cover yet, run `$CR
     app-install <owner/component>`, as for any repo connected later (step 3). The
     coordinator's product permissions (contents, issues, and pull requests read, issues
     write, metadata read) are a subset of a session's, so an installation made for
     sessions covers them

   Then tell the maintainer what works today and what doesn't yet:

   - **Works today:** the home's gate is the coordinator, with a token over the listed
     repos (`shipmill app-token --product`, `shipmill gh --product`); a component's agent
     reports a fault in another repo as an `upstream` issue in its own repo, and the
     coordinator routes it (`upstream_state.py`, `chains.py link --product --child`) and
     closes it. `doctor` checks the product's repos and their links back
     (shipmill/shipmill#604, closed), and the coordinator routes a report filed in the
     home repo itself (shipmill/shipmill#596, closed)
   - **Not yet:** a plan across repos (D-46, on hold); the maintainer's queue across
     repos; a component reading its home's direction (shipmill/shipmill#579). Each line
     goes when its issue closes

   **With `[product]` set, the links back are doctor's.** Run no check of the links back
   of your own. The `$CR doctor` run before you report the agent side connected prints a
   `product` block: relay each of its lines with its fix.

   - In the home, per repo `[product] repos` lists (S-038-27): a FAIL `<repo>: ...; the
     coordinator can't reach it: run $CR app-install <repo>` when the App isn't installed
     there or lacks a product permission; run it, as above
   - In the home, per listed repo (S-038-28): a WARN `<repo>'s .github/shipmill.toml has
     no [product] home`, `<repo> has no .github/shipmill.toml`, or `<repo>'s [product]
     home names <other>, not this home <home>`, each with the fix `set [product] home =
     "<home>" in <repo>'s .github/shipmill.toml`: give the maintainer that repo's line
     above, to run in its checkout
   - In a component (S-038-30): a WARN `<home>'s [product] repos doesn't list <repo>`,
     with the fix `add "<repo>" to [product] repos in <home>'s .github/shipmill.toml`:
     give the maintainer the home's line, to run in its checkout
   - A WARN that the App's key isn't on this host, or that a config can't be read, names
     what was left unchecked: pass it on as it is
3. **Its own identity (required for the gate, D-19).** Every gate gets a GitHub App, so its
   sessions' pull requests, comments, merges, and commits are made by the App's bot
   (D-14). Without `app_id`, a session writes as the host's `gh` login: its work reads as
   the user's own, the user can't approve its pull requests, and GitHub doesn't notify
   them of its mentions. Until `app_id` is set, `setup_state.py` reads `AGENTS_NO_APP` and
   github-ship-watch reads `GATE_NO_APP`, both an action for the user (exit 1). Ask the
   user who should own the App (below), then create it with `$CR app-create` (spec 006),
   or for a repo added to an existing App, run `$CR app-install`:
   - **Plan it:** `$CR app-create --dry-run` finds the accounts the user's `gh` login
     administers and the repos in them holding `.github/shipmill.toml`, and prints the
     plan: the App is the user's own (personal account) by default, **private** when every
     gated repo is in it and **public** when any is in an org (a private App installs only
     on its owner; a public one on any account, but only the key's holder can mint its
     tokens). Ask the user who should own it, their personal account first as the default
     or an org they administer, then show the plan and ask whether to create it; `--owner`,
     `--public`, `--private`, and `--name` change it. It needs the `read:org` scope, and
     it names the App `shipmill-<owner>`, or `shipmill-<login>` when that is taken, saying so
   - **Create it:** once the user agrees, run it yourself with their `--owner` and without
     `--dry-run`, in the
     background: it waits up to 10 minutes for the click. It opens a local page showing
     the plan and the permissions; the user clicks **Create on GitHub**, then **Create
     GitHub App** on GitHub's page, where every field is filled in. If GitHub asks them to
     sign in first it shows *We didn't find an App Manifest*: they go back to the local
     page and click again. Then they pick the repos on the install page it opens next. It saves the key to `~/.config/shipmill/app-<app_id>.pem`
     (mode `0600`), prints `installed on <owner/repo>` as each appears, and ends with the
     `app_id = <id>` line to commit; exit 1 names a repo still missing the App
   - **Set `app_id`** in `[agents]` through a PR, in each gated repo: the printed id in
     place of the placeholder
   - **A repo connected later, or in another account:** run `$CR app-install <owner/repo>`.
     It never installs or adds anything itself: for a repo the App doesn't cover it opens
     the App's **Install App** page and says what to click there (Install for a new account,
     Configure to add a repo to an existing installation). Relay those steps, ask the user
     to click, and wait for its `installed on <owner/repo>`

   By hand instead, in GitHub's settings (Developer settings, GitHub Apps, New GitHub App):
   - **No webhook:** clear Webhook's Active box; the App needs no callback URL either
   - **These repository permissions, and no others:**

     | Permission | Access | Why |
     |---|---|---|
     | Contents | write | push branches, merge |
     | Pull requests | write | open, review, and merge pull requests |
     | Issues | write | comments, labels, closing |
     | Actions | write | rerun a failed release job (github-ship-watch) |
     | Workflows | write | push a change under `.github/workflows/` |
     | Checks | read | CI state |
     | Commit statuses | read | CI state |
     | Discussions | read | product-intake's input |
     | Metadata | read | required by GitHub |

   - **Install it only on the repos the gate works on** ("Only select repositories")
   - **The private key:** generate one on the App's page, move the download to
     `~/.config/shipmill/app-<app_id>.pem`, and `chmod 600` it. The key is a host secret
     and never goes in the repo; a key elsewhere goes to `gate --app-key <path>`
   - **`app_id`:** the App ID from its settings page (not the client ID), set in
     `[agents]` in the same PR as the rest of the section

   With `app_id` set, each launch reads the key (missing, or readable by group or others:
   exit 2 naming its path), signs the App's JWT with `openssl dgst -sha256 -sign`, checks
   that the App is installed on the repo with every permission above, and starts the
   session as `<slug>[bot]`, with `<id>+<slug>[bot]@users.noreply.github.com` as its git
   author and committer. The session holds no token: the gate writes two helpers, mode
   `0700`, to `$(git rev-parse --git-common-dir)/shipmill/bin/` (a `gh` wrapper and
   `git-credential-shipmill`), puts that folder first on the session's `PATH`, and sends
   `git@github.com:` remotes over https so a push goes through the helper too. Each call
   runs `shipmill app-token`, which mints an installation token limited to this one repo
   and caches it in `shipmill/app-token.json` (mode `0600`) next to them while it has at
   least 10 minutes left. Any failure exits 2 and starts no session; it never falls back
   to the user's login. The gate's own reads keep the host's `gh` login. A session that
   works on other repos (fleet mode) fails there, since the token is limited to this one.
   A gate without `app_id` (one set up before D-19) still runs: its sessions launch as
   before, as the host's `gh` login, and the two reports above flag it until it is set

   The App's identity covers the sessions a person starts too, not only the gate's (spec
   012). `$CR gh <gh's arguments>` runs `gh` as the App when the checkout's config sets
   `app_id`: it mints or reuses the same token, limited to the `-R` repo or else `origin`'s,
   and exits with `gh`'s code; any failure to get the token exits 2 naming the fix and never
   runs `gh`. With no `app_id` it runs a read as the host's login and refuses a write with
   exit 2 (spec 037). `$CR app-token` works with
   no checkout too, caching under `$XDG_CACHE_HOME/shipmill/<owner>/<repo>/app-token.json`
   (`~/.cache` when `XDG_CACHE_HOME` is unset), mode `0600`. **Write as the App when the
   repo has one:** with `[agents] app_id` set, every `gh` call that writes (an issue, a
   comment, a label, a pull request, a review, a merge, a release) runs as `shipmill gh
   <the same arguments>` (`$CR gh`) from the repo's checkout, in every session, gated or
   started by hand, this skill's own included once `app_id` merges. Reads may keep plain
   `gh`. A `shipmill gh` that exits 2 is a stop: report its message and never retry the
   write with plain `gh`. Without `app_id`, `shipmill gh` refuses a write with exit 2
   unless the config sets `[agents] identity = "host"` (spec 037): that exit 2 is a stop
   too, never retried with plain `gh`, and a session passes `--as-host` only for a write a
   person approved in the chat, never on its own judgment or in a headless session, and
   says so in its report. Without the App, shipmill drafts and the person posts (spec 033,
   D-54): with `app_id` set, the skill runs `shipmill app-token --check` before its first
   write to GitHub, a push included, from the repo's checkout and through the same pinned
   `uvx` as `shipmill gh`; reading, and local work in the checkout (the config, the
   workflow, a branch, a commit), come before it as they are. Exit 0: go on. On its exit
   2, or a `shipmill gh` exit 2 naming the missing key, it stops there: its report's first
   line says the App isn't available here, quoting the check's reason, and that shipmill
   wrote nothing to GitHub, and it hands over the text of each write it would have made,
   in order, each with its target and the exact text (the repo; each label's name, color,
   and description; a pull request's base, the local branch holding the commits, its title
   and body), final and ready to paste or to post with the person's own `gh`, a command it
   may print and never runs. It never writes with plain `gh`, `GH_TOKEN`, or a push as the
   person, and never asks for or fetches the key. `shipmill status` and `doctor` flag agent text a person's login
   posted in the last 7 days as `AGENT_AS_PERSON`
4. **Interactive or headless (asked every time, D-20).** On a machine nobody watches, a
   session that asks a question holds the repo until someone attaches. Ask whether anyone
   watches this one, with step 3's App question, and write the answer in `[agents]`:
   - **`mode = "interactive"`:** someone attaches to a session (`claude attach <id>`) and
     answers its questions on this machine. Each question goes to GitHub first anyway, as
     the needs-decision protocol below, and then to the session (D-21): the prompt ends with
     the gate's `Gate session:` paragraph, naming the host's `gh` login. An answer in the
     session is posted on the item, the label comes off, and the session goes on; with no
     answer the item waits on GitHub, out of the gate's work, and `max_wait_minutes` stops
     the session
   - **`mode = "headless"`** (spec 005, D-17): questions go to GitHub only

   The config's default is interactive, so a gate set up before D-20 keeps working, but
   never rely on it: with no `mode` key `setup_state.py` reads `AGENTS_NO_MODE`, an
   action (exit 1) that `--fix` leaves to the user. In headless mode each launch runs
   `claude -p` with no prompts, AskUserQuestion removed, and an allowlist of tools; it
   can't wait on anyone, so it ends, and a decision for the user
   becomes the needs-decision protocol
   ([needs-decision.md](../github-issue-triage/references/needs-decision.md)): a comment
   whose first line is `<!-- shipmill:needs-decision -->`, mentioning the host's `gh`
   login, and the `needs-decision` label. The item waits on GitHub, out of the gate's work,
   until an OWNER, MEMBER, or COLLABORATOR replies; the rest of the repo keeps moving. Tell
   the user:
   - **The allowlist** is `HEADLESS_TOOLS` in `src/shipmill/gate.py`: `Read Edit Write
     Glob Grep Skill Agent SendMessage ListAgents TodoWrite Bash(gh *) Bash(git *) Bash(uv
     *) Bash(uvx *)`. A call outside it is denied, and the session posts a needs-decision
     comment naming the tool. To widen it, pass `--claude-arg=--allowedTools --claude-arg
     "Bash(npm *)"` (the `=` matters: `--claude-arg --allowedTools` is an argument error)
     to `gate`, and to `launchd` again so the job gets it. It is not a sandbox: `git`, `gh`,
     and `uv run` run code. Headless refuses a `--claude-arg` of `--permission-mode`,
     `--permission-prompts`, `--dangerously-skip-permissions`,
     `--allow-dangerously-skip-permissions`, `--bg`, `--background`, or `--session-id`
     with exit 2
   - **The trust filter** (D-16): headless works only on issues opened by an OWNER,
     MEMBER, or COLLABORATOR or by the App's bot, on the release workflow's config upgrade
     issues (`github-actions[bot]` with the `shipmill-upgrade` label and its first-line
     marker, D-30), and on pull requests whose branch is in the repo. The rest read
     UNTRUSTED (`watch_state.py --trusted-only`), start no session, and wait for an
     interactive one; github-ship-watch reports them
   - **The label:** `setup_state.py --fix` creates `needs-decision` whenever the config
     has an `[agents]` section, interactive or headless (D-21), and with it
     `role:maintainer` and `role:<name>` for each role `[agents.roles]` defines (a role's
     item, spec 036), `human` (the older label for a person's item, spec 017), `upstream` (a report for another repo, spec 038), and
     `decided` (a notify decision, spec 030); it
     reads `LABELS_MISSING` until then. Without `[agents]` none is wanted
   - **Notifications:** with `app_id`, the question is `<slug>[bot]`'s, so its mention
     notifies the user on GitHub and the gate sends no desktop notification. Without it,
     the comment is the user's own and GitHub doesn't notify anyone of their own mention:
     `setup_state.py` reads `AGENTS_NO_APP` (an action, D-19), a launch prints `no app_id:
     needs-decision comments post as <login>, so GitHub won't notify you`, and with
     `notify = true` the gate sends a desktop notification, `#<n> waits on your decision:
     <url>`, at once and every `remind_hours` while the item waits. Either way it records
     waiting items in `shipmill/needs-decision.json`, and `gate --json` reports `mode` (null
     on a HELD, WAITING, or RUNNING tick, which reads no config) and `decisions`
5. **A dedicated checkout.** The session branches and commits where it starts, so never
   use the user's working copy: `git worktree add --detach tmp/shipmill-gate
   origin/<default>` inside the trusted checkout (a worktree outside it would need its
   own trust prompt). If `git check-ignore tmp` prints nothing, add `tmp/` to
   `.git/info/exclude`, which stays local. The gate moves the checkout to the default
   branch's head before each launch
6. **Try it once.** `$CR --repo tmp/shipmill-gate gate <owner/repo> --dry-run` prints the
   decision and changes nothing. With `app_id` set, a tick that would launch also checks
   the key, the installation, and the permissions, writes no helpers and no token cache,
   and prints `would launch as <slug>[bot]`: that line proves the App's setup. A tick
   that would launch nothing checks no App; then `$CR app-install <owner/repo>` printing
   `already installed on <owner/repo>` confirms at least the installation. Don't go on to
   step 7 until `app_id` is set and one of the two has passed. For the prune it follows
   the tick's schedule: `prune due at <time>` when not due, else the `would prune` lines;
   `$CR worktrees --prune --dry-run` lists them anytime
7. **Schedule it.** `$CR --repo tmp/shipmill-gate launchd <owner/repo> --every 15` writes
   `~/Library/LaunchAgents/dev.shipmill.gate.<owner>.<repo>.plist`, loads it, and runs
   it once now. Its log is under `~/Library/Logs/shipmill/`. `--remove` unloads it; on
   Linux, run the same `gate` command from a systemd timer. With an App whose key isn't at
   the default path, add `--app-key <path>`: the job's gate gets it, made absolute, and
   install refuses it when `app_id` is unset or the key is missing or readable by others.
   Recommend the Claude token for every gate on launchd, in either mode (spec 035): the
   interactive login can expire overnight and leave every session dead. Tell the person to
   run `claude setup-token` themselves and save the token it prints to
   `~/.config/shipmill/claude-token` with mode `600` (`install -m 600 /dev/null <path>`,
   then paste it on one line). Never run `claude setup-token` yourself, never read the file,
   and never ask for the token in the chat. A file elsewhere goes to `--claude-token
   <path>` on `launchd`, which writes the path, never the token, into the job: the token
   never goes in the plist or the repo. Then `$CR doctor`'s `claude auth` line should read
   `token file`
8. **Hand over.** Tell the user how to see a session (`claude agents`, `claude attach
   <id>`), that a session waiting on a question holds the repo until they answer, that
   such a session sends a desktop notification at once and every `remind_hours` while it
   waits (`osascript` on macOS, `notify-send` elsewhere), that `max_wait_minutes` (15 by
   default; 0 never stops) stops it with `claude stop` so the repo moves again (`claude attach <id>` still
   shows its question), that with an App a session's work is `<slug>[bot]`'s, which they
   can approve and github-ship-watch's metrics count as a bot, that an open `shipmill-hold` issue stops every launch as well as
   every release but not that stop (D-15), and how to remove the job (`launchd
   <owner/repo> --remove`). In headless mode, tell them instead that a session never
   waits: `tail -f` its log under `shipmill/sessions/`, `claude --resume <uuid>` reopens
   it, and they answer a `needs-decision` item by replying on GitHub

## Migrating from hand-made or scripted releases

- Releases made by commits on main (`Release X` commits tagged on main) keep working as
  history: the bot reads their tags. Delete the old scripts and workflows in the same pull
  request
- A package from the retired oss-package-engineer skill (its `publish.yml` runs on
  `push: tags: v*`, installs Python 3.11, and has "Smoke test (wheel)" and "Smoke test
  (source distribution)" steps): keep its smoke-test steps and `tests/smoke_test.py`, give
  it the `workflow_dispatch` `tag` input, and drop the tag trigger. Its `chore: release vX`
  commits are history like any other; their CHANGELOG sections stay as written
- Under the bot, rc releases do not write CHANGELOG sections; their entries stay under
  Unreleased until the stable release. Existing rc sections stay until the stable release
  of their version, which folds their entries into its own section and removes them (D-25);
  the prose before an rc section's first `### ` heading is dropped, and any other text
  outside an entry fails the fold (D-26)
- A repo already on shipmill moves onto changelog fragments by setting `fragments =
  "changelog.d"` in `[changelog]` and adding the folder with a `README.md`, nothing else:
  `$CR upgrade --apply changelog-fragments` does both. Entries already under Unreleased stay
  there and release alongside the fragments, and a tag or an rc cut before the folder
  existed reads as having no fragments (D-27)
- A project in an rc series (`1.0.0rc9`) continues it: the next rc is `1.0.0rc10`, and the
  stable lane promotes to `1.0.0`. If the user wants 1.0.0 to be a deliberate step, leave
  stable without triggers so it only runs by hand

## Improve the skill

When a setup goes wrong (a prerequisite missed, a lane the user didn't choose, a gate that
never started), add the lesson to the matching step, or a check to `setup_state.py` with a
test in shipmill's `tests/test_setup_state.py`. When a lesson goes into the skill, add a
case under `evals/` that fails without it, in the same pull request.
