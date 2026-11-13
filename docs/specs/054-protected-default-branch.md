# S-054: Land as the App on a protected default branch

status: approved
serves: G-1, G-2

## Problem

A repository that releases with shipmill can't protect its default branch when it lives in a
GitHub organization (shipmill/shipmill#1038).

`land` (`src/shipmill/land.py`) pushes the release commit `Release X.Y.Z` straight to the
default branch, a hotfix to `release/X.Y`, and a stable release made off the default branch
back into it as a `Sync X.Y.Z into <branch>` commit, all with the workflow token, as
`github-actions[bot]`. The setup docs say to let `github-actions[bot]` bypass the branch
rules (`docs/install.md`, `docs/release-lanes.md` Limits, `skills/shipmill-setup/SKILL.md`).
On an organization repository that can't be done, as the issue records:

- A ruleset refuses the GitHub Actions integration (id 15368) as a bypass actor with 422
  "must be part of the ruleset source or owner organization"
- Classic branch protection accepts `bypass_pull_request_allowances.apps: ["github-actions"]`
  and stores an empty list
- A required status check refuses the push too: the release commit's CI runs through
  `workflow_call` from the Release workflow, so its check is named `ci / checks`, not the
  `checks` a pull request reports

So the maintainer of an organization repository chooses between an unprotected default
branch, where any collaborator can push unreviewed code to what ships next, and releases a
person lands by hand, which breaks G-1. A rule on the default branch is also what lets the
maintainer trust agent work without reading every diff (G-2): an agent's change reaches the
default branch only through a reviewed, green pull request.

## Behaviour

### The design: land pushes protected branches as the App

A repository that sets `[agents] app_id` and gives the Release workflow the App's private key
lands its branch pushes as the App. An App installed on the organization is accepted as a
ruleset bypass actor (the issue's finding), so the rule becomes "pull request and `checks`
required; bypass: the App", and the App is the one identity that can write the default
branch without a pull request. A repository that gives no key lands exactly as today.

What the App pushes, and what stays with the workflow token:

| Push | Today | With the key |
|---|---|---|
| The release commit to the default branch (stable on an unmoved branch) | workflow token | the App |
| The hotfix release commit to `release/X.Y` | workflow token | the App |
| The `Sync X.Y.Z into <branch>` commit (`_sync_main`) | workflow token | the App |
| The release tag `vX.Y.Z` | workflow token | workflow token |
| The work branch `shipmill/<tag>`: prepare's push, cleanup's delete | workflow token | workflow token |
| The GitHub release, the dispatch of the lane's workflows | workflow token | workflow token |

The tag stays with the workflow token on purpose: a branch ruleset doesn't cover tags, and a
tag pushed with an App token would start every `on: push: tags` workflow, which could
publish a second time beside the lane's `dispatch` (D-50 orders the publish and the moves of
references; a tag-triggered workflow would sit outside that order).

### The key

The App's private key reaches the land job as the secret `SHIPMILL_LAND_KEY` of a GitHub
environment, `shipmill-land` by default, whose deployment branches are limited to the
default branch. Only a job that runs from the default branch and names that environment can
read it, so a collaborator who pushes a workflow to another branch can't read the key and
push the default branch as the App, which a repository secret would allow.

- `.github/workflows/land.yml` gains an input `land-environment` (string, default `""`). With
  it set, the `land` job runs in that environment, writes `SHIPMILL_LAND_KEY` to a file under
  `$RUNNER_TEMP` with mode `0600` (as `.github/workflows/downstream.yml` writes its key), and
  runs `shipmill land ... --app-key <file>`. With it empty, the job names no environment and
  runs `shipmill land` as today
- The caller's `.github/workflows/release.yml` opts in with one line on its `land` job:
  `land-environment: shipmill-land`. `shipmill init` writes it only with `--land-as-app`, and
  then only when the config sets `[agents] app_id` (else exit 2 naming the key)
- The key is never printed: the step masks it, and the token minted from it, with
  `::add-mask::`

### `shipmill land --app-key <path>`

- Reads the App id from `[agents] app_id`; `--app-key` while it is unset exits 2 naming the
  key, as `shipmill gate --app-key` does (S-004-2)
- Before its first push it mints one installation token (`src/shipmill/app.py`, `mint`)
  limited to the repository, asking for `contents: write` and `workflows: write` only (a
  hotfix's cherry-picked merges may touch `.github/workflows/`). A missing or unreadable key,
  an App not installed on the repository, or an installation without those permissions exits
  2 naming the problem and its fix, having pushed nothing: no fallback to the workflow token
  (the reasoning of D-14 applied to landing)
- Pushes the three branch refs of the table with that token, through `GIT_CONFIG_*`
  variables that clear the checkout's persisted `http.https://github.com/.extraheader` and
  send the App's credential, so the token appears in no process argument and no output
- An empty `SHIPMILL_LAND_KEY` in a job that named the environment fails the step before
  `shipmill land` runs, naming the secret and the environment, so a half-done opt-in never
  lands as the workflow token by surprise

### What changes for a repository that opts in

A push made with an App token starts workflows; one made with the workflow token starts none
(`docs/release-lanes.md`, Limits). After an opt-in:

- The release commit and the sync commit start the repository's `on: push` workflows on the
  default branch: CI runs on them, so the default branch's head carries its `checks`, and the
  sync commit, which today runs no CI, now does
- The caller's Release workflow starts on that push too, and plans no release when nothing
  was merged since: the release commit leaves no pending changelog entry
- Other `on: push` workflows on the default branch (a docs deploy, say) run on the release
  commit; the docs say so

### The report: `shipmill doctor`, row `landing`

`src/shipmill/doctor.py` gains one row named `landing`, when `.github/workflows/release.yml`
exists and the policy releases. It reads, with the person's `gh` login:

- `GET repos/<repo>/rules/branches/<branch>`: the rules every active ruleset, the
  organization's included, applies to the default branch; and the same for
  `release/<series>` of the newest stable tag when the policy has a hotfix lane
- `GET repos/<repo>/rulesets/<id>` for each ruleset those rules come from: its bypass actors
- `GET repos/<repo>/branches/<branch>/protection`: classic protection, with its push
  restrictions and pull request bypass allowances

A rule refuses land's push when it is a ruleset's `pull_request`, `required_status_checks`,
`required_signatures`, `required_deployments`, `update`, or (for a new `release/X.Y`)
`creation` rule, or classic protection's required reviews, required status checks, required
signatures, or push restrictions. Landing passes a refusing rule when its ruleset lists the
landing identity as a bypass actor with `bypass_mode` `always`: the App (`Integration` with
the App's id) under the opt-in, the GitHub Actions integration (15368) without it; or, for
classic protection, when its bypass allowances and push restrictions name that identity.

| State | Level | Detail |
|---|---|---|
| No rule refuses land's push | PASS | `<branch> has no rule that refuses landing's push` |
| Every refusing rule is bypassed by the landing identity | PASS | names the identity and the rulesets |
| A refusing rule doesn't list the landing identity | FAIL | names the ruleset or the classic protection, the rule types, the identity, and the fix |
| The rules or a bypass list can't be read (no `gh`, a 403 or 404 for a login without admin) | WARN | what couldn't be read, and that landing may be refused |
| The release workflow opts in, but `[agents] app_id` is unset | FAIL | names the key |

The FAIL's fix, without the opt-in: install an App, set `[agents] app_id`, create the
environment with its secret, add `land-environment` to the release workflow, and add the App
to the bypass list, with `shipmill ruleset` printing the ruleset. With the opt-in: add the App
to the named ruleset's bypass list.

A tag ruleset whose `include` patterns match the next release tag's ref, and whose bypass
list doesn't name the GitHub Actions integration, is a WARN on the same row: landing pushes
the tag as `github-actions[bot]`.

### `shipmill ruleset`

A new command in `src/shipmill/cli.py` that prints, on stdout, the JSON body of a branch
ruleset for `gh api -X POST repos/<repo>/rulesets --input -`; it writes nothing and calls no
API:

- `target: branch`, `enforcement: active`, `conditions.ref_name.include`: `~DEFAULT_BRANCH`,
  plus `refs/heads/release/*` when the policy has a hotfix lane
- Rules: `deletion`, `non_fast_forward`, `pull_request` (0 required approvals; the
  maintainer raises it), and `required_status_checks` with one context per job of the CI
  workflow the release workflow calls, by the name a pull request reports
- `bypass_actors`: one `Integration` actor, `[agents] app_id`, `bypass_mode: always`

Without `[agents] app_id` it exits 2: a protected branch on an organization repository lands
unattended only through an App.

### When a push is refused anyway

When the push of the release commit, a hotfix, or the sync commit is refused and git's error
carries GitHub's rule refusal (`GH013`, or `protected branch`), land's error adds the fix:
`<branch>'s rules refuse <identity>: run shipmill doctor, and see Protected default branch in
docs/release-lanes.md`. The release commit's work branch is cleaned up as today, so the next
run plans the release again.

### Facts relied on

From GitHub's documentation, unless marked:

- An org-installed App is accepted as a ruleset bypass actor where the GitHub Actions
  integration is refused with 422 (observed in the issue)
- A push with an installation token whose App is a bypass actor with `bypass_mode` `always`
  passes the ruleset's rules, required status checks included (documented; the build proves
  it on a real organization repository, S-054-20)
- A push or a pull request made with the workflow token starts no workflow, save
  `workflow_dispatch` and `repository_dispatch`; one made with an App's token does
- A branch ruleset doesn't apply to tags; a tag ruleset does
- An environment secret reaches only a job that names the environment, and a deployment
  branch policy refuses a job from another branch. In a reusable workflow the job names the
  caller repository's environment and reads its secret by name; the caller can't pass an
  environment secret through `secrets:`
- Unverified: that `environment:` given an expression that is empty runs the job with no
  environment. If GitHub refuses it, `land.yml` splits the `land` job into two, one per case,
  chosen by `if:` on `land-environment`
- Unverified: that a job naming an environment records a GitHub deployment for it, which
  `shipmill operate` and `shipmill status` ignore since they read only the environments the
  config lists; the build checks they do
- Unverified: which logins can read a ruleset's `bypass_actors` and a branch's classic
  protection (admin is assumed); a read that answers 403 or 404 is the WARN above
- Unverified: whether a ruleset on a repository a person owns accepts the GitHub Actions
  integration as a bypass actor; doctor reports what the bypass list holds either way

### Docs

- `docs/release-lanes.md`: a "Protected default branch" section (the opt-in, the
  environment and its secret, the ruleset, what an App push starts), and its Limits line
  rewritten: the workflow token can't pass branch rules; on an organization repository land
  as the App
- `docs/install.md`: the prerequisites row "`github-actions[bot]` can push main, `release/*`,
  and `v*` tags" names the App opt-in for a protected default branch
- `skills/shipmill-setup/SKILL.md`: the Branch protection inspection row reads the doctor
  `landing` row, and setup offers the opt-in when the default branch has rules or the
  maintainer wants them
- `.github/workflows/land.yml`: its header comment says which pushes go as the App

## Acceptance criteria

- S-054-1: With `land-environment` empty, `.github/workflows/land.yml`'s `land` job names no environment, reads no secret, and runs `shipmill land` with the arguments it has today; actionlint accepts the file
- S-054-2: `shipmill land` without `--app-key` makes the same pushes, with the same refspecs and the same credential, as before this spec, for a stable lane on an unmoved branch, a stable lane off a moved branch (tag and sync), a hotfix, and a pre-release
- S-054-3: With `land-environment` set, the `land` job runs in that environment, writes `SHIPMILL_LAND_KEY` to a mode `0600` file under `$RUNNER_TEMP`, masks it, and passes `--app-key <file>`; an empty secret fails the step before `shipmill land` runs, naming `SHIPMILL_LAND_KEY` and the environment
- S-054-4: `shipmill land --app-key <path>` with `[agents] app_id` unset exits 2 naming the key and pushes nothing
- S-054-5: `shipmill land --app-key <path>` mints one token limited to the repository with `contents: write` and `workflows: write` only, before its first push; a missing key, an App not installed on the repository, or a missing permission exits 2 naming the problem and its fix, with no push made
- S-054-6: With `--app-key`, the push of the release commit to the default branch, of a hotfix to `release/X.Y`, and of the sync commit carry the App's token, and the tag and the work branch's push and delete carry the workflow token
- S-054-7: No process argument and no line of land's output holds the App's token or key
- S-054-8: A Release run started by the push of a release commit or a sync commit, with nothing merged since, plans no release
- S-054-9: A refused push to the default branch or `release/X.Y` whose git error carries `GH013` or `protected branch` fails land with the fix naming `shipmill doctor` and the docs section; any other refusal keeps today's message
- S-054-10: `shipmill doctor` prints a PASS `landing` row when the default branch has no rule that refuses land's push
- S-054-11: `shipmill doctor` prints a FAIL `landing` row naming the ruleset, its rule types, `github-actions[bot]`, and the App opt-in as the fix, for a ruleset with `pull_request` and `required_status_checks` that doesn't bypass the GitHub Actions integration, on a repository without the opt-in
- S-054-12: With the opt-in, `shipmill doctor` prints PASS when every refusing ruleset lists `[agents] app_id` as an `Integration` bypass actor with `bypass_mode` `always`, and FAIL naming each ruleset that doesn't, `bypass_mode` `pull_request` included
- S-054-13: `shipmill doctor` reads the rules of `release/<series>` too when the policy has a hotfix lane, and reports classic protection's required reviews, status checks, signatures, and push restrictions as refusing rules
- S-054-14: `shipmill doctor` prints a WARN `landing` row naming what it couldn't read when `gh` is missing, or a rules or bypass list read answers 403 or 404, and still prints every other row
- S-054-15: `shipmill doctor` prints a FAIL `landing` row naming `[agents] app_id` when the release workflow sets `land-environment` and the config sets no `app_id`
- S-054-16: `shipmill doctor` prints a WARN on the `landing` row for an active tag ruleset whose `include` matches the next release tag's ref and doesn't bypass the GitHub Actions integration
- S-054-17: `shipmill ruleset` prints a JSON body GitHub's create-ruleset API accepts, with the default branch (and `refs/heads/release/*` with a hotfix lane), the `pull_request` and `required_status_checks` rules, one context per job of the called CI workflow, and the App as an `Integration` bypass actor with `bypass_mode` `always`; it exits 2 naming `[agents] app_id` when the config sets none
- S-054-18: `shipmill init --land-as-app` writes `land-environment: shipmill-land` on the release workflow's `land` job and exits 2 naming `[agents] app_id` when the config sets none; `shipmill init` without it writes the release workflow it writes today
- S-054-19: `docs/release-lanes.md` has a Protected default branch section covering the opt-in, the environment limited to the default branch with its `SHIPMILL_LAND_KEY` secret, `shipmill ruleset`, and the workflows an App push starts, and its Limits, `docs/install.md`'s prerequisites row, and `skills/shipmill-setup/SKILL.md`'s Branch protection row name the opt-in
- S-054-20: On an organization repository whose default branch has an active ruleset requiring a pull request and the `checks` status, with the App as its only bypass actor, a stable lane lands, tags, and publishes with no person, and a collaborator's direct push to the default branch is refused

## Out of scope

- Landing through a pull request (the issue's option B). It works without an App, but only
  for a narrow shape of rule, and it changes what ships:
  - The workflow token opens a pull request only where the repository's and the
    organization's "Allow GitHub Actions to create and approve pull requests" setting is on,
    which organizations often turn off
  - A pull request the workflow token opens starts no workflow, so the required `checks`
    never reports on it; land would have to start CI again by `workflow_dispatch`, a new
    trigger every repository's CI would need, running CI twice per release
  - GitHub merges a pull request by a merge commit, a squash, or a rebase, never a fast
    forward: a squash or a rebase puts a commit CI never ran on the default branch, against
    Q-3, and leaves the tag off it; a merge commit is refused under "require linear history"
  - A rule requiring an approval can't be met by the workflow token, which can't approve the
    pull request it opened, so the release waits on a person
  - A stable release made off a moved branch needs a second pull request for its sync
    commit, and `release/X.Y` a third
- Landing as the App on a repository without `[agents]`. Q-6 holds as before: the release
  side works without the agents, and an unprotected default branch lands as today; a
  protected one on an organization repository needs an App, which shipmill knows as
  `[agents] app_id`. A release-only key for the App can come later, through its own issue
- The App key as a repository secret passed through `secrets:`, as
  `.github/workflows/downstream.yml` takes its own: simpler, but any collaborator with write
  access could read it from a workflow on another branch and push the default branch as the
  App, which the protection exists to stop
- Pushing the tag as the App, and tag rulesets: doctor warns about a tag ruleset that would
  refuse the workflow token; shipmill doesn't create or bypass one
- Applying the ruleset: `shipmill ruleset` prints it, and creating it stays the maintainer's,
  with admin rights shipmill's token doesn't have
- `shipmill sync`, the recovery of a failed sync run by a person: on a protected branch that
  person opens a pull request with its commit, as for any other change
- shipmill's own `move-major-tag.yml`, which pushes the marketplace ref to this repository's
  default branch: it is this repository's workflow, not a reusable one, and this repository's
  own protection is a separate change
- Signed release commits: the App's bypass covers `required_signatures`; signing is a later
  spec (spec 004 leaves it out too)

## Decisions relied on

- D-3: the prose calls the automation shipmill
- D-4: the opt-in reads `[agents] app_id` from `.github/shipmill.toml`
- D-9: the `landing` row reports a rule only where the repository has one
- D-14: no fallback to another identity when the App's can't be set up
- D-50: the tag and the lane's dispatches keep their order; no tag push starts a workflow
- D-54: shipmill writes to GitHub as the App, a separate identity
- D-63: a repository that doesn't opt in lands exactly as today
- D-80: the land job keeps its pinned uv

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-054-1, S-054-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

- shipmill/shipmill#1075: S-054-2, S-054-4, S-054-5, S-054-6, S-054-7, S-054-9
- shipmill/shipmill#1079: S-054-1, S-054-3, S-054-8, S-054-18
- shipmill/shipmill#1080: S-054-10, S-054-11, S-054-12, S-054-13, S-054-14, S-054-15, S-054-16
- shipmill/shipmill#1081: S-054-17
- shipmill/shipmill#1082: S-054-19, S-054-20

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
