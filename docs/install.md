# Install shipmill

shipmill has three parts. Each one works without the next, so stop after the part you
need:

| Part | Runs | You get |
|---|---|---|
| 1. The skills | in Claude Code, when you ask | triage, fixes, PR landing, and watch, on demand |
| 2. Release lanes | in the repo's own GitHub Actions | releases cut by policy from the CHANGELOG, no agent needed |
| 3. The agents' schedule | on your machine or in the cloud | triage and landing without you starting them |

The fast path, from the root of your repo:

```bash
claude plugin marketplace add shipmill/shipmill && claude plugin install shipmill@shipmill --scope user && claude "/shipmill:shipmill-setup"
```

It adds the marketplace, installs the plugin (both are safe to rerun), and starts Claude
Code with the `shipmill-setup` skill, which inspects the repo, asks you to choose the
lanes, and does parts 2 and 3 on a branch, ending with a pull request. The rest of this
page is what it does, for doing it by hand or checking its work.

## Before you start

- A GitHub repository with a hand-written `CHANGELOG.md`, or one you're willing to start
- [`gh`](https://cli.github.com/) signed in (`gh auth status`) as someone who can push,
  run workflows, and change the repo's settings
- [`uv`](https://docs.astral.sh/uv/), to install the CLI. Python 3.10 or newer for the
  skills' scripts
- [Claude Code](https://code.claude.com/) for parts 1 and 3

Install the CLI from PyPI once, the one way to get it on your `PATH`, and upgrade it after
each plugin update:

```bash
uv tool install shipmill
uv tool upgrade shipmill
```

That puts `shipmill` on your `PATH` (`uv tool update-shell` adds uv's tool folder if it
isn't there yet). The plugin runs its own pinned release (below), so a `shipmill` on your
`PATH` drifts from it until you upgrade: `doctor` and `status` report a `shipmill` on
`PATH` whose version differs from the plugin's, `doctor` as a WARN, with the fix
(`uv tool upgrade shipmill`, or the plugin's update when the CLI is the newer one).
`shipmill --version` prints the version it is. The commands below use:

```bash
CR=shipmill
```

Without the install, `uvx shipmill <command>` runs the latest release from PyPI, cached by
uv after the first call:

```bash
CR="uvx shipmill"
```

The plugin pins its CLI (spec 031): its skills, their scripts, and its hooks run `uvx
shipmill==<version>`, the version in the plugin's own `.claude-plugin/plugin.json`, in every
session, a headless gate's included (its allowlist has `Bash(uvx *)`). Whatever release of
the plugin a session loads, the CLI it runs is the same release, so an older install is an
older release that is consistent with itself.

The marketplace serves releases, not `main`: its entry names the latest release tag
(`"source": {"source": "github", "repo": "shipmill/shipmill", "ref": "vX.Y.Z"}`), which each
release's stamp moves with `plugin.json`. Installing or updating the plugin gets that
release; the commits merged since wait for the next one. `doctor`, `status`, and the gate
compare an install against that ref.

shipmill is published to PyPI on each stable and hotfix release, as `shipmill`, the same
releases `@v0` follows. It needs Python 3.14: `uv tool install` and `uvx` fetch that
interpreter when you don't have it, while `pip install shipmill` on an older Python fails
to find a version that fits.

## 1. Install the skills

In Claude Code, run these one at a time. The first adds the marketplace, the second
installs the plugin from it:

```
/plugin marketplace add shipmill/shipmill
```

```
/plugin install shipmill@shipmill
```

In the interactive `/plugin` menu, the marketplace source is only `shipmill/shipmill`.

Or from a shell, at user scope:

```bash
claude plugin marketplace add shipmill/shipmill && claude plugin install shipmill@shipmill --scope user
```

The skills are then `/shipmill:github-issue-triage`, `/shipmill:github-pr-triage`, and so
on; [flow.md](flow.md) shows what to say to each.

The plugin is installed per person by default (spec 033): each person who wants shipmill
installs it on their own host, and nothing in the repo turns it on. A gate session loads the
install that applies to its checkout (D-50), so the maintainer's own install is enough for
the gate. Keep this default for a repo that takes outside contributions: see
[Contributors](#contributors).

### One install, at user scope

Keep one install of `shipmill@shipmill` on a host, at user scope (spec 039). Every folder
loads it, gate checkouts included, and one command, run anywhere, updates it:

```bash
claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope user
```

A repo's `.claude/settings.json` may enable the plugin (`enabledPlugins`, below); that turns
it on for the repo, and the user install supplies it. An install at project or local scope
is keyed on one folder and wins over the user install there, so that folder keeps loading
its own release until someone updates it in that folder: with many of them, sessions run
stale skills. shipmill never creates one or prints a command that does. `doctor`, `status`,
the setup checklist, and the gate's tick report every project- and local-scope install on
the host as one row, `PLUGIN_SHADOWING`, with their count, versions, folders, and how many
of those are missing, and the fix:

```bash
shipmill plugin-clean          # a dry run: one line per install, deepest folder first
shipmill plugin-clean --apply  # remove them, from your terminal
```

The dry run changes nothing. `--apply` runs only with a terminal on standard input, so no
agent session runs it, and only when the host has a user-scope install (else it names
`claude plugin install shipmill@shipmill --scope user`). For each install it runs `claude
plugin uninstall shipmill@shipmill --scope <scope>` in its folder and writes the folder's
`.claude/settings.json` and `.claude/settings.local.json` back byte for byte, since the
uninstall also drops the plugin from `enabledPlugins`; it then checks `claude plugin list
--json` and stops, exit 2, on any change beyond that install. A folder that no longer
exists is created for the uninstall and removed again. An install keyed on a linked git
worktree is a `manual` line: no `claude plugin` command reaches it, so you delete its entry
in `~/.claude/plugins/installed_plugins.json` by hand, as the line says. The last line is the
user install's update when it lags. Exit 0 when no keyed install is left, 1 when some are.

To turn the plugin on for everyone who opens the repo instead, set `[agents] plugin = "repo"`
in `.github/shipmill.toml` and commit this to its `.claude/settings.json`. Then every
contributor's Claude Code is offered the plugin and its hooks when they open the repo:

```json
{
  "extraKnownMarketplaces": {
    "shipmill": { "source": { "source": "github", "repo": "shipmill/shipmill" }, "autoUpdate": true }
  },
  "enabledPlugins": { "shipmill@shipmill": true }
}
```

The delivery hooks come with the plugin (spec 026): in a repo whose `.github/shipmill.toml`
has an `[agents]` section, they refuse with exit 2 a `gh` write without `shipmill gh` while
`app_id` is set and the App is available to the session (its key at
`~/.config/shipmill/app-<app_id>.pem`, or `SHIPMILL_APP_KEY` set, as in every gate session;
spec 033), a push to the default branch, a rebase merge, a force push without a lease
pinned to a commit, and a copy of a `[hooks] private` path out of the repo, each with the
command to run instead. Everywhere else they allow every command. They need `uv` on your
`PATH`, which runs them on a Python 3.11 or newer it finds or installs. When a hook can't
start its script (no `uv`, no such Python to be had, offline or with `python-downloads =
"never"`, or the script missing), it prints `shipmill hook: can't start hooks/delivery.py
(<the reason>); this command runs unchecked, see shipmill doctor` and exits 1, so the
command runs unchecked rather than every command being blocked. `$CR doctor` tests them:
for a repo with `[agents]` it prints one line per rule, on or off, and runs a self-test
that FAILs naming the fix when the hook doesn't refuse, which keeps a headless gate from
starting a session. The switches are in [the policy](release-lanes.md#delivery-hooks).

For a checkout of shipmill you edit, or for Codex, link the skill folders instead:

```bash
for s in ~/src/shipmill/skills/*/; do ln -sfn "$s" ~/.agents/skills/; done
```

A linked skill answers its name without the plugin's prefix on this machine in place of
the plugin's, so a gate session whose prompt leaves the prefix out runs the checkout,
behind or on a feature branch. Prompts call the plugin's as `/shipmill:<skill>`, and `shipmill status`
and the setup checklist report each link or copy in `~/.claude/skills` or
`~/.agents/skills` as `SKILL_SHADOWED`, with its fix.

## 2. Set up release lanes

Work on a branch; everything below lands in one pull request.

### Prerequisites

| Needed | Fix |
|---|---|
| `CHANGELOG.md` with an Unreleased section, in keep-a-changelog (`## [Unreleased]`) or dash (`## Unreleased`) style | create it, or rewrite the entries `doctor` names |
| A stable `vX.Y.Z` tag to count from | tag the last release; shipmill never invents one |
| A CI workflow other workflows can call, on the commit they name | add the trigger below and pass `ref: ${{ inputs.ref }}` to `actions/checkout` |
| A publish workflow started by hand with a `tag` input, building that tag | add the input; drop any check that the tag is on main, since rc and stable tags are off it |
| `github-actions[bot]` can push main, `release/*`, and `v*` tags | let it bypass the branch rules, or landing fails |
| No other release automation | remove or disable it in the same pull request, so two tools never tag |

The CI trigger:

```yaml
on:
  workflow_call:
    inputs:
      ref:
        type: string
        required: true
```

Outside a call `inputs.ref` is empty, so pushes and pull requests keep checking out their
own commit.

### Write the files

```bash
$CR init --ci ci.yml
```

This writes `.github/shipmill.toml` in `mode = "dry-run"` and
`.github/workflows/release.yml`, which wires shipmill's reusable workflows to your CI, and
turns on changelog fragments: `fragments = "changelog.d"` in the policy and
`changelog.d/README.md`, so each pull request adds its entry as a file there instead of
editing `CHANGELOG.md` (spec 013). `$CR init --ci ci.yml --no-fragments` writes neither, and
each pull request edits Unreleased. `--runs-on <runner>` puts shipmill's release jobs on a
runner: a label, such as `self-hosted`, or a JSON list of labels. The policy's
`[autonomy]` is written out, with `release` at its default, `act` (spec 040). Then edit the policy: which lanes, when each releases, what each dispatches, and the
gates. The keys are in [The policy](release-lanes.md#the-policy). For a uv
project, add `after_stamp = ["uv lock --check"]`.

`release.yml`'s schedule follows the policy's triggers: an hourly tick when a lane sets
`milestone` or the stable lane promotes with `quiet_minutes`, one cron per window time when
the lanes only use `schedule`, and none when every run starts from a push or by hand. After
editing the policy, rewrite `release.yml` alone with
`$CR init --caller --force --ci ci.yml` (add the same `--runs-on`); `--caller` reads the
policy already there and can't be combined with `--operate` or `--no-fragments`.

### Check

```bash
$CR doctor
$CR plan --lane rc --dry-run
$CR plan --lane stable --dry-run
```

`doctor` must pass every line. It checks:

- A CHANGELOG with an Unreleased section, in keep-a-changelog or dash style
- A stable `vX.Y.Z` tag to count from
- A CI workflow that runs on `workflow_call` with a `ref` input and checks that ref out
- A `release.yml` schedule holding every cron the policy needs: a WARN names each missing
  line and `init --caller --force` as the fix; an hourly `M * * * *` cron covers every need,
  and extra crons are never warned about
- A workflow for each `dispatch` entry that runs on `workflow_dispatch` with a `tag` input
- For each environment, a workflow that runs on `workflow_dispatch` with `tag` and
  `environment` inputs, and a job that sets `environment:`
- When an environment uses `from` or `health`, `.github/workflows/operate.yml` (which
  `init --operate` writes) granting `deployments: write` and `actions: write`, and
  `issues: write` once an environment has `health` (for incidents) or a stage proposes
- An `[operate]` section with known keys only, `rollback_after` in 1..20 and a non-empty
  `incident_label`
- No `[tool.uv.sources]` entry taken from a local path, which CI and users don't have
- No branch named `shipmill` on origin, which would block the `shipmill/<tag>` work branches
- The `shipmill@shipmill` plugin installs on this host, as `status` reads them: a WARN with
  the update when the user install is behind the latest release (read with `gh`), and a
  `PLUGIN_SHADOWING` WARN naming `plugin-clean` for the project- and local-scope installs;
  without `claude` on PATH it says they weren't read

Each `plan` prints JSON; its `version` must be the next version you expect. If it isn't,
fix the bump lists or the tags, not the version.

### Go live

1. Open the pull request and merge it
2. Run the Release workflow by hand in dry-run, and read the release commit it would make
   in the run's summary:

   ```bash
   gh workflow run release.yml -f dry-run=true
   ```

3. Create the labels the skills and gates read (`postponed`, `blocked`, `shipmill-hold`,
   the blocker label, and with an `[agents]` section `needs-decision`, `role:maintainer`
   and a `role:<name>` label for each role `[agents.roles]` defines, a role's item, and
   `human`, the older label for one). The setup checklist reports what's missing, and `--fix` creates
   it:

   ```bash
   uv run --no-project python <skills>/shipmill-setup/scripts/setup_state.py <owner/repo> --fix
   ```

   `<skills>` is the plugin's `skills` folder, or a checkout's. `--fix` writes the plugin
   into `.claude/settings.json` only with `plugin = "repo"`; commit that in a follow-up pull
   request. With the default, `plugin = "host"`, it never touches that file: the checklist
   reads `PLUGIN_OK` when an install applies to the repo's folder, `PLUGIN_MISSING` with the
   install command when none does, `PLUGIN_COMMITTED` when the file still enables the
   plugin, so you keep it with `plugin = "repo"` or delete it, and `PLUGIN_SHADOWING` when
   the host has project- or local-scope installs, which `--fix` leaves. It turns
   on the repo setting that deletes a pull request's branch when it merges, too: stacked
   pull requests are retargeted only when the branch under them is deleted

4. Set `mode = "release"` in `.github/shipmill.toml` and merge it

From here, releases are cut by policy on each push to main, on the lanes' schedules, and
by hand from the Release workflow.

## 3. Choose where the agents run

Releasing needs no agent. Triage, landing, and the shipped notices do, and run wherever
you start them:

| Option | Runs | Stops when |
|---|---|---|
| On demand | in your session, when you invoke a skill | the task is done |
| `/loop 30m /shipmill:github-ship-watch <owner/repo> — watch and triage` | in an open session | the session closes |
| The gate | a new background session on your machine, only when the repo needs one | you remove the job |
| A `/schedule` routine | in the cloud, with your machine off | you delete it |

Start on demand. For anything that runs for days, prefer the gate: each launch is a fresh
session, and a quiet tick makes no model call. A cloud routine may not load the plugin,
so give it the prompt in [flow.md](flow.md#keeping-it-running), which clones shipmill.

### The gate

`shipmill gate` reads the repo's state and starts a Claude Code background session only
when something needs an agent, no session it started is still working or waiting on you,
and the findings changed since its last launch. Something needs an agent when
github-ship-watch's `watch_state.py` marks a row `agent: true`: a failed or stalled release
bot, a release missing from PyPI or not announced, issues triage owes, a failed operate
run, or an open incident; open PRs count too unless `[autonomy] land` is `observe`. A
promotion waiting on you or an unhealthy environment starts nothing. [Agent
modes](design/agent-modes.md) has the details.

1. **Say what a session may do**, in `.github/shipmill.toml`, merged before the job
   starts. Start without merges for the first week:

   ```toml
   [agents]
   prompt = "/shipmill:github-issue-triage {repo} triage the new issues; do not merge"
   retry_hours = 24   # unchanged findings start a new session after this
   notify = true      # a desktop notification when a session waits on you
   remind_hours = 4   # repeat it while the session still waits
   max_wait_minutes = 15 # stop a session that waited this long; 0: never
   # app_id = 123456  # sessions write as this GitHub App; unset: as your gh login
   # mode = "headless" # interactive (default): sessions ask you; headless: `claude -p`, they ask on GitHub
   # wip = 3          # at most 3 issues in progress at once (1..100); unset: no limit

   # [agents.roles]   # who receives a step an agent can't do (spec 036); optional
   # maintainer = ["octocat"]        # unset or []: your gh login
   # infra = ["octocat", "hubot"]    # GitHub logins, never an App's [bot]
   # legal = ["@example-org/legal"]  # a team, as @org/team: mentioned, not assigned
   # accounting = []                 # nobody yet: falls back to the maintainer
   ```

   `shipmill roles` prints each role resolved (`--json`, or `--flags` for triage_state.py's
   `--role` arguments); a malformed `[agents.roles]` exits 2 from every command that reads
   the config, `doctor` included.

   Gate sessions load the installed plugin (spec 031, D-44), as any session on the host
   does: the gate passes no `--plugin-dir` and never changes an install. A session loads the
   most specific scope the plugin is installed at for the checkout's project (local, then
   project, then user, then managed; a linked worktree's project is its main checkout, so an
   install keyed on the worktree itself is never loaded). Before it starts a session the
   gate reads that install and the latest release, and the tick prints one line, with its
   fix, for the user install when it lags, each project- or local-scope install that
   applies, at any version, with `plugin-clean` as its fix, an install keyed on the gate's
   linked worktree, the gate's own CLI when it lags, and a config whose `requires` the
   version sessions load doesn't meet; the session starts all the same. With `notify =
   true` the first gate on the host to find a lagging install sends one desktop
   notification per release. The one hold is PyPI: while it answers 404 for the version
   sessions load (the release tag moves a few minutes before the package is uploaded), the
   tick prints `plugin <version> waits for PyPI` and the next tick tries again. A failed
   read is printed and the session starts. `status`, `doctor`, and the setup checklist
   report the user install when it is behind and the keyed installs as one
   `PLUGIN_SHADOWING` row ([One install, at user scope](#one-install-at-user-scope)), and
   name the install a session loads.

   `[agents] plugin_update` was removed (spec 031): 0.60.0 ignored it, and since 0.61.0 a
   config with the key, whatever its value, exits 2 with `[agents] plugin_update was removed
   (spec 031); delete it`, and `doctor` fails the policy with that line. To bring
   the install up to date, run the fix `doctor` or `status` prints, `claude plugin
   marketplace update shipmill && claude plugin update shipmill@shipmill --scope user`

   A config may name the oldest shipmill it is written for with a top-level `requires =
   ">=X.Y"` ([the policy](release-lanes.md#the-policy)): an older CLI exits 2 naming the
   bound and the commands that update the plugin and the CLI, instead of failing on a key it
   doesn't know

   Without `app_id`, a session writes as your `gh` login, so its pull requests, merges,
   and commits read as yours. Set it before you schedule the gate, to have them made by a
   GitHub App's bot instead (see
   [Give the sessions their own identity](#give-the-sessions-their-own-identity)): until
   then the setup checklist reads `AGENTS_NO_APP` and github-ship-watch `GATE_NO_APP`,
   both an action for you (D-19)

2. **Give it its own checkout.** A session branches and commits where it starts, so never
   your working copy. Inside the repo's trusted checkout:

   ```bash
   git worktree add --detach tmp/shipmill-gate origin/main
   ```

   If `git check-ignore tmp` prints nothing, add `tmp/` to `.git/info/exclude`

3. **Try it once.** This prints the decision and changes nothing:

   ```bash
   $CR --repo tmp/shipmill-gate gate <owner/repo> --dry-run
   ```

4. **Schedule it.** On a Mac:

   ```bash
   $CR --repo tmp/shipmill-gate launchd <owner/repo> --every 15
   ```

   This writes `~/Library/LaunchAgents/dev.shipmill.gate.<owner>.<repo>.plist`, loads it,
   and runs it once now; the log is under `~/Library/Logs/shipmill/`. On Linux, run
   `$CR --repo tmp/shipmill-gate gate <owner/repo> --refresh` from a systemd timer

5. **Watch a session** with `claude agents` and `claude attach <id>`. A session waiting on
   your answer holds the repo until you give it; on a machine nobody watches,
   [run it headless](#run-it-headless)

### Give the sessions their own identity

Part of setting up the gate (D-19); the gate still runs without one. With a GitHub App, a
session's pull requests, comments, reviews, merges, and commits are made by the App's bot,
`<slug>[bot]`, not by you: you can approve its pull requests, and github-ship-watch's
metrics count its merges as a bot's. The token it uses reaches this one repo only, never
everything your login can.

The quick way is one command:

```bash
$CR app-create --dry-run   # print the plan; create nothing
$CR app-create             # create it: one click on GitHub, then pick the repos
```

It finds the accounts your `gh` login administers (it needs the `read:org` scope: `gh auth
refresh -s read:org`) and the repos in them holding `.github/shipmill.toml`, then plans:

| Your gated repos | The App |
|---|---|
| all in your personal account, or none yet | yours, private |
| any in an org | yours, public, so it installs on the org |

It asks who should own it, your personal account first as the default; pick an org you
administer to have the org own it, or pass `--owner`.

A private App can be installed only on the account that owns it; a public one on any
account, but only you hold its key, so nobody else can use it. The App is named
`shipmill-<owner>`, or `shipmill-<login>` when that is taken. `--owner`, `--public`,
`--private`, `--name`, and `--repos` change the plan. The command opens GitHub's create
page with the permissions below filled in and the webhook off; you click **Create GitHub
App**, then pick the repos on the install page it opens. It saves the key to
`~/.config/shipmill/app-<app_id>.pem` with mode `0600`, waits for the installations, and
prints the `app_id = <id>` line for step 4. Then go on at step 4.

For a repo connected later, or in another account:

```bash
$CR app-install                 # the checkout's repo, with [agents] app_id
$CR app-install acme/web beta/x # or name them
```

shipmill never installs the App or adds a repo for you, since which accounts and repos get it
is your choice. For each repo the App doesn't cover yet, it opens the App's **Install App**
page and says per account what to click there: **Install** (then Only select repositories
and the repos) for an account without the App, **Configure** (then add the repos under
Repository access) for one that has it. It then waits until each repo is covered, and exits 1
naming any still missing after 10 minutes.

By hand instead:

1. **Create the App** once, in GitHub's settings (Developer settings, GitHub Apps, New
   GitHub App). Clear Webhook's Active box: it needs no
   webhook. Give it these repository permissions and no others:

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

2. **Install it** only on the repos the gate works on ("Only select repositories")

3. **Save its private key** where the gate looks for it, readable by you alone. Generate
   one on the App's page, then:

   ```bash
   mkdir -p ~/.config/shipmill
   mv ~/Downloads/<app>.*.private-key.pem ~/.config/shipmill/app-<app_id>.pem
   chmod 600 ~/.config/shipmill/app-<app_id>.pem
   ```

   The gate refuses a key readable by group or others. The key never goes in the repo; a
   key elsewhere goes to `gate --app-key <path>`, and to `launchd --app-key <path>`, which
   puts it in the job's arguments

4. **Set `app_id`** in `[agents]` to the App ID on the App's settings page (not its client
   ID), and merge it

5. **Prove it** with the gate's dry run (step 3 above). When the tick would launch, it
   also checks the key, signs the App's JWT with `openssl`, checks the installation and
   every permission above, and prints `would launch as <slug>[bot]`; anything missing
   exits 2 naming it. It writes nothing. A tick that would launch nothing checks no App

Each launch then runs those checks again, writes a `gh` wrapper and
`git-credential-shipmill` (mode `0700`, holding no token) to
`$(git rev-parse --git-common-dir)/shipmill/bin/`, and starts the session with that folder
first on its `PATH` and `<slug>[bot]` as its git author. Each `gh` or `git push` call mints
or reuses a token through `shipmill app-token`, cached in `shipmill/app-token.json`
(mode `0600`) while it has at least 10 minutes left. A failed check starts no session and
never falls back to your login. The gate's own reads still use your `gh` login. Remove
`app_id` and sessions launch as before, as your `gh` login

### Give the sessions a Claude token

Recommended for every gate on launchd (spec 035). Without it, the gate's sessions lean on the
interactive Claude Code login you made by hand, which can expire overnight and leave every
session dead within a second. `claude setup-token` prints a long-lived token for your Claude
subscription instead; save it where the gate looks for it, readable by you alone:

```bash
claude setup-token                      # opens the browser; prints the token
mkdir -p ~/.config/shipmill
install -m 600 /dev/null ~/.config/shipmill/claude-token
$EDITOR ~/.config/shipmill/claude-token # paste the token on one line
```

The gate reads `~/.config/shipmill/claude-token` on each tick; a file elsewhere goes to
`gate --claude-token <path>`, and to `launchd --claude-token <path>`, which puts the path in
the job's arguments. The token never goes in the plist or the repo: only the path does. With
no file at the default path and no `--claude-token`, sessions use the login as before.

The gate refuses, with `CLAUDE_AUTH` and exit 2, starting no session and stopping none, a
file that isn't a regular file, isn't yours, has mode other than `600` or `400`, is empty,
or holds more than one line, whitespace inside the token, a non-ASCII byte, or anything not
starting with `sk-ant-oat` (an API key, `sk-ant-api...`, goes nowhere here); so does a
`--claude-token` path that doesn't exist. It never falls back to the login, and no message
shows the file's bytes.

The token goes only into the environment of the `claude -p` or `claude --bg` process that
starts a session, as `CLAUDE_CODE_OAUTH_TOKEN` with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, so
the session's tools don't see it, and without `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`,
which would outrank it. Before a launch, `claude auth status --json` runs with it and must
name the token. `shipmill status` prints a `claude auth` line, and `shipmill doctor` warns
when the gate leans on the login, and when the token file is older than 330 days: the token
lasts a year, so run `claude setup-token` again and save it over the old one

The App's identity covers the sessions you start yourself too, not only the gate's. The
shipmill skills run every `gh` call that writes (an issue, a comment, a label, a pull
request, a review, a merge, a release) as `shipmill gh` when `app_id` is set, in every
session, and stop rather than retry with plain `gh` when it fails. Before its first write a
skill runs `shipmill app-token --check`, which says whether the App is available here: its
key at `~/.config/shipmill/app-<app_id>.pem`, or `SHIPMILL_APP_KEY` set, as the gate sets it
on every session it starts (spec 033). Where it isn't, the skill writes nothing and hands you
the text instead ([Contributors](#contributors)). Keep the key at its default path, or set
`SHIPMILL_APP_KEY` to its path in your shell, so your own sessions write as the App too;
`doctor`'s `app-writes:` line says which case your host is in. You can use it by hand the
same way:

```bash
shipmill gh issue comment 250 --body-file tmp/comment.md
shipmill gh pr create -R owner/repo --title "..." --body-file tmp/pr.md
```

Everything after `gh` goes to `gh` unchanged. With `app_id` set in the checkout's
`.github/shipmill.toml`, it mints or reuses a token limited to the `-R` repo, else to
`origin`'s, runs `gh` with it, and exits with `gh`'s code. The key is a leading `--app-key`,
else `SHIPMILL_APP_KEY`, else the default path; a missing key (with a second line saying
the App isn't available here), a key others can read, an App not installed on the repo, or
a missing permission exits 2 naming the fix, and `gh` never runs. With no `app_id` it runs `gh` as your login. `shipmill app-token`
works outside a checkout too: there it caches the token in
`$XDG_CACHE_HOME/shipmill/<owner>/<repo>/app-token.json` (`~/.cache` when
`XDG_CACHE_HOME` is unset), mode `0600`. `shipmill status` and `doctor` warn
`AGENT_AS_PERSON` when agent text went out under a person's login in the last 7 days

### Run it headless

Optional, for a machine nobody watches. By default a session that asks you something
posts the question on GitHub as the protocol below, then waits for your answer in the
session (D-21); the gate starts nothing else for the repo until you answer or
`max_wait_minutes` stops it, and the item then waits on GitHub. With `mode = "headless"` in `[agents]`, merged like the rest
of the section, each launch runs `claude -p` instead: no permission prompts, no
AskUserQuestion, and a fixed list of tools. It can't wait on you, so it ends, and a
decision for you becomes a comment on the issue or pull request plus the `needs-decision`
label ([the protocol](../skills/github-issue-triage/references/needs-decision.md)). The
comment's first line is `<!-- shipmill:needs-decision -->`, it mentions your `gh` login,
and it gives the options with a recommendation. The item then waits on GitHub, out of the
gate's work, while the rest of the repo keeps moving. Reply on the item (as an owner,
member, or collaborator) and a later tick takes it up again; the session removes the label.
A headless session isn't listed in `claude agents`: follow it with `tail -f` on its log in
`$(git rev-parse --git-common-dir)/shipmill/sessions/`, and `claude --resume <uuid>`
reopens it after it ends. The gate starts it with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`
in its environment, so Claude Code waits for its background subagents however long they
run instead of stopping them 10 minutes after its last turn (#246); set the variable in
the gate's own environment to choose another ceiling.

1. **Create the label.** The setup checklist wants `needs-decision` whenever the config
   has an `[agents]` section, in either mode; `setup_state.py <owner/repo> --fix` creates it

2. **Know the allowlist.** A headless session may use `HEADLESS_TOOLS`, defined in
   `src/shipmill/gate.py`:

   ```
   Read Edit Write Glob Grep Skill Agent SendMessage ListAgents TodoWrite
   Bash(gh *) Bash(git *) Bash(uv *) Bash(uvx *)
   ```

   Any other call is denied without a prompt, and the session posts a `needs-decision`
   comment naming the tool and the command it tried. It is not a sandbox: `git`, `gh`, and
   `uv run` can run code. To widen it, say for a repo whose checks run `npm test`, pass the
   extra tools to the gate (the `=` matters; `--claude-arg --allowedTools` is an argument
   error), and install the job again so it gets them too:

   ```bash
   $CR --repo tmp/shipmill-gate gate <owner/repo> --dry-run --claude-arg=--allowedTools --claude-arg "Bash(npm *)"
   $CR --repo tmp/shipmill-gate launchd <owner/repo> --every 15 --claude-arg=--allowedTools --claude-arg "Bash(npm *)"
   ```

   A headless gate refuses a `--claude-arg` of `--permission-mode`, `--permission-prompts`,
   `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--bg`,
   `--background`, or `--session-id` with exit 2: each would bring the prompts back or
   break how the gate tracks the session

3. **Know what it skips.** Headless works only on trusted items (D-16): issues opened by
   an owner, member, or collaborator, or by the App's bot, the config upgrade issues the
   release workflow opens as `github-actions[bot]` (with the `shipmill-upgrade` label and
   its first-line marker, D-30), and pull requests whose branch is in the repo rather than
   a fork. Every other open item reads UNTRUSTED, starts no session, and waits for an
   interactive one; github-ship-watch lists them

4. **Choose how you hear about a question.**
   - **With `app_id`** (recommended): the comment comes from `<slug>[bot]`, so its mention
     notifies you on GitHub like any other. The gate sends no desktop notification
   - **Without it:** the comment is your own, and GitHub doesn't notify you of your own
     mention. The checklist reads `AGENTS_NO_APP` (an action, D-19), and each launch
     prints `no app_id: needs-decision comments post as <login>, so GitHub won't notify
     you`. With `notify = true` the gate sends a desktop notification instead, `#<n>
     waits on your decision: <url>`, at once and every `remind_hours` while the item
     waits, and prints `notified #<n> (waiting <N>h)`

   Either way a tick that reads the state records the waiting items in
   `shipmill/needs-decision.json`, and `gate --json` reports `mode` and a `decisions` list
   (`item`, `since`, `waited_hours`, `notified`, `error`). `mode` is null on a HELD,
   WAITING, or RUNNING tick, which reads no config. `loaded` is the install a launch's
   session would load (spec 031: `project`, `scope`, `folder`, `version`, `latest`, `lags`,
   `shadowing` (spec 039), `unloaded`, `cli`, `requires`, and `error`), and `pypi` PyPI's answer for its version
   (`version`, `status`, `error`), each null on a tick that reached no launch. Releases up
   to 0.59.1 also gave `plugin`, the daily update of `plugin_update = true`, which is gone

## Contributors

For you, the maintainer: what shipmill does when someone other than you works in a repo
connected to it (spec 033, D-54). Three kinds of contributor meet the repo:

1. **With Claude Code and the shipmill plugin**, installed on their own host, or offered by
   the repo's `.claude/settings.json` when you set `[agents] plugin = "repo"`
2. **By hand, without Claude.** shipmill changes nothing for them
3. **With Claude Code but without shipmill.** With the default, `plugin = "host"`, nothing
   in the repo offers them the plugin; with `"repo"`, accepting the offer makes them the
   first kind

shipmill writes to GitHub only as the App, a separate identity, never as the person at the
keyboard. The App's key is yours: where it isn't available, such as a contributor's host,
shipmill's skills stop before their first write to GitHub, say the App isn't available
here, and hand the person the text to post (each comment, label, and pull request's title
and body, with its target), and never fetch the key or write as them.

The delivery hooks' `app-writes` rule applies only where the App's key is, or in gate
sessions, which carry `SHIPMILL_APP_KEY`. So what a contributor posts themselves, by hand
or with their own Claude outside shipmill's skills, goes out as them, as it would without
the plugin; the other rules (default-branch push, rebase merge, force push, private paths)
hold for them as for you. Only your host decides: nothing a contributor's pull request adds
turns the rule off in your sessions.

A fork pull request, or an issue from someone outside the repo, waits for an interactive
session and is never landed automatically (D-16). Telling contributors so is your choice:
shipmill writes nothing to the repo's `CONTRIBUTING.md`, `README.md`, or other docs, and
prints no text for them.

Keep the App's key at `~/.config/shipmill/app-<app_id>.pem`, or set `SHIPMILL_APP_KEY` to its
path in your shell: a key elsewhere, without the variable, leaves your own sessions without
the App, so the skills draft there and a `gh` write you run yourself goes out as you.

## Pause or remove it

| To | Do |
|---|---|
| Pause releases and the gate | open an issue labelled `shipmill-hold`; a hotfix started by hand still runs (D-8, D-15) |
| Stop releases | set `mode = "off"` in `.github/shipmill.toml` |
| Stop the gate | `$CR --repo tmp/shipmill-gate launchd <owner/repo> --remove` |
| Remove the skills | `/plugin uninstall shipmill@shipmill` |
| Remove the CLI | `uv tool uninstall shipmill` |

Everything shipmill knows lives in the repo and on GitHub, so removing it leaves your
tags, releases, issues, and CHANGELOG as they are.

## Clean up old builds

Each uvx run can leave a build of shipmill in uv's cache, and each plugin update leaves the
previous version on disk:

- **uv's cache:** `uv cache prune` removes dangling entries and the environments uvx
  cached; `uv cache dir` says where the cache is. A `uv tool install` lives outside the
  cache, so pruning leaves the installed CLI alone
- **The plugin's old versions:** Claude Code keeps each version of the plugin in
  `~/.claude/plugins/cache/shipmill/shipmill/<version>/`. It has no command to prune them:
  when a plugin updates or is uninstalled, it marks the previous version with an
  `.orphaned_at` file and deletes it 14 days later. A version folder that holds
  `.orphaned_at` is safe to delete by hand once no running session started before the
  update; leave the version `~/.claude/plugins/installed_plugins.json` records
