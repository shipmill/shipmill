# Decisions

Rules the maintainers settled, numbered in order. Triage designs and code reviews check
every change against the entries whose "Applies to" it touches. Change a rule by adding an
entry that supersedes it, never by editing an old one.

## D-1: Only a push cancels the settle wait; lane=policy follows the policy

- Decided: 2026-10-04, in romamo/shipmill#6
- Rule: The settle job's cancelling concurrency group is shared by push runs only, and a hand-started lane=policy run evaluates triggers exactly as a scheduled run does (quiet is never due by hand)
- Why: A dispatch or cron run cancelled a push run's quiet wait and then skipped; making lane=policy count quiet as due would change its meaning and make local shipmill plan previews report quiet as due. Ending a batch by hand means starting the lane
- Applies to: .github/workflows/prepare.yml, src/shipmill/planner.py, workflow_dispatch lane input
- Enforced by: tests/test_workflows.py (with #14); review for the planner

## D-2: Work branches keep the shipmill/ prefix; collisions are detected

- Decided: 2026-10-04, in romamo/shipmill#7
- Rule: Release work branches stay under shipmill/ (WORK_PREFIX); a branch that blocks them is reported by prepare and doctor with a fix, never avoided by renaming the prefix
- Why: Branch protection rules or CI filters may match shipmill/, and a run straddling a tool upgrade could miss its work branch; a new prefix only makes a collision less likely
- Applies to: src/shipmill/land.py, src/shipmill/doctor.py, work branch names
- Enforced by: tests/test_lanes.py and tests/test_setup.py (with #15); review for the prefix

## D-3: User-facing prose calls the release automation shipmill

- Decided: 2026-10-04, in romamo/shipmill#18
- Rule: README, docs, workflow comments, init's generated files, and skill prose call the release workflows and CLI shipmill; 'release bot' appears only as a skill trigger phrase or when it means any release bot (such as a legacy release-bot.yml)
- Why: 'Run by agents and one release bot' read as a service separate from shipmill, when it is shipmill's own prepare.yml and land.yml running the shipmill CLI; people still ask for 'a release bot', so skill descriptions keep the phrase to match
- Applies to: README.md, docs/*.md, .github/workflows/*.yml, src/shipmill/init.py, skills/*/SKILL.md
- Enforced by: review

## D-4: One factory config file: .github/shipmill.toml

- Decided: 2026-10-04, in romamo/shipmill#26
- Rule: Every shipmill layer reads its settings from one file, .github/shipmill.toml, one top-level section per layer
- Why: doctor checks the whole factory in one pass, and users learn one file
- Applies to: src/shipmill/policy.py, src/shipmill/doctor.py, src/shipmill/init.py, .github/shipmill.toml
- Enforced by: review, until the config loader tests land

## D-5: Specs are files in docs/specs/

- Decided: 2026-10-04, in romamo/shipmill#26
- Rule: A feature's spec is a file docs/specs/NNN-<slug>.md merged through a pull request before its build starts; issue bodies link to the spec, they don't hold it
- Why: a file is reviewed line by line, versioned with the code it describes, and readable by agents from the checkout
- Applies to: docs/specs/*, skills/github-issue-triage/*, spec gate
- Enforced by: review

## D-6: Operations data starts minimal

- Decided: 2026-10-04, in romamo/shipmill#26
- Rule: The operate and incident layers read only health URLs from the config and GitHub deployments; an external tracker or metrics source is added later behind its own config section, never required
- Why: a factory that needs no third-party account works for every repo on day one; richer sources can come once the minimal loop is proven
- Applies to: operate layer, incident layer, deploy_state.py, ops-watch skill
- Enforced by: review

## D-7: Production deploys act by default

- Decided: 2026-10-04, in romamo/shipmill#26
- Rule: A production environment's autonomy defaults to act: it deploys once its source environment has passed health checks for the bake time, with no human approval, unless the config sets propose or the stop switch is on
- Why: the release lanes already gate what ships; a bake time with health checks and automatic rollback is the safety, and the stop switch is the human override
- Applies to: deploy layer, [autonomy] config, environments config
- Enforced by: review

## D-8: A hold stops every release except a hand-started hotfix

- Decided: 2026-10-04, in romamo/shipmill#32
- Rule: While an issue labelled shipmill-hold is open, no lane releases (scheduled, push, or started by hand), except a hotfix a person starts by hand; the skip reason names the hold and says a hotfix can still be started
- Why: A hold usually means an incident, and a hotfix is its cure; making a person close the hold first adds a step at the worst moment, while everything automatic still stops
- Applies to: src/shipmill/autonomy.py, src/shipmill/planner.py, shipmill-hold label
- Enforced by: tests/test_autonomy.py (with #38)

## D-9: Warn about a new permission only where it is needed

- Decided: 2026-10-04, in romamo/shipmill#32
- Rule: doctor warns about a permission the caller's release.yml lacks only when the repo's config or state needs it (issues: write when a stage proposes or a hold is open); setups that don't use the feature see no new warning
- Why: a warning every existing setup gets for a feature it doesn't use trains people to ignore doctor; the failing job still explains the one-line fix when the need arises
- Applies to: src/shipmill/doctor.py, .github/workflows/prepare.yml, caller permissions
- Enforced by: review

## D-10: Product intake never acts; the maintainer accepts or declines

- Decided: 2026-10-05, in romamo/shipmill#69
- Rule: Product intake proposes and reports only ([autonomy] intake is observe or propose, never act): an opportunity becomes planned work only when the maintainer accepts it, and a declined opportunity keeps its recorded reason and is never re-proposed
- Why: what to build is the maintainer's call; the factory's job is to gather the evidence and keep the decision on record, so the same request isn't argued twice
- Applies to: skills/product-intake/*, src/shipmill/autonomy.py, [autonomy] intake, opportunity issues
- Enforced by: tests/test_autonomy.py (intake refuses act, with #76); review

## D-11: A hold stops the gate from starting sessions

- Decided: 2026-10-04, in romamo/shipmill#45
- Rule: While an issue labelled shipmill-hold is open, shipmill gate starts no Claude Code session for the repo (it reports HELD); a session already running is left to finish, and the gate names it so a person can stop it
- Why: A hold usually means an incident; an agent that triages, implements, or merges while one is open adds changes at the worst moment, and the stop switch should stop every automatic actor, not only releases (D-8)
- Applies to: src/shipmill/gate.py, shipmill-hold label
- Enforced by: tests/test_gate.py (with the implementing PR)
- Superseded by: D-13

## D-12: Whoever creates a worktree removes it

- Decided: 2026-10-05, in shipmill/shipmill#116
- Rule: Whoever creates a worktree removes it once its PR merges; once the creating session has exited, shipmill gate's prune owns it and removes only what the spec's checks prove landed
- Why: Sessions that exit before their PR merges leave worktrees and local branches no later pass touches, since each pass removes only what it created; one owner for the orphans, acting only on proof, collects them without risking unlanded work
- Applies to: src/shipmill/gate.py, skills/*/SKILL.md, worktrees
- Enforced by: review
- Superseded by: D-24

## D-13: A hold stops the gate from starting sessions, not from stopping a stuck one

- Decided: 2026-10-05, in shipmill/shipmill#119
- Rule: While an issue labelled shipmill-hold is open, shipmill gate starts no Claude Code session for the repo (it reports HELD); a session already running is left to finish, and the gate names it so a person can stop it. The one exception: a session that has waited on the user for [agents] max_wait_hours is stopped, held or not
- Why: A hold exists to stop automatic actors from adding changes; stopping a session that waits on a question adds none, and leaving it would keep the repo stalled after the hold closes
- Applies to: src/shipmill/gate.py, shipmill-hold label, [agents] max_wait_hours
- Enforced by: tests/test_gate.py (with the implementing PR)
- Supersedes: D-11
- Superseded by: D-15

## D-14: Agent sessions write as the App or not at all

- Decided: 2026-10-05, in shipmill/shipmill#137
- Rule: When [agents] app_id is set, shipmill gate starts a session only as that GitHub App, with a token limited to the gate's repo; any failure to set up the App's identity exits 2 instead of falling back to the host's gh login
- Why: A silent fallback would make agent work look like the maintainer's again, defeating the metrics and the reviews that rely on telling the two apart, and would hand the session the maintainer's full token
- Applies to: src/shipmill/gate.py, [agents] app_id, shipmill app-token
- Enforced by: tests/test_gate.py (with the implementing PR)

## D-15: A session waiting on the user is stopped after 15 minutes unless configured

- Decided: 2026-10-06, in shipmill/shipmill#147
- Rule: While an issue labelled shipmill-hold is open, shipmill gate starts no Claude Code session for the repo (it reports HELD); a session already running is left to finish, and the gate names it so a person can stop it. A session that has waited on the user for [agents] max_wait_minutes is stopped, held or not; the key counts minutes, defaults to 15, and 0 never stops one
- Why: The gate runs one session per repo, so a session waiting on a question stops triage, landing, and shipped notices for every issue; with no limit by default, one unanswered question stalled the repo for 10 hours. A stopped session keeps its conversation, so `claude attach <id>` still shows the question, and the next tick can start fresh work
- Applies to: src/shipmill/agents.py, src/shipmill/gate.py, shipmill-hold label, [agents] max_wait_minutes
- Enforced by: tests/test_gate_waiting.py, tests/test_config.py
- Supersedes: D-13

## D-16: Unattended agent sessions work only on trusted authors' items

- Decided: 2026-10-06, in shipmill/shipmill#148
- Rule: A shipmill gate session that nobody can watch ([agents] mode = "headless", and any later unattended mode) is started only for issues opened by an OWNER, MEMBER, or COLLABORATOR or by the gate's own App bot, and for pull requests whose head is in the repo; everything else waits for an interactive session
- Why: An unattended session reads issue text with the whole workspace in reach and is allowed git, gh, and uv run, which can each run code; the tool allowlist only keeps prompts from blocking it, so who opened the item is the control that keeps an outsider's text from steering it
- Applies to: src/shipmill/gate.py, skills/github-issue-triage/scripts/triage_state.py, skills/github-ship-watch/scripts/watch_state.py, [agents] mode
- Enforced by: tests/test_gate.py and the triage_state.py and watch_state.py tests (with the implementing PR)

## D-17: Headless gate sessions run as claude -p, tracked by their process

- Decided: 2026-10-06, in shipmill/shipmill#160
- Rule: In [agents] mode = "headless", shipmill gate starts each session with `claude -p`, never `claude --bg`, detached from the tick with its output in a log under the state directory, and decides whether it still runs from the recorded pid and process start time, not from `claude agents`; a headless session never reads as waiting on the user
- Why: The probe for #160 showed a `--bg` session reads `blocked` whenever its last reply asks for something, with no prompt pending, so a session that posts its question on GitHub would still hold the repo as WAITING until max_wait_minutes; `--bg` and `--print` refuse to combine, and a print session exits when its prompt is done, so it has no state in which it waits. The cost is `claude attach`: `claude --resume <id>` and the log replace it
- Applies to: src/shipmill/gate.py, src/shipmill/launchd.py, [agents] mode, gate.json
- Enforced by: tests/test_gate.py and tests/test_launchd.py (with the implementing PR)

## D-18: A Release run recovers an orphaned work branch

- Decided: 2026-10-06, in shipmill/shipmill#175
- Rule: When prepare finds the shipmill/vX.Y.Z work branch on origin and no queued or in-progress run of the same release workflow owns it, it deletes the branch and pushes its own; this needs actions: read on the caller's prepare job, and without that permission prepare keeps the stop, with a warning annotation and a step-summary line naming the branch, and the run stays green
- Why: A run cancelled before its cleanup job gets a runner can't clean up after itself, so recovery has to come from a later run; the permission is new for callers, so a caller that doesn't grant it keeps today's behaviour, visibly, instead of breaking
- Applies to: src/shipmill/land.py, src/shipmill/cli.py, .github/workflows/release.yml, shipmill init, skills/github-ship-watch/scripts/watch_state.py
- Enforced by: tests (with the implementing PR)

## D-19: A gate without an App is unfinished setup

- Decided: 2026-10-07, in shipmill/shipmill#204
- Rule: shipmill-setup sets [agents] app_id before it installs the gate's launchd job, and an [agents] prompt with no app_id reads as an action for a person in setup_state.py (AGENTS_NO_APP) and watch_state.py (GATE_NO_APP), never as done; the gate and launchd commands still run without one
- Why: Without an App a session's comments, PRs, and commits read as the maintainer's own, the maintainer can't approve its PRs, and GitHub doesn't notify them of its mentions; on romamo/treaty a gate went live that way unnoticed because the report counted it as done. Refusing in the gate itself would break gates already installed
- Applies to: skills/shipmill-setup/SKILL.md, skills/shipmill-setup/scripts/setup_state.py, skills/github-ship-watch/scripts/watch_state.py, [agents] app_id, shipmill status
- Enforced by: the setup_state.py and watch_state.py tests (with the implementing PR)

## D-20: Setup writes [agents] mode explicitly

- Decided: 2026-10-07, in shipmill/shipmill#205
- Rule: shipmill-setup asks for [agents] mode every time it sets up the gate and writes the answer as mode = "interactive" or mode = "headless"; an [agents] prompt with no mode key reads as an action in setup_state.py (AGENTS_NO_MODE), while the config's default stays interactive
- Why: A setup that skipped the question installed an interactive gate on a machine nobody watches (romamo/treaty); the default keeps existing gates working, and the report makes the missing answer visible
- Applies to: skills/shipmill-setup/SKILL.md, skills/shipmill-setup/scripts/setup_state.py, [agents] mode
- Enforced by: the setup_state.py tests (with the implementing PR)

## D-21: Every gate session asks through the needs-decision protocol

- Decided: 2026-10-07, in shipmill/shipmill#206
- Rule: A shipmill gate session, interactive or headless, posts each question as a needs-decision marker comment with the needs-decision label before anything else; an interactive session also asks in the session, and when the answer comes there it removes the label and goes on; setup creates the needs-decision label whenever the config has an [agents] section
- Why: An interactive gate session nobody attached to improvised plain question comments without the marker or the label (romamo/treaty), so watch_state.py kept counting the items as work and the gate stuck in its UNCHANGED cooldown; a session can't tell whether anyone is attached, and posting first takes the item out of the gate's work at once. Switching to headless after a wait would need new gate behaviour to restart sessions
- Applies to: skills/github-issue-triage/references/needs-decision.md, skills/github-issue-triage/SKILL.md, skills/github-issue-resolve/SKILL.md, skills/github-pr-triage/SKILL.md, skills/shipmill-setup/scripts/setup_state.py, src/shipmill/gate.py, needs-decision label
- Enforced by: the setup_state.py and gate prompt tests (with the implementing PR)

## D-22: The gate updates its checkout's plugin once a day, only when the config allows it

- Decided: 2026-10-07, in shipmill/shipmill#233
- Rule: With [agents] plugin_update = true, shipmill gate checks at most once per 24 hours (the last check recorded under the repo's git directory) whether its checkout's project install of shipmill@shipmill is behind the latest release and, when it is, updates that install before it starts a session; a failed update is reported on the tick and the session still starts. The key defaults to false, and then the gate changes no install. Either way, shipmill status, doctor, and setup_state.py report a behind install in the repo's folder and in the gate's checkout as separate rows, each with a fix that works when run in that folder
- Why: Gate sessions ran a plugin install in tmp/shipmill-gate that was 0.25.0 while 0.32.1 was out, and the update status printed resolved to that nested install, so the repo's own install stayed stale and the line never cleared (romamo/treaty). A check before every session would cost a claude call per tick; a default of false keeps gates already installed from changing installs without a config change
- Applies to: src/shipmill/gate.py, src/shipmill/agents.py, src/shipmill/init.py, src/shipmill/doctor.py, skills/github-ship-watch/scripts/watch_state.py, skills/shipmill-setup/scripts/setup_state.py, [agents] plugin_update, shipmill status
- Enforced by: the gate, watch_state.py, and setup_state.py tests (with the implementing PR)
- Superseded by: D-23

## D-23: The gate updates every install keyed on its checkout, project or local scope

- Decided: 2026-10-08, in shipmill/shipmill#240
- Rule: With [agents] plugin_update = true, shipmill gate checks at most once per 24 hours (the last check recorded under the repo's git directory) whether any install of shipmill@shipmill keyed on its checkout, at project or local scope, is behind the latest release and, when one is, updates it before it starts a session; a failed update is reported on the tick and the session still starts. The key defaults to false, and then the gate changes no install. Either way, shipmill status, doctor, and setup_state.py report a behind install in the repo's folder and in the gate's checkout as separate rows, each with a fix that works when run in that folder
- Why: shipmill's own gate checkout holds a local-scope install (0.25.0) that D-22's project-only rule never updated, so its sessions kept old skills while the other gated repos, on project scope, got the latest; the maintainer chose to cover any install keyed on the checkout
- Applies to: src/shipmill/gate.py, src/shipmill/plugin.py, src/shipmill/agents.py, src/shipmill/doctor.py, skills/github-ship-watch/scripts/watch_state.py, skills/shipmill-setup/scripts/setup_state.py, [agents] plugin_update, shipmill status
- Enforced by: the gate and plugin tests (with the implementing PR)
- Supersedes: D-22
- Superseded by: D-35

## D-24: A worktree whose tip was a merged PR's head has landed

- Decided: 2026-10-08, in shipmill/shipmill#244
- Rule: Whoever creates a worktree removes it once its PR merges; once the creating session has exited, shipmill gate's prune owns it and removes only what the spec's checks prove landed, where a branch also counts as landed when its tip is, or was before a force-push, the head of a merged pull request on that branch; a commit made after that tip keeps the worktree
- Why: Review often rebases, amends, or drops part of a PR before a squash merge, so the worktree's own commit is in no merged history and its worktree read as not landed forever (treaty PR #75); the merged PR was that commit's review, so work dropped there has landed in effect, and a later commit still protects real unlanded work
- Applies to: src/shipmill/worktrees.py, src/shipmill/gate.py, skills/*/SKILL.md, worktrees, docs/specs/002-*
- Enforced by: the worktrees tests (with the implementing PR)
- Supersedes: D-12

## D-25: A stable promotion folds its version's rc sections into one section

- Decided: 2026-10-08, in shipmill/shipmill#243
- Rule: When a stable release promotes an rc and the CHANGELOG holds sections for that version's rcs ([X.Y.ZrcN], newer than the last stable), the X.Y.Z section gets every entry of those sections plus Unreleased, merged under their headings, and the rc sections are removed; those sections count as pending, so a promotion never skips as nothing pending while they hold entries
- Why: A repo that moved to shipmill from a release bot that wrote rc sections had an empty Unreleased at every rc's base, so stable promotion skipped and 1.0.0 could not release (romamo/treaty); one stable section shows everything since the last stable, and the per-rc history stays in the rc tags and their GitHub releases
- Applies to: src/shipmill/planner.py, src/shipmill/changelog.py, src/shipmill/stamp.py, CHANGELOG, stable lane
- Enforced by: the planner and changelog tests (with the implementing PR)

## D-26: The stable fold drops an rc section's intro prose

- Decided: 2026-10-08, in shipmill/shipmill#283
- Rule: When a stable release folds its rc sections (D-25), prose that sits before the first '### ' heading of an rc section is dropped; any other text outside an entry (between entries, a '#### ' heading, a numbered list) still fails the fold
- Why: An intro line describes that rc, not the stable release, and earlier release bots wrote one per rc (treaty has 36); text anywhere else may be part of an entry, and the fold removes the section, so it must fail rather than vanish
- Applies to: src/shipmill/changelog.py, the stable fold
- Enforced by: review

## D-27: A revision older than the fragments folder has no fragments

- Decided: 2026-10-08, in shipmill/shipmill#291
- Rule: When shipmill reads fragments at a revision whose tree has no fragments folder and whose own config doesn't set [changelog] fragments, it counts no fragments there; the current revision, and any revision whose config sets the key, still exit 2 naming a missing folder (S-013-2)
- Why: A repo that turns fragments on mid-cycle must still promote an rc cut before the folder existed and run notes against an older tag; a revision that itself asked for fragments and lacks the folder is still a mistake that must fail
- Applies to: src/shipmill/fragments.py, src/shipmill/planner.py, src/shipmill/propose.py, src/shipmill/stamp.py, changelog fragments
- Enforced by: review

## D-28: A stable promotion skips when the CI workflows changed since its rc

- Decided: 2026-10-09, in shipmill/shipmill#317
- Rule: When .github/workflows/ differs between the rc tag a stable lane would promote and the run's base, the stable lane skips with a reason naming the rc and the changed CI, and the same run plans the next lane (rc), so the next rc carries the new CI and soaks before it is promoted
- Why: A local reusable workflow resolves at the commit that started the run, so a promotion's CI is main's while its tree is the rc's; a CI change that pairs with code fails every promotion of an older rc and, retried hourly, starves rc. Restarting the soak was chosen over promoting without a fresh CI run
- Applies to: src/shipmill/planner.py, release lanes, stable promotion
- Enforced by: review

## D-29: A trusted marker comment confirms a close

- Decided: 2026-10-10, in shipmill/shipmill#332
- Rule: A closed issue stops reading SUSPECT_CLOSE once a comment posted after its last close has `<!-- shipmill:close-confirmed -->` as its first line and comes from an OWNER, MEMBER, or COLLABORATOR or from the `--bot-login` App; an outsider's marker never counts, and a reopen and a new close re-arm it
- Why: A correct close with no merged closer had no way to say so, and the gate started a session for it every retry_hours; a marker carries its reason in the comment and counts only from the authors D-16 trusts, where a label would carry no reason, could be added by anyone with triage rights, and would survive a reopen
- Applies to: skills/github-issue-triage/scripts/triage_state.py, skills/github-ship-watch/scripts/watch_state.py, SUSPECT_CLOSE, comment markers
- Enforced by: the triage_state.py tests (with the implementing PR)

## D-30: An unattended gate trusts shipmill's own upgrade issues

- Decided: 2026-10-10, in shipmill/shipmill#314
- Rule: Extending D-16, an unattended gate session also takes up an issue authored by `github-actions[bot]` when it carries both the `shipmill-upgrade` label and a first line `<!-- shipmill-upgrade: <id> <version> -->` marker; any other `github-actions[bot]` issue stays untrusted
- Why: Only a workflow running in the repo can author as github-actions[bot], and the label plus marker narrow that to shipmill's own config-upgrade proposals; without this a headless gate never asked the upgrade question (S-014-10), and answered upgrades had to be applied by hand. Merging still waits on the maintainer's accepting answer (S-014-13)
- Applies to: skills/github-issue-triage/scripts/triage_state.py, skills/github-ship-watch/scripts/watch_state.py, src/shipmill/gate.py, --trusted-only, [agents] mode
- Enforced by: the triage_state.py and watch_state.py tests (with the implementing PR)

## D-31: shipmill decides and verifies a rollout; the platform executes it

- Decided: 2026-10-16, in shipmill/shipmill#370
- Rule: shipmill owns the policy of a rollout: when a release is promoted to the next lane, environment, or ring, which signals count as ready or bad (health, bake, a dependent's CI, an eval, a person's answer), what holds it (blockers, freezes, needs-decision), when to roll back, and the record of each of those decisions. Executing it belongs to the deploy platform, reached through the repo's own workflows: shifting traffic or canary percentages, feature flags, a store's phased release, redeploying the previous tag, and updating a consumer's dependency. shipmill grows adapters that start that execution and read its signals, never its own traffic, flag, or dependency-update machinery. The one delivery shipmill performs itself is moving its own references, such as a floating major tag, since no platform owns those
- Why: shipmill already never deploys: `land` starts the repo's deploy workflow on the tag, and `operate` reads health, bakes, and decides a rollback. Writing the line down keeps the policy across lanes, environments, and holds in one place while each platform keeps the mechanics it does better, and stops scope from drifting into a rollout engine. A floating tag is the exception because moving it is the release reaching every consumer at once, so its promotion has to be shipmill's decision
- Applies to: src/shipmill/operate.py, src/shipmill/land.py, [environments], move-major-tag.yml, new rollout, canary, flag, or ring features
- Enforced by: review

## D-32: Without goals there is no roadmap plan; a milestone is the maintainer's list

- Decided: 2026-10-17, in shipmill/shipmill#376
- Rule: shipmill drops the roadmap plan: product-intake no longer proposes, ranks, or creates milestones, and `roadmap_state.py`, `src/shipmill/roadmap.py`, and the `[roadmap]` section go. A milestone stays as the maintainer's own list of what a version must hold, and `milestone = true` keeps making a lane due by it. The work-in-progress limit triage reads moves from `[roadmap] wip` to `[agents] wip`. `[roadmap]` is deprecated before it is removed: for one minor release the policy accepts it, `doctor` warns and names `[agents] wip`, and the next minor refuses it. Product intake keeps grouping requests into opportunities and handing accepted ones to triage
- Why: The plan ranked opportunities by evidence per load, so with no product goals above it a milestone followed the loudest requests, not a goal; no repo used it, while a manual milestone holds a real release (a 1.0.0). Planning comes back with a goals layer, which is out of scope for now; removing the code keeps agents from reading and acting on a plan that has no basis. The WIP limit governs agents' work in the delivery loop, so it outlives the roadmap
- Applies to: skills/product-intake/SKILL.md, skills/product-intake/scripts/roadmap_state.py, src/shipmill/roadmap.py, src/shipmill/policy.py, src/shipmill/doctor.py, skills/github-issue-triage/references/spec-gate.md, skills/github-issue-triage/scripts/triage_state.py, docs/release-lanes.md, docs/flow.md, [roadmap], [agents] wip, milestones
- Enforced by: review

## D-33: Land a pull request with a squash, and the base of a stack with a merge commit

- Decided: 2026-10-17, in shipmill/shipmill#378
- Rule: github-pr-triage merges a pull request with a squash merge, and a pull request another open pull request is stacked on with a merge commit; where the repo's settings don't allow a squash merge, it uses a merge commit. It never rebase-merges. The choice no longer follows "the repo's history"
- Why: The repo allows all three methods and its history mixes squash and merge commits, so "match the repo's history" left each session to choose: on 2026-10-16 a squash of a stack's base meant the child had to be rebased and force-pushed by hand. A squash keeps main one commit per pull request, which is how a reader and a revert see it; a merge commit keeps a stack's base SHAs, so its child retargets and rebases clean; a rebase merge rewrites SHAs and gives neither
- Applies to: skills/github-pr-triage/SKILL.md, skills/github-pr-triage/references/landing.md (Merge style), gh pr merge
- Enforced by: review

## D-34: Agents work toward the product's written direction

- Decided: 2026-10-18, in shipmill/shipmill#382
- Rule: A repo whose agents implement (its config has `[agents]`) keeps its direction in `docs/product.md`, in a fixed structure code parses: mission, then users, goals, non-goals, and quality bar as items with ids (`U-n`, `G-n`, `N-n`, `Q-n`); a section that outgrows a page moves to `docs/product/` behind a link. Only the maintainer changes it. Triage, product intake, specs, implementers' plans, and reviews read the parts they need: new behaviour names the goal it serves or is postponed, a non-goal is won't fix, and a pull request carries its plan. `REVIEW.md` at the root, shared with Claude's Code Review, is the repo's optional review rubric: free sections for people and the model, and structured ones (Important rules with `I-n` ids, the nit cap, protected globs) that code extracts (spec 024). A repo where shipmill only cuts releases needs none. This replaces the earlier view that a goals page is needed only by the features that ask for one
- Why: Without a written direction the loop closes tasks correctly and can still take the product where nobody chose: triage judges each issue alone, intake ranks by volume, review checks a diff against its issue. D-32 removed the roadmap plan for lack of goals and said planning comes back with a goals layer; one structured file is the cheapest layer every agent can read and code can check, ids make a reference to a goal verifiable, and the maintainer reviews it like code
- Applies to: docs/product.md, docs/product/, REVIEW.md, docs/specs/, src/shipmill/product.py, src/shipmill/doctor.py, skills/github-issue-triage/SKILL.md, skills/github-issue-triage/references/triage-rubric.md, skills/github-issue-triage/scripts/specs.py, skills/product-intake/SKILL.md, skills/github-issue-resolve/SKILL.md, skills/github-pr-triage/references/reviewer-brief.md, skills/github-pr-triage/scripts/pr_gate.py, skills/shipmill-setup/SKILL.md, [agents]
- Enforced by: review, until spec 024 is built

## D-35: The gate starts no session on skills older than the latest release

- Decided: 2026-10-18, in shipmill/shipmill#417
- Rule: Before it starts a session, shipmill gate reads the shipmill@shipmill version a session in its checkout would load, at any scope (user scope included), and when that version is older than the latest release it starts no session: the tick reports the stale install, its scope, and the command that updates it, and the gate starts sessions again once the install is current. With [agents] plugin_update = true it still first updates the installs keyed on its checkout once a day, as D-23 says; shipmill status and doctor report the version a session would load against the latest release
- Why: Unattended sessions ran older skills than the repo (a 0.25.0 local install the update never reached, then a 0.48.0 user-scope install whose watch_state.py exits 2 on this repo), and Claude Code offers no way to update an install by its folder; the maintainer chose a paused gate over old skills doing unattended work
- Applies to: src/shipmill/gate.py, src/shipmill/plugin.py, src/shipmill/agents.py, src/shipmill/doctor.py, skills/github-ship-watch/scripts/watch_state.py, skills/shipmill-setup/scripts/setup_state.py, [agents] plugin_update, shipmill status
- Enforced by: the gate and plugin tests (with the implementing PR)
- Supersedes: D-23
- Superseded by: D-43

## D-36: Delivery rules that guard irreversible writes are enforced by plugin hooks in repos with [agents]

- Decided: 2026-10-18, in shipmill/shipmill#433
- Rule: In a repo whose .github/shipmill.toml has an [agents] section, the shipmill plugin's PreToolUse hook refuses, with exit 2 and the command to run instead: a gh write while [agents] app_id is set unless it runs as shipmill gh (an inline GH_TOKEN=$T gh is refused too, since an empty $T falls back to the maintainer's login; shipmill gh is the way to write), a push to the default branch unless [hooks] default_branch = false, a rebase merge, a force push without --force-with-lease=<ref>:<sha>, and a cp, mv, or rsync of a [hooks] private path out of the repo; the app-writes, rebase-merge, and force-push rules have no switch, and no session can turn a rule off for itself. A headless gate whose hook self-test fails starts no session (spec 026)
- Why: Skills are advice an agent can miss, and these mistakes are writes nobody can take back: a write attributed to the maintainer, an unreviewed change on main, a rewritten history, a private file in a public repo. A hook refuses them before they happen; the maintainer chose refusal over report-only, and a paused headless gate over unattended sessions without the hooks, as D-35 chose for stale skills
- Applies to: hooks/hooks.json, hooks/delivery.py, src/shipmill/policy.py, src/shipmill/doctor.py, src/shipmill/gate.py, skills/github-pr-triage/SKILL.md, skills/github-pr-triage/references/landing.md, skills/shipmill-setup/SKILL.md, [hooks], [agents] app_id, shipmill gh
- Enforced by: tests/test_delivery_hooks.py and the doctor and gate tests (with the implementing PR)
- Superseded by: D-40

## D-37: A change to the agents' instructions lands only when the evals don't regress

- Decided: 2026-10-18, in shipmill/shipmill#380
- Rule: A pull request that touches the agents' instructions (`skills/**`, `.claude-plugin/**`, `evals/**`, or the gate's session paragraphs in `src/shipmill/gate.py`) lands only on a green `evals` check: `shipmill evals compare` against the default branch's latest run finds no drop in the suite pass rate beyond 0.05, no case that passed 3 of 3 there passing at most 1 of 3, and no new or changed case passing fewer than 2 of 3 (spec 025). A fork's pull request runs its evals only when the maintainer dispatches them, and lands only after that run is green
- Why: The scripts' tests never covered the judgment a skill's prose asks for, so a rewording could turn a verdict, drop a review finding, or make a headless session guess, and that showed only as a bad verdict or merge in a real repo; a gate on real cases from shipmill's history catches it before it lands, and a fork's change runs the repository's scaffold and the API key, so it waits for the maintainer as unattended work does (D-16)
- Applies to: skills/**, .claude-plugin/**, evals/**, src/shipmill/gate.py, src/shipmill/evals.py, .github/workflows/evals.yml, skills/github-pr-triage/SKILL.md
- Enforced by: the evals check in .github/workflows/evals.yml, once spec 025 is built; review until then

## D-38: An accepted goal plan may create the milestone it names

- Decided: 2026-10-18, in shipmill/shipmill#430
- Rule: When the maintainer accepts a goal plan whose Milestone section names a title, product intake puts the plan's filed and existing items of this repository in that milestone and creates it when it doesn't exist; a plan naming `none` touches no milestone, and intake still never proposes, ranks, or creates a milestone on its own. This refines D-32: a milestone stays the maintainer's list, and accepting a plan that names one is the maintainer adding to it
- Why: A plan is how the maintainer chooses the work that completes a goal, and the milestone is what makes a lane wait until that goal is built (spec 022); asking the maintainer to create it by hand before every accept adds a step that carries no decision the accept didn't already make
- Applies to: skills/product-intake/SKILL.md, skills/product-intake/references/plan.md, skills/product-intake/scripts/intake_state.py, milestones
- Enforced by: review, until spec 028 is built

## D-39: Stable releases every green batch; a breaking change waits for the maintainer; a soak only when something is observed

- Decided: 2026-10-18, in shipmill/shipmill#451
- Rule: A stable lane releases every batch of merges whose CI passed on the release commit, with no time soak: min_soak_days is deprecated for one minor release and then refused (spec 029); a stable candidate whose pending entries bump the major part (before 1.0 too) is never released by a trigger, only proposed, and releases when a person starts the stable lane by hand; a pre-release lane is kept where people try a change first, and a soak is added only when something is observed during it, such as an environment's health over bake_minutes
- Why: A time soak with nobody running the rc and no telemetry read (treaty, cloudfall: promote_from = 'rc', min_soak_days = 3) caught no defect and only added lead time; proof belongs before the merge (CI, agent review, evals, hooks, protected areas) and recovery after it (fix-forward, yank, rollback). A breaking change is the one release a person must choose, so it waits for a hand start an App can't make. A signal-based soak was considered and rejected; consumer cooldown is the consumer's tool; a milestone is a scope decision and stays
- Applies to: src/shipmill/planner.py, src/shipmill/policy.py, src/shipmill/init.py, src/shipmill/upgrades.py, src/shipmill/propose.py, src/shipmill/doctor.py, docs/release-lanes.md, docs/product.md, skills/shipmill-setup/SKILL.md, stable lane, min_soak_days, promote_from, release lanes
- Enforced by: review, until spec 029 is built

## D-40: A delivery hook that can't start lets the command run, with a warning

- Decided: 2026-10-18, in shipmill/shipmill#458
- Rule: In a repo whose .github/shipmill.toml has an [agents] section, the shipmill plugin's PreToolUse hook refuses, with exit 2 and the command to run instead: a gh write while [agents] app_id is set unless it runs as shipmill gh (an inline GH_TOKEN=$T gh is refused too, since an empty $T falls back to the maintainer's login; shipmill gh is the way to write), a push to the default branch unless [hooks] default_branch = false, a rebase merge, a force push without --force-with-lease=<ref>:<sha>, and a cp, mv, or rsync of a [hooks] private path out of the repo; the app-writes, rebase-merge, and force-push rules have no switch, and no session can turn a rule off for itself. Only hooks/delivery.py's own refusal exits 2: when the hook can't start the script (uv missing, no Python 3.11 or newer that uv can find or install, the script missing), it exits 1 with one stderr line naming shipmill doctor, and the command runs unchecked. shipmill doctor FAILs on that case, and a headless gate whose hook self-test fails starts no session (spec 026)
- Why: Exit 2 from uv itself (offline, or python-downloads = never) read as a refusal of every shell command, so a person's session offline stalled until a Python 3.11 was installed; the maintainer chose fail-open with a warning, since doctor and the headless gate's self-test still catch the case, so only a person's session ever runs unchecked
- Applies to: hooks/hooks.json, hooks/delivery.py, src/shipmill/policy.py, src/shipmill/doctor.py, src/shipmill/gate.py, skills/github-pr-triage/SKILL.md, skills/github-pr-triage/references/landing.md, skills/shipmill-setup/SKILL.md, [hooks], [agents] app_id, shipmill gh
- Enforced by: tests/test_delivery_hooks.py and the doctor and gate tests (with the implementing PR)
- Supersedes: D-36
- Superseded by: D-54

## D-41: An environment hears of the fixes since the release it ran before

- Decided: 2026-10-19, in shipmill/shipmill#434
- Rule: An environment's deployment notice (S-021-4) tells the closed issues fixed from the release tag of the newest earlier successful deployment there (else the release tag just below) up to the deployed tag, so fixes released before an environment's first deployment are never told for it; an environment may not be named pre-release or stable, the notice stages' names (shipped.py --environment exits 2)
- Why: Read literally, S-021-4 would tell every closed issue the project ever fixed on the first deployment to a new environment, flooding old threads; the maintainer (@romamo, on #434) chose the range, whose cost is that fixes released before an environment's first deployment are never told for it. An environment named like a notice stage would read as told by the release notices, so the name is refused
- Applies to: skills/github-pr-triage/scripts/shipped.py, skills/github-ship-watch/scripts/watch_state.py, docs/specs/021-requester-ring.md
- Enforced by: tests/test_shipped.py and tests/test_ship_watch.py (S-021-4)

## D-42: A client repo's own docs are the maintainer's

- Decided: 2026-10-20, in shipmill/shipmill#496
- Rule: shipmill never writes to, appends to, or drafts text for a client repo's own docs (README.md, CONTRIBUTING.md, CLAUDE.md, AGENTS.md, and the like): not in shipmill-setup, init, upgrades, or any agent session. It may read them, for check commands and repo rules, and report what it found as file and line, leaving the change to the maintainer. Files in folders shipmill owns, such as changelog.d/README.md, are not client docs
- Why: Those files speak for the maintainer to their contributors; text shipmill writes there reads as the maintainer's and goes stale when shipmill changes. Set by @romamo in chat, relayed in #496 and #495
- Applies to: skills/shipmill-setup, src/shipmill/init.py, src/shipmill/upgrades.py, docs/install.md
- Enforced by: Review; setup_state.py reports such lines without fixing them

## D-43: The plugin pins its release; the gate loads the latest release per session and never pauses on a stale install

- Decided: 2026-10-19, in shipmill/shipmill#477
- Rule: Skills, their scripts, and the plugin's hooks run the CLI as `uvx shipmill==<version>`, the version in the plugin's own .claude-plugin/plugin.json, from PyPI, never from the @v0 tag's source or a bare shipmill on PATH; the @v0 tag may stay for outside users. The marketplace entry names the release tag, moved by the release workflow together with plugin.json, so the marketplace never serves unreleased commits, and its ref is the latest release every comparison uses. .github/shipmill.toml may set `requires = ">=X.Y"`; a CLI or script that doesn't meet it exits 2 saying which version to update to and the command. Before each session shipmill gate reads the latest version from the marketplace, materializes it once into an immutable cache (~/.cache/shipmill/plugin/<version>/, written to a temporary folder and renamed), and starts the session with --plugin-dir on that folder and settings that disable shipmill@shipmill; it changes no install, a running session keeps its folder, and a new release is picked up on the next tick. doctor, status, and the tick report each install at user, project, or local scope that lags the latest release, an install keyed on a gate checkout that no session loads, the gate's own CLI when it lags, and a config whose requires isn't met, each with its fix, plus one desktop notification per release under notify = true; only a failed materialization of the needed version, with no usable cached version, stops the gate's sessions. [agents] plugin_update is deprecated for one minor release and ignored, then refused (spec 031)
- Why: Every release paused every gate on a host until the maintainer updated the user-scope install by hand (four releases on 2026-10-18 left four gates paused overnight), and plugin_update reported success while an install keyed on a worktree checkout never moved (#485). The pause treated drift between the plugin a session loads, the CLI it runs from @v0 or PATH, and a marketplace serving main; pinning the CLI to the plugin's version, serving releases only, and loading the release per session removes the drift instead of pausing on it
- Applies to: src/shipmill/gate.py, src/shipmill/plugin.py, src/shipmill/agents.py, src/shipmill/doctor.py, src/shipmill/status.py, src/shipmill/policy.py, src/shipmill/launchd.py, src/shipmill/init.py, src/shipmill/upgrades.py, src/shipmill/__init__.py, .claude-plugin/marketplace.json, .claude-plugin/plugin.json, .github/shipmill.toml, hooks/delivery.py, skills/*/SKILL.md, skills/github-ship-watch/scripts/watch_state.py, skills/shipmill-setup/scripts/setup_state.py, skills/github-pr-triage/scripts/shipped.py, [agents] plugin_update, requires, shipmill status
- Enforced by: review, until spec 031 is built
- Supersedes: D-35
- Superseded by: D-44

## D-44: Gate sessions load the plugin installed from the marketplace; shipmill keeps no copy of it

- Decided: 2026-10-21, in shipmill/shipmill#564
- Rule: As D-43, save how a gate session gets the plugin: the gate starts its sessions with the install of shipmill@shipmill that applies to its checkout, as any session on the host does, with no --plugin-dir, no shipmill-owned cache of plugin versions, and no change to enabledPlugins; it never updates an install. Skills, their scripts, and the plugin's hooks run the CLI as `uvx shipmill==<version>`, the version in the plugin's own .claude-plugin/plugin.json; the marketplace entry names the release tag and its ref is the latest release every comparison uses; .github/shipmill.toml may set `requires`. doctor, status, and the tick report each install that lags the latest release, an install keyed on a gate checkout that no session loads, the gate's own CLI when it lags, and a config whose requires isn't met, each with its fix, plus one desktop notification per release under notify = true. The one plugin check that holds a session is PyPI answering 404 for the version sessions load: the tick starts none and reports that version waits for PyPI. [agents] plugin_update is deprecated for one minor release and ignored, then refused (spec 031)
- Why: Once the plugin pins its CLI (#548, v0.58.0), a lagging install is an older release consistent with itself, so the drift D-43 removed no longer needs a second delivery path. The marketplace stays the single registry and the single way the plugin reaches a host, and Claude Code already keeps its own copy of each installed version; a shipmill cache of the same tags added a mechanism without a need
- Applies to: src/shipmill/gate.py, src/shipmill/plugin.py, src/shipmill/agents.py, src/shipmill/doctor.py, src/shipmill/status.py, src/shipmill/policy.py, src/shipmill/launchd.py, src/shipmill/init.py, src/shipmill/upgrades.py, src/shipmill/__init__.py, .claude-plugin/marketplace.json, .claude-plugin/plugin.json, .github/shipmill.toml, hooks/delivery.py, skills/*/SKILL.md, skills/github-ship-watch/scripts/watch_state.py, skills/shipmill-setup/scripts/setup_state.py, skills/github-pr-triage/scripts/shipped.py, [agents] plugin_update, requires, shipmill status
- Enforced by: review, until spec 031 is built
- Supersedes: D-43
- Superseded by: D-50

## D-45: The product's manager owns work across repos; a component's session stays in its repo

- Decided: 2026-10-24, in shipmill/shipmill#338
- Rule: A component repo's gate session reads and writes only its own repo (D-14, unchanged), plus the docs/product.md of its product's home repo (D-46); an item there waits only on items in the same repo. Work across repos belongs to the manager: the gate session of the product's home repo, which gets a second App token over the product's repos with contents, issues, and pull requests read and issues write. With it the manager reads the product's code and items, files and links issues in the component repos, and closes the stand-ins it watches, never changing files, pushing, creating a branch, opening a pull request, or merging outside the home repo. A cross-repo dependency in a repo with a manager is a local stand-in: a report labelled upstream, which an agent files in its own repo for a fault it traced to another module (how to reproduce it, the object it touches, and the suspected place in the code when it found one), or a stand-in for a dependency on another repo's work. The manager routes it to the owning repos as its children, and closes it, with a summary of what changed, once they close (as not planned when they won't be done). Without a manager the stand-in waits for the maintainer. This refines D-14
- Why: Chains across repos (spec 017) read an upstream item's state, but the App's token covers only the gate's repo, so an upstream in another private repo reads UNREADABLE and the chain stalls; and an agent that finds a bug in another repo's module has nowhere to put it. Which repos own a fault is a question of the whole product, often answered by several repos at once, and a coding agent usually can't run another repo's services, so it reports what it saw and the manager routes it. Keeping every cross-repo read and write in one role gives one token beyond a single repo instead of one per component, keeps other repos' text out of component sessions, and brings everything an agent needs to resume, the stand-in's closing summary, into its own repo. The cost is one manager tick per cross-repo step
- Applies to: src/shipmill/app.py, src/shipmill/gate.py, shipmill app-token, shipmill gh, skills/github-issue-triage/scripts/chains.py, skills/github-issue-triage/scripts/triage_state.py, skills/github-issue-triage/references/comments.md, skills/github-issue-resolve/SKILL.md, [agents] app_id, upstream label, home repo
- Enforced by: the tokens' permissions (a component's token covers its own repo; the manager's has no contents or pull requests write); review for the stand-in rules, until the implementing PR adds tests
- Superseded by: D-47

## D-46: A plan across repos lives in the product's home repo and reaches the others through a trusted marker

- Decided: 2026-10-24, in shipmill/shipmill#338
- Rule: A plan for a product that spans repos, with its stand-in issues and milestone, lives in the product's home repo: the repo whose docs/product.md describes the product as a whole, whether or not it holds code. Each component repo keeps its own docs/product.md for its own scope (D-34). Once the maintainer accepts the plan, they post a trusted marker that names each repo's items, and each repo's own session takes up its part, the way D-29's marker confirms a close; no session writes the plan's items into another repo
- Why: A plan is the maintainer's choice of work, so its items reach another repo only with the maintainer's word there; the manager's issue rights of D-45 route a bug report, a fact the owning repos' triage weighs, not accepted work. Filing each repo's items by hand in a session the maintainer starts would add a manual step to every plan; a trusted marker carries the maintainer's accept to each repo without letting one repo's text steer another's session (D-16)
- Applies to: skills/product-intake/*, docs/design/product-layer.md, docs/product.md, plans across repos, milestones
- Enforced by: review

## D-47: The product's coordinator owns delivery across repos and never plans the product; a component's session stays in its repo

- Decided: 2026-10-24, in shipmill/shipmill#580
- Rule: A component repo's gate session reads and writes only its own repo (D-14, unchanged), plus the docs/product.md of its product's home repo (D-46); an item there waits only on items in the same repo. Delivery across repos belongs to the coordinator, the role D-45 and D-46 called the manager: the gate session of the product's home repo, which gets a second App token over the product's repos with contents, issues, and pull requests read and issues write. With it the coordinator reads the product's code and items, files and links issues in the component repos, and closes the stand-ins it watches, never changing files, pushing, creating a branch, opening a pull request, or merging outside the home repo. A cross-repo dependency in a repo with a coordinator is a local stand-in: a report labelled upstream, which an agent files in its own repo for a fault it traced to another module (how to reproduce it, the object it touches, and the suspected place in the code when it found one), or a stand-in for a dependency on another repo's work. The coordinator routes it to the owning repos as its children, and closes it, with a summary of what changed, once they close (as not planned when they won't be done). It also builds the maintainer's queue across the product's repos. It coordinates delivery only: it never plans the product, sets priorities, or decides what to build, which stay with the maintainer and with whatever the product keeps outside shipmill for strategy, support, and operations. Without a coordinator the stand-in waits for the maintainer. This refines D-14
- Why: D-45's name, manager, promised product management, which shipmill's direction leaves out for now (N-4) and the maintainer narrowed shipmill to the delivery loop on 2026-10-17. What a product spanning repos needs from shipmill is delivery: dependencies that release across repos, faults routed to the repos that own them, and one queue (G-1, G-4). Planning a product across repos stays on hold (#338). The rest of D-45 holds unchanged: one role with a token beyond a single repo instead of one per component, other repos' text kept out of component sessions, and everything an agent needs to resume brought into its own repo, at the cost of one coordinator tick per cross-repo step
- Applies to: src/shipmill/app.py, src/shipmill/gate.py, shipmill app-token, shipmill gh, skills/github-issue-triage/scripts/chains.py, skills/github-issue-triage/scripts/triage_state.py, skills/github-issue-triage/references/comments.md, skills/github-issue-resolve/SKILL.md, docs/design/product-layer.md, [agents] app_id, upstream label, home repo, coordinator
- Enforced by: the tokens' permissions (a component's token covers its own repo; the coordinator's has no contents or pull requests write); review for the stand-in rules and the coordinator's scope, until the implementing PR adds tests
- Supersedes: D-45

## D-48: Agents decide by a written decision policy: act, notify, ask, or never per zone

- Decided: 2026-10-19, in shipmill/shipmill#486
- Rule: Each decision an agent meets falls in a zone of spec 030, and the zone's level in .github/shipmill.toml [decisions] (defaults and floors in spec 030) says what the agent does: act (decide), notify (decide, post a decided marker and the decided label, keep working; a trusted veto within veto_hours, default 24, reverts it or opens a follow-up), ask (the needs-decision protocol), never (prepare the change and hand it to the maintainer, who takes the step by hand even after a yes in chat). direction defaults to never with floor ask; decision-policy is fixed at never; scope, rule-departure, and unknown never go below ask; security never below notify. Levels are read from the base branch, never from the pull request. A notify pull request merges without waiting for its window. [autonomy] stays as it is and is shown mapped beside the zones. A rule an agent sets at notify is recorded as a D-n with a Zone line, which a veto supersedes
- Why: Decision rights were scattered over [autonomy], the needs-decision protocol, the design and spec gates, pr_gate's D-34 check, and the hooks, so agents asked whenever unsure: on 2026-10-18 the maintainer settled nine questions, all by taking the agent's recommendation. Reversibility sets the level: one-way doors stay the maintainer's (N-3), two-way doors are decided and reported, and the retro's veto counts move a zone's level, always by the maintainer's edit
- Applies to: src/shipmill/policy.py, src/shipmill/decide.py, src/shipmill/app_gh.py, skills/github-pr-triage/scripts/pr_gate.py, skills/github-issue-triage/references/needs-decision.md, skills/github-issue-triage/scripts/triage_state.py, skills/github-ship-watch/scripts/watch_state.py, skills/github-ship-watch/scripts/retro.py, [decisions], decided label
- Enforced by: review, until spec 030 is built

## D-49: A spec pull request is approved by the maintainer's merge or by a trusted answer that takes every recommendation

- Decided: 2026-10-25, in shipmill/shipmill#547
- Rule: A spec pull request is approved either by the maintainer's merge or by a trusted answer to its needs-decision question that takes every recommendation unchanged, read by the reply rules needs-decision already uses: a comment by an OWNER, MEMBER, or COLLABORATOR other than the App, or a relayed `Decision by @<login>` naming the maintainer. After such an answer github-pr-triage rebases the spec pull request, renumbering a `D-n` it claims when needed, and lands it once it is mergeable and every check is green; the maintainer may still merge by hand. An answer that changes a recommendation revises the spec in the pull request and asks again. A pull request that edits `docs/product.md` stays merged by the maintainer only (D-34). This refines D-5: a spec still merges before its build starts, and an accepting answer is now enough to merge it
- Why: The answer already records the approval on GitHub, where anyone can read it; a second, mechanical merge only delays the build: #487 waited five days after its answer for the maintainer's merge
- Applies to: skills/github-issue-triage/references/spec-gate.md, skills/github-issue-triage/references/needs-decision.md, skills/github-issue-triage/references/comments.md, skills/github-pr-triage/SKILL.md, docs/specs
- Enforced by: review, and an eval case under evals/ once #547 is built

## D-50: A release publishes before it moves its references

- Decided: 2026-10-25, in shipmill/shipmill#598
- Rule: As D-44, save when the marketplace entry's ref moves: a release publishes before it moves its references. `land` pushes the tag, dispatches publish.yml, waits for that run to succeed and for PyPI to serve the version, and only then dispatches move-major-tag.yml; the marketplace entry's ref is no longer written in the release commit but moves to the release tag in that same step, after publish. So @v0, the marketplace ref, and every comparison that reads it only ever name a version PyPI serves, and a publish that fails leaves @v0 and the ref on the previous release. Everything else in D-44 holds: a gate session loads the install of shipmill@shipmill that applies to its checkout, with no --plugin-dir, no shipmill-owned cache, and no change to enabledPlugins, and never updates an install; skills, their scripts, and the plugin's hooks run the CLI as `uvx shipmill==<version>`, the version in .claude-plugin/plugin.json; .github/shipmill.toml may set `requires`; doctor, status, and the tick report lagging installs, a gate checkout's unused install, the gate's own lagging CLI, and an unmet requires, each with its fix, plus one desktop notification per release under notify = true; the one plugin check that holds a session is PyPI answering 404 for the version sessions load; [agents] plugin_update is deprecated for one minor release and ignored, then refused (spec 031)
- Why: On 2026-10-24 v0.66.0 was tagged at 17:13:45 and served by PyPI at 17:18:16, and a session that loaded the plugin in that window ran `uvx shipmill==0.66.0` against a PyPI without it; #597 made the window survivable, and this closes it. Moving its own references is the one delivery shipmill performs itself (D-31), so it is shipmill's to order after the publish it depends on
- Applies to: src/shipmill/land.py, .github/workflows/land.yml, .github/workflows/move-major-tag.yml, .github/workflows/publish.yml, .claude-plugin/marketplace.json, src/shipmill/operate.py, [environments], move-major-tag.yml, src/shipmill/gate.py, src/shipmill/plugin.py, src/shipmill/agents.py, src/shipmill/doctor.py, src/shipmill/status.py, src/shipmill/policy.py, src/shipmill/launchd.py, src/shipmill/init.py, src/shipmill/upgrades.py, src/shipmill/__init__.py, .claude-plugin/plugin.json, .github/shipmill.toml, hooks/delivery.py, skills/*/SKILL.md, skills/github-ship-watch/scripts/watch_state.py, skills/shipmill-setup/scripts/setup_state.py, skills/github-pr-triage/scripts/shipped.py, [agents] plugin_update, requires, shipmill status
- Enforced by: review, until #598 is built
- Supersedes: D-44

## D-51: Agent stages have [autonomy] levels: triage and fix act, land proposes by default

- Decided: 2026-10-26, in shipmill/shipmill#656
- Rule: [autonomy] in .github/shipmill.toml sets triage, fix, and land, the stages agent sessions run, to observe, propose, or act, with the same error shape as release: any other value, a non-string included, exits 2 naming the key and the levels. An absent key takes its default: triage act, fix act, land propose. An open shipmill-hold issue turns each of them from act into propose and leaves observe and propose as they are, as it does for release, deploy, and rollback. The CI stages (release, deploy, rollback, intake, upgrade) keep their keys, defaults, and hold behaviour unchanged (D-7, D-8, D-10); each stage's level is a ceiling over the zones of [decisions] (D-48)
- Why: How far a gate session goes was set by the free words of [agents] prompt, which nothing checks, while the release side had a checked enum; one model answers 'how far does shipmill go by itself' for the whole pipeline (spec 040). The defaults keep what shipmill-setup recommends today: a verdict and a pull request are reversible, a merge waits for a person
- Applies to: src/shipmill/autonomy.py, [autonomy] triage, [autonomy] fix, [autonomy] land, shipmill-hold label
- Enforced by: tests/test_autonomy.py (S-040-1, S-040-2, S-040-3)

## D-52: A draft pull request belongs to whoever opened it

- Decided: 2026-10-26, in shipmill/shipmill#673
- Rule: A draft pull request belongs to whoever opened it, a person or a session. Agents don't review, push to, rebase, or merge it, whatever their session was started for: github-pr-triage lists it as draft, left to its author, and pr_gate.py refuses it with exit 8 (DRAFT). It enters triage once it is marked ready. A person or session that keeps fixing its own pull request (an auto-fix loop, say) opens it as a draft and marks it ready once CI is green, which hands it to the agents; github-issue-triage hands over only pull requests marked ready
- Why: A pull request needs one owner at a time, and its draft state is the one GitHub already shows. Until now it held only because watch_state.py lists non-draft pull requests in PRS_OPEN, so a draft never started a gate session by itself, but a session started for other work could still review, push to, or merge a draft: on 2026-10-26 a session fixing its own pull request in an auto-fix loop and the gate's reviewer both pushed to one branch
- Applies to: skills/github-pr-triage/SKILL.md, skills/github-pr-triage/references/landing.md, skills/github-pr-triage/scripts/pr_gate.py, skills/github-issue-triage/SKILL.md, skills/github-ship-watch/scripts/watch_state.py, draft pull requests
- Enforced by: tests/test_pr_gate.py (pr_gate.py's exit 8); review for the skills' text

## D-53: A component may read its home's config to check that the home lists it

- Decided: 2026-10-25, in shipmill/shipmill#580
- Rule: As D-46, plus a component repo's session, and its doctor, may read its home repo's .github/shipmill.toml to check the back-link, that the home's [product] repos lists this repo, and nothing else of that file or repo beyond what D-46 and D-47 already allow; it still writes nothing in the home repo. This refines D-46, and the reads of the home repo D-47 allows a component
- Why: A component the home doesn't list can't be found from the home: the coordinator's product token covers only the listed repos (S-038-6), so the home's doctor can't read an unlisted repo's [product] home. The component knows its home, so its own doctor is the one place that can see a missing back-link and name the fix
- Applies to: src/shipmill/doctor.py, [product] home, [product] repos, home repo, docs/specs/038-product-coordinator.md
- Enforced by: review, until #604 is built

## D-54: shipmill writes to GitHub only as the App; without it, shipmill drafts and the person posts

- Decided: 2026-10-25, in shipmill/shipmill#521
- Rule: shipmill writes to GitHub only as the App, a separate identity: its skills and their scripts write only through shipmill gh, never as the person at the keyboard (Q-2 and D-14 stand as they are). In a session where the App isn't available, a skill stops before its first write to GitHub, says the App isn't available here, and gives the person the text it would have written (the comment, the label, the pull request's title and body), ready to post themselves. The App is available to a session when its environment has a non-empty SHIPMILL_APP_KEY, which shipmill gate sets on every session it starts, or when the App's key file ~/.config/shipmill/app-<app_id>.pem exists on the host. A contributor's own writes are theirs: in a repo whose .github/shipmill.toml has an [agents] section, the shipmill plugin's PreToolUse hook refuses, with exit 2 and the command to run instead: a gh write while [agents] app_id is set and the App is available to the session, unless it runs as shipmill gh (an inline GH_TOKEN=$T gh is refused too, since an empty $T falls back to the maintainer's login; shipmill gh is the way to write), a push to the default branch unless [hooks] default_branch = false, a rebase merge, a force push without --force-with-lease=<ref>:<sha>, and a cp, mv, or rsync of a [hooks] private path out of the repo; in a session without the App, app-writes refuses nothing, so a person writes as themselves, by hand or with their own Claude outside shipmill's skills, and the other rules apply as before. Availability is read from the host alone: the variable can only turn the rule on, a command's own NAME=value assignments are never read for it, and nothing in the repo but removing app_id turns it off. The app-writes, rebase-merge, and force-push rules have no switch, and no session can turn a rule off for itself. Only hooks/delivery.py's own refusal exits 2: when the hook can't start the script (uv missing, no Python 3.11 or newer that uv can find or install, the script missing), it exits 1 with one stderr line naming shipmill doctor, and the command runs unchecked. shipmill doctor FAILs on that case, and a headless gate whose hook self-test fails starts no session (specs 026 and 033)
- Why: A contributor whose Claude Code loads the plugin, from the repo's committed settings or their own install, has no App key: the rule refused every plain gh write and pointed at shipmill gh, which exits 2 without the key, so their Claude couldn't open a pull request (#495). The maintainer (@romamo, on #495 and #521) chose that shipmill keeps one identity: text an agent writes always reads as the App's, never as a person's, so a reader can tell the maintainer's word from agent text, and where the App can't write shipmill hands its text to the person rather than post it under their name. What a person writes themselves is theirs, so the hook stops refusing it where the App isn't available. Reading availability from the host, never the repo, keeps a contributor's change from turning the rule off in the maintainer's sessions, and Q-2 still holds in every gate session and in the maintainer's own sessions wherever the key sits at its default path
- Applies to: hooks/hooks.json, hooks/delivery.py, src/shipmill/policy.py, src/shipmill/doctor.py, src/shipmill/gate.py, src/shipmill/app.py, src/shipmill/cli.py, skills/*/SKILL.md, skills/github-pr-triage/references/landing.md, docs/install.md, [hooks], [agents] app_id, shipmill gh, shipmill app-token, SHIPMILL_APP_KEY
- Enforced by: tests/test_delivery_hooks.py and the doctor and gate tests (with the implementing PR); review until spec 033 is built
- Supersedes: D-40

## D-55: shipmill status reports the pipeline; the host's machinery is shipmill factory's

- Decided: 2026-10-26, in shipmill/shipmill#710
- Rule: `shipmill status` reports whether the factory works and what waits on whom, from GitHub, with one `factory` line summing up this host's checks; it never reads worktrees. `shipmill factory` reports the host's machinery for the repo (the gate's launchd job and log, its sessions, the App, the plugin and CLI installs, the local checkout, the worktrees), one line per check. Each factory check runs on its own: one that fails to run prints its error as its line and the rest still run, and in `shipmill status` it makes the verdict STUCK without stopping the report
- Why: The worktree read behind the report-only `WORKTREE_STALE` row overran GitHub's query limit on a host with 137 agent worktrees, and `shipmill status` exited 2 with no verdict and no queue. Host state is local to one machine and reads nothing on a fresh clone, so mixing it into the pipeline report made the report depend on where it ran
- Applies to: src/shipmill/status.py, src/shipmill/factory.py, src/shipmill/cli.py, skills/github-ship-watch/scripts/watch_state.py, skills/github-ship-watch/SKILL.md, skills/shipmill-setup/SKILL.md, shipmill status, shipmill factory, WORKTREE_STALE
- Enforced by: the tests of spec 044 (with the implementing PR)

## D-56: The gate's prune runs after the tick's decision, every prune_hours, and never fails a tick

- Decided: 2026-10-27, in shipmill/shipmill#712
- Rule: shipmill gate prunes landed worktrees once the tick has its decision, whatever it is, after any session it starts, and only when a prune is due: no attempt recorded in the state directory's prune.json, or the last one prune_hours ([agents], default 6, 0 for every tick) or more ago. A prune that fails with a shipmill error prints `prune failed: <first line>` and leaves the tick's decision, launch, and exit code as they would be without it; prune.json records the failure and when the run of failures started, and shipmill factory's prune check reports it as a problem, counted on shipmill status's factory line without changing the verdict. What the prune removes and who owns orphaned worktrees are unchanged (D-24)
- Why: The prune ran first on every tick and its error exited 2, so on 2026-10-26 one GitHub query limit in the judge (#709) stopped every tick for about 11 hours, though decide() reads no worktree; on a host with 137 worktrees it also cost about 57 s and 2,000 git calls on every tick, RUNNING and WAITING ones too. Housekeeping that starts no session can't be what stops the factory, and orphaned worktrees can wait a few hours
- Applies to: src/shipmill/gate.py, src/shipmill/agents.py, src/shipmill/factory.py, src/shipmill/status.py, src/shipmill/cli.py, skills/shipmill-setup/SKILL.md, docs/install.md, docs/specs/002-*, shipmill gate, shipmill factory, [agents] prune_hours, prune.json
- Enforced by: the tests of spec 045 (with the implementing PR)

## D-57: A gate tick checks for change before it reads the state, then walks the work tiers to the first untaken item

- Decided: 2026-10-27, in shipmill/shipmill#753
- Rule: After its hold, busy, and still-working checks, a shipmill gate tick first asks GitHub whether anything changed since the cursor in the state directory's cursor.json: one GraphQL query (issues and pull requests updated since the cursor, the open pull requests' heads, labels, drafts and check rollups, the open incidents, the default head, the newest release) and one read of the release and operate runs; a handed item past retry_hours and a dead last session count as changes too. With no change it reads nothing else. On a change it walks the work tiers in order (1 production, 2 release lane, 3 pull requests to land, 4 decided items and vetoes, 5 upgrades and upstream, 6 the other issues triage owes, 7 direction and plans, 8 notices) and stops at the first item no session was handed within retry_hours; it reads a tier only when every tier above it is empty or already handed, a tier the change check already covers costs no read, and it never reads the whole queue to sort it. The timed sections (BOT_STALLED, UPGRADE_PENDING, UPSTREAM_DUE, DIRECTION_PENDING, PLANS, UNANNOUNCED) run only on a sweep, every [agents] sweep_hours (default 6), and their tiers read the sweep's stored rows; a new release tag runs UNANNOUNCED for that tag. A session is handed that one item, so one stuck item never holds back the next. Trusted-only and waiting items are never items (D-16, S-005-9). shipmill status keeps the full report (D-55)
- Why: Measured on 2026-10-27, each tick ran the whole pipeline report, about 90 s and 93 sequential gh calls, even when nothing had changed, about 35 s of it the per-commit and per-issue UNANNOUNCED reads, to decide from a handful of rows; and a fingerprint over the whole set kept a stuck finding handed out with every new one. The maintainer asked for the gate to take the next item and put it to work, checking the tiers in order rather than reading and sorting everything
- Applies to: src/shipmill/gate.py, src/shipmill/agents.py, src/shipmill/github.py, src/shipmill/cli.py, skills/github-ship-watch/scripts/watch_state.py, skills/github-ship-watch/SKILL.md, skills/shipmill-setup/SKILL.md, docs/install.md, shipmill gate, [agents] sweep_hours, cursor.json, sweep.json, handed.json
- Enforced by: the tests of spec 046 (with the implementing PR)

## D-58: A config that loaded keeps loading; a deprecated key or reading warns and is refused only once nothing uses it

- Decided: 2026-10-28, in shipmill/shipmill#735
- Rule: Retiring a config key or a reading never stops a config that loaded in an earlier release. shipmill accepts the deprecated key, ignores it or reads it as its replacement, and `doctor` warns naming the replacement; a deprecated reading that sets a level (spec 040's reading of `[agents] prompt`) keeps applying while the config sets none of the keys that replace it, with the same warning. A new default applies to a config that sets one of the new keys, never to one that set none, so no repo changes behaviour by upgrading shipmill alone. A key shipmill never knew stays an error, so a typo still fails fast; a deprecated key is not unknown. Refusing a deprecated key or ending a reading takes its own decision, made once the maintainer has checked that no connected repo still relies on it, never on a release count. This supersedes D-32's "the next minor refuses it" for `[roadmap]`, and spec 040's one-minor window for `[agents] prs` and the prompt reading; the keys already refused (`[lanes.stable] min_soak_days`, S-029-9; `[agents] plugin_update`, S-031-22) stay refused
- Why: shipmill/shipmill#761 closed spec 040's window on schedule. Released, it would have made `[agents] prs` exit 2 on every gate tick in each connected repo that still set it, so the gate stopped before doing anything; and once `prs` was deleted, a repo whose prompt said "merge when green" would have stopped merging without an error, since an absent `land` takes `propose`. The `agent-autonomy` upgrade meant to migrate those repos first is opened by a repo's own release workflow, so it had reached two connected repos of eight, while one user-scope plugin reaches every gate on a host in the same release. Tools that run unattended retire config the same way: accept and warn, migrate in place, and remove only on evidence that nothing uses it
- Applies to: src/shipmill/agents.py, src/shipmill/autonomy.py, src/shipmill/policy.py, src/shipmill/roadmap.py, src/shipmill/doctor.py, src/shipmill/upgrades.py, skills/github-ship-watch/scripts/watch_state.py, docs/release-lanes.md, docs/specs/040-agent-autonomy.md, [agents] prs, [agents] prompt, [roadmap], deprecated config keys
- Enforced by: review, and `tests/test_autonomy_prompt.py` (`test_d58_a_config_from_before_spec_040_keeps_loading_and_landing`)
