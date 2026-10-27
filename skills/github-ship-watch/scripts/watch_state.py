#!/usr/bin/env python3
"""Report what a repo's issue-to-release pipeline still owes: the release bot, the
recent releases, the environments shipmill operate runs, and the issue intake.

Usage: watch_state.py <owner/repo> [--repo-dir PATH] [--releases N] [--grace MIN]
                      [--tool SPEC] [--incident-label LABEL] [--json]
                      [--bot-login LOGIN] [--trusted-only]
                      [--role NAME=FILLER[,FILLER...] ...]

Release bot (a repo with .github/shipmill.toml). "The default branch" in this help is the branch
releases land on: the config's top-level branch, else GitHub's default branch (#694); it is the
one branch fetched, and every read at origin/<branch> reads it.
  BOT_FAILED      the bot's latest finished run failed (cancelled runs are ignored:
                  a newer push cancels the settle wait on purpose)
  BOT_STALLED     a shipmill bot in release mode has a release due now, no run of
                  its workflow is queued or running, and none started in --grace minutes
  BOT_PLAN_FAILED a shipmill bot's `shipmill plan --event schedule --dry-run` on the default
                  branch failed with its own `shipmill: ` error (a CHANGELOG it refuses, say;
                  any other failure, such as uvx's, still exits 2): that error line, and the
                  plan to run in the checkout to see it. The watch reads the plan as no release
                  due and reads the rest; the release workflow's own plan stops at the same error
  BOT_OK          none of these; BOT_NONE when the repo has no bot (it releases by "tag X")
  WORK_BRANCH_STALE  for a shipmill bot: a shipmill/v* work branch on origin while no run of
                  the workflow is unfinished (asked by status, however old), so no run owns it: a
                  run cancelled before its cleanup job left it, and each later run stops
                  at it unless its prepare job may list the runs (actions: read)
  WORKTREE_STALE  for a shipmill bot: a worktree `shipmill worktrees` keeps, under
                  .claude/worktrees/ or tmp/wt-*, created over 7 days ago, with why it is
                  kept (reported, never an action: a person finishes, pushes, or removes
                  the work; the main checkout, the --repo-dir checkout, and worktrees that
                  aren't shipmill's are never reported)

Milestones (spec 022; for a shipmill bot whose config has a lane with milestone = true, from
`uvx shipmill==<version> --repo <repo-dir> milestones --json`, never run without one):
  MILESTONE_WAITING   a goal's milestone with no open issues whose specs aren't built or
                  shipped, with what holds it (reported, never an action: the build work is
                  the factory's)
  MILESTONE_OVERTAKEN an open milestone with open issues whose version a stable tag already
                  took: the version the lane cuts next, and the fix, the rename to it
                  through `shipmill gh api -X PATCH` (an action, never an agent's by itself)
  A milestones read the planner failed is a warning on stderr with no row; a failing
  `shipmill milestones`, or JSON it can't read, stops the watch (exit 2)

Each of the --releases newest version tags (default 3):
  NOT_PUBLISHED   the package is on PyPI but this version isn't, --grace minutes after
                  the tag
  PUBLISHING      the same, inside --grace
  PREDATES_PUBLISH  the same, for a tag created before the package's first upload to
                  PyPI (the earliest file of any release): cut before the repo published,
                  so nothing to repair (reported, never an action)
  PUBLISHED       PyPI lists it; NO_REGISTRY when the package isn't on PyPI at all
  UNANNOUNCED     closed issues it fixed that have no notice for the tag's stage,
                  pre-release or stable (github-pr-triage's shipped.py, in plan mode)

The requester's answer (spec 021), for each closed issue that a published pre-release tag
among those has told (read on its newest comment with the `<!-- shipmill:available:
pre-release <tag> -->` marker, the notice); the
requester is the issue's author, compared by login exactly, and an issue a bot or a deleted
account opened has none. Both are reported, never an action by itself: no label, hold, or
reopen follows from either (D-16):
  REQUESTER_CONFIRMED  the requester reacted 👍 to the notice: the issue, the tag, when, and
                  the notice's link. A 👍 by anyone else gives no row
  REQUESTER_REPORT  the requester commented after the notice (a shipmill notice is no
                  comment of theirs), or reacted 👎 to it: the issue, the tag, and the
                  comment's or the notice's link, for triage to read as a possible regression
  The notice's reactions are read (one more gh call) only when it has a 👍 or 👎 at all

Hold and postmortems (a repo with a shipmill config):
  HOLD            an open shipmill-hold issue, with who opened it and when (reported, never
                  an action by itself: a person stopped the factory on purpose)
  POSTMORTEM_DUE  an issue labelled [operate] incident_label (default "incident") closed as
                  completed (not as not planned or a duplicate) that no docs/postmortems/*.md
                  on the default branch names in an "Incident: owner/repo#N" line (or the
                  issue's URL, or "#N" for the repo itself), read through the GitHub
                  contents API, not the checkout

Config upgrades (a repo with a shipmill config; spec 014's shipmill-upgrade issues, each
with the `<!-- shipmill-upgrade: <id> <version> -->` marker on its first line):
  UPGRADE_PENDING an open upgrade issue an agent session takes up now, as #N with the
                  upgrade's id and what the session does: ask the maintainer (the
                  [autonomy] upgrade default, propose, and act under an open shipmill-hold),
                  open the pull request (act), take up a trusted reply to its question, or
                  close it as not planned when a pull request from the repo's own
                  shipmill/upgrade-<id> branch closed unmerged. None under observe, nor for an
                  issue labelled shipmill-upgrade-later ("not now") or with an open pull request
                  closing it. One labelled needs-decision whose question has no trusted reply
                  is in NEEDS_DECISION instead. Upgrade issues are never in ISSUES or
                  ISSUES_OPEN. With --trusted-only, one the release workflow opened as the
                  Bot github-actions[bot], with both the label and the marker, reads as above
                  (D-30); one triage_state.py reads as UNTRUSTED (opened by neither an OWNER,
                  MEMBER, or COLLABORATOR, the --bot-login, nor so by the release workflow)
                  stays in UNTRUSTED and nothing else (D-16)

The direction (spec 034; only for a config with an [agents] table, which nothing reads
without): `git cat-file -e origin/<branch>:docs/product.md` after the fetch of the default
branch, and when it is there `shipmill --repo <repo-dir> product check --ref origin/<branch>`;
any other failure of either stops the watch (exit 2). The direction issues (labelled
shipmill-direction, open and closed, one REST read) are read only while the file is absent,
and the pull requests from shipmill/direction only while one is open:
  DIRECTION_MISSING  subject docs/product.md: the file is absent, or product check refuses it
                  (its first problem). The fix names where the question stands: the open
                  direction issue's URL, the open shipmill/direction pull request's (the repo's
                  own, never a fork's), with neither the github-ship-watch skill, and for a
                  refused file `shipmill product check`. An action (exit 1), never an
                  agent's: the answer is the maintainer's (D-34)
  DIRECTION_PENDING  while the file is absent, what a session does: open the direction
                  question (no direction issue at all), or on the oldest open one, #N: ask the
                  maintainer (no needs-decision label), take up the answer (labelled, a trusted
                  reply after its question), or close it as not planned (a pull request from
                  the repo's own shipmill/direction closed unmerged since it was opened or
                  last reopened, read from its events only then). None while its question
                  waits (it is in NEEDS_DECISION), while a shipmill/direction pull request is
                  open, or for a refused file. An agent's row
  A direction issue closed for any reason, with none open and no file, is a decline: no row,
  and TRIAGE_MODE adds "no direction: declined in #N"

Operations (only when the config declares environments; read from the
deployments and issues shipmill operate writes):
  OPERATE_FAILED  the latest finished run of the workflow that calls shipmill's operate.yml
                  failed (cancelled runs are ignored)
  UNHEALTHY       an environment's newest "shipmill health" deployment status is a failure
  PROMOTION_DUE   an open "Ready to promote" proposal issue, with its approve command; or a
                  `from` environment operate would promote (act) or propose promoting
                  (propose, or the hold) now if it ran: its source baked a release
                  (bake_minutes since its success, or since the first health status after
                  a failed check), it is behind that release and never tried it, and
                  deploy.<name> autonomy isn't observe; yet no operate workflow runs on a
                  schedule (no caller, no schedule in it, or no run in the last hour).
                  Unlike operate, it doesn't look for a deploy run started on the tag that
                  hasn't made its deployment yet, so a hand-started deploy can read as due
                  for those few minutes
  INCIDENT_OPEN   an open issue labelled [operate] incident_label (default "incident"),
                  with its age and the pull requests linked to close it
  UNANNOUNCED     per environment, the closed issues its current deployment (the newest that
                  reached success; a failed or unfinished one never counts) of a release tag
                  fixed that have no notice of the environment, as "<tag> #N ... deployed to
                  <environment> (since <prev>)": prev is the release tag of the newest
                  earlier successful deployment there, else the release tag below the
                  current one (github-pr-triage's shipped.py --environment, in plan mode;
                  S-021-4)

Intake (github-issue-triage's triage_state.py):
  ISSUES          issues needing triage action, counted by state
  ISSUES_OPEN     the other open issues, by state: in progress, blocked, triaged, or
                  postponed, less the ones NEEDS_DECISION and UNTRUSTED list (reported,
                  never an action by itself). A person's item waiting on its assignees
                  (WITH_PERSON, spec 017) names them, then its roles' teams (spec 036),
                  which may stand alone: WITH_PERSON #N (@login ... @org/team ...). An
                  upstream report, which waits outside (spec 038), is listed here only, as
                  UPSTREAM #N: never in ISSUES, NEEDS_DECISION, or an agent row. With
                  [agents], an open direction issue (spec 034: labelled shipmill-direction,
                  <!-- shipmill-direction --> as its body's first line, opened by an OWNER,
                  MEMBER, or COLLABORATOR or the --bot-login, which triage_state.py marks
                  "direction": true on its line) is in neither ISSUES nor ISSUES_OPEN
  PRS_OPEN        open non-draft pull requests (reported, never an action by itself),
                  less the ones NEEDS_DECISION and UNTRUSTED list. Its fix follows the
                  config's [autonomy] land as shipmill reads it (spec 040: default propose;
                  with none of triage, fix, and land set, act when the [agents] prompt says
                  "merge when green" or "land"; an open shipmill-hold issue turns act into
                  propose): none under act, a person merges the ones labelled shipmill-ready
                  under propose, [autonomy] land named under observe, and adding [agents]
                  without one
  NEEDS_DECISION  issues and pull requests labelled needs-decision whose question has no
                  reply, as #N only (triage_state.py's rule, applied to pull requests'
                  comments too): a person owes the answer, so an action, but never an
                  agent's
  VETOED          issues and pull requests, open, closed, or merged, whose decision taken at
                  notify (spec 030, labelled decided) holds an unanswered trusted veto, as #N
                  only: the issues triage_state.py reads as VETOED (a closed one's line says
                  "closed": true), the open pull requests labelled decided (their comments read
                  only then, by triage_state.py's rule), and the closed and merged ones labelled
                  decided and updated in the last 14 days (one gh pr list; with --trusted-only,
                  never a fork's). An agent's row: the gate starts a session to take the veto up.
                  One in it is in no other row; an item labelled decided without such a veto
                  reads as it would without the label
  UNTRUSTED       with --trusted-only, the issues triage_state.py reads as UNTRUSTED, the
                  open plan issues the --bot-login didn't open (PLANS), and the pull
                  requests whose head is in a fork, as #N only (reported, never an
                  action: an interactive session takes them up, D-16)
  PLANS           goals' plans that need a session (spec 028), from product-intake's
                  `intake_state.py --plans --json` (run in the checkout, with --tool when given, the
                  --bot-login, and [agents] wip as --wip; only when the checkout has
                  docs/product.md): PLAN_DUE with its goals (G-n), PLAN_MALFORMED,
                  PLAN_ANSWERED, and PLAN_ACCEPTED with their plan issues (#N); the session
                  runs product intake. With --trusted-only, an open plan issue the
                  --bot-login didn't open is in none of these and in UNTRUSTED, and in no
                  other row (D-16)
  CHAIN_NO_GATE   an item of a chain one of the repo's open issues belongs to (spec 017,
                  github-issue-triage's chains.py show --trusted-only, run once over the open
                  issues but the ones read as UNTRUSTED or closed, and never reading or
                  following an issue whose author is neither an OWNER, MEMBER, or COLLABORATOR
                  of this repo (in another repo: its owner or collaborator) nor the
                  --bot-login, D-16) that is ready, linked to another item, and in a
                  repo whose .github/shipmill.toml has no [agents] table, or that has none:
                  nothing takes it up, so the chain stalls there. One row per item, naming it
                  and its repo; an action for a person (a gate there, or the item done by
                  hand), never an agent's
  CHAIN_UNREADABLE  the chain walk failed (a gh error, an issue past a page of labels or
                  relations, a config it can't parse): one row naming the item the error
                  names (else the repo) and the error's first line, in place of the
                  CHAIN_NO_GATE rows, while the rest of the watch stands; an action for a
                  person, never an agent's

Upstream reports (spec 038; only in a home repo's checkout, whose config has [product] repos,
from github-issue-triage's `upstream_state.py <repo> --json`, run in the checkout with the
--bot-login; never run without [product] repos, and then none of these rows appear):
  UPSTREAM_DUE    the reports the coordinator acts on, as owner/repo#N by state: ROUTE_DUE
                  (route it to the owning repos), ANSWERED (route it by the maintainer's
                  answer), CLOSE_DUE (every child closed: close it with its summary). An
                  agent's row: the gate starts the coordinator's session for it
  UPSTREAM_ASKED  the reports whose needs-decision question has no reply, as owner/repo#N:
                  the maintainer owes the answer, so an action, never an agent's
  UPSTREAM_UNTRUSTED  the reports whose author is neither an OWNER, MEMBER, or COLLABORATOR
                  of their repo nor the --bot-login, as owner/repo#N (reported, never an
                  action: an interactive session takes them up, D-16)
  UPSTREAM_UNREADABLE  upstream_state.py failed (a gh error, `shipmill gh --product` refusing,
                  a config it refuses): one row with the error's first line, in place of the
                  rows above, while the rest of the watch stands; an action for a person,
                  never an agent's

PyPI's window (#597; the pinned `uvx shipmill==<version>` form only, never --tool's):
  PYPI_WAIT       uv found no shipmill==<version> on PyPI (its "there is no version of" resolution
                  error), even run once more as `uvx --refresh-package shipmill ...`, since a
                  release's tag moves minutes before PyPI serves it and uv caches the index up to
                  10 minutes: one row per version, naming the reads it stands in for (the release
                  plan, worktrees, milestones, the direction, plans, upstream reports; with --trusted-only, a
                  plans read takes the issues and pull requests with it, since its untrusted plan
                  issues aren't known), with the release's publish.yml run as the fix. The rest of
                  the watch stands; reported, never an action by itself, and never an agent's

--bot-login and --trusted-only go through to triage_state.py: the login shipmill's
sessions write as (whose comment is the question, and whose issue is trusted), and the
trust filter of an unattended gate. The config's [product] home (spec 038) goes through
as --home, which words an upstream report's note; a home that isn't owner/name exits 2.
Each --role flag (spec 036: a role's resolved fillers, one per role, maintainer included, as
`shipmill roles --flags` prints them) goes through to triage_state.py as given, so a person's
item reads ASSIGN_DUE (an ISSUES action) rather than NO_ASSIGNEE; flags triage_state.py would
refuse exit 2 before anything is read.

Repository settings:
  BRANCH_DELETE_OFF  delete_branch_on_merge is off: merged pull request branches stay on
                  GitHub, and a stacked pull request isn't retargeted when the one under it
                  merges. A person turns it on (shipmill-setup's setup_state.py --fix does), so
                  an action but never an agent's; no row while it is on

Workflows:
  RUNS_ACTIVE     a queued or running workflow run of any workflow, one row each, with its
                  status, age, event, branch, and link (reported, never an action by itself)

Agents (all reported, never an action by itself):
  TRIAGE_MODE     how far the gate's sessions go: the effective triage, fix, and land levels,
                  each with its source as `shipmill autonomy` reads it (config, default,
                  prompt, or hold), then the rest of [agents], less the prompt and the
                  deprecated prs; "no [agents]" without one
  AGENT_SESSION   a Claude Code session on this host working the repo, one row each, from
                  `claude agents --json`: a gate session (named "shipmill <owner/repo>") or one
                  whose folder is in the checkout, with its kind, status, and age
  LOOP            on a Mac, the launchd job running `shipmill gate` for the repo: its
                  interval, whether it runs now, its last exit code, and its log's last
                  decision; "none" without one. A /loop or a /schedule routine lives in a
                  session or the cloud, where no script reads it
  HOST_UNKNOWN    the agent sessions weren't read: claude isn't on PATH (a cloud session)
  GATE_SESSIONS_DEAD  on a Mac, the gate log's last decision is SESSION_DEAD: its last
                  session ended within 60 s of its launch or on an authentication failure
                  (an interactive one: claude agents lists it failed, or done within 60 s),
                  with how many did so
                  in a row and the session log's last line. A person clears it (`claude auth
                  login`, or reading the session's log or `claude logs <id>`), so an action
                  but never an agent's

Gate setup (the config's [agents] table):
  GATE_NO_APP     an [agents] prompt with no app_id: no GitHub App is connected, so the
                  gate's sessions write as the host's gh login (their PRs, comments, and
                  commits read as the maintainer's, who can't approve them). A person
                  connects one with shipmill-setup's step 3 under The gate (app-create,
                  then app_id in [agents]), so an action but never an agent's (D-19); no
                  row without a prompt or with app_id

shipmill on this host (from `claude plugin list --json` and `claude plugin marketplace list --json`):
  SHIPMILL_VERSION   the latest shipmill release (the ref of the marketplace entry on
                  shipmill/shipmill's default branch, spec 031; an entry without a github
                  source and a vX.Y.Z ref exits 2), the shipmill@shipmill plugin's installs
                  that apply to the repo (user scope, and local or project scope in the
                  checkout or the gate's launchd working directory, each taken as the project
                  Claude Code loads it as: a linked worktree's main checkout), the gate's
                  checkout's own installs (tmp/shipmill-gate, the launchd working directory,
                  or the checkout itself when it is a linked worktree: Claude Code keys an
                  install on each), the install a session in the gate's folder loads
                  ("a session loads <scope> <version> (<project>)": the most specific scope
                  installed for its project, local, project, user, then managed; ", older
                  than <latest>" when it lags, which the gate reports and still starts
                  sessions on, spec 031), and the marketplace's source when it isn't
                  shipmill/shipmill (reported, never an action)
  SHIPMILL_OUTDATED  one row per install of those older than the latest release, with the
                  command that updates it, run in its folder, after `claude plugin
                  marketplace update shipmill` (Claude Code updates from its local copy of
                  the marketplace, which may predate the release). When an install at the same
                  scope is keyed on a folder nested in it (the gate's checkout in the repo),
                  `claude plugin update` picks the nested one (a Claude Code bug), so the
                  fix reinstalls the folder's own instead. An install keyed on a gate
                  checkout that is a linked worktree is a row at any version: no session
                  loads it and no `claude plugin` command reaches it, so the fix deletes its
                  entry in ~/.claude/plugins/installed_plugins.json by hand (#485). One more
                  row, subject "shipmill on PATH" (#583), when the person's CLI differs from
                  the install a session loads: the first `shipmill` on PATH outside the
                  environment running the check (a folder whose shipmill resolves into it, or
                  into a uvx run's environment in uv's cache, is skipped), asked `shipmill
                  --version` with only PATH and HOME and 10 s; older, or exiting non-zero
                  ("predates shipmill --version"), or never answering in time or starting
                  ("doesn't answer shipmill --version"), or exiting 0 with anything but
                  `shipmill X.Y.Z` ("answers shipmill --version with '<its first line>'",
                  #628), its fix is `uv tool upgrade shipmill`, newer the install's update.
                  No row without one on PATH or without an install a session loads. An
                  action for a person, never an agent's
  SKILL_SHADOWED  one row per link or copy of a shipmill skill (a folder name under skills/)
                  in ~/.claude/skills or ~/.agents/skills, a folder with a SKILL.md (a broken
                  link or a plain file loads as nothing), that doesn't resolve into the
                  plugin's cache (~/.claude/plugins/cache/shipmill): a prompt's /<name> loads
                  it, not the plugin's (#236). The fix, removing it or calling the skill as
                  /shipmill:<name>, is a person's in their home folder: an action, never an
                  agent's

A gh read (the watch never writes GitHub) that fails on a server or network error (HTTP 5xx,
a timeout, a reset or refused connection, an unexpected EOF) is run once more after 5
seconds; when that fails too, the watch exits 2 with an error line ending "transient GitHub
API error: rerun". An auth, not-found, or any other failure stops it at once.

--incident-label names the label the repo's incidents carry, in place of the config's
[operate] incident_label (fleet.py passes a fleet file's incident_label this way).

--json prints one JSON object per row: state, subject, detail, and agent, true when the
row needs an agent (BOT_FAILED, BOT_STALLED, WORK_BRANCH_STALE, NOT_PUBLISHED, UNANNOUNCED,
ISSUES, PLANS, OPERATE_FAILED, INCIDENT_OPEN, UPGRADE_PENDING, DIRECTION_PENDING, UPSTREAM_DUE, VETOED): the rows
shipmill gate starts a
session for. A waiting
item is in no agent row, so it neither starts a session nor changes the gate's fingerprint.
Each line has a fix too (spec 011): the one line that clears the row, an exact command where
one exists (every gh naming the repo, every git its checkout with -C), else the decision to
make; null for a row with nothing to clear. Every action row, HOLD, WORKTREE_STALE,
UNTRUSTED, and UPSTREAM_UNTRUSTED carry one, and PRS_OPEN unless [autonomy] land is act with [agents].
A fix is built from the repo, numbers, run ids, tags, paths, and config keys, never from an
issue's or a pull request's text (D-16). The table prints it on an indented "fix:" line
after its row, unless the row's detail already ends with it. The PRS_OPEN line also has
heads, each listed pull request's number (a string) mapped to its head commit's SHA, so a
push to one changes the gate's fingerprint (#546); the table never prints it.

Holds and incidents lead the report. Exit 0 when nothing needs action, 1 when any
BOT_FAILED, BOT_STALLED, BOT_PLAN_FAILED, WORK_BRANCH_STALE, NOT_PUBLISHED, UNANNOUNCED,
ISSUES, PLANS, OPERATE_FAILED, UNHEALTHY, PROMOTION_DUE, INCIDENT_OPEN, POSTMORTEM_DUE,
NEEDS_DECISION, BRANCH_DELETE_OFF, SHIPMILL_OUTDATED, GATE_NO_APP, DIRECTION_MISSING, GATE_SESSIONS_DEAD,
SKILL_SHADOWED, UPGRADE_PENDING, DIRECTION_PENDING, CHAIN_NO_GATE, CHAIN_UNREADABLE, MILESTONE_OVERTAKEN,
UPSTREAM_DUE, UPSTREAM_ASKED, UPSTREAM_UNREADABLE, or VETOED row is present, 2
on bad input or a git, gh, or uvx failure (a failing `shipmill worktrees` or `shipmill
milestones`, or a failing intake_state.py --plans; a `shipmill plan` failing with its own
`shipmill: ` error is the BOT_PLAN_FAILED row instead, and uv finding no pinned version the
PYPI_WAIT row), and on a missing or malformed
.claude-plugin/plugin.json (spec 031).
Needs git, an authenticated gh, and uvx (for a shipmill bot's plan, worktrees, and milestones,
a direction's check and its plans; `shipmill
worktrees` needs claude on PATH too, to see the live sessions). Python 3.10+,
standard library only.

Every shipmill command runs as `uvx shipmill==<version>`, the version in the plugin's own
.claude-plugin/plugin.json three folders above scripts/ (spec 031), or as `uvx --from <tool>
shipmill` with --tool.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: the config is read with regexes instead
    tomllib = None

SKILLS = Path(__file__).resolve().parents[2]
SHIPPED = SKILLS / "github-pr-triage" / "scripts" / "shipped.py"
TRIAGE_STATE = SKILLS / "github-issue-triage" / "scripts" / "triage_state.py"
CHAINS = SKILLS / "github-issue-triage" / "scripts" / "chains.py"
UPSTREAM_STATE = SKILLS / "github-issue-triage" / "scripts" / "upstream_state.py"
INTAKE_STATE = SKILLS / "product-intake" / "scripts" / "intake_state.py"
DIRECTION = Path("docs/product.md")  # the product's direction (spec 024), whose goals a plan serves
# intake_state.py's plan states (spec 028): the ones that make it exit 1, in its order, and the rest
PLAN_ACTION = ("PLAN_DUE", "PLAN_MALFORMED", "PLAN_ANSWERED", "PLAN_ACCEPTED")
PLAN_STATES = frozenset({*PLAN_ACTION, "PLAN_WAITS", "PLAN_OPEN", "PLAN_FILED", "PLAN_DECLINED"})
GOAL_ID = re.compile(r"G-[1-9]\d*")
# triage_state.py's ACTION: the issue states that make it exit 1
TRIAGE_ACTION = {
    "NEW",
    "NEEDS_PR",
    "UNBLOCKED",
    "UNFILLED",
    "MALFORMED_DEPENDS",  # spec 041: a Depends on line outside the strict shape
    "SPEC_REFUSED",
    "REVISIT",
    "DONE_NOT_CLOSED",
    "DECIDED",
    "VETOED",
    "SUSPECT_CLOSE",
    "HANDOFF_DUE",
    "VERIFY_DUE",
    "CHECK_FAILED",  # spec 042: a parent's ## Check failed, file the fix as a child
    "NO_ASSIGNEE",
    "ASSIGN_DUE",  # spec 036: assign a person's item to its roles' users
    "VERIFY_CLOSED",
    "OFF_MILESTONE",
}
VETOED = "VETOED"  # triage_state.py's state and this script's row for an unanswered veto (spec 030)
POLICY = Path(".github/shipmill.toml")
# a GitHub login, as a WITH_PERSON line's assignees name them: the row shows nothing else (D-16)
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\[bot\])?$")
# The plugin's own plugin.json, three folders above scripts/: the repo's root in a checkout,
# the package's folder in the wheel, which force-includes it there (spec 031)
PLUGIN_JSON = Path(__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json"
PLUGIN_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")  # X.Y.Z, matched whole (fullmatch)
# The latest release is the marketplace's: the ref its shipmill entry names on the default branch
MARKETPLACE_FILE = ".claude-plugin/marketplace.json"
RELEASE_REF = re.compile(r"^v\d+\.\d+\.\d+$")
READ_MARKETPLACE = [
    "gh",
    "api",
    "-H",
    "Accept: application/vnd.github.raw+json",
    f"repos/shipmill/shipmill/contents/{MARKETPLACE_FILE}",
]
# an app_id key anywhere in the config, bare or as agents.app_id: only [agents] has one
APP_ID_KEY = re.compile(r"^\s*(?:[\"']?agents[\"']?\s*\.\s*)?[\"']?app_id[\"']?\s*=", re.MULTILINE)


def triage_module() -> ModuleType:
    """triage_state.py itself, for its needs-decision rule: one rule for issues and pull requests"""
    spec = importlib.util.spec_from_file_location("shipmill_triage_state", TRIAGE_STATE)
    if spec is None or spec.loader is None:
        sys.stderr.write(f"error: can't load {TRIAGE_STATE}\n")
        raise SystemExit(2)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRIAGE = triage_module()
GATE_SESSION = "shipmill "  # shipmill gate names its sessions "shipmill <owner/repo> ..."
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
SHIPMILL_REPO = "shipmill/shipmill"  # where shipmill releases
PLUGIN = "shipmill@shipmill"  # the Claude Code plugin, in its marketplace
# the home folder's user skills: one named like a shipmill skill answers a prompt's /<name>
# in place of the plugin's /shipmill:<name> (#236)
USER_SKILLS = (Path(".claude/skills"), Path(".agents/skills"))
PLUGIN_CACHE = Path(".claude/plugins/cache") / PLUGIN.partition("@")[2]  # the plugin's own copies, by version
GATE_CHECKOUT = Path("tmp/shipmill-gate")  # where shipmill-setup puts the gate's checkout
# the gate log's decision lines: QUIET, LAUNCH, RUNNING, WAITING, UNCHANGED, HELD,
# PYPI_WAIT, HOOKS_FAILED, CLAUDE_AUTH, SESSION_DEAD, or an error
GATE_DECISION = re.compile(r"^(?:[A-Z][A-Z_]*|error): ")
SESSION_DEAD = "SESSION_DEAD: "  # the gate's last session ended dead and it starts another (#500)
AUTH_FIX = "claude auth login"  # shipmill's claude_auth.FIX
# shipmill's claude_token.rejected_fix: a dead session's fix when the gate uses a token file (spec 035)
TOKEN_FIX = re.compile(r"the token in (?P<path>.+) was not accepted; run claude setup-token and save it to (?P=path)")
VERSION_TAG = re.compile(r"^v\d+\.\d+")  # skips moving major tags such as v0
ACTION = {
    "BOT_FAILED",
    "BOT_STALLED",
    "BOT_PLAN_FAILED",
    "WORK_BRANCH_STALE",
    "NOT_PUBLISHED",
    "UNANNOUNCED",
    "ISSUES",
    "PLANS",
    "OPERATE_FAILED",
    "UNHEALTHY",
    "PROMOTION_DUE",
    "INCIDENT_OPEN",
    "POSTMORTEM_DUE",
    "NEEDS_DECISION",
    "BRANCH_DELETE_OFF",
    "SHIPMILL_OUTDATED",
    "GATE_NO_APP",
    "DIRECTION_MISSING",
    "GATE_SESSIONS_DEAD",
    "SKILL_SHADOWED",
    "UPGRADE_PENDING",
    "DIRECTION_PENDING",
    "CHAIN_NO_GATE",
    "CHAIN_UNREADABLE",
    "MILESTONE_OVERTAKEN",
    "UPSTREAM_DUE",
    "UPSTREAM_ASKED",
    "UPSTREAM_UNREADABLE",
    VETOED,
}
# the states whose row needs an agent: --json marks each row's "agent" from this, and
# shipmill gate starts a session on those rows (SKILL.md's repair table says what it does)
AGENT = {
    "BOT_FAILED",
    "BOT_STALLED",
    "WORK_BRANCH_STALE",
    "NOT_PUBLISHED",
    "UNANNOUNCED",
    "ISSUES",
    VETOED,
    "PLANS",
    "OPERATE_FAILED",
    "INCIDENT_OPEN",
    "UPGRADE_PENDING",
    "DIRECTION_PENDING",
    "UPSTREAM_DUE",
}
# the states whose every row carries a fix, the one line that clears it (spec 011): every
# action, and the report-only rows a person still has to act on. PRS_OPEN carries one unless
# a gate lands pull requests ([autonomy] land act, land_fix); every other state's fix is None
FIXED = ACTION | {"HOLD", "WORKTREE_STALE", "UNTRUSTED", "UPSTREAM_UNTRUSTED", "PYPI_WAIT"}
FIX_INDENT = " " * 15  # the table's fix line starts under the subject column
RUN_ID = re.compile(r"/actions/runs/(\d+)(?:/|$)")  # a workflow run's URL names its id
HEAD_SHA = re.compile(r"[0-9a-f]{40}")  # a pull request's headRefOid (#546)
STALE = dt.timedelta(days=7)  # a kept shipmill worktree older than this is reported
# the reasons `shipmill worktrees` keeps a worktree that isn't a shipmill worktree at all
NOT_SHIPMILL = {"main checkout", "current checkout", "not a shipmill worktree"}
LEAD = ("INCIDENT_OPEN", "HOLD")  # the report starts with these, in this order
# the statuses of a run that hasn't finished: shipmill's github.ACTIVE_STATUSES, in its order
UNFINISHED = ("queued", "in_progress", "waiting", "pending", "requested")
ACTIVE = set(UNFINISHED)
# a release's work branch: shipmill's land.WORK_PREFIX and a version tag
WORK_BRANCH = re.compile(r"^refs/heads/(shipmill/v\d+\.\d+\S*)$")
HOLD_LABEL = "shipmill-hold"  # shipmill's autonomy.HOLD_LABEL
READY_LABEL = "shipmill-ready"  # shipmill's status.READY_LABEL: a pull request a person may merge
INCIDENT_LABEL = "incident"  # the default of [operate] incident_label
HEALTH_PREFIX = "shipmill health"  # starts the description of every status shipmill operate writes
OPERATE_SILENT = dt.timedelta(hours=1)  # a scheduled operate runs every 10 minutes
AUTONOMY = ("observe", "propose", "act")
RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?(?:\.dev(\d+))?")  # shipmill's version.PATTERN
PRE_RANK = {"a": 1, "b": 2, "rc": 3}
POSTMORTEMS = "docs/postmortems"  # one file per incident, named in an "Incident: owner/repo#N" line
# "Incident: owner/repo#N", the issue's URL, or "#N" for the repo itself; one per line
POSTMORTEM_NAMES = re.compile(
    r"^Incident:[ \t]*(?:https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)|([\w.-]+/[\w.-]+)?#(\d+))[ \t]*$",
    re.MULTILINE,
)
POSTMORTEM_REASONS = {None, "", "COMPLETED"}  # closed as done; "" or None on issues closed before GitHub kept a reason
ISSUE_LIMIT = 1000  # per label or search; no repo has that many holds, incidents, or proposals
PROPOSAL_LABEL = "shipmill-proposal"  # shipmill's github.PROPOSAL_LABEL
PROPOSAL_SEARCH = 'in:title "Ready to"'  # proposals opened before the label; the marker in the body decides
PROPOSAL = re.compile(r"<!-- shipmill:propose deploy=(?P<env>\S+) -->")  # shipmill's operate.deploy_marker
PROPOSED_TAG = re.compile(r"<!-- shipmill:tag=(?P<tag>\S+) -->")
# a notice's first line: shipped.py's MARKER (spec 021; tests/test_ship_watch.py keeps the two equal)
AVAILABLE = re.compile(r"^<!-- shipmill:available: (\S+) (\S+) -->\s*$")
COMMENT_ID = re.compile(r"#issuecomment-(\d+)$")  # an issue comment's URL names its id
GHOST = "ghost"  # the login GitHub shows for every deleted account
ENV_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # shipmill's environments._NAME
# a gh read that fails on one of these on its stderr is run once more (S-011-11): a server
# error, a timeout, a reset or refused connection, or a cut-off response. shipmill's
# status.GH_TRANSIENT is the same pattern (tests/test_ship_watch.py keeps the two equal)
GH_TRANSIENT = re.compile(
    r"\bHTTP 5\d\d\b|\btime(?:d )?out\b|deadline exceeded|connection (?:reset|refused)|unexpected EOF",
    re.IGNORECASE,
)
GH_CLIENT_ERROR = re.compile(r"\bHTTP 4\d\d\b")  # auth, not found, a bad query: never retried
GH_FIELDS = ("-f", "-F", "--field", "--raw-field", "--input")  # make gh api POST unless -X says otherwise
GH_PAUSE = 5.0  # seconds before the one rerun
GH_RERUN = "transient GitHub API error: rerun"  # ends the error line when the rerun failed too
# uv's resolution error for a pinned shipmill its index doesn't list: PyPI doesn't serve the
# release yet, or uv's cached index (kept up to 10 minutes) predates the upload (#597). Read
# with the stderr's whitespace collapsed, since uv wraps it; any other failure never matches
NO_VERSION = re.compile(
    r"No solution found when resolving tool dependencies: \S+ Because there is no version of"
    r" shipmill==(\d+\.\d+\.\d+) and you require shipmill==\1, we can conclude that your requirements"
    r" are unsatisfiable"
)
PINNED = re.compile(r"shipmill==(\d+\.\d+\.\d+)")  # the second word of the pinned uvx form, whole
# a config upgrade's issue (spec 014): triage_state.py's label and first-line marker, one
# definition for the watch and for the trust filter that lets the release workflow's in (D-30)
UPGRADE_LABEL: str = TRIAGE.UPGRADE_LABEL
UPGRADE_LATER_LABEL = "shipmill-upgrade-later"  # shipmill's github.UPGRADE_LATER_LABEL: answered "not now"
UPGRADE_BRANCH = "shipmill/upgrade-"  # an upgrade pull request's head: this and the upgrade's id
# shipmill's question for a missing direction (spec 034): triage_state.py's label, marker, and
# rule (direction_issue), one definition for the watch and for triage
DIRECTION_LABEL: str = TRIAGE.DIRECTION_LABEL
DIRECTION_BRANCH = "shipmill/direction"  # the head of the pull request adding docs/product.md
# a refused direction is the maintainer's to repair (D-34): the fix names the check, nothing else
DIRECTION_REPAIR = f"fix {DIRECTION.as_posix()}, then run shipmill product check"
# git cat-file -e's error for a path its ref lacks (LC_ALL=C); any other failure is a failure
GIT_ABSENT = re.compile(r"^fatal: path '[^']*' (?:does not exist|exists on disk, but not) in '")
OPERATE_USES = re.compile(
    r"^\s*(?:-\s*)?uses:\s*[\"']?(?:[\w.-]+/[\w.-]+/\.github/workflows/operate\.ya?ml@|\./\.github/workflows/operate\.ya?ml)",
    re.MULTILINE,
)


class Refused(SystemExit):
    """Bad input: the message goes to stderr, and the watch exits 2"""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class Row:
    """One finding. fix is the one line that clears it, built from trusted values only (the
    repo, numbers, run ids, tags, paths, config keys), never an issue's or a pull request's
    text (D-16); a FIXED state without one is a programming error. heads, on a PRS_OPEN row
    only, is each listed pull request's head SHA by number: in --json only, so the gate sees
    a push to one (#546)"""

    state: str
    subject: str
    detail: str
    fix: str | None = None
    heads: tuple[tuple[int, str], ...] = ()

    def __post_init__(self) -> None:
        if self.state in FIXED and not self.fix:
            raise ValueError(f"a {self.state} row needs a fix: {self.subject} {self.detail}")
        if self.heads and self.state != "PRS_OPEN":
            raise ValueError(f"only a PRS_OPEN row has heads, not {self.state}")

    def text(self) -> str:
        line = f"{self.state:<14} {self.subject:<16} {self.detail}"
        if self.fix is None or self.detail.endswith(self.fix):
            return line
        return f"{line}\n{FIX_INDENT}fix: {self.fix}"

    def json(self) -> dict[str, Any]:
        found: dict[str, Any] = {
            "state": self.state,
            "subject": self.subject,
            "detail": self.detail,
            "agent": self.state in AGENT,
            "fix": self.fix,
        }
        if self.heads:
            found["heads"] = {str(number): sha for number, sha in self.heads}
        return found


def plugin_version(path: Path = PLUGIN_JSON) -> str:
    """The version in the plugin's plugin.json, X.Y.Z: the CLI release the plugin pins (spec
    031, D-43). A missing file, one that isn't JSON, or another version is refused, naming it"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"error: {path} is missing: the plugin's version names the shipmill it runs") from None
    except json.JSONDecodeError as exc:
        raise Refused(f"error: {path} is not JSON: {exc}") from None
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or PLUGIN_VERSION.fullmatch(version) is None:
        raise Refused(f"error: {path}: version must be X.Y.Z, got {version!r}")
    return version


def shipmill_cli(tool: str | None = None, path: Path = PLUGIN_JSON) -> list[str]:
    """How a skill script runs the CLI: `uvx shipmill==<the plugin's version>` from PyPI, the
    release the skills were written against (spec 031); `uvx --from <tool> shipmill` when a
    person passes --tool"""
    if tool is not None:
        return ["uvx", "--from", tool, "shipmill"]
    return ["uvx", f"shipmill=={plugin_version(path)}"]


def marketplace_release(text: str) -> str:
    """The latest release's tag: the ref of the marketplace entry named shipmill, from the text
    of shipmill/shipmill's .claude-plugin/marketplace.json. An entry whose source isn't a
    github object with a ref vX.Y.Z is refused, naming the file and the entry (S-031-2)"""
    where = f"{SHIPMILL_REPO}:{MARKETPLACE_FILE}"
    name = PLUGIN.partition("@")[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"error: {where} is not JSON: {exc}") from None
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        raise Refused(f"error: {where} has no plugins list")
    found = [p for p in plugins if isinstance(p, dict) and p.get("name") == name]
    if len(found) != 1:
        raise Refused(f"error: {where} lists the plugin {name!r} {len(found)} times, want exactly 1")
    source = found[0].get("source")
    ref = source.get("ref") if isinstance(source, dict) and source.get("source") == "github" else None
    if not isinstance(ref, str) or not RELEASE_REF.match(ref):
        raise Refused(
            f"error: {where}: the plugins entry {name!r} has source {json.dumps(source)},"
            ' not {"source": "github", "repo": ..., "ref": "vX.Y.Z"}'
        )
    return ref


def rerun_fix(repo: str, url: str) -> str:
    """The rerun of a failed run's failed jobs, the id read from the run's URL"""
    found = RUN_ID.search(url)
    if found is None:
        raise Refused(f"error: {url!r} is not a workflow run's URL")
    return f"gh run rerun {found.group(1)} --failed -R {repo}"


def skill_fix(skill: str, repo: str) -> str:
    return f"/shipmill:{skill} {repo}"


@dataclass(frozen=True)
class Run:
    status: str
    conclusion: str
    created: dt.datetime
    url: str


@dataclass(frozen=True)
class ActiveRun:
    """A workflow run of any workflow, as the RUNS_ACTIVE row shows it"""

    workflow: str
    status: str
    event: str
    branch: str
    created: dt.datetime
    url: str


@dataclass(frozen=True)
class Tag:
    name: str
    created: dt.datetime


def spawn(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    return checked(cmd, retried(cmd, lambda c: spawn(c, cwd, env)))


def capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return retried(cmd, spawn)


def gh_read(cmd: Sequence[str]) -> bool:
    """A gh command that only reads GitHub: a list or view, or a GET through gh api (its
    default unless a field is passed). Only a read is ever run twice"""
    if len(cmd) < 3 or cmd[0] != "gh":
        return False
    if cmd[1] != "api":
        return cmd[2] in {"list", "view"}
    words = list(cmd)
    method = None  # the last -X wins, as gh reads it: "-X POST", "-XPOST", "--method=POST"
    fields = False  # "-f x", "-fx", "--field=x", "--input=x"
    for at, word in enumerate(words):
        if word in ("-X", "--method"):
            method = words[at + 1] if at + 1 < len(words) else ""
        elif word.startswith("--method="):
            method = word.partition("=")[2]
        elif word.startswith("-X"):
            method = word[2:]
        elif word.split("=")[0] in GH_FIELDS or word[:2] in ("-f", "-F"):
            fields = True
    return method.upper() == "GET" if method is not None else not fields


def transient(cmd: Sequence[str], proc: subprocess.CompletedProcess[str]) -> bool:
    """A gh read that failed on a server or network error, never on auth, a missing
    resource, or a bad query (S-011-11)"""
    if proc.returncode == 0 or not gh_read(cmd) or GH_CLIENT_ERROR.search(proc.stderr):
        return False
    return GH_TRANSIENT.search(proc.stderr) is not None


def retried(
    cmd: list[str],
    execute: Callable[[list[str]], subprocess.CompletedProcess[str]],
    pause: Callable[[float], None] = time.sleep,
) -> subprocess.CompletedProcess[str]:
    """The command's result, a gh read that failed on a transient error run once more after
    GH_PAUSE seconds (S-011-11)"""
    proc = execute(cmd)
    if transient(cmd, proc):
        pause(GH_PAUSE)
        proc = execute(cmd)
    return proc


def failure(cmd: Sequence[str], proc: subprocess.CompletedProcess[str]) -> str:
    """A failed command's error for the watch's error line; a transient one, already rerun,
    on one line that ends GH_RERUN"""
    if transient(cmd, proc):
        return f"{' '.join(proc.stderr.split())}; {GH_RERUN}"
    return proc.stderr.strip()


def checked(cmd: list[str], proc: subprocess.CompletedProcess[str]) -> str:
    """The command's output; a failed command stops the watch (exit 2)"""
    if proc.returncode != 0:
        sys.stderr.write(f"error: {' '.join(cmd[:3])}...: {failure(cmd, proc)}\n")
        raise SystemExit(2)
    return proc.stdout


class PypiWait(Exception):
    """The pinned shipmill isn't on PyPI as uv sees it, even with its index refreshed (#597)"""

    def __init__(self, version: str) -> None:
        super().__init__(version)
        self.version = version


def no_version(text: str) -> str | None:
    """The version uv's "no version of shipmill==<v>" resolution error names in text, else None"""
    found = NO_VERSION.search(" ".join(text.split()))
    return found.group(1) if found else None


def unserved(cmd: Sequence[str], proc: subprocess.CompletedProcess[str]) -> str | None:
    """The version when cmd runs the pinned CLI, `uvx shipmill==<v> ...` (never --tool's `uvx
    --from`), and failed on uv's "no version" error for that very version; None otherwise"""
    pinned = PINNED.fullmatch(cmd[1]) if proc.returncode != 0 and len(cmd) > 1 and cmd[0] == "uvx" else None
    if pinned is None or no_version(proc.stderr) != pinned.group(1):
        return None
    return pinned.group(1)


def pinned(
    cmd: list[str], execute: Callable[[list[str]], subprocess.CompletedProcess[str]]
) -> subprocess.CompletedProcess[str]:
    """The pinned CLI's result, run once more as `uvx --refresh-package shipmill ...` when uv
    found no such version, since its cached index may predate the upload (#597)"""
    proc = execute(cmd)
    if unserved(cmd, proc) is None:
        return proc
    return execute([cmd[0], "--refresh-package", "shipmill", *cmd[1:]])


def pinned_run(cmd: list[str], execute: Callable[[list[str]], subprocess.CompletedProcess[str]] = capture) -> str:
    """run for the CLI: its output; PyPI's wait, retried, raises PypiWait; any other failure
    stops the watch (exit 2)"""
    proc = pinned(cmd, execute)
    version = unserved(cmd, proc)
    if version is not None:
        raise PypiWait(version)
    return checked(cmd, proc)


def pypi_wait_row(version: str, what: str) -> Row:
    """PYPI_WAIT: the reads the pinned CLI owed this pass, in place of their rows (#597). Report
    only, never an agent's: the next pass reads them once PyPI serves the release. The fix is
    doctor's and status's for a version PyPI doesn't serve, the release's publish.yml run"""
    tag = f"v{version}"
    fix = (
        f"check the publish.yml run for {tag}: gh run list --repo {SHIPMILL_REPO} --workflow publish.yml;"
        f" if none passed, publish it: gh workflow run publish.yml --repo {SHIPMILL_REPO} -f tag={tag}"
    )
    return Row("PYPI_WAIT", f"shipmill=={version}", f"waits for PyPI; not read: {what}", fix)


def merged_waits(rows: list[Row]) -> list[Row]:
    """The rows with one PYPI_WAIT row per version, where its first stood, naming every read"""
    waits: dict[str, list[str]] = {}
    for row in rows:
        if row.state == "PYPI_WAIT":
            waits.setdefault(row.subject, []).append(row.detail.partition("; not read: ")[2])
    merged = []
    for row in rows:
        if row.state != "PYPI_WAIT":
            merged.append(row)
        elif row.subject in waits:
            merged.append(pypi_wait_row(row.subject.partition("==")[2], ", ".join(waits.pop(row.subject))))
    return merged


def parse_time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


# -- release bot ---------------------------------------------------------------------------


def policy_file(repo_dir: Path) -> Path | None:
    """The release policy shipmill reads, or None without one"""
    return POLICY if (repo_dir / POLICY).is_file() else None


def bot_workflow(repo_dir: Path) -> tuple[str, bool] | None:
    """The bot's workflow file and whether it is a shipmill bot, or None without a bot"""
    policy = policy_file(repo_dir)
    if policy is None:
        return None
    workflows = repo_dir / ".github" / "workflows"
    caller = workflows / "release.yml"
    if caller.is_file() and re.search(r"shipmill|release-lanes|\./\.github/workflows/prepare\.yml", caller.read_text()):
        return "release.yml", True
    if (workflows / "release-bot.yml").is_file():
        return "release-bot.yml", False
    raise Refused(f"error: {policy} exists but neither release.yml nor release-bot.yml calls a bot")


@dataclass(frozen=True)
class Due:
    """A release the shipmill planner would cut now: its reason and the lane it names"""

    reason: str
    lane: str


def failed_run(runs: list[Run]) -> Run | None:
    """The newest finished run, newest first, when it failed; a cancelled run is skipped: a
    newer push cancels the settle wait on purpose"""
    finished = [r for r in runs if r.status == "completed" and r.conclusion != "cancelled"]
    return finished[0] if finished and finished[0].conclusion not in {"success", "skipped"} else None


def bot_rows(
    runs: list[Run], due: Due | None, now: dt.datetime, grace: dt.timedelta, name: str, repo: str
) -> list[Row]:
    """Classify the bot from its recent runs, newest first, and a planned due release"""
    rows = []
    failed = failed_run(runs)
    if failed is not None:
        rows.append(Row("BOT_FAILED", name, f"{failed.conclusion}: {failed.url}", rerun_fix(repo, failed.url)))
    if due is not None:
        active = any(r.status in ACTIVE for r in runs)
        recent = bool(runs) and now - runs[0].created < grace
        if not active and not recent:
            start = f"gh workflow run {name} -R {repo} -f lane={due.lane} -f dry-run=false"
            rows.append(Row("BOT_STALLED", name, f"due and not running: {due.reason}", start))
    return rows or [Row("BOT_OK", name, "")]


def work_branch_rows(branches: dict[str, str], runs: list[Run], workflow: str, repo: str) -> list[Row]:
    """Each work branch on origin (name to commit) while none of the workflow's unfinished
    runs (fetch_unfinished) is queued or in progress: no run owns it, so it stops every
    later run. Its fix is the watch's repair, which checks the owners again before it
    deletes the branch: never a bare delete"""
    if any(r.status in ACTIVE for r in runs):
        return []
    return [
        Row(
            "WORK_BRANCH_STALE",
            name,
            f"at {sha[:12]}, and no run of {workflow} is queued or in progress",
            skill_fix("github-ship-watch", repo),
        )
        for name, sha in sorted(branches.items())
    ]


def work_branches(repo_dir: Path) -> dict[str, str]:
    """The shipmill/v* work branches on origin, asked of origin itself, with their commits"""
    found = {}
    for line in run(["git", "ls-remote", "--heads", "origin"], cwd=repo_dir).splitlines():
        sha, _, ref = line.partition("\t")
        match = WORK_BRANCH.match(ref)
        if match:
            found[match.group(1)] = sha
    return found


def fetch_runs(repo: str, workflow: str) -> list[Run]:
    out = run(
        ["gh", "run", "list", "-R", repo, "-w", workflow, "-L", "10", "--json", "status,conclusion,createdAt,url"]
    )
    return [Run(r["status"], r["conclusion"] or "", parse_time(r["createdAt"]), r["url"]) for r in json.loads(out)]


def fetch_unfinished(
    repo: str, workflow: str, execute: Callable[[list[str]], subprocess.CompletedProcess[str]] = capture
) -> list[Run]:
    """The workflow's runs that haven't finished, newest first, asked of GitHub by status as
    prepare's active_runs does, however many newer runs have finished. A failed query stops
    the watch: it must never read as no owner, which deletes a branch"""
    found = {}
    # in_progress is asked again last: a run approved after the first in_progress query and
    # before the waiting one would otherwise be in neither list
    for status in (*UNFINISHED, "in_progress"):
        cmd = ["gh", "run", "list", "-R", repo, "-w", workflow, "-s", status, "-L", "100"]
        cmd += ["--json", "status,conclusion,createdAt,url"]
        listed = json.loads(checked(cmd, execute(cmd)))
        if not isinstance(listed, list):
            raise Refused(f"error: gh run list -s {status} printed {type(listed).__name__}, not a JSON array")
        for r in listed:
            found[r["url"]] = Run(r["status"], r["conclusion"] or "", parse_time(r["createdAt"]), r["url"])
    return sorted(found.values(), key=lambda r: r.created, reverse=True)


class PlanFailed(Exception):
    """`shipmill plan` itself refused the default branch: its last stderr line, its `shipmill: `
    error"""


Spawn = Callable[[list[str], Path | None, dict[str, str] | None], subprocess.CompletedProcess[str]]


def planned_release(
    repo: str, repo_dir: Path, policy: Path, branch: str, tool: str | None, execute: Spawn = spawn
) -> Due | None:
    """What the shipmill planner would release now on the default branch, or None. The plan's
    own failure (its `shipmill: ` error line) raises PlanFailed (#276); a failed worktree add
    or remove, any other failure (uvx unable to fetch the tool, say), or a plan that prints no
    JSON stops the watch as any failed command does. A pinned shipmill PyPI doesn't serve yet,
    retried with uv's index refreshed, raises PypiWait (#597)"""
    shipmill = shipmill_cli(tool)  # before the worktree: a broken plugin.json leaves none behind
    work = repo_dir / "tmp" / f"ship-watch-{os.getpid()}"
    add = ["git", "worktree", "add", "-q", "--detach", str(work), f"origin/{branch}"]
    checked(add, execute(add, repo_dir, None))
    plan = [*shipmill, "plan", "--event", "schedule", "--dry-run"]
    try:
        env = {**os.environ, "GITHUB_REPOSITORY": repo}
        proc = pinned(plan, lambda cmd: execute(cmd, work, env))
    finally:
        remove = ["git", "worktree", "remove", "--force", str(work)]
        checked(remove, execute(remove, repo_dir, None))
    version = unserved(plan, proc)
    if version is not None:
        raise PypiWait(version)
    if proc.returncode != 0:
        lines = [line.strip() for line in proc.stderr.splitlines() if line.strip()]
        if lines and lines[-1].startswith("shipmill: "):  # the planner's own error, not uvx's
            raise PlanFailed(lines[-1])
    out = checked(shipmill, proc)
    decision = json.loads(out)
    policy_mode = re.search(r'^mode\s*=\s*"(\w[\w-]*)"', (repo_dir / policy).read_text(), re.MULTILINE)
    if decision["action"] != "release" or policy_mode is None or policy_mode.group(1) != "release":
        return None
    lane = decision.get("lane")
    if not isinstance(lane, str) or not lane:
        raise Refused(f"error: shipmill plan decided a release but named no lane: {out[:200]!r}")
    return Due(str(decision["reason"]), lane)


def plan_failed_row(failed: PlanFailed, workflow: str, repo_dir: Path, branch: str, tool: str | None) -> Row:
    """The plan's failure as the bot's row: its error line, and the same plan run in the
    checkout, which shows the error once the checkout is at origin's default branch"""
    checkout = shlex.quote(str(repo_dir))
    plan = f"{shlex.join(shipmill_cli(tool))} --repo {checkout} plan --event schedule --dry-run"
    return Row("BOT_PLAN_FAILED", workflow, f"shipmill plan failed: {failed}", f"on an up-to-date {branch}: {plan}")


def bot_plan(
    repo: str, repo_dir: Path, policy: Path, branch: str, tool: str | None, workflow: str, execute: Spawn = spawn
) -> tuple[Due | None, list[Row]]:
    """The planned release, or the plan's failure as a row read as no release due, so the
    watch goes on to the issues and pull requests (#276); PyPI's wait for the pinned shipmill is
    its PYPI_WAIT row, read the same way (#597)"""
    try:
        return planned_release(repo, repo_dir, policy, branch, tool, execute), []
    except PlanFailed as failed:
        return None, [plan_failed_row(failed, workflow, repo_dir, branch, tool)]
    except PypiWait as wait:
        return None, [pypi_wait_row(wait.version, "the release plan")]


def stale_rows(text: str, main: Path, branch: str) -> list[Row]:
    """`shipmill worktrees --json`'s kept shipmill worktrees created over STALE ago; main is
    the main checkout its paths are relative to, and branch the default branch, for the fix
    that shows the work not landed on it (D-24: the person finishes or removes it)"""
    try:
        report = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"error: shipmill worktrees --json printed no JSON: {exc}") from None
    trees = report.get("worktrees") if isinstance(report, dict) else None
    if not isinstance(trees, list):
        raise Refused(f"error: shipmill worktrees --json printed {text[:200]!r}, not a worktrees list")
    rows = []
    for tree in trees:
        if not isinstance(tree, dict) or not all(isinstance(tree.get(k), str) for k in ("path", "verdict")):
            raise Refused(f"error: shipmill worktrees --json printed a row without a path and verdict: {tree!r}")
        if tree["verdict"] != "KEPT" or tree.get("reason") in NOT_SHIPMILL:
            continue
        reason, age = tree.get("reason"), tree.get("age_hours")
        if not isinstance(reason, str) or not isinstance(age, int) or isinstance(age, bool):
            raise Refused(f"error: shipmill worktrees --json printed a kept row without a reason and age: {tree!r}")
        if dt.timedelta(hours=age) > STALE:
            rows.append(
                Row(
                    "WORKTREE_STALE",
                    tree["path"],
                    f"{reason}; created {age // 24}d ago",
                    stale_fix(main, tree["path"], branch),
                )
            )
    return rows


def stale_fix(main: Path, path: str, branch: str) -> str:
    where = shlex.quote(str(main / path))
    see = f"git -C {where} log origin/{branch}..HEAD"
    remove = f"git -C {shlex.quote(str(main))} worktree remove {where}"
    return f"see the work not landed: {see}; then push it and open a pull request, or remove it: {remove}"


def stale_worktrees(
    repo_dir: Path, tool: str | None, branch: str, execute: Callable[[list[str]], str] = pinned_run
) -> list[Row]:
    """The kept shipmill worktrees of the checkout's repository created over STALE ago; the
    PYPI_WAIT row in their place while PyPI doesn't serve the pinned shipmill (#597)"""
    try:
        out = execute([*shipmill_cli(tool), "--repo", str(repo_dir), "worktrees", "--json"])
    except PypiWait as wait:
        return [pypi_wait_row(wait.version, "worktrees")]
    return stale_rows(out, project_folder(repo_dir), branch)


def milestone_lanes(text: str, policy: Path) -> bool:
    """Whether a lane of the config sets milestone = true (spec 022): only then is `shipmill
    milestones` run. Read as shipmill reads it, with tomllib on 3.11+, the regex fallback on
    3.10; a milestone that isn't a boolean is refused"""
    if tomllib is None:
        return milestone_lanes_310(text, policy)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Refused(f"error: {policy}: {exc}") from None
    lanes = raw.get("lanes", {})
    if not isinstance(lanes, dict):
        raise Refused(f"error: {policy}: lanes is not a table")
    found = False
    for name, table in lanes.items():
        value = table.get("milestone", False) if isinstance(table, dict) else None
        if not isinstance(value, bool):
            raise Refused(f"error: {policy}: lanes.{name} is not a table with a boolean milestone")
        found = found or value
    return found


def milestone_lanes_310(text: str, policy: Path) -> bool:
    """milestone_lanes on Python 3.10: plain [lanes.<name>] tables, each with milestone = true
    or false; any other form of [lanes] is refused rather than misread"""
    unreadable = Refused(
        f"error: {policy}: can't read [lanes] on Python 3.10: use 3.11+ or plain [lanes.<name>] tables"
    )
    tables = toml_tables(text)
    if not blank(tables.get("lanes", "")) or re.search(
        r"^\s*[\"']?lanes[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE
    ):
        raise unreadable
    found = False
    for name, body in tables.items():
        if name.split(".")[0] != "lanes" or len(name.split(".")) != 2:
            continue
        for line in body.splitlines():
            if not re.match(r"^\s*[\"']?milestone[\"']?\s*=", line):
                continue
            value = re.match(r"^\s*[\"']?milestone[\"']?\s*=\s*(true|false)\s*(?:#.*)?$", line)
            if value is None:
                raise unreadable
            found = found or value.group(1) == "true"
    return found


MILESTONE_STATES = ("MILESTONE_WAITING", "MILESTONE_OVERTAKEN")


def milestone_rows(text: str) -> list[Row]:
    """`shipmill milestones --json`'s rows (#475, spec 022): MILESTONE_WAITING, report only,
    and MILESTONE_OVERTAKEN, an action whose fix is the rename. Anything else it prints stops
    the watch (exit 2); a read the planner failed goes to stderr as a warning, with no row,
    since the release's own plan reports its errors as BOT_PLAN_FAILED"""
    try:
        report = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"error: shipmill milestones --json printed no JSON: {exc}") from None
    if not isinstance(report, dict) or not {"milestones", "error"} <= set(report):
        raise Refused(f"error: shipmill milestones --json printed {text[:200]!r}, not milestones and an error")
    found, error = report["milestones"], report["error"]
    if not isinstance(found, list) or not (error is None or isinstance(error, str) and error):
        raise Refused(f"error: shipmill milestones --json printed {text[:200]!r}, not milestones and an error")
    if error is not None and found:
        raise Refused(f"error: shipmill milestones --json printed rows and an error: {text[:200]!r}")
    if error is not None:
        sys.stderr.write(f"warning: shipmill milestones: not read: {' '.join(error.split())}\n")
    rows = []
    for item in found:
        if not isinstance(item, dict) or not milestone_item(item):
            raise Refused(f"error: shipmill milestones --json printed a malformed row: {item!r}")
        rows.append(Row(item["state"], item["milestone"], item["detail"], item["fix"]))
    return rows


def milestone_item(item: dict[str, Any]) -> bool:
    """A well-formed row: a waiting one names no number, version, or fix; an overtaken one its
    milestone's number, the version next, and the rename"""
    texts = all(isinstance(item.get(k), str) and item[k] for k in ("milestone", "detail"))
    if not texts or item.get("state") not in MILESTONE_STATES:
        return False
    if item["state"] == "MILESTONE_WAITING":
        return all(item.get(k) is None for k in ("number", "next", "fix"))
    number = item.get("number")
    numbered = isinstance(number, int) and not isinstance(number, bool) and number > 0
    return numbered and all(isinstance(item.get(k), str) and item[k] for k in ("next", "fix"))


def milestones(
    repo_dir: Path, policy: Path, tool: str | None, execute: Callable[[list[str]], str] = pinned_run
) -> list[Row]:
    """Spec 022's milestone rows of the checkout's repository, from `shipmill milestones`, run
    only when a lane of its config sets milestone = true; none and nothing run otherwise. The
    PYPI_WAIT row stands in their place while PyPI doesn't serve the pinned shipmill (#597)"""
    if not milestone_lanes((repo_dir / policy).read_text(encoding="utf-8"), policy):
        return []
    try:
        out = execute([*shipmill_cli(tool), "--repo", str(repo_dir), "milestones", "--json"])
    except PypiWait as wait:
        return [pypi_wait_row(wait.version, "milestones")]
    return milestone_rows(out)


# -- releases ------------------------------------------------------------------------------


def version_tags(repo_dir: Path) -> list[Tag]:
    out = run(
        [
            "git",
            "for-each-ref",
            "--sort=-creatordate",
            "--format=%(refname:short)%00%(creatordate:iso-strict)",
            "refs/tags",
        ],
        cwd=repo_dir,
    )
    tags = []
    for line in out.splitlines():
        name, _, created = line.partition("\x00")
        if VERSION_TAG.match(name):
            tags.append(Tag(name, parse_time(created)))
    return tags


def package_name(repo_dir: Path) -> str | None:
    pyproject = repo_dir / "pyproject.toml"
    if not pyproject.is_file():
        return None
    project = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", pyproject.read_text(), re.MULTILINE | re.DOTALL)
    name = re.search(r'^name\s*=\s*"([^"]+)"', project.group(1), re.MULTILINE) if project else None
    return name.group(1) if name else None


def pypi_json(path: str) -> Any:
    """PyPI's JSON for a project or a project/version, or None when PyPI hasn't it (404);
    any other failure stops the watch (exit 2)"""
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{path}/json", timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        sys.stderr.write(f"error: PyPI {path}: HTTP {exc.code}\n")
        raise SystemExit(2) from exc
    except urllib.error.URLError as exc:
        sys.stderr.write(f"error: PyPI {path}: {exc.reason}\n")
        raise SystemExit(2) from exc


def on_pypi(path: str) -> bool:
    return pypi_json(path) is not None


def first_upload(project: object, package: str) -> dt.datetime | None:
    """The earliest upload time across every file of every release in a project's PyPI
    JSON; None when PyPI holds no file of it. A malformed answer stops the watch"""
    releases = project.get("releases") if isinstance(project, dict) else None
    if not isinstance(releases, dict):
        raise Refused(f"error: PyPI {package}: the project JSON has no releases table")
    times = []
    for version, files in releases.items():
        if not isinstance(files, list):
            raise Refused(f"error: PyPI {package}: release {version} lists no files")
        for file in files:
            uploaded = file.get("upload_time_iso_8601") if isinstance(file, dict) else None
            if not isinstance(uploaded, str):
                raise Refused(f"error: PyPI {package}: a file of {version} has no upload_time_iso_8601")
            times.append(parse_time(uploaded))
    return min(times) if times else None


def publish_row(
    tag: Tag,
    package: str | None,
    listed: bool | None,
    now: dt.datetime,
    grace: dt.timedelta,
    first: dt.datetime | None = None,
    *,
    repo: str,
    runs_on: Callable[[str], list[Run]],
) -> Row:
    """A version tag against PyPI; first is the package's earliest upload there, and a tag
    created before it was cut before the repo published, so its absence needs no repair.
    runs_on reads the runs on a tag, newest first, only for a NOT_PUBLISHED row's fix"""
    if package is None or listed is None:
        return Row("NO_REGISTRY", tag.name, "")
    if listed:
        return Row("PUBLISHED", tag.name, f"{package} {tag.name[1:]} on PyPI")
    if first is not None and tag.created < first:
        return Row("PREDATES_PUBLISH", tag.name, f"{package} {tag.name[1:]} tagged before the first PyPI upload")
    if now - tag.created < grace:
        return Row("PUBLISHING", tag.name, f"tagged {int((now - tag.created).total_seconds() // 60)} min ago")
    fix = publish_fix(repo, tag.name, runs_on(tag.name))
    return Row("NOT_PUBLISHED", tag.name, f"{package} {tag.name[1:]} missing from PyPI", fix)


def publish_fix(repo: str, tag: str, runs: list[Run]) -> str:
    """The rerun of the newest finished run on the tag when it failed; else where to look"""
    failed = failed_run(runs)
    if failed is not None:
        return rerun_fix(repo, failed.url)
    return f"find the publish run for {tag}: gh run list -R {repo} --branch {tag}"


def fetch_tag_runs(repo: str, tag: str) -> list[Run]:
    """The workflow runs a tag started, newest first"""
    out = run(
        ["gh", "run", "list", "-R", repo, "--branch", tag, "-L", "20", "--json", "status,conclusion,createdAt,url"]
    )
    found = [Run(r["status"], r["conclusion"] or "", parse_time(r["createdAt"]), r["url"]) for r in json.loads(out)]
    return sorted(found, key=lambda r: r.created, reverse=True)


def shipped_plan(
    repo: str,
    repo_dir: Path,
    prev: str,
    tag: str,
    env: dict[str, str] | None = None,
    environment: str | None = None,
) -> tuple[list[str], list[str]]:
    """The issues shipped.py in plan mode would tell, of the release, or with environment, of
    tag's deployment there, and the ones it finds told already; ``env`` is the process
    environment it runs in"""
    cmd = [sys.executable, str(SHIPPED), repo, prev, tag, "--repo-dir", str(repo_dir)]
    out = run(cmd if environment is None else [*cmd, "--environment", environment], env=env)
    # "#N     <WHAT>  <title>  [source]": read by position, so a title never reads as what it does
    lines = [line.split() for line in out.splitlines()]
    return [w[0] for w in lines if w[1:3] == ["WOULD", "POST"]], [w[0] for w in lines if w[1:3] == ["SKIP", "notified"]]


def unannounced(
    repo: str,
    repo_dir: Path,
    prev: str,
    tag: str,
    env: dict[str, str] | None = None,
    environment: str | None = None,
) -> list[str]:
    """The issues shipped.py would tell in plan mode"""
    return shipped_plan(repo, repo_dir, prev, tag, env, environment)[0]


def unannounced_row(repo: str, tag: str, prev: str, issues: list[str]) -> Row:
    """The issues the tag fixed that no notice for its stage tells; the watch posts them"""
    return Row("UNANNOUNCED", tag, f"{' '.join(issues)} (since {prev})", skill_fix("github-ship-watch", repo))


def deployed_row(repo: str, environment: str, tag: str, prev: str, issues: list[str]) -> Row:
    """The issues tag's deployment to the environment fixed that no notice of it tells (S-021-4)"""
    detail = f"{' '.join(issues)} deployed to {environment} (since {prev})"
    return Row("UNANNOUNCED", tag, detail, skill_fix("github-ship-watch", repo))


# -- the requester's answer (spec 021) -----------------------------------------------------


@dataclass(frozen=True)
class Notice:
    """An issue's newest pre-release notice, and what its requester (the issue's author) did
    after it: the comments they wrote, and whether anyone reacted 👍 or 👎 to it at all"""

    number: int
    tag: str
    url: str  # the notice comment's, ending #issuecomment-<id>
    requester: str
    voted: bool  # a 👍 or 👎 by anyone: only then are its reactions read
    after: tuple[str, ...]  # the URLs of the requester's comments after the notice, oldest first


@dataclass(frozen=True)
class Reaction:
    login: str
    content: str  # the REST API's: +1, -1, laugh, ...
    created: dt.datetime


def pre_release(tag: str) -> bool:
    """A dev, a, b, or rc release tag, whose notice asks the requester to answer"""
    key = version_key(tag)
    return key is not None and (key[3] < 4 or key[5] != 2**62)


def pre_release_notice(number: int, view: dict[str, Any]) -> Notice | None:
    """The issue's newest pre-release notice, from `gh issue view --json author,comments`;
    None without one, or when the author is a bot or a deleted account: a requester is a
    person, compared by login exactly (gh names an App author app/<slug>, its comments <slug>)"""
    author = view.get("author") or {}
    login = author.get("login")
    if not isinstance(login, str) or not login or author.get("is_bot") or login == GHOST:
        return None
    comments = view["comments"]
    found = None
    for at, comment in enumerate(comments):
        marker = AVAILABLE.match(comment["body"].partition("\n")[0])
        # anyone can write a marker: one whose tag is no pre-release tag is no notice, so its
        # text never reaches the row (D-16)
        if marker is not None and marker.group(1) == "pre-release" and pre_release(marker.group(2)):
            found = at, marker.group(2)
    if found is None:
        return None
    at, tag = found
    notice = comments[at]
    after = tuple(
        c["url"]
        for c in comments[at + 1 :]
        if (c.get("author") or {}).get("login") == login and AVAILABLE.match(c["body"].partition("\n")[0]) is None
    )
    groups = {g["content"] for g in notice.get("reactionGroups") or [] if g["users"]["totalCount"] > 0}
    return Notice(number, tag, notice["url"], login, bool(groups & {"THUMBS_UP", "THUMBS_DOWN"}), after)


def requester_rows(notice: Notice, reactions: list[Reaction], now: dt.datetime) -> list[Row]:
    """REQUESTER_CONFIRMED when the requester reacted 👍 to the notice (S-021-6); REQUESTER_REPORT
    when they commented after it or reacted 👎 (S-021-7). Anyone else's reaction or comment is
    triage's, as before; both rows are reported only, and nothing follows from them by itself"""
    mine = sorted((r for r in reactions if r.login == notice.requester), key=lambda r: r.created)
    up = [r for r in mine if r.content == "+1"]
    down = [r for r in mine if r.content == "-1"]
    subject = f"#{notice.number}"
    rows = []
    if up:
        detail = f"{notice.tag}: the requester reacted 👍 {ago(now - up[0].created)} ago, {notice.url}"
        rows.append(Row("REQUESTER_CONFIRMED", subject, detail))
    said = []
    if notice.after:
        more = f" (+{len(notice.after) - 1} more)" if len(notice.after) > 1 else ""
        said.append(f"commented after the notice, {notice.after[0]}{more}")
    if down:
        said.append(f"reacted 👎 {ago(now - down[0].created)} ago, {notice.url}")
    if said:
        rows.append(Row("REQUESTER_REPORT", subject, f"{notice.tag}: the requester {'; '.join(said)}"))
    return rows


def fetch_view(repo: str, number: int) -> dict[str, Any]:
    view: dict[str, Any] = json.loads(
        run(["gh", "issue", "view", str(number), "-R", repo, "--json", "author,comments"])
    )
    return view


def fetch_reactions(repo: str, url: str) -> list[Reaction]:
    """The reactions to an issue comment, by its URL, through the REST API"""
    found = COMMENT_ID.search(url)
    if found is None:
        raise Refused(f"error: {url} names no issue comment")
    jq = '.[] | [(.user.login // ""), .content, .created_at]'
    cmd = ["gh", "api", "-X", "GET", "--paginate", f"repos/{repo}/issues/comments/{found.group(1)}/reactions"]
    out = run([*cmd, "--jq", jq])
    return [Reaction(str(r[0]), str(r[1]), parse_time(str(r[2]))) for r in map(json.loads, out.splitlines())]


def answers_rows(
    repo: str,
    numbers: list[int],
    now: dt.datetime,
    view_of: Callable[[int], dict[str, Any]],
    reactions_of: Callable[[str], list[Reaction]],
) -> list[Row]:
    """The requester rows of the issues a pre-release told: each issue read once, and its
    notice's reactions only when someone reacted 👍 or 👎 to it"""
    rows = []
    for number in numbers:
        notice = pre_release_notice(number, view_of(number))
        if notice is not None:
            rows += requester_rows(notice, reactions_of(notice.url) if notice.voted else [], now)
    return rows


# -- holds and operations ------------------------------------------------------------------


@dataclass(frozen=True)
class Environment:
    name: str
    source: str | None  # `from`: promoted from this environment
    bake_minutes: int
    deploy: str = "act"  # [autonomy] deploy.<name>: observe, propose, or act (the default, D-7)


@dataclass(frozen=True)
class Deployment:
    id: int
    ref: str  # a release tag, as shipmill dispatches deploys on the tag
    sha: str
    created: dt.datetime


@dataclass(frozen=True)
class Status:
    id: int
    state: str
    description: str
    created: dt.datetime


@dataclass(frozen=True)
class Current:
    """An environment's newest deployment that reached success, with its statuses oldest first"""

    deployment: Deployment
    statuses: tuple[Status, ...]

    @property
    def tag(self) -> str:
        return self.deployment.ref.removeprefix("refs/tags/")


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    created: dt.datetime
    author: str
    labels: tuple[str, ...]
    closing_prs: tuple[int, ...]  # pull requests linked to close it
    closed: dt.datetime | None = None
    state_reason: str | None = None  # a closed issue's: COMPLETED, NOT_PLANNED, or DUPLICATE


@dataclass(frozen=True)
class Config:
    """What the watch reads from the shipmill config"""

    environments: list[Environment]
    incident_label: str
    upgrade: str = "propose"  # [autonomy] upgrade: observe, propose (the default), or act (spec 014)
    land: str = "propose"  # [autonomy] land, with the legacy reading of [agents] prompt (spec 040)


def ago(span: dt.timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // (24 * 60)} d"


def config(text: str, policy: Path, incident_label: str | None = None) -> Config:
    """The environments, the incident label, and the upgrade and land autonomy of the config, read as
    shipmill reads it: with tomllib on Python 3.11+, with the regex fallback on 3.10. A given
    incident_label (the --incident-label flag) takes the place of the config's, which is still
    checked"""
    if tomllib is None:
        envs, levels = environments_310(text, policy), deploy_autonomy_310(text, policy)
        label, upgrade = incident_label_310(text, policy), upgrade_autonomy_310(text, policy)
        land = land_autonomy_310(text, policy)
    else:
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise Refused(f"error: {policy}: {exc}") from None
        envs, levels = environments_toml(raw, policy), deploy_autonomy_toml(raw, policy)
        label, upgrade = incident_label_toml(raw, policy), upgrade_autonomy_toml(raw, policy)
        land = land_autonomy_toml(raw, policy)
    deployed = [replace(e, deploy=levels.get(e.name, "act")) for e in envs]
    return Config(deployed, incident_label or label, upgrade, land)


# -- requires (spec 031): the oldest shipmill the config is written for, checked against the
# plugin's own version (plugin_version, above) with shipmill's requires.py text, since a
# script can't import shipmill

REQUIRES_KEY = "requires"
REQUIRES_BOUND = re.compile(r">=(\d+)\.(\d+)(?:\.(\d+))?")


def requires_invalid(value: object) -> str:
    return (
        f'{POLICY.as_posix()}: {REQUIRES_KEY} must be ">=X.Y" or ">=X.Y.Z", the oldest shipmill it needs; got {value!r}'
    )


def requires_unmet(bound: str, version: str) -> str:
    return (
        f"{POLICY.as_posix()} requires shipmill {bound}; this is {version}\n"
        "update the plugin: claude plugin marketplace update shipmill"
        " && claude plugin update shipmill@shipmill --scope <scope>\n"
        "or the CLI: uv tool upgrade shipmill"
    )


def requires_value(text: str, policy: Path) -> object:
    """The config's top-level requires, None without one: tomllib on 3.11+, a plain string
    line before the first table on 3.10"""
    if tomllib is None:
        return requires_value_310(text, policy)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Refused(f"error: {policy}: {exc}") from None
    return raw.get(REQUIRES_KEY)


def requires_value_310(text: str, policy: Path) -> str | None:
    """requires on Python 3.10: one plain string line before the first table, or refused"""
    top = toml_tables(text).get("", "")
    lines = [line for line in top.splitlines() if re.match(rf"^\s*[\"']?{REQUIRES_KEY}[\"']?\s*=", line)]
    if not lines:
        return None
    found = re.match(rf"^\s*{REQUIRES_KEY}\s*=\s*(?:\"([^\"]*)\"|'([^']*)')\s*(?:#.*)?$", lines[0])
    if found is None or len(lines) > 1:
        raise Refused(f'error: {policy}: can\'t read {REQUIRES_KEY} on Python 3.10: write it as requires = ">=X.Y"')
    return found.group(1) if found.group(1) is not None else found.group(2)


def landing_branch(text: str | None, policy: Path, default: str) -> str:
    """The branch releases land on, which the fetch, the plan, the worktrees' fix, and every
    read at origin/<branch> use: the config's top-level branch, else default, GitHub's default
    branch, as shipmill's landing checks read it (#694). text is the config, None without one"""
    if text is None:
        return default
    if tomllib is None:
        value: object = landing_branch_310(text, policy)
    else:
        try:
            value = tomllib.loads(text).get("branch")
        except tomllib.TOMLDecodeError as exc:
            raise Refused(f"error: {policy}: {exc}") from None
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise Refused(f"error: {policy}: branch must be a non-empty string, got {value!r}")
    return value


def landing_branch_310(text: str, policy: Path) -> str | None:
    """branch on Python 3.10: one plain string line before the first table, or refused"""
    top = toml_tables(text).get("", "")
    lines = [line for line in top.splitlines() if re.match(r"^\s*[\"']?branch[\"']?\s*=", line)]
    if not lines:
        return None
    found = re.match(r"^\s*branch\s*=\s*(?:\"([^\"]*)\"|'([^']*)')\s*(?:#.*)?$", lines[0])
    if found is None or len(lines) > 1:
        raise Refused(f'error: {policy}: can\'t read branch on Python 3.10: write it as branch = "<name>"')
    return found.group(1) if found.group(1) is not None else found.group(2)


def check_requires(text: str, policy: Path, version: Callable[[], str] = plugin_version) -> None:
    """Refuse a malformed requires, and one the plugin's version doesn't meet, with shipmill's
    words; the version is read only when the config sets one"""
    value = requires_value(text, policy)
    if value is None:
        return
    bound = REQUIRES_BOUND.fullmatch(value) if isinstance(value, str) else None
    if bound is None:
        raise Refused(f"error: {requires_invalid(value)}")
    have = version()
    found = PLUGIN_VERSION.match(have)
    if found is None:
        raise Refused(f"error: not an X.Y.Z version: {have!r}")
    parts = [int(n) for n in bound.groups() if n is not None]
    if tuple(int(n) for n in found.groups()) < tuple(parts + [0] * (3 - len(parts))):
        raise Refused(requires_unmet(">=" + ".".join(str(n) for n in parts), have))


def autonomy_level(value: object, name: str, policy: Path) -> str:
    if not isinstance(value, str) or value not in AUTONOMY:
        raise Refused(f"error: {policy}: [autonomy] deploy.{name} must be one of {list(AUTONOMY)}, got {value!r}")
    return value


def upgrade_level(value: object, policy: Path) -> str:
    if not isinstance(value, str) or value not in AUTONOMY:
        raise Refused(f"error: {policy}: [autonomy] upgrade must be one of {list(AUTONOMY)}, got {value!r}")
    return value


def upgrade_autonomy_toml(raw: dict[str, object], policy: Path) -> str:
    """[autonomy] upgrade of the parsed config, or its default, propose"""
    table = raw.get("autonomy", {})
    if not isinstance(table, dict):
        raise Refused(f"error: {policy}: autonomy is not a table")
    return upgrade_level(table.get("upgrade", "propose"), policy)


def upgrade_autonomy_310(text: str, policy: Path) -> str:
    """[autonomy] upgrade, a plain string key of a plain [autonomy] table, or propose"""
    found = autonomy_string_310(text, policy, "upgrade")
    return upgrade_level("propose" if found is None else found, policy)


def autonomy_string_310(text: str, policy: Path, name: str) -> str | None:
    """[autonomy] <name> on Python 3.10, a plain string key of a plain [autonomy] table, or
    None without it; any other form is refused rather than misread"""
    tables = toml_tables(text)
    if re.search(r"^\s*[\"']?autonomy[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE):
        raise Refused(f"error: {policy}: can't read [autonomy] on Python 3.10: use 3.11+ or a plain [autonomy] table")
    found = None
    for line in tables.get("autonomy", "").splitlines():
        if not re.match(rf"^\s*[\"']?{name}[\"']?\s*=", line):
            continue
        key = re.match(rf"^\s*[\"']?{name}[\"']?\s*=\s*(?:\"([^\"]*)\"|'([^']*)')\s*(?:#.*)?$", line)
        if key is None or found is not None:
            raise Refused(f"error: {policy}: can't read [autonomy] {name} on Python 3.10: use 3.11+")
        found = key.group(1) if key.group(1) is not None else key.group(2)
    return found


# -- [autonomy] triage, fix, and land (spec 040): how far the gate's sessions go, read as
# shipmill's AutonomyPolicy reads them, since a script can't import shipmill

AGENT_STAGES = ("triage", "fix", "land")  # shipmill's autonomy.AGENT_STAGES
# shipmill's AutonomyPolicy defaults (D-51): a pull request waits for a person to merge it
AGENT_DEFAULTS = {"triage": "act", "fix": "act", "land": "propose"}
# the legacy reading's words (S-040-6): shipmill's autonomy._LANDS
LANDS = re.compile(r"\b(?:merge\s+when\s+green|land)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AgentLevel:
    """One agent stage's row of `shipmill autonomy`: its configured level and where that
    comes from, config, default, or prompt (the legacy reading); the hold is applied on read"""

    stage: str
    configured: str
    source: str

    def effective(self, held: bool) -> str:
        return held_level(self.configured, held)

    def record(self, held: bool) -> dict[str, str]:
        """The row as `shipmill autonomy --json` prints it: a stage the hold lowers reads hold"""
        effective = self.effective(held)
        source = "hold" if effective != self.configured else self.source
        return {"stage": self.stage, "configured": self.configured, "effective": effective, "source": source}

    def text(self, held: bool) -> str:
        """`land propose (hold)`: the effective level and its source"""
        row = self.record(held)
        return f"{self.stage} {row['effective']} ({row['source']})"


def agent_level(value: object, stage: str, policy: Path) -> str:
    if not isinstance(value, str) or value not in AUTONOMY:
        raise Refused(f"error: {policy}: [autonomy] {stage} must be one of {list(AUTONOMY)}, got {value!r}")
    return value


def agent_levels(found: dict[str, object], sets_stage: bool, prompt: object, policy: Path) -> tuple[AgentLevel, ...]:
    """The agent stages' levels from the keys [autonomy] sets (found), each checked, the rest at
    their default; and S-040-6, for one minor release: a config that sets none of triage, fix,
    and land reads land as act from an [agents] prompt holding "merge when green" or "land" as a
    word"""
    levels = {
        stage: AgentLevel(stage, agent_level(found[stage], stage, policy), "config")
        if stage in found
        else AgentLevel(stage, AGENT_DEFAULTS[stage], "default")
        for stage in AGENT_STAGES
    }
    if not sets_stage and isinstance(prompt, str) and LANDS.search(prompt) is not None:
        levels["land"] = AgentLevel("land", "act", "prompt")
    return tuple(levels[stage] for stage in AGENT_STAGES)


def agent_levels_toml(raw: dict[str, object], policy: Path) -> tuple[AgentLevel, ...]:
    """[autonomy] triage, fix, and land of the parsed config, with the legacy reading of
    [agents] prompt (S-040-6)"""
    table = raw.get("autonomy", {})
    if not isinstance(table, dict):
        raise Refused(f"error: {policy}: autonomy is not a table")
    found = {stage: table[stage] for stage in AGENT_STAGES if stage in table}
    agents = raw.get("agents")
    prompt = agents.get("prompt") if isinstance(agents, dict) else None
    return agent_levels(found, bool(found), prompt, policy)


def agent_levels_310(text: str, policy: Path) -> tuple[AgentLevel, ...]:
    """[autonomy] triage, fix, and land, each a plain string key of a plain [autonomy] table,
    with the legacy reading of [agents] prompt (S-040-6): a triage, fix, or land key in any
    form ends it"""
    found: dict[str, object] = {}
    for stage in AGENT_STAGES:
        value = autonomy_string_310(text, policy, stage)
        if value is not None:
            found[stage] = value
    stages = "|".join(AGENT_STAGES)
    body = toml_tables(text).get("autonomy", "")
    sets_stage = re.search(rf"^\s*[\"']?(?:{stages})[\"']?\s*[.=]", body, re.MULTILINE) is not None
    table = agents_table_310(text, policy)
    prompt = table.get("prompt") if table is not None else None
    said = json.loads(prompt) if prompt is not None and prompt.startswith('"') else None
    return agent_levels(found, sets_stage, said, policy)


def land_autonomy_toml(raw: dict[str, object], policy: Path) -> str:
    """[autonomy] land of the parsed config, or its default, propose, with the legacy reading
    of [agents] prompt (S-040-6)"""
    return agent_levels_toml(raw, policy)[-1].configured


def land_autonomy_310(text: str, policy: Path) -> str:
    """[autonomy] land on Python 3.10, as agent_levels_310 reads it"""
    return agent_levels_310(text, policy)[-1].configured


def held_level(level: str, held: bool) -> str:
    """The effective level: an open shipmill-hold issue turns act into propose (D-8)"""
    return "propose" if level == "act" and held else level


def held_land(level: str, held: bool) -> str:
    """The effective land level, under the hold as every stage's is"""
    return held_level(level, held)


def deploy_autonomy_toml(raw: dict[str, object], policy: Path) -> dict[str, str]:
    """[autonomy] deploy.<name> of the parsed config, per environment that sets it"""
    table = raw.get("autonomy", {})
    deploy = table.get("deploy", {}) if isinstance(table, dict) else None
    if not isinstance(deploy, dict):
        raise Refused(f"error: {policy}: [autonomy] deploy is a table of environments")
    return {name: autonomy_level(value, name, policy) for name, value in deploy.items()}


def environments_toml(raw: dict[str, object], policy: Path) -> list[Environment]:
    """The [environments] tables of the parsed config, in the order the config declares them"""
    tables = raw.get("environments", {})
    if not isinstance(tables, dict):
        raise Refused(f"error: {policy}: environments is not a table")
    found = []
    for name, table in tables.items():
        if not isinstance(table, dict):
            raise Refused(f"error: {policy}: environments.{name} is not a table")
        source = table.get("from")
        bake = table.get("bake_minutes", 0)
        if not (source is None or isinstance(source, str)) or isinstance(bake, bool) or not isinstance(bake, int):
            raise Refused(f"error: {policy}: environments.{name} has a malformed from or bake_minutes")
        found.append(Environment(name, source or None, bake))
    return found


def incident_label_toml(raw: dict[str, object], policy: Path) -> str:
    """[operate] incident_label of the parsed config, or the default"""
    table = raw.get("operate", {})
    label = table.get("incident_label", INCIDENT_LABEL) if isinstance(table, dict) else None
    if not isinstance(label, str) or not label:
        raise Refused(f"error: {policy}: [operate] incident_label must be a non-empty string")
    return label


# -- the Python 3.10 fallback: no tomllib, so the plain forms are read with regexes, and any
# other form is refused rather than misread


TOML_HEADER = re.compile(r"^\s*(\[\[?)\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$")  # a [table] or [[array]] header
AGENTS_HEADER = re.compile(r"^\s*\[+\s*[\"']?agents\b")  # a line that opens an [agents] header, well formed or not


def toml_tables(text: str) -> dict[str, str]:
    """Each [table] header of a TOML file, its dotted parts unquoted, mapped to its body; the
    keys before the first header are under "". Arrays of tables ([[x]]) are skipped"""
    tables: dict[str, str] = {}
    name: str | None = ""
    body: list[str] = []
    for line in [*text.splitlines(), "[[end]]"]:
        header = TOML_HEADER.match(line)
        if header is None:
            body.append(line)
            continue
        if name is not None:
            tables[name] = "\n".join(body)
        body = []
        parts = [p.strip().strip("\"'") for p in header.group(2).split(".")]
        name = None if header.group(1) == "[[" else ".".join(parts)
    return tables


def toml_string(body: str, key: str) -> str | None:
    found = re.search(rf"^\s*[\"']?{re.escape(key)}[\"']?\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", body, re.MULTILINE)
    return None if found is None else found.group(1) if found.group(1) is not None else found.group(2)


def blank(body: str) -> bool:
    """Only whitespace and comments"""
    return all(not line.strip() or line.strip().startswith("#") for line in body.splitlines())


def environments_310(text: str, policy: Path) -> list[Environment]:
    """The [environments.<name>] tables of the config, in order; an empty list without any"""
    unreadable = Refused(
        f"error: {policy}: can't read [environments] on Python 3.10: use 3.11+ or plain [environments.<name>] tables"
    )
    tables = toml_tables(text)
    if not blank(tables.get("environments", "")) or re.search(
        r"^\s*[\"']?environments[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE
    ):
        raise unreadable
    found = []
    for name, body in tables.items():
        parts = name.split(".")
        if parts[0] != "environments" or len(parts) == 1:
            continue
        if len(parts) != 2:
            raise unreadable
        bake = re.search(r"^\s*[\"']?bake_minutes[\"']?\s*=\s*(\d+)\s*(?:#.*)?$", body, re.MULTILINE)
        if bake is None and re.search(r"^\s*[\"']?bake_minutes[\"']?\s*=", body, re.MULTILINE):
            raise unreadable
        found.append(Environment(parts[1], toml_string(body, "from") or None, int(bake.group(1)) if bake else 0))
    return found


def deploy_autonomy_310(text: str, policy: Path) -> dict[str, str]:
    """[autonomy] deploy.<name>, written as dotted keys in a plain [autonomy] table or as keys
    of a plain [autonomy.deploy] table"""
    unreadable = Refused(
        f"error: {policy}: can't read [autonomy] deploy on Python 3.10: use 3.11+, deploy.<name> keys in a plain"
        " [autonomy] table, or a plain [autonomy.deploy] table"
    )
    tables = toml_tables(text)
    if re.search(r"^\s*[\"']?autonomy[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE):
        raise unreadable
    if any(name.startswith("autonomy.") and name != "autonomy.deploy" for name in tables):
        raise unreadable
    level = r"\s*=\s*(?:\"(?P<level>[^\"]*)\"|'(?P<plain>[^']*)')\s*(?:#.*)?$"
    found: list[tuple[str, str]] = []
    for line in tables.get("autonomy", "").splitlines():
        if not re.match(r"^\s*[\"']?deploy\b", line):
            continue
        key = re.match(rf"^\s*deploy\s*\.\s*[\"']?(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*?)[\"']?{level}", line)
        if key is None:
            raise unreadable
        found.append((key["name"], key["level"] if key["level"] is not None else key["plain"]))
    for line in tables.get("autonomy.deploy", "").splitlines():
        if blank(line):
            continue
        key = re.match(rf"^\s*[\"']?(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*?)[\"']?{level}", line)
        if key is None:
            raise unreadable
        found.append((key["name"], key["level"] if key["level"] is not None else key["plain"]))
    return {name: autonomy_level(value, name, policy) for name, value in found}


def incident_label_310(text: str, policy: Path) -> str:
    """[operate] incident_label, or the default"""
    tables = toml_tables(text)
    if re.search(r"^\s*[\"']?operate[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE):
        raise Refused(f"error: {policy}: can't read [operate] on Python 3.10: use 3.11+ or a plain [operate] table")
    body = tables.get("operate", "")
    label = toml_string(body, "incident_label")
    if label is None and re.search(r"^\s*[\"']?incident_label[\"']?\s*=", body, re.MULTILINE):
        raise Refused(f"error: {policy}: can't read [operate] incident_label on Python 3.10: use 3.11+")
    if label == "":
        raise Refused(f"error: {policy}: [operate] incident_label must be a non-empty string")
    return label or INCIDENT_LABEL


def operate_caller(repo_dir: Path) -> tuple[str, bool] | None:
    """The workflow that calls shipmill's operate.yml and whether it runs on a schedule, or None"""
    workflows = repo_dir / ".github" / "workflows"
    if not workflows.is_dir():
        return None
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        text = path.read_text()
        if OPERATE_USES.search(text):
            return path.name, re.search(r"^\s*schedule:", text, re.MULTILINE) is not None
    return None


def current_deployment(deployments: list[Deployment], statuses_of: Callable[[int], list[Status]]) -> Current | None:
    """The newest of the deployments, newest first, that reached success, as shipmill operate reads it"""
    for deployment in deployments:
        statuses = tuple(statuses_of(deployment.id))
        if any(s.state == "success" for s in statuses):
            return Current(deployment, statuses)
    return None


def deployed_since(
    deployments: list[Deployment], current: Current, statuses_of: Callable[[int], list[Status]], tags: list[str]
) -> str | None:
    """The tag an environment ran before current's, which its notices count from (S-021-4):
    the newest earlier deployment, newest first, of another of the release tags that reached
    success, else the release tag just below current's. None when current's ref is no release
    tag of the checkout, or no tag is below it. A failed or unfinished deployment never counts"""
    key = version_key(current.tag)
    if key is None or current.tag not in tags:
        return None
    for deployment in deployments:
        earlier = deployment.ref.removeprefix("refs/tags/")
        if deployment.id >= current.deployment.id or earlier == current.tag or earlier not in tags:
            continue
        if any(s.state == "success" for s in statuses_of(deployment.id)):
            return earlier
    below = sorted((k, t) for k, t in ((version_key(t), t) for t in tags) if k is not None and k < key)
    return below[-1][1] if below else None


def operate_rows(runs: list[Run], caller: str, repo: str) -> list[Row]:
    failed = failed_run(runs)
    if failed is not None:
        return [Row("OPERATE_FAILED", caller, f"{failed.conclusion}: {failed.url}", rerun_fix(repo, failed.url))]
    return []


def operate_idle(caller: tuple[str, bool] | None, runs: list[Run], now: dt.datetime) -> str | None:
    """Why no shipmill operate runs on a schedule, or None while one does"""
    if caller is None:
        return "no workflow calls shipmill's operate.yml"
    name, scheduled = caller
    if not scheduled:
        return f"{name} has no schedule"
    if not runs:
        return f"{name} has never run"
    if now - runs[0].created >= OPERATE_SILENT:
        return f"{name} last ran {ago(now - runs[0].created)} ago"
    return None


def unhealthy_row(env: str, current: Current | None, now: dt.datetime) -> Row | None:
    ours = [s for s in current.statuses if s.description.startswith(HEALTH_PREFIX)] if current else []
    if current is None or not ours or ours[-1].state != "failure":
        return None
    why = ours[-1].description[len(HEALTH_PREFIX) :].lstrip(": ")
    fix = f"operate rolls {env} back after [operate] rollback_after failures; check its health check if it persists"
    return Row("UNHEALTHY", env, f"{current.tag}: {why}, since {ago(now - ours[-1].created)} ago", fix)


def proposal_issues(labelled: list[Issue], search: Callable[[], list[Issue]]) -> list[Issue]:
    """The open proposals: by their label, and always by the title search too, for one opened
    before the label (shipmill labels each on its next update), one issue once by number"""
    seen = {i.number for i in labelled}
    return labelled + [i for i in search() if i.number not in seen]


def proposal_rows(issues: list[Issue], caller: str, held: bool, repo: str) -> list[Row]:
    """The open proposal issues shipmill operate opens for a deploy that waits on approval;
    the fix is the detail's approve command, naming the repo. The environment comes from the
    issue's body, which anyone can write on an issue the title search finds, so a name no
    environment can have never reaches the fix (D-16)"""
    rows = []
    for issue in issues:
        found = PROPOSAL.search(issue.body)
        if found is None:
            continue
        env = found.group("env")
        tag = PROPOSED_TAG.search(issue.body)
        approve = f"gh workflow run {caller} -f approve={env} -f dry-run=false"
        first = f"close the {HOLD_LABEL} issues, then " if held else ""
        detail = f"#{issue.number} {tag.group('tag') if tag else issue.title}: {first}{approve}"
        if ENV_NAME.fullmatch(env):
            fix = f"{first}gh workflow run {caller} -R {repo} -f approve={env} -f dry-run=false"
        else:
            n = issue.number
            fix = f"check proposal #{n} by hand, it names no environment: gh issue view {n} -R {repo}"
        rows.append(Row("PROMOTION_DUE", env, detail, fix))
    return rows


def version_key(tag: str) -> tuple[int, int, int, int, int, int] | None:
    """A release tag's order, as shipmill's Version sorts it (PEP 440: X.Y.Z.devN < X.Y.ZaN <
    X.Y.ZbN < X.Y.ZrcN < X.Y.Z); None when the tag names no release"""
    found = RELEASE_TAG.fullmatch(tag)
    if found is None:
        return None
    major, minor, patch, pre, pre_n, dev = found.groups()
    if pre is None:
        phase, n = (0, 0) if dev is not None else (4, 0)
    else:
        phase, n = PRE_RANK[pre], int(pre_n)
    return int(major), int(minor), int(patch), phase, n, int(dev) if dev is not None else 2**62


def bake_start(current: Current) -> dt.datetime | None:
    """When the current healthy stretch began, as shipmill operate counts it: from the first
    success, but after a failed health check from the first health status that followed it;
    None while the newest check failed"""
    ours = [s for s in current.statuses if s.description.startswith(HEALTH_PREFIX)]
    failures = [s for s in ours if s.state == "failure"]
    if not failures:
        return min(s.created for s in current.statuses if s.state == "success")
    recovered = [s for s in ours if s.id > failures[-1].id]
    return recovered[0].created if recovered else None


def unpromoted_row(
    env: Environment,
    source: Current | None,
    target: Current | None,
    deployments: list[Deployment],
    idle: str | None,
    held: bool,
    command: str,
    now: dt.datetime,
    fix: str,
) -> Row | None:
    """A `from` environment that operate would promote, or propose promoting, now if it ran:
    its source baked a release, the environment is behind it and never tried it, and its
    deploy autonomy isn't observe. With operate running, its proposal issue or its deploy is
    the signal instead; with it idle, no proposal issue ever opens, so this row stands in.
    command is the detail's way to run operate, and fix the same as one line naming the repo"""
    if env.source is None or idle is None or source is None or env.deploy == "observe":
        return None  # observe never promotes, nor proposes
    wanted = version_key(source.tag)
    if wanted is None:
        return None  # operate promotes only a deployment whose ref names a release tag
    on = version_key(target.tag) if target else None
    if on is not None and on >= wanted:
        return None
    if any(d.ref.removeprefix("refs/tags/") == source.tag for d in deployments):
        return None  # tried there already, in any state: operate deploys a release once
    since = bake_start(source)
    if since is None or now - since < dt.timedelta(minutes=env.bake_minutes):
        return None
    healthy = f"{source.tag} healthy on {env.source} for {ago(now - since)}"
    if env.deploy == "act" and not held:
        would = f"operate would promote {source.tag} to {env.name} ({healthy})"
    else:  # propose, or act under the hold: operate opens a proposal issue
        after = f" after the {HOLD_LABEL} issues close" if held else ""
        approve = f"approve with `shipmill operate --approve {env.name}` once it runs{after}"
        would = f"operate would propose promoting {source.tag} to {env.name} ({approve}; {healthy})"
    return Row("PROMOTION_DUE", env.name, f"{would}, but {idle}; {command}", fix)


def incident_rows(issues: list[Issue], label: str, now: dt.datetime, repo: str) -> list[Row]:
    rows = []
    for issue in issues:
        if label not in issue.labels:
            continue
        prs = " ".join(f"#{n}" for n in issue.closing_prs)
        linked = f"PR {prs} links it" if prs else "no PR links it"
        detail = f"{issue.title}; open {ago(now - issue.created)}, {linked}"
        if issue.closing_prs:
            hotfix = " or ".join(f"{repo}#{n}" for n in issue.closing_prs)
            fix = f"land the hotfix pull request linked to it: {hotfix}"
        else:
            fix = f"{skill_fix('github-issue-resolve', repo)}#{issue.number}"
        rows.append(Row("INCIDENT_OPEN", f"#{issue.number}", detail, fix))
    return rows


def postmortem_named(texts: list[str], repo: str) -> set[int]:
    """The incidents of the repo that the postmortems name, by number"""
    named = set()
    for text in texts:
        for url_repo, url_number, short_repo, number in POSTMORTEM_NAMES.findall(text):
            owner_repo = url_repo or short_repo or repo  # a plain #N is the repo's own
            if owner_repo.lower() == repo.lower():
                named.add(int(url_number or number))
    return named


def postmortem_rows(issues: list[Issue], label: str, texts: list[str], repo: str, now: dt.datetime) -> list[Row]:
    """A closed incident that no postmortem names; an open one isn't due yet, and one closed
    as not planned or as a duplicate was no incident"""
    named = postmortem_named(texts, repo)
    rows = []
    for i in issues:
        if label not in i.labels or i.closed is None or i.state_reason not in POSTMORTEM_REASONS or i.number in named:
            continue
        missing = f"no {POSTMORTEMS}/*.md names it (Incident: {repo}#{i.number})"
        line = f"Incident: {repo}#{i.number}"
        draft = f"{skill_fix('github-ship-watch', repo)} (drafts the postmortem with its {line} line)"
        rows.append(
            Row("POSTMORTEM_DUE", f"#{i.number}", f"{i.title}; closed {ago(now - i.closed)} ago, {missing}", draft)
        )
    return rows


def postmortem_texts(repo: str, branch: str) -> list[str]:
    """Every docs/postmortems/*.md on the default branch, through the contents API; none
    without the folder"""
    listing = ["gh", "api", "-X", "GET", f"repos/{repo}/contents/{POSTMORTEMS}", "-f", f"ref={branch}"]
    proc = capture(listing)
    raw = ["gh", "api", "-X", "GET", "-H", "Accept: application/vnd.github.raw+json"]
    return [
        run([*raw, f"repos/{repo}/contents/{path}", "-f", f"ref={branch}"])
        for path in postmortem_paths(proc, repo, branch)
    ]


def postmortem_paths(proc: subprocess.CompletedProcess[str], repo: str, branch: str) -> list[str]:
    """The *.md files of the folder listing; none when the folder is missing. Any other
    failure, a missing ref included, stops the watch"""
    if proc.returncode != 0 and "Not Found (HTTP 404)" in proc.stderr:
        return []
    if proc.returncode != 0:
        sys.stderr.write(f"error: gh api {POSTMORTEMS}: {failure(proc.args, proc)}\n")
        raise SystemExit(2)
    entries = json.loads(proc.stdout)
    if not isinstance(entries, list):
        raise Refused(f"error: {repo}: {POSTMORTEMS} on {branch} is not a folder")
    return [e["path"] for e in entries if e["type"] == "file" and e["name"].endswith(".md")]


def hold_rows(issues: list[Issue], now: dt.datetime, repo: str) -> list[Row]:
    """The open holds; the fix is the person's decision to lift one (D-15), never an agent's"""
    return [
        Row(
            "HOLD",
            f"#{i.number}",
            f"{i.title}; opened by @{i.author} {ago(now - i.created)} ago ({i.created:%Y-%m-%d %H:%M} UTC)",
            f"close #{i.number} when the factory may go on: gh issue close {i.number} -R {repo}",
        )
        for i in issues
        if HOLD_LABEL in i.labels
    ]


def ordered(rows: list[Row]) -> list[Row]:
    """Incidents and holds first, the rest in the order found"""
    return sorted(rows, key=lambda r: LEAD.index(r.state) if r.state in LEAD else len(LEAD))


def fetch_issues(repo: str, *filters: str, state: str = "open") -> list[Issue]:
    """The issues a filter picks: a label, or a title search, so no repo has too many"""
    fields = "number,title,body,createdAt,closedAt,stateReason,author,labels,closedByPullRequestsReferences"
    cmd = ["gh", "issue", "list", "-R", repo, "--state", state, *filters, "-L", str(ISSUE_LIMIT), "--json", fields]
    found = json.loads(run(cmd))
    if len(found) >= ISSUE_LIMIT:
        raise Refused(f"error: {repo} has {ISSUE_LIMIT}+ {state} issues for {' '.join(filters)}")
    return [
        Issue(
            int(i["number"]),
            i["title"],
            i["body"] or "",
            parse_time(i["createdAt"]),
            (i["author"] or {}).get("login", "ghost"),
            tuple(label["name"] for label in i["labels"]),
            tuple(int(p["number"]) for p in i["closedByPullRequestsReferences"]),
            parse_time(i["closedAt"]) if i["closedAt"] else None,
            i["stateReason"],
        )
        for i in found
    ]


def fetch_deployments(repo: str, environment: str) -> list[Deployment]:
    query = ["-f", f"environment={environment}", "-f", "per_page=100"]  # as shipmill operate reads them
    out = run(["gh", "api", "-X", "GET", f"repos/{repo}/deployments", *query])
    found = [Deployment(int(d["id"]), d["ref"], d["sha"], parse_time(d["created_at"])) for d in json.loads(out)]
    return sorted(found, key=lambda d: d.id, reverse=True)


def fetch_statuses(repo: str, deployment: int) -> list[Status]:
    out = run(["gh", "api", "-X", "GET", f"repos/{repo}/deployments/{deployment}/statuses", "-f", "per_page=100"])
    found = [
        Status(int(s["id"]), s["state"], s["description"] or "", parse_time(s["created_at"])) for s in json.loads(out)
    ]
    return sorted(found, key=lambda s: s.id)


def operate_start(caller: tuple[str, bool] | None, repo: str, repo_dir: Path) -> tuple[str, str]:
    """How an idle operate runs once: the words a PROMOTION_DUE detail ends with, and the fix
    as one line naming the repo and the checkout"""
    if caller:
        command = f"run it once: gh workflow run {caller[0]} -f dry-run=false"
        return command, f"gh workflow run {caller[0]} -R {repo} -f dry-run=false"
    written = f"shipmill --repo {shlex.quote(str(repo_dir))} init --operate"
    fix = f"{written}, land it, then run it once: gh workflow run operate.yml -R {repo} -f dry-run=false"
    return "write one with `shipmill init --operate`, then run it once", fix


def deployed_rows(
    repo: str,
    repo_dir: Path,
    environment: str,
    deployments: list[Deployment],
    current: Current | None,
    statuses_of: Callable[[int], list[Status]],
    tags: list[str],
) -> list[Row]:
    """UNANNOUNCED for the issues the environment's current deployment fixed that no notice of
    the environment tells yet (S-021-4); none without a successful deployment of a release tag"""
    if current is None:
        return []
    prev = deployed_since(deployments, current, statuses_of, tags)
    if prev is None:
        return []
    issues = unannounced(repo, repo_dir, prev, current.tag, environment=environment)
    return [deployed_row(repo, environment, current.tag, prev, issues)] if issues else []


def operations_rows(
    repo: str, repo_dir: Path, envs: list[Environment], held: bool, label: str, now: dt.datetime, tags: list[str]
) -> list[Row]:
    caller = operate_caller(repo_dir)
    runs = fetch_runs(repo, caller[0]) if caller else []
    rows = operate_rows(runs, caller[0], repo) if caller else []
    deployments = {e.name: fetch_deployments(repo, e.name) for e in envs}

    def statuses_of(deployment: int) -> list[Status]:
        return fetch_statuses(repo, deployment)

    current = {e.name: current_deployment(deployments[e.name], statuses_of) for e in envs}
    for env in envs:
        row = unhealthy_row(env.name, current[env.name], now)
        if row is not None:
            rows.append(row)
    for env in envs:
        rows += deployed_rows(repo, repo_dir, env.name, deployments[env.name], current[env.name], statuses_of, tags)
    issues = proposal_issues(
        fetch_issues(repo, "--label", PROPOSAL_LABEL), lambda: fetch_issues(repo, "--search", PROPOSAL_SEARCH)
    )
    proposals = proposal_rows(issues, caller[0] if caller else "operate.yml", held, repo)
    rows += proposals
    idle = operate_idle(caller, runs, now)
    command, fix = operate_start(caller, repo, repo_dir)
    proposed = {r.subject for r in proposals}
    for env in envs:
        if env.name in proposed or env.source is None:
            continue
        source = current.get(env.source)
        row = unpromoted_row(env, source, current[env.name], deployments[env.name], idle, held, command, now, fix)
        if row is not None:
            rows.append(row)
    return rows + incident_rows(fetch_issues(repo, "--label", label), label, now, repo)


# -- intake --------------------------------------------------------------------------------


Comments = list[tuple[str, str, str]]  # (login, author association, body), oldest first


def pr_comments(repo: str, number: int, read: Callable[[list[str]], str] = run) -> Comments:
    """A pull request's conversation comments, every page, through the REST API (a Bot's
    login carries "[bot]" there, as --bot-login does)"""
    jq = '.[] | [(.user.login // "ghost"), .author_association, (.body // "")]'
    out = read(["gh", "api", "--paginate", f"repos/{repo}/issues/{number}/comments", "--jq", jq])
    return [(str(c[0]), str(c[1]), str(c[2])) for c in map(json.loads, out.splitlines())]


@dataclass(frozen=True)
class Upgrades:
    """What the open shipmill-upgrade issues add to the report (spec 014)"""

    rows: list[Row]  # UPGRADE_PENDING, one per issue an agent session takes up now
    waiting: list[int]  # labelled needs-decision, the question with no trusted reply yet
    owned: frozenset[int]  # every upgrade issue: the watch reads it here, never as triage's work


def upgrade_id(issue: Issue) -> str | None:
    """The upgrade an issue proposes, from the marker on its body's first line; None without one"""
    name: str | None = TRIAGE.upgrade_id(issue.body)
    return name


def upgrade_rows(
    issues: list[Issue],
    level: str,
    held: bool,
    comments_of: Callable[[int], Comments],
    declined_of: Callable[[str], list[int]],
    repo: str,
    bot_login: str | None = None,
) -> Upgrades:
    """The open shipmill-upgrade issues (S-014-10): level is [autonomy] upgrade, held whether
    a shipmill-hold issue is open (act then reads as propose, D-8). Under observe none is
    taken up. One answered "not now" (shipmill-upgrade-later) or with an open pull request
    closing it waits; one labelled needs-decision waits too until a trusted reply (its
    comments read only then, by triage_state.py's rule); any other is UPGRADE_PENDING. Its
    detail says what the session does: close it as not planned when a pull request on its
    branch closed unmerged (declined_of, read only then; a merged one closed the issue
    already), take up the answer, open the pull request (act), or ask. The id comes from the
    marker only; the fix never holds issue text (D-16)"""
    rows: list[Row] = []
    waiting: list[int] = []
    owned: set[int] = set()
    fix = skill_fix("github-ship-watch", repo)
    for issue in sorted(issues, key=lambda i: i.number):
        name = upgrade_id(issue) if UPGRADE_LABEL in issue.labels else None
        if name is None:
            continue  # not shipmill's proposal: triage reads it as any issue
        owned.add(issue.number)
        if level == "observe" or UPGRADE_LATER_LABEL in issue.labels or issue.closing_prs:
            continue
        asked = TRIAGE.DECISION_LABEL in issue.labels
        if asked and TRIAGE.waits_on_decision(comments_of(issue.number), bot_login):
            waiting.append(issue.number)
            continue
        declined = declined_of(name)
        if declined:
            pr = f"#{max(declined)}"
            detail = f"{name}: pull request {pr} closed unmerged, a decline: close #{issue.number} as not planned"
        elif asked:
            detail = f"{name}: answered; take up the answer"
        elif level == "act" and not held:
            detail = f"{name}: open the pull request (upgrade = act)"
        else:
            under = f"act, held by {HOLD_LABEL}" if level == "act" else level
            detail = f"{name}: ask the maintainer (upgrade = {under})"
        rows.append(Row("UPGRADE_PENDING", f"#{issue.number}", detail, fix))
    return Upgrades(rows, waiting, frozenset(owned))


def is_direction(issue: dict[str, Any], bot_login: str | None = None) -> bool:
    """Whether one of the REST API's issues is a direction issue (spec 034): triage_state.py's
    direction_issue, labelled, marked, and opened by an OWNER, MEMBER, or COLLABORATOR or the
    --bot-login (D-16); a pull request is none"""
    if "pull_request" in issue:
        return False
    user = issue.get("user")
    node = {
        "body": issue.get("body") or "",
        "author": {"login": user["login"], "__typename": user.get("type")} if user else None,
        "authorAssociation": issue.get("author_association"),
        "labels": {"nodes": [{"name": label["name"]} for label in issue["labels"]]},
    }
    found: bool = TRIAGE.direction_issue(node, bot_login)
    return found


def direction_numbers(found: list[dict[str, Any]], bot_login: str | None = None) -> frozenset[int]:
    """The direction issues among the REST API's issues, by number"""
    return frozenset(int(issue["number"]) for issue in found if is_direction(issue, bot_login))


def triage_directions(triage: str) -> frozenset[int]:
    """The open direction issues triage_state.py marks on its --json lines ("direction": true),
    read from the one triage run, so keeping them out of the issue rows costs no gh call"""
    found = set()
    for line in triage.splitlines():
        row = json.loads(line)
        if row.get("direction") is True:
            found.add(int(row["number"]))
    return frozenset(found)


@dataclass(frozen=True)
class Direction:
    """What a repo's direction adds to the report (spec 034)"""

    rows: list[Row]  # DIRECTION_MISSING and DIRECTION_PENDING
    declined: int | None = None  # the newest closed direction issue, a decline, when none is open


def direction_present(repo_dir: Path, branch: str, execute: Spawn = spawn) -> bool:
    """Whether origin/<branch> holds docs/product.md: `git cat-file -e`, whose exit 128 with
    git's "path ... does not exist in" (or "exists on disk, but not in") says it is absent.
    Any other failure, such as a ref git can't resolve, stops the watch (exit 2)"""
    cmd = ["git", "cat-file", "-e", f"origin/{branch}:{DIRECTION.as_posix()}"]
    proc = execute(cmd, repo_dir, {**os.environ, "LC_ALL": "C"})  # git's message in English
    if proc.returncode == 0:
        return True
    if proc.returncode == 128 and GIT_ABSENT.match(proc.stderr.strip()):
        return False
    sys.stderr.write(f"error: {' '.join(cmd)}: exit {proc.returncode}: {proc.stderr.strip()}\n")
    raise SystemExit(2)


def direction_check_command(repo_dir: Path, branch: str, tool: str | None) -> list[str]:
    """`shipmill product check` at origin/<branch>, the pinned CLI or --tool's (spec 034)"""
    return [*shipmill_cli(tool), "--repo", str(repo_dir), "product", "check", "--ref", f"origin/{branch}"]


def direction_problems(repo_dir: Path, branch: str, tool: str | None, execute: Spawn = spawn) -> list[str]:
    """The problems `shipmill product check --ref origin/<branch>` names, one per line; none
    for a well-formed direction (exit 0). An exit 1 that names none, or any other exit, stops
    the watch (exit 2), never read as a direction; PyPI's wait for the pinned CLI raises
    PypiWait (#597)"""
    cmd = direction_check_command(repo_dir, branch, tool)
    proc = pinned(cmd, lambda c: execute(c, repo_dir, None))
    version = unserved(cmd, proc)
    if version is not None:
        raise PypiWait(version)
    if proc.returncode == 0:
        return []
    problems = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode == 1 and problems:
        return problems
    sys.stderr.write(f"error: {' '.join(cmd)}: exit {proc.returncode}: {(proc.stderr or proc.stdout).strip()}\n")
    raise SystemExit(2)


def direction_found(repo: str, read: Callable[[list[str]], str] = run) -> list[dict[str, Any]]:
    """The issues labelled shipmill-direction, open and closed, through the REST API, which
    gives each author's association (gh issue list doesn't), every page: one read"""
    path = f"repos/{repo}/issues?labels={DIRECTION_LABEL}&state=all&per_page=100"
    out = read(["gh", "api", "--paginate", path, "--jq", ".[]"])
    return [json.loads(line) for line in out.splitlines() if line]


def direction_prs(repo: str, read: Callable[[list[str]], str] = run) -> list[dict[str, Any]]:
    """The pull requests from shipmill/direction, open, closed, and merged"""
    cmd = ["gh", "pr", "list", "-R", repo, "--head", DIRECTION_BRANCH, "--state", "all"]
    fields = "number,state,isCrossRepository,closedAt"
    found: list[dict[str, Any]] = json.loads(read([*cmd, "--json", fields, "-L", "100"]))
    return found


def direction_reopened(repo: str, number: int, read: Callable[[list[str]], str] = run) -> dt.datetime | None:
    """When the direction issue was last reopened, from its events, every page; None if never"""
    jq = '.[] | select(.event == "reopened") | .created_at'
    out = read(["gh", "api", "--paginate", f"repos/{repo}/issues/{number}/events", "--jq", jq])
    times = [parse_time(line) for line in out.splitlines() if line]
    return max(times) if times else None


def declined_while_open(
    question: dict[str, Any], own: list[dict[str, Any]], reopened: Callable[[], dt.datetime | None]
) -> list[int]:
    """The repo's own shipmill/direction pull requests that closed unmerged while the question
    was open (spec 034): after it was opened and after its last reopen, so a reopened issue,
    or a new one, asks again (S-034-7). reopened, the issue's events, is read only when such a
    pull request closed after the issue was opened"""
    opened = parse_time(question["created_at"])
    closed = [p for p in own if p["state"] == "CLOSED" and parse_time(p["closedAt"]) > opened]
    if not closed:
        return []
    last = reopened()
    return sorted(int(p["number"]) for p in closed if last is None or parse_time(p["closedAt"]) > last)


def direction_rows(
    repo: str,
    branch: str,
    present: bool,
    problems: Callable[[], list[str]],
    found: Callable[[], list[dict[str, Any]]],
    prs: Callable[[], list[dict[str, Any]]],
    comments_of: Callable[[int], Comments],
    bot_login: str | None,
    reopened_of: Callable[[int], dt.datetime | None],
) -> Direction:
    """DIRECTION_MISSING and DIRECTION_PENDING for a repo with [agents] (spec 034). present is
    whether origin/<branch> holds docs/product.md; problems, what `shipmill product check`
    names there, is read only then. Otherwise found, the direction issues, is read: none at
    all asks for the question; a closed one with none open is a decline, no row; an open one
    (the oldest) reads prs, from the repo's own shipmill/direction only (never a fork's, D-16):
    an open one waits on the maintainer's merge, no DIRECTION_PENDING. comments_of is read only
    for an issue labelled needs-decision: with no trusted reply after its question it waits,
    in NEEDS_DECISION, no DIRECTION_PENDING. Each fix is built from the repo, the numbers, and
    the path, never from an issue's text (D-16)"""
    subject = DIRECTION.as_posix()
    absent = f"no {subject} on origin/{branch}"
    session = skill_fix("github-ship-watch", repo)
    if present:
        named = problems()
        if not named:
            return Direction([])
        more = f" (and {len(named) - 1} more)" if len(named) > 1 else ""
        detail = f"shipmill product check refuses {subject} on origin/{branch}: {named[0]}{more}"
        return Direction([Row("DIRECTION_MISSING", subject, detail, DIRECTION_REPAIR)])
    issues = [issue for issue in found() if is_direction(issue, bot_login)]
    opened = sorted(int(issue["number"]) for issue in issues if issue["state"] == "open")
    closed = [int(issue["number"]) for issue in issues if issue["state"] == "closed"]
    if not opened and closed:
        return Direction([], max(closed))
    if not opened:
        missing = Row("DIRECTION_MISSING", subject, f"{absent}; no direction question asked yet", session)
        return Direction([missing, Row("DIRECTION_PENDING", subject, "open the direction question", session)])
    number = opened[0]  # with several open, the oldest is the question
    question = next(issue for issue in issues if int(issue["number"]) == number)
    own = [p for p in prs() if p["isCrossRepository"] is False]
    waiting = sorted(int(p["number"]) for p in own if p["state"] == "OPEN")
    if waiting:
        pr = waiting[-1]
        detail = f"{absent}; pull request #{pr} adds it, for the maintainer to merge"
        return Direction(
            [Row("DIRECTION_MISSING", subject, detail, f"review and merge https://github.com/{repo}/pull/{pr}")]
        )
    answer = f"answer the direction question: https://github.com/{repo}/issues/{number}"
    asked = TRIAGE.DECISION_LABEL in {label["name"] for label in question["labels"]}
    if asked and TRIAGE.waits_on_decision(comments_of(number), bot_login):
        detail = f"{absent}; the direction question #{number} waits on the maintainer"
        return Direction([Row("DIRECTION_MISSING", subject, detail, answer)])
    declined_own = declined_while_open(question, own, lambda: reopened_of(number))
    if declined_own:
        pr = declined_own[-1]
        stands = f"pull request #{pr} for #{number} closed unmerged"
        pending = f"pull request #{pr} closed unmerged, a decline: close #{number} as not planned"
    elif asked:
        stands, pending = f"#{number} has the maintainer's answer", "answered; take up the answer"
    else:
        stands, pending = f"#{number} is open, its question not asked", "ask the maintainer"
    return Direction(
        [
            Row("DIRECTION_MISSING", subject, f"{absent}; {stands}", answer),
            Row("DIRECTION_PENDING", f"#{number}", pending, session),
        ]
    )


def direction_state(
    table: dict[str, str] | None,
    repo: str,
    repo_dir: Path,
    branch: str,
    tool: str | None = None,
    bot_login: str | None = None,
    execute: Spawn = spawn,
    read: Callable[[list[str]], str] = run,
) -> Direction:
    """The direction's rows for a repo whose config has [agents] (table, agents_table's), after
    the fetch of the default branch; nothing at all is read without it (spec 034). PyPI's wait
    for the pinned CLI is its PYPI_WAIT row, the direction unread (#597)"""
    if table is None:
        return Direction([])
    present = direction_present(repo_dir, branch, execute)
    try:
        return direction_rows(
            repo,
            branch,
            present,
            lambda: direction_problems(repo_dir, branch, tool, execute),
            lambda: direction_found(repo, read),
            lambda: direction_prs(repo, read),
            lambda n: pr_comments(repo, n, read),
            bot_login,
            lambda n: direction_reopened(repo, n, read),
        )
    except PypiWait as wait:
        return Direction([pypi_wait_row(wait.version, "the direction")])


def declined_prs(repo: str, name: str) -> list[int]:
    """The pull requests from the repo's own upgrade branch that closed without merging. gh's
    closed state lists merged ones too, which GitHub tells apart as MERGED; a fork's branch of
    the same name is anyone's, so it never declines (D-16)"""
    cmd = ["gh", "pr", "list", "-R", repo, "--head", f"{UPGRADE_BRANCH}{name}", "--state", "closed"]
    found = json.loads(run([*cmd, "--json", "number,state,isCrossRepository", "-L", "100"]))
    return declined(found)


def declined(found: list[dict[str, Any]]) -> list[int]:
    """gh pr list's closed pull requests that closed unmerged, from the repo itself"""
    return sorted(int(p["number"]) for p in found if p["state"] == "CLOSED" and p["isCrossRepository"] is False)


def intake(
    repo: str,
    code: int,
    triage: str,
    prs: list[dict[str, Any]],
    comments_of: Callable[[int], Comments],
    bot_login: str | None = None,
    trusted_only: bool = False,
    land: str | None = None,
    upgrades: Upgrades | None = None,
    untrusted_plans: frozenset[int] = frozenset(),
    closed_prs: Sequence[dict[str, Any]] = (),
    directions: frozenset[int] = frozenset(),
) -> list[Row]:
    """The intake rows from triage_state.py's exit code and --json lines, and the open pull
    requests (number, isDraft, isCrossRepository, labels, headRefOid). Each pull request is UNTRUSTED
    (with trusted_only, a head in a fork), else waiting on a decision (labelled, no reply;
    its comments are read only then), else VETOED (labelled decided with an unanswered
    trusted veto, triage_state.py's rule; its comments are read only then), else in PRS_OPEN
    unless a draft. closed_prs are the closed and merged pull requests labelled decided in the
    veto window (number, isCrossRepository): each with such a veto is VETOED too, save a
    fork's with trusted_only. VETOED issues and pull requests share one row, an agent's
    (spec 030), and an issue in it is in no other row. land is the effective [autonomy] land
    level, None without [agents]: PRS_OPEN's fix (land_fix) follows it. upgrades
    are the shipmill-upgrade issues: their UPGRADE_PENDING rows come first, none is in the
    issue rows, and the ones waiting on a reply join NEEDS_DECISION. One triage_state.py
    reads as UNTRUSTED (with trusted_only, an author who is neither trusted nor the
    --bot-login; the release workflow's github-actions[bot] upgrade issue, label and marker
    both, is trusted, D-30) stays UNTRUSTED and nothing else: an unattended session never
    starts for it (D-16). So does each of untrusted_plans, the open plan issues plans_rows
    left out (spec 028), whatever triage_state.py reads it as. directions are the open
    direction issues (spec 034), shipmill's question: none is in the issue rows, one whose
    question waits on the maintainer is in NEEDS_DECISION, and one triage_state.py reads as
    UNTRUSTED stays there, as an upgrade issue does"""
    if land is not None and (not isinstance(land, str) or land not in AUTONOMY):
        raise ValueError(f"land must be None or one of {list(AUTONOMY)}, got {land!r}")
    owned = (upgrades.owned if upgrades is not None else frozenset()) | directions
    counts: dict[str, list[int]] = {}
    waits_on: dict[int, list[str]] = {}  # a WITH_PERSON issue's assignees (spec 017) and teams (spec 036)
    untrusted_upgrades = set()
    for line in triage.splitlines():
        row = json.loads(line)
        number = int(row["number"])
        if number in untrusted_plans:
            continue  # in UNTRUSTED below, and nothing else
        if number in owned and row["state"] == "UNTRUSTED":
            untrusted_upgrades.add(number)
        elif number in directions and row["state"] == "NEEDS_DECISION":
            pass  # its question waits on the maintainer: in NEEDS_DECISION (spec 034)
        elif number in owned:
            continue
        if row["state"] == "WITH_PERSON":
            waits_on[number] = person_logins(row)
        counts.setdefault(row["state"], []).append(number)
    held_back = {f"#{n}" for n in untrusted_upgrades}
    rows = [r for r in (upgrades.rows if upgrades is not None else []) if r.subject not in held_back]
    detail = "; ".join(
        f"{s} {' '.join(f'#{n}' for n in numbers)}"
        for s, numbers in sorted(counts.items())
        if s in TRIAGE_ACTION and s != VETOED  # VETOED has a row of its own
    )
    if code == 1 and detail:  # triage_state.py exits 1 only with an action line: an upgrade issue's, left out
        rows.append(Row("ISSUES", repo, detail, skill_fix("github-issue-triage", repo)))
    elsewhere = TRIAGE_ACTION | {"NEEDS_DECISION", "UNTRUSTED"}  # rows of their own
    rest = "; ".join(
        f"{s} {' '.join(open_issue(n, waits_on) for n in numbers)}"
        for s, numbers in sorted(counts.items())
        if s not in elsewhere
    )
    if rest:
        rows.append(Row("ISSUES_OPEN", repo, rest))
    waiting = list(counts.get("NEEDS_DECISION", []))
    untrusted = [*counts.get("UNTRUSTED", []), *untrusted_plans]
    waiting += [n for n in (upgrades.waiting if upgrades is not None else []) if n not in untrusted_upgrades]
    vetoed = list(counts.get(VETOED, []))
    ready: list[tuple[int, str]] = []
    for pr in prs:
        number = int(pr["number"])
        labels = {label["name"] for label in pr["labels"]}
        if trusted_only and pr["isCrossRepository"]:
            untrusted.append(number)
        elif TRIAGE.DECISION_LABEL in labels and TRIAGE.waits_on_decision(comments_of(number), bot_login):
            waiting.append(number)
        elif TRIAGE.DECIDED_LABEL in labels and TRIAGE.vetoed(comments_of(number), bot_login) is not None:
            vetoed.append(number)
        elif not pr["isDraft"]:  # a draft is its author's until marked ready: it starts no session (D-52)
            ready.append((number, head_sha(pr)))
    for pr in closed_prs:
        number = int(pr["number"])
        if trusted_only and pr["isCrossRepository"]:
            continue  # a fork's closed pull request starts no unattended session (D-16)
        if TRIAGE.vetoed(comments_of(number), bot_login) is not None:
            vetoed.append(number)
    if ready:
        listed = " ".join(f"#{n}" for n, _ in ready)
        rows.append(Row("PRS_OPEN", repo, listed, land_fix(land, repo), tuple(sorted(ready))))
    if vetoed:
        named = " ".join(f"#{n}" for n in sorted(set(vetoed)))
        take_up = f"take up each veto (needs-decision.md): {skill_fix('github-issue-triage', repo)}"
        rows.append(Row(VETOED, repo, named, take_up))
    if waiting:
        named = " ".join(f"#{n}" for n in sorted(set(waiting)))
        rows.append(Row("NEEDS_DECISION", repo, named, f"answer the needs-decision question on {repo} {named}"))
    if untrusted:
        review = (
            f"review them in an interactive session: {skill_fix('github-issue-triage', repo)} for issues,"
            f" {skill_fix('github-pr-triage', repo)} for pull requests"
        )
        rows.append(Row("UNTRUSTED", repo, " ".join(f"#{n}" for n in sorted(set(untrusted))), review))
    return rows


def head_sha(pr: dict[str, Any]) -> str:
    """An open pull request's headRefOid, 40 lowercase hex characters, or refused (#546)"""
    sha = pr.get("headRefOid")
    if not isinstance(sha, str) or HEAD_SHA.fullmatch(sha) is None:
        raise Refused(f"error: gh pr list printed #{pr['number']} with headRefOid {sha!r}, not a commit SHA")
    return sha


def person_logins(row: dict[str, Any]) -> list[str]:
    """Whom a WITH_PERSON line waits on, as shown: its assignees as @login, then its teams as
    @org/team. assignees is a list of logins; teams (spec 036, absent from a line read without
    --role flags) a list of teams, and the assignees may be empty only with a team. Anything
    else is malformed"""
    found = row.get("assignees")
    teams = row.get("teams", [])
    logins = isinstance(found, list) and all(isinstance(p, str) and LOGIN.match(p) for p in found)
    named = isinstance(teams, list) and all(isinstance(t, str) and TRIAGE.TEAM.fullmatch(t) for t in teams)
    if not logins or not named or not (found or teams):
        raise Refused(f"error: triage_state.py printed a WITH_PERSON line without its assignees or teams: {row!r}")
    return [*(f"@{p}" for p in found), *teams]


def open_issue(number: int, waits_on: dict[int, list[str]]) -> str:
    """An ISSUES_OPEN issue as #N, a person's item with whom it waits on: #N (@a @b @org/team)"""
    people = waits_on.get(number)
    return f"#{number}" if people is None else f"#{number} ({' '.join(people)})"


def land_fix(land: str | None, repo: str) -> str | None:
    """PRS_OPEN's fix by the effective [autonomy] land level, as `shipmill status` words it
    (S-040-11): without [agents] no gate lands them; under observe no session does; under
    propose a session reviews them and a person merges the ones labelled shipmill-ready; under
    act the gate lands them, so there is nothing to clear"""
    by_hand = f"or land them by hand: {skill_fix('github-pr-triage', repo)}"
    if land is None:
        return f"add [agents] to {POLICY} for a gate to land them, {by_hand}"
    if land == "observe":
        return f'set land = "propose" or "act" in [autonomy], {by_hand}'
    if land == "propose":
        merge = f"merge each pull request labelled {READY_LABEL} once you have read it"
        return f'{merge}, or set land = "act" in [autonomy] in {POLICY}'
    return None


def triage_command(
    repo: str,
    bot_login: str | None = None,
    trusted_only: bool = False,
    home: str | None = None,
    roles: Sequence[str] = (),
) -> list[str]:
    """triage_state.py's command line: with the config's [product] home as --home (spec 038),
    and each of roles, a --role flag's NAME=FILLER[,FILLER...] value, as its own --role
    (spec 036)"""
    cmd = [sys.executable, str(TRIAGE_STATE), repo, "--json"]
    cmd += ["--bot-login", bot_login] if bot_login is not None else []
    cmd += ["--trusted-only"] if trusted_only else []
    cmd += ["--home", home] if home is not None else []
    cmd += [item for value in roles for item in ("--role", value)]
    return cmd


def triage_run(
    repo: str,
    bot_login: str | None = None,
    trusted_only: bool = False,
    home: str | None = None,
    roles: Sequence[str] = (),
) -> tuple[int, str]:
    """triage_state.py's exit code (0 or 1) and its --json lines"""
    cmd = triage_command(repo, bot_login, trusted_only, home, roles)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode not in (0, 1):
        sys.stderr.write(f"error: triage_state.py: {proc.stderr.strip()}\n")
        raise SystemExit(2)
    return proc.returncode, proc.stdout


def intake_rows(
    repo: str,
    code: int,
    triage: str,
    bot_login: str | None,
    trusted_only: bool,
    land: str | None,
    upgrades: Upgrades | None,
    untrusted_plans: frozenset[int],
    now: dt.datetime,
    directions: frozenset[int] = frozenset(),
) -> list[Row]:
    """The intake rows from triage_run's exit code and lines, the open pull requests, and the
    closed and merged ones labelled decided and updated in the veto window (spec 030);
    land is the effective [autonomy] land level, None without [agents]; directions are the
    open direction issues, never in the issue rows (spec 034)"""
    fields = "number,isDraft,isCrossRepository,labels,headRefOid"
    prs = json.loads(run(["gh", "pr", "list", "-R", repo, "--json", fields, "-L", "100"]))

    def comments_of(number: int) -> Comments:
        return pr_comments(repo, number)

    closed = decided_prs(repo, now)
    return intake(
        repo,
        code,
        triage,
        prs,
        comments_of,
        bot_login,
        trusted_only,
        land,
        upgrades,
        untrusted_plans,
        closed,
        directions,
    )


def decided_prs_command(repo: str, now: dt.datetime) -> list[str]:
    """gh's list of the closed and merged pull requests labelled decided and updated in
    triage_state.py's veto window (a veto comment updates one): gh's closed state lists merged
    ones too"""
    since = (now - TRIAGE.VETO_WINDOW).astimezone(TRIAGE.UTC).strftime("%Y-%m-%d")
    cmd = ["gh", "pr", "list", "-R", repo, "--state", "closed", "--label", TRIAGE.DECIDED_LABEL]
    return [*cmd, "--search", f"updated:>={since}", "--json", "number,isCrossRepository", "-L", str(ISSUE_LIMIT)]


def decided_prs(repo: str, now: dt.datetime) -> list[dict[str, Any]]:
    """The pull requests decided_prs_command lists; as many as its limit is refused"""
    found: list[dict[str, Any]] = json.loads(run(decided_prs_command(repo, now)))
    if len(found) >= ISSUE_LIMIT:
        raise Refused(f"error: {repo} has {ISSUE_LIMIT}+ closed pull requests labelled {TRIAGE.DECIDED_LABEL}")
    return found


# -- goal plans (spec 028) ------------------------------------------------------------------


@dataclass(frozen=True)
class Plans:
    """What intake_state.py --plans adds to the report"""

    rows: list[Row]  # PLANS, one row for every plan state that needs a session
    untrusted: frozenset[int]  # with trusted_only, the open plan issues the --bot-login didn't open


def plan_wip(table: dict[str, str] | None, policy: Path) -> int | None:
    """[agents] wip (agents_table's), the limit no-work plans wait under; None without it"""
    value = None if table is None else table.get("wip")
    if value is None:
        return None
    if re.fullmatch(r"[1-9]\d*", value) is None:
        raise Refused(f"error: {policy}: [agents] wip must be a whole number from 1, got {value}")
    return int(value)


def plans_run(
    repo: str,
    repo_dir: Path,
    tool: str | None = None,
    bot_login: str | None = None,
    wip: int | None = None,
    execute: Spawn = spawn,
) -> str:
    """intake_state.py --plans --json's lines, run in the checkout, where it reads the
    direction with `shipmill product show` (the plugin's pinned version, or --tool's when a
    person passed one) and the config; a failure (exit 2) stops the watch, save the pinned
    shipmill's "no version" error, which it has retried already: that raises PypiWait (#597)"""
    cmd = [sys.executable, str(INTAKE_STATE), repo, "--plans", "--json"]
    cmd += ["--tool", tool] if tool is not None else []
    cmd += ["--wip", str(wip)] if wip is not None else []
    cmd += ["--bot-login", bot_login] if bot_login is not None else []
    proc = execute(cmd, repo_dir, None)
    if proc.returncode == 2 and tool is None and no_version(proc.stderr) == plugin_version():
        raise PypiWait(plugin_version())
    if proc.returncode not in (0, 1):  # 1 is "something needs action", not a failure
        raise Refused(f"error: intake_state.py --plans failed with exit {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def plan_line(line: str) -> dict[str, Any] | None:
    """One of intake_state.py's --json lines when it is a plan row, checked; None for the
    autonomy line and the feedback rows"""
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise Refused(f"error: intake_state.py printed {line[:200]!r}, not JSON: {exc}") from None
    if not isinstance(row, dict) or row.get("kind") not in ("goal", "plan"):
        return None
    number, author = row.get("number"), row.get("author")
    well_formed = row.get("state") in PLAN_STATES
    if row["kind"] == "goal":
        well_formed &= isinstance(row.get("goal"), str) and GOAL_ID.fullmatch(row["goal"]) is not None
    else:
        well_formed &= isinstance(number, int) and not isinstance(number, bool) and number > 0
        well_formed &= isinstance(author, str) and bool(author)
    if not well_formed:
        raise Refused(f"error: intake_state.py printed a malformed plan row: {line[:200]!r}")
    return row


def plans_rows(text: str, repo: str, bot_login: str | None = None, trusted_only: bool = False) -> Plans:
    """PLANS from intake_state.py --plans --json's lines: each plan state that needs a session
    (PLAN_DUE, PLAN_MALFORMED, PLAN_ANSWERED, PLAN_ACCEPTED) with its goals (G-n) and plan
    issues (#N). With trusted_only, an open plan issue the --bot-login didn't open is in none
    and in untrusted instead (D-16): an unattended session never starts for it. A goal's row
    (no-work, or a request intake_state.py read from a trusted author only) is the direction's.
    Goal ids and numbers only, never an issue's text (D-16)"""
    listed: dict[str, list[str]] = {}
    untrusted: set[int] = set()
    for line in text.splitlines():
        row = plan_line(line)
        if row is None:
            continue
        if row["kind"] == "plan" and trusted_only and row["state"] != "PLAN_DECLINED":
            ours = bot_login is not None and row["author"].lower() == bot_login.lower()
            if not ours:
                untrusted.add(row["number"])
                continue
        if row["state"] in PLAN_ACTION:
            token = row["goal"] if row["kind"] == "goal" else f"#{row['number']}"
            listed.setdefault(row["state"], []).append(token)
    detail = "; ".join(f"{s} {' '.join(listed[s])}" for s in PLAN_ACTION if s in listed)
    rows = [Row("PLANS", repo, detail, skill_fix("product-intake", repo))] if detail else []
    return Plans(rows, frozenset(untrusted))


# triage_state.py's states of an issue that isn't open (SUSPECT_CLOSE, VERIFY_CLOSED), or
# that no unattended pass reads the links of (UNTRUSTED, D-16): no chain starts from one
NOT_CHAIN_STARTS = frozenset({"SUSPECT_CLOSE", "VERIFY_CLOSED", "UNTRUSTED"})
CHAIN_REF = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)#[1-9]\d*$")
NAMED_REF = re.compile(r"(?<![\w.-])[\w.-]+/[\w.-]+#[1-9]\d*\b")  # the item a chains.py error names


def chain_starts(repo: str, triage: str) -> list[str]:
    """The repo's open issues, as owner/repo#N, from triage_state.py's --json lines; none it
    reads as UNTRUSTED, whose "Depends on" lines an outsider wrote, and no closed one (a
    closed VETOED issue's line says "closed": true)"""
    numbers = set()
    for line in triage.splitlines():
        row = json.loads(line)
        if row["state"] not in NOT_CHAIN_STARTS and row.get("closed") is not True:
            numbers.add(int(row["number"]))
    return [f"{repo}#{n}" for n in sorted(numbers)]


def chain_no_gate_rows(shown: object) -> list[Row]:
    """CHAIN_NO_GATE, one row per item `chains.py show --json` marks NO_GATE that is linked to
    another item: one that waits on nothing and that nothing waits on is in no chain. The
    reference is GitHub's own spelling of the item (chains.py reads it from the forge), checked
    here, so the fix names a repo and a number, never an issue's text (D-16)"""
    if not isinstance(shown, dict) or not isinstance(shown.get("rows"), list):
        raise Refused('error: chains.py show --json printed no {"rows": [...]} object')
    rows = []
    for item in shown["rows"]:
        if not isinstance(item, dict) or item.get("gate") != "NO_GATE":
            continue
        if not (item.get("waits_on") or item.get("waited_on_by")):
            continue
        ref = str(item.get("ref"))
        found = CHAIN_REF.match(ref)
        if found is None:
            raise Refused(f"error: chains.py show --json printed a malformed reference {ref!r}")
        where = found.group("repo")
        detail = f"ready in {where}, whose {POLICY} has no [agents] table: no gate takes it up, so its chain stalls"
        fix = f"set up a gate on {where} ({skill_fix('shipmill-setup', where)}), or do {ref} by hand"
        rows.append(Row("CHAIN_NO_GATE", ref, detail, fix))
    return rows


def chain_unreadable_row(repo: str, starts: list[str], error: str) -> Row:
    """CHAIN_UNREADABLE: the chain walk failed (a gh error, an issue past a page of labels or
    relations, a config it can't parse), so the chains weren't checked; the rest of the
    watch stands. The subject is the item the error's first line names, checked as
    owner/repo#N, else the repo; the fix reruns the walk on it (else on the starts, the
    repo's own open issues) to see the error, from those checked values alone"""
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    first = next((line for line in lines if line.startswith("error:")), lines[0] if lines else "no error output")
    named = NAMED_REF.search(first)
    subject = named.group(0) if named is not None else repo
    again = subject if named is not None else " ".join(starts)
    fix = f"see why: uv run --no-project python {CHAINS} show --trusted-only {again}"
    return Row("CHAIN_UNREADABLE", subject, first, fix)


def chain_rows(
    repo: str,
    triage: str,
    bot_login: str | None = None,
    execute: Callable[[list[str]], subprocess.CompletedProcess[str]] = capture,
) -> list[Row]:
    """The CHAIN_NO_GATE rows of the chains the repo's open issues belong to: one chains.py
    show over all of them, which reads each item once and each repo's config once, and never
    reads or follows an untrusted author's issue (--trusted-only, D-16). A walk that fails is
    one CHAIN_UNREADABLE row instead, never the watch's exit 2"""
    starts = chain_starts(repo, triage)
    if not starts:
        return []
    cmd = [sys.executable, str(CHAINS), "show", "--json", "--trusted-only"]
    cmd += ["--bot-login", bot_login] if bot_login is not None else []
    proc = execute([*cmd, *starts])
    if proc.returncode not in (0, 1):
        return [chain_unreadable_row(repo, starts, proc.stderr or f"error: chains.py show exited {proc.returncode}")]
    try:
        return chain_no_gate_rows(json.loads(proc.stdout))
    except json.JSONDecodeError as exc:
        return [chain_unreadable_row(repo, starts, f"error: chains.py show --json printed no JSON: {exc}")]
    except Refused as refused:
        return [chain_unreadable_row(repo, starts, str(refused))]


# -- upstream reports (spec 038) ------------------------------------------------------------

# upstream_state.py's states: the ones that make it exit 1, the coordinator's to act on, in
# its order, and the rest
UPSTREAM_ACTION = ("ROUTE_DUE", "ANSWERED", "CLOSE_DUE")
UPSTREAM_STATES = frozenset({*UPSTREAM_ACTION, "ASKED", "ROUTED", "UNTRUSTED"})


def upstream_unreadable_row(repo: str, repo_dir: Path, error: str) -> Row:
    """UPSTREAM_UNREADABLE: upstream_state.py failed (a gh error, a `shipmill gh --product`
    refusal, a config it refuses), so the reports weren't read; the rest of the watch stands,
    as for CHAIN_UNREADABLE. The detail is the error's first line; the fix reruns the script in
    the checkout to see it, from the repo and the path alone"""
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    first = next((line for line in lines if line.startswith("error:")), lines[0] if lines else "no error output")
    fix = f"see why: uv run --directory {repo_dir} --no-project python {UPSTREAM_STATE} {repo}"
    return Row("UPSTREAM_UNREADABLE", repo, first, fix)


def upstream_report_rows(repo: str, code: int, text: str) -> list[Row]:
    """UPSTREAM_DUE (the reports the coordinator routes, takes the answer of, or closes),
    UPSTREAM_ASKED (a question the maintainer owes), and UPSTREAM_UNTRUSTED (reports by an
    author the coordinator doesn't trust, D-16), from upstream_state.py's exit code and --json
    lines. Each names its reports as owner/repo#N, checked, never a report's text or note.
    A line it can't read, or an exit code its lines don't explain, is refused"""
    listed: dict[str, list[str]] = {}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Refused(f"error: upstream_state.py printed {line[:200]!r}, not JSON: {exc}") from None
        if not isinstance(row, dict) or row.get("state") not in UPSTREAM_STATES:
            raise Refused(f"error: upstream_state.py printed a row without a known state: {line[:200]!r}")
        ref = row.get("ref")
        if not isinstance(ref, str) or CHAIN_REF.match(ref) is None:
            raise Refused(f"error: upstream_state.py printed a malformed reference {ref!r}")
        listed.setdefault(row["state"], []).append(ref)
    due = "; ".join(f"{s} {' '.join(listed[s])}" for s in UPSTREAM_ACTION if s in listed)
    if (code == 1) != bool(due):
        raise Refused(f"error: upstream_state.py exited {code}, which its rows don't explain")
    rows = []
    if due:
        rows.append(Row("UPSTREAM_DUE", repo, due, skill_fix("github-issue-triage", repo)))
    if "ASKED" in listed:
        named = " ".join(listed["ASKED"])
        rows.append(Row("UPSTREAM_ASKED", repo, named, f"answer the needs-decision question on {named}"))
    if "UNTRUSTED" in listed:
        review = f"review them in an interactive session: {skill_fix('github-issue-triage', repo)}"
        rows.append(Row("UPSTREAM_UNTRUSTED", repo, " ".join(listed["UNTRUSTED"]), review))
    return rows


def upstream_rows(repo: str, repo_dir: Path, bot_login: str | None = None, execute: Spawn = spawn) -> list[Row]:
    """The upstream report rows of a home repo, a checkout whose config has [product] repos:
    one upstream_state.py run in the checkout, where it reads the config and the product's
    token. A run that fails is one UPSTREAM_UNREADABLE row instead, never the watch's exit 2;
    one that failed on the pinned shipmill's "no version" error, retried already, is the
    PYPI_WAIT row (#597)"""
    cmd = [sys.executable, str(UPSTREAM_STATE), repo, "--json"]
    cmd += ["--bot-login", bot_login] if bot_login is not None else []
    proc = execute(cmd, repo_dir, None)
    if proc.returncode == 2 and no_version(proc.stderr) == plugin_version():
        return [pypi_wait_row(plugin_version(), "upstream reports")]
    if proc.returncode not in (0, 1):
        why = proc.stderr or f"error: upstream_state.py exited {proc.returncode}"
        return [upstream_unreadable_row(repo, repo_dir, why)]
    try:
        return upstream_report_rows(repo, proc.returncode, proc.stdout)
    except Refused as refused:
        return [upstream_unreadable_row(repo, repo_dir, str(refused))]


def coordinator_rows(
    text: str | None,
    policy: Path | None,
    repo: str,
    repo_dir: Path,
    bot_login: str | None = None,
    execute: Spawn = spawn,
) -> list[Row]:
    """The upstream report rows when the config (its text, None without one) has [product]
    repos, the home repo's coordinator (spec 038); none, and no upstream_state.py run, without"""
    if text is None or policy is None or product_repos(text, policy) is None:
        return []
    return upstream_rows(repo, repo_dir, bot_login, execute)


# -- agents --------------------------------------------------------------------------------


def triage_mode_row(text: str, policy: Path, declined: int | None = None, held: bool = False) -> Row:
    """The agent stages' effective levels under the hold (held), each with its source as
    `shipmill autonomy` reads it (spec 040), then the config's other [agents] keys as the
    config sets them, less the prompt, whose words are not the levels, and the deprecated prs,
    which decides nothing; declined is the direction issue whose close declined the direction
    (spec 034), said last"""
    table = agents_table(text, policy)
    if table is None:
        return Row("TRIAGE_MODE", "[agents]", "no [agents]: no gate session runs for this repo")
    # agents_table parsed the text already, so tomllib.loads can't fail here
    levels = agent_levels_310(text, policy) if tomllib is None else agent_levels_toml(tomllib.loads(text), policy)
    said = [", ".join(level.text(held) for level in levels)]
    said += [f"{k} = {table[k]}" for k in sorted(table) if k not in ("prompt", "prs")]
    said += [] if declined is None else [f"no direction: declined in #{declined}"]
    return Row("TRIAGE_MODE", "[agents]", "; ".join(said))


def gate_app_rows(table: dict[str, str] | None) -> list[Row]:
    """D-19: the [agents] table (agents_table's) configures a gate without an App, which only a
    person connects; never an agent's row, or every tick on an app-less repo would start a session"""
    if table is None or "prompt" not in table or "app_id" in table:
        return []
    fix = "run shipmill-setup's step 3 (app-create), then set app_id in [agents]"
    return [Row("GATE_NO_APP", "[agents]", f"no app connected: sessions write as the host's gh login; {fix}", fix)]


def agents_table(text: str, policy: Path) -> dict[str, str] | None:
    """[agents] of the config, each value as TOML writes it; None without the table"""
    if tomllib is None:
        return agents_table_310(text, policy)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Refused(f"error: {policy}: {exc}") from None
    return agents_table_toml(raw, policy)


def agents_table_toml(raw: dict[str, object], policy: Path) -> dict[str, str] | None:
    table = raw.get("agents")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise Refused(f"error: {policy}: agents is not a table")
    return {k: json.dumps(v) if isinstance(v, (str, bool)) else str(v) for k, v in table.items()}


def agents_table_310(text: str, policy: Path) -> dict[str, str] | None:
    """[agents] as a plain table of one-line keys; any other form is refused, a broken
    header such as "[agents" too, which tomllib refuses and the table reader would skip"""
    for line in text.splitlines():
        if AGENTS_HEADER.match(line) and TOML_HEADER.match(line) is None:
            raise Refused(f"error: {policy}: can't read [agents] on Python 3.10: a malformed header {line.strip()!r}")
    tables = toml_tables(text)
    if "agents" not in tables:
        return None
    if any(name.startswith("agents.") for name in tables):
        raise Refused(f"error: {policy}: can't read [agents] on Python 3.10: use 3.11+ or a plain [agents] table")
    found = {}
    for line in tables["agents"].splitlines():
        if blank(line):
            continue
        key = re.match(r"^\s*(\w+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^#\s]+)\s*(?:#.*)?$", line)
        if key is None:
            raise Refused(f"error: {policy}: can't read [agents] on Python 3.10: use 3.11+ ({line.strip()!r})")
        value = key.group(2)
        found[key.group(1)] = json.dumps(value[1:-1]) if value[0] in "\"'" else value
    return found


# -- product (spec 038) ----------------------------------------------------------------------


PRODUCT_HEADER = re.compile(r"^\s*\[+\s*[\"']?product\b")  # a line that opens a [product] header, well formed or not
PRODUCT_HOME = re.compile(r"^\s*[\"']?home[\"']?\s*[.=]")  # a home key's line in [product], dotted or not
PRODUCT_HOME_VALUE = re.compile(r"^\s*[\"']?home[\"']?\s*=\s*(?:\"([^\"\\]*)\"|'([^']*)')\s*(?:#.*)?$")


def product_home(text: str, policy: Path) -> str | None:
    """[product] home of the config, the product's home repo as owner/name (spec 038); None
    without the table or the key, or for `standalone = true` (spec 043). The other key, repos,
    is the home repo's own and not read here. A home that isn't owner/name by triage_state.py's
    rule is refused, and so is standalone set to anything but true or beside another key"""
    if tomllib is None:
        return product_home_310(text, policy)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Refused(f"error: {policy}: {exc}") from None
    return product_home_toml(raw, policy)


def checked_home(home: object, policy: Path) -> str | None:
    """A [product] home as read, refused unless it is owner/name by triage_state.py's rule"""
    if home is None:
        return None
    if isinstance(home, str) and TRIAGE.home_repo(home):
        return home
    raise Refused(f"error: {policy}: [product] home must be owner/name, such as acme/product; got {home!r}")


def product_home_toml(raw: dict[str, object], policy: Path) -> str | None:
    table = raw.get("product")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise Refused(f"error: {policy}: product is not a table")
    if standalone_toml(table, policy):
        return None
    return checked_home(table.get("home"), policy)


def standalone_toml(table: dict[str, object], policy: Path) -> bool:
    """True for a [product] table that is `standalone = true` alone, a repo that stands alone
    (spec 043), which reads as no table; False without the key. standalone with any other
    value, or beside another key, is refused naming the key, as shipmill's ProductConfig does"""
    if "standalone" not in table:
        return False
    others = sorted(set(table) - {"standalone"})
    if others:
        raise Refused(
            f"error: {policy}: [product] standalone can't be set beside {others[0]}; a repo that stands alone"
            " sets standalone = true alone, a product's repo sets home or repos instead"
        )
    if table["standalone"] is not True:
        raise Refused(f"error: {policy}: [product] standalone takes only true; got {table['standalone']!r}")
    return True


PRODUCT_KEY = re.compile(r"^\s*[\"']?([A-Za-z0-9_-]+)[\"']?\s*[.=]")  # a key's line in [product], dotted or not
PRODUCT_STANDALONE_VALUE = re.compile(r"^\s*[\"']?standalone[\"']?\s*=\s*(.*?)\s*(?:#.*)?$")


def standalone_310(body: str, policy: Path) -> bool:
    """standalone_toml on Python 3.10, from the body of a plain [product] table: only a line
    `standalone = true` alone reads as standalone; a value other than true, a second standalone,
    or another key or line beside it is refused naming it"""
    lines = [line for line in body.splitlines() if not blank(line)]
    keys = [PRODUCT_KEY.match(line) for line in lines]
    if not any(key is not None and key.group(1) == "standalone" for key in keys):
        return False
    for line, key in zip(lines, keys, strict=True):
        if key is None:
            raise Refused(f"error: {policy}: can't read [product] on Python 3.10: use 3.11+ ({line.strip()!r})")
        if key.group(1) != "standalone":
            raise Refused(
                f"error: {policy}: [product] standalone can't be set beside {key.group(1)}; a repo that stands"
                " alone sets standalone = true alone, a product's repo sets home or repos instead"
            )
    if len(lines) > 1:
        raise Refused(f"error: {policy}: [product] standalone is set twice")
    found = PRODUCT_STANDALONE_VALUE.match(lines[0])
    value = None if found is None else found.group(1)
    if value != "true":
        raise Refused(f"error: {policy}: [product] standalone takes only true; got {value or lines[0].strip()!r}")
    return True


def product_table_310(text: str, policy: Path) -> str | None:
    """The body of a plain [product] table on Python 3.10; None without one. Any other form
    of the table (an array of tables, a dotted key, a malformed header) is refused"""
    for line in text.splitlines():
        header = TOML_HEADER.match(line)
        if PRODUCT_HEADER.match(line) and (header is None or header.group(1) == "[["):
            # toml_tables skips an array of tables, which tomllib reads as no table: refused
            raise Refused(f"error: {policy}: can't read [product] on Python 3.10: a malformed header {line.strip()!r}")
    tables = toml_tables(text)
    if re.search(r"^\s*[\"']?product[\"']?\s*[.=]", tables.get("", ""), re.MULTILINE) or any(
        name.startswith("product.") for name in tables
    ):
        raise Refused(f"error: {policy}: can't read [product] on Python 3.10: use 3.11+ or a plain [product] table")
    return tables.get("product")


def product_home_310(text: str, policy: Path) -> str | None:
    """[product] home on Python 3.10: a plain [product] table whose home is a one-line
    string; any other form of home is refused rather than misread. repos may take any form"""
    body = product_table_310(text, policy)
    if body is None or standalone_310(body, policy):
        return None
    home = None
    for line in body.splitlines():
        if PRODUCT_HOME.match(line) is None:
            continue
        found = PRODUCT_HOME_VALUE.match(line)
        if found is None or home is not None:
            raise Refused(f"error: {policy}: can't read [product] home on Python 3.10: use 3.11+ ({line.strip()!r})")
        home = found.group(1) if found.group(1) is not None else found.group(2)
    return checked_home(home, policy)


PRODUCT_KEYS = ("home", "repos", "standalone")
PRODUCT_REPOS_VALUE = re.compile(r"^\s*[\"']?repos[\"']?\s*=\s*\[(.*)\]\s*(?:#.*)?$")
PRODUCT_LIST_ITEM = re.compile(r"\s*(?:\"([^\"\\]*)\"|'([^']*)')\s*")


def product_repos(text: str, policy: Path) -> tuple[str, ...] | None:
    """[product] repos of the config, the home repo's component repos (spec 038); None without
    the table, in a component's (home set), or for `standalone = true` (spec 043). Checked as
    shipmill's ProductConfig checks them: only home, repos, or standalone in the table, one of
    them and never two, and repos a non-empty list of owner/name with no repo twice (case
    ignored); anything else is refused naming the key.
    That repos needs [agents] app_id is the caller's to check, as it is the writer's"""
    if tomllib is None:
        return product_repos_310(text, policy)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Refused(f"error: {policy}: {exc}") from None
    table = raw.get("product")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise Refused(f"error: {policy}: product is not a table")
    unknown = sorted(set(table) - set(PRODUCT_KEYS))
    if unknown:
        raise Refused(
            f"error: {policy}: [product] has an unknown key {unknown[0]!r}; it holds home, repos, or standalone"
        )
    if standalone_toml(table, policy):
        return None
    repos = table.get("repos")
    if repos is not None and not (isinstance(repos, list) and all(isinstance(r, str) for r in repos)):
        raise Refused(f"error: {policy}: [product] repos must be a list of owner/name strings; got {repos!r}")
    return checked_repos("home" in table, repos, policy)


def checked_repos(has_home: bool, repos: list[str] | None, policy: Path) -> tuple[str, ...] | None:
    """[product] repos as read, refused unless it is a non-empty list of owner/name by
    triage_state.py's rule with no repo twice, in a table without home"""
    if repos is None:
        if not has_home:
            raise Refused(f"error: {policy}: [product] sets neither home (in a component) nor repos (in the home repo)")
        return None
    if has_home:
        raise Refused(f"error: {policy}: [product] home and repos can't both be set; a repo is the home or a component")
    if not repos:
        raise Refused(f"error: {policy}: [product] repos must list at least one repo")
    seen: set[str] = set()
    for repo in repos:
        if not TRIAGE.home_repo(repo):
            raise Refused(f"error: {policy}: [product] repos holds {repo!r}; each repo is owner/name")
        if repo.lower() in seen:
            raise Refused(f"error: {policy}: [product] repos lists {repo} twice")
        seen.add(repo.lower())
    return tuple(repos)


def product_repos_310(text: str, policy: Path) -> tuple[str, ...] | None:
    """[product] repos on Python 3.10: a plain [product] table whose repos is a one-line list
    of strings and whose other keys are home alone; any other form is refused rather than
    misread. product_home_310 checks the headers and home"""
    home = product_home_310(text, policy)
    tables = toml_tables(text)
    if "product" not in tables:
        return None
    headers = [TOML_HEADER.match(line) for line in text.splitlines()]
    if sum(1 for h in headers if h is not None and h.group(1) == "[" and h.group(2).strip("\"' ") == "product") > 1:
        # toml_tables keeps the last of two [product] tables, which tomllib refuses: refused too
        raise Refused(f"error: {policy}: [product] is declared twice; keep one [product] table")
    if standalone_310(tables["product"], policy):
        return None
    repos: list[str] | None = None
    for line in tables["product"].splitlines():
        if blank(line) or PRODUCT_HOME.match(line):
            continue
        found = PRODUCT_REPOS_VALUE.match(line)
        if found is None or repos is not None:
            raise Refused(f"error: {policy}: can't read [product] on Python 3.10: use 3.11+ ({line.strip()!r})")
        inner = found.group(1).strip().rstrip(",")
        items = [PRODUCT_LIST_ITEM.fullmatch(part) for part in inner.split(",")] if inner.strip() else []
        if any(item is None for item in items):
            raise Refused(f"error: {policy}: can't read [product] repos on Python 3.10: use 3.11+ ({line.strip()!r})")
        repos = [item.group(1) if item.group(1) is not None else item.group(2) for item in items if item is not None]
    return checked_repos(home is not None, repos, policy)


def gh_writer(repo_dir: Path) -> list[str]:
    """The command a skill script's writing gh call starts with (spec 012, #290): with [agents]
    app_id set in the checkout's config, `shipmill gh` run as `uvx shipmill==<the plugin's
    version>`, as the skills run it (spec 031), so
    the write posts as the App; else plain gh, the host's login. A config this reader refuses
    raises Refused rather than reading as no App, and so does an app_id key the reader didn't
    find in [agents] (Python 3.10's fallback skips a header it can't parse). Reads keep plain gh.
    The config is the checkout's, found from a subfolder as `shipmill gh` finds it"""
    here = repo_dir.resolve()
    top = next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), here)
    path = top / POLICY
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    table = agents_table(text, path) if text else None
    if table is None or "app_id" not in table:
        if APP_ID_KEY.search(text):
            raise Refused(f"error: {path}: app_id is set but not read from a plain [agents] table; fix the file")
        return ["gh"]
    return [*shipmill_cli(), "--repo", str(top), "gh"]


def session_rows(text: str, repo: str, repo_dir: Path, now: dt.datetime) -> list[Row]:
    """`claude agents --json`'s sessions working the repo: the gate's, by name, and any whose
    folder is in the checkout"""
    try:
        sessions = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"error: claude agents --json printed no JSON: {exc}") from None
    if not isinstance(sessions, list):
        raise Refused("error: claude agents --json: expected a JSON array")
    rows = []
    for s in sessions:
        if not isinstance(s, dict) or not isinstance(s.get("startedAt"), int):
            raise Refused(f"error: claude agents --json printed a session without startedAt: {s!r}")
        name, cwd = str(s.get("name") or ""), Path(str(s.get("cwd") or "/"))
        gate = name == GATE_SESSION + repo or name.startswith(f"{GATE_SESSION}{repo} ")
        if not gate and cwd != repo_dir and repo_dir not in cwd.parents:
            continue
        started = dt.datetime.fromtimestamp(s["startedAt"] / 1000, tz=dt.timezone.utc)  # noqa: UP017
        status = "/".join(str(s[k]) for k in ("status", "state") if s.get(k))
        who = "gate" if gate else str(s.get("kind") or "session")
        detail = f"{who} {status}, started {ago(now - started)} ago: {name or s.get('sessionId', '')}"
        rows.append(Row("AGENT_SESSION", str(s.get("id") or s.get("pid") or ""), detail))
    return rows


def gate_label(repo: str) -> str:
    """The gate's launchd label, as shipmill's launchd.label builds it"""
    owner, _, name = repo.partition("/")
    return "dev.shipmill.gate." + re.sub(r"[^a-z0-9.-]", "-", f"{owner}.{name}".lower())


def loop_row(
    label: str, plist: dict[str, object] | None, printed: str | None, log: str | None, now: dt.datetime
) -> Row:
    """The gate's launchd job: from its plist, `launchctl print` (None when not loaded), and
    its log's text (None without a log)"""
    if plist is None:
        return Row("LOOP", "none", "no launchd job runs shipmill gate for this repo (shipmill launchd)")
    interval = plist.get("StartInterval")
    parts = [f"launchd every {ago(dt.timedelta(seconds=interval))}" if isinstance(interval, int) else "launchd"]
    if printed is None:
        parts.append("installed but not loaded")
    else:
        state = re.search(r"^\tstate = (.+)$", printed, re.MULTILINE)
        code = re.search(r"^\tlast exit code = (.+)$", printed, re.MULTILINE)
        parts.append(state.group(1) if state else "state unknown")
        if code:
            parts.append(f"last exit {code.group(1)}")
    if log is not None:
        decisions = [line for line in log.splitlines() if GATE_DECISION.match(line)]
        if decisions:
            parts.append(f"last: {decisions[-1]}")
    return Row("LOOP", label, "; ".join(parts))


def gate_plist(repo: str) -> dict[str, object] | None:
    """The gate's launchd job for the repo, on a Mac; None without one"""
    path = LAUNCH_AGENTS / f"{gate_label(repo)}.plist"
    if sys.platform != "darwin" or not path.is_file():
        return None
    with path.open("rb") as handle:
        found = plistlib.load(handle)
    if not isinstance(found, dict):
        raise Refused(f"error: {path} is not a launchd job")
    return found


def agent_rows(repo: str, repo_dir: Path, now: dt.datetime) -> list[Row]:
    """The sessions and, on a Mac, the gate's launchd job; what this host can see"""
    claude = shutil.which("claude")
    if claude is None:
        rows = [Row("HOST_UNKNOWN", "claude", "not on PATH: the agent sessions weren't read")]
    else:
        rows = session_rows(run([claude, "agents", "--json"]), repo, repo_dir, now)
    if sys.platform != "darwin":
        return rows
    label = gate_label(repo)
    plist = gate_plist(repo)
    if plist is None:
        return [*rows, loop_row(label, None, None, None, now)]
    proc = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True, check=False
    )
    printed = proc.stdout if proc.returncode == 0 else None
    log_path = plist.get("StandardOutPath")
    log = Path(log_path).read_text(errors="replace") if isinstance(log_path, str) and Path(log_path).is_file() else None
    dead = dead_rows(label, log, log_path if isinstance(log_path, str) else None)
    return [*rows, loop_row(label, plist, printed, log, now), *dead]


def dead_rows(label: str, log: str | None, log_path: str | None) -> list[Row]:
    """#500: GATE_SESSIONS_DEAD when the gate log's last decision is SESSION_DEAD, the gate's
    sessions ending right after they start (a run of them in a row when it says so). The fix is
    the one the gate wrote last on the line when it is `claude auth login`, a token file's
    `claude setup-token` fix (spec 035), a `tail` of the
    session's log, or an interactive session's `claude logs <id>`, else a tail of the gate's
    own log"""
    decisions = [line for line in (log or "").splitlines() if GATE_DECISION.match(line)]
    if not decisions or not decisions[-1].startswith(SESSION_DEAD):
        return []
    line = decisions[-1]
    named = line.rpartition("; fix: ")[2]  # the gate writes its fix last, after the session log's line
    # claude logs <id>: an interactive session's, which leaves no log of the gate's
    if (
        named == AUTH_FIX
        or TOKEN_FIX.fullmatch(named)
        or re.fullmatch(r"tail -n 20 \S+\.log|claude logs [\w-]+", named)
    ):
        fix = named
    elif log_path is not None:
        fix = f"tail -n 50 {shlex.quote(log_path)}"
    else:
        fix = f"launchctl print gui/{os.getuid()}/{label}"
    return [Row("GATE_SESSIONS_DEAD", label, line[len(SESSION_DEAD) :], fix)]


def plugin_fix(scope: str, where: str | None, keyed: list[tuple[str, Path]]) -> str:
    """The command that updates one install, run in its folder. Claude Code's `plugin update
    --scope project` picks an install at the same scope keyed on a folder nested in the cwd,
    such as the gate's tmp/shipmill-gate, over the cwd's own (#233, a Claude Code bug); with
    one nested, the fix reinstalls the folder's own at that scope instead. Either way it
    refreshes the marketplace first: Claude Code updates from its local copy of it, which may
    predate the release (#477); the refresh isn't folder-specific, so it runs there too"""
    refresh = f"claude plugin marketplace update {PLUGIN.partition('@')[2]}"
    update = f"{refresh} && claude plugin update {PLUGIN} --scope {scope}"
    if where is None:
        return update
    folder = Path(where)
    nested = sorted(p for s, p in keyed if s == scope and folder in p.parents)
    if not nested:
        return f"in {where}: {update}"
    again = (
        f"{refresh} && claude plugin uninstall {PLUGIN} --scope {scope}"
        f" && claude plugin install {PLUGIN} --scope {scope}"
    )
    return f"in {where}: {again} (`update` picks the nested install in {nested[0]}, a Claude Code bug)"


INSTALLED = "~/.claude/plugins/installed_plugins.json"  # Claude Code's record of installs, never written


def unloaded_fix(where: str) -> str:
    """S-031-16: an install keyed on a linked worktree is reached by no `claude plugin` command
    run there, so its entry is deleted by hand; shipmill's plugin.unloaded_fix, the same text"""
    return f'delete the entry with "projectPath": "{where}" under "{PLUGIN}" in {INSTALLED}'


SESSION_PRECEDENCE = ("local", "project", "user", "managed")


def session_install(
    keyed: list[tuple[str, Path]], unkeyed: list[tuple[str, str]], versions: dict[tuple[str, Path], str], project: Path
) -> tuple[str, str] | None:
    """The scope and version of the install a session in the project loads (D-35), as
    shipmill's gate reads it (plugin.py's effective()): the most specific scope the plugin is
    installed at for the project, local, then project, then user, then managed; None without"""
    for scope in SESSION_PRECEDENCE:
        found = [versions[(s, p)] for s, p in keyed if s == scope and p == project]
        found += [v for s, v in unkeyed if s == scope]
        if len(found) > 1:
            raise Refused(f"error: claude plugin list --json lists {PLUGIN} twice at {scope} scope for {project}")
        if found:
            return scope, found[0]
    return None


PATH_CLI = "shipmill on PATH"  # the subject of the person's CLI's SHIPMILL_OUTDATED row (#583)
UV_UPGRADE = "uv tool upgrade shipmill"  # the fix for a lagging `uv tool install shipmill`, shipmill's launchd.UPGRADE
CLI_VERSION = re.compile(r"shipmill (\d+\.\d+\.\d+)")  # what `shipmill --version` prints (S-031-25), matched whole
VERSION_TIMEOUT = 10.0  # seconds a shipmill on PATH has to answer --version
ANSWER_SHOWN = 80  # characters of an answer that isn't `shipmill X.Y.Z` its row shows (#628)
UV_CACHE_ENVS = re.compile(r"archive-v\d+|environments-v\d+")  # the folders of uv's cache holding uvx's environments


@dataclass(frozen=True)
class PathCli:
    """The person's shipmill on PATH (#583): its path as PATH names it, and the version its
    --version printed; None for a release from before --version, which answers it exit 2, for
    one that never answered, whose reason is silent (a timeout, or it can't start), and for one
    that exits 0 printing something else, whose answer is its first line, bounded (#628)"""

    path: Path
    version: str | None
    silent: str | None = None
    answer: str | None = None


def shown_answer(stdout: str) -> str:
    """What a row shows of a --version answer that isn't `shipmill X.Y.Z`: its first line,
    cut to ANSWER_SHOWN characters; the row quotes it with control characters escaped"""
    lines = stdout.strip().splitlines()
    first = lines[0] if lines else ""
    return first if len(first) <= ANSWER_SHOWN else first[:ANSWER_SHOWN] + "..."


class NoAnswer(Exception):
    """A shipmill on PATH that never answered --version: it timed out or couldn't start. A row,
    never a stop: the gate reads this script every tick, and only PyPI holds a session (D-50)"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def own_environments(prefix: str = sys.prefix, script: Path = Path(__file__)) -> tuple[Path, ...]:
    """The environment running the check: the interpreter's, and the virtual environment that
    holds this script, when one does (the one `uvx shipmill==<version> status` puts first on
    PATH for its own run, #236)"""
    found = [Path(prefix).resolve()]
    held = next((p for p in script.resolve().parents if (p / "pyvenv.cfg").is_file()), None)
    if held is not None and held not in found:
        found.append(held)
    return tuple(found)


def uvx_environment(program: Path) -> bool:
    """Whether a resolved program lives in an environment uv's cache made for one uvx run
    (<cache>/archive-v0/<id>/, the folder holding pyvenv.cfg): another run's, such as the gate's
    `uvx shipmill@latest`, whose bin its sessions inherit first on PATH, never a person's
    install; a `uv tool install` lives in uv's tools folder instead"""
    held = next((p for p in program.parents if (p / "pyvenv.cfg").is_file()), None)
    return held is not None and UV_CACHE_ENVS.fullmatch(held.parent.name) is not None


def path_shipmill(path: str, environments: Sequence[Path]) -> Path | None:
    """The first `shipmill` on path outside the environments: a folder whose `shipmill`
    resolves into one of them is skipped, as shipmill's cli_command() skips it (#236), and so is
    one in an environment of uv's cache, a uvx run's own. An empty or relative entry names the
    working folder, a checkout that may be a pull request's, so it is never searched"""
    for folder in path.split(os.pathsep):
        if not folder or not os.path.isabs(folder):
            continue
        found = shutil.which("shipmill", path=folder)
        if found is None:
            continue
        resolved = Path(found).resolve()
        if any(resolved == env or env in resolved.parents for env in environments) or uvx_environment(resolved):
            continue
        return Path(found)
    return None


def answer_version(program: Path, timeout: float = VERSION_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """`<program> --version`, given PATH and HOME only, never the watch's tokens, and timeout
    seconds; one that doesn't answer in time or can't start raises NoAnswer with the reason"""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())}
    try:
        return subprocess.run(
            [str(program), "--version"],
            capture_output=True,
            text=True,
            errors="replace",  # an arbitrary program's bytes: never a decode error (#628)
            check=False,
            env=env,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise NoAnswer(f"timed out after {timeout:g} s") from None
    except OSError as exc:
        raise NoAnswer(f"can't start: {exc.strerror or exc}") from None


def path_cli(
    path: str | None = None,
    environments: Sequence[Path] | None = None,
    execute: Callable[[Path], subprocess.CompletedProcess[str]] = answer_version,
) -> PathCli | None:
    """The person's shipmill (S-031-26): the first on path (default: $PATH) outside the
    environment running the check, with the version its --version printed; None without one. A
    non-zero exit predates --version (S-031-27), one that never answers is silent, and an exit 0
    that isn't `shipmill X.Y.Z` keeps its answer: all rows, never a stop, since the gate reads
    this script every tick (#628)"""
    searched = os.environ.get("PATH", "") if path is None else path
    program = path_shipmill(searched, own_environments() if environments is None else environments)
    if program is None:
        return None
    try:
        proc = execute(program)
    except NoAnswer as silent:
        return PathCli(program, None, silent.reason)
    if proc.returncode != 0:
        return PathCli(program, None)
    found = CLI_VERSION.fullmatch(proc.stdout.strip())
    if found is None:
        return PathCli(program, None, answer=shown_answer(proc.stdout))
    return PathCli(program, found.group(1))


def path_cli_row(cli: PathCli, plugin: str, update: str) -> Row | None:
    """S-031-26, S-031-27: the person's shipmill against the plugin a session loads (plugin, its
    version), one SHIPMILL_OUTDATED row when they differ. Older, or from before --version: uv's
    upgrade. Newer: the plugin is behind, so update, S-031-15's update of that install. None
    when they match. One that never answered is the row too, with its reason and uv's upgrade,
    and so is one whose exit 0 printed something else, with that answer quoted (#628)"""
    if cli.silent is not None:
        detail = f"{cli.path} doesn't answer shipmill --version: {cli.silent}, the plugin is {plugin}; {UV_UPGRADE}"
        return Row("SHIPMILL_OUTDATED", PATH_CLI, detail, UV_UPGRADE)
    if cli.answer is not None:
        detail = f"{cli.path} answers shipmill --version with {cli.answer!r}, the plugin is {plugin}; {UV_UPGRADE}"
        return Row("SHIPMILL_OUTDATED", PATH_CLI, detail, UV_UPGRADE)
    if cli.version is None:
        detail = f"{cli.path} predates shipmill --version, the plugin is {plugin}; {UV_UPGRADE}"
        return Row("SHIPMILL_OUTDATED", PATH_CLI, detail, UV_UPGRADE)
    mine, theirs = version_key(f"v{cli.version}"), version_key(f"v{plugin}")
    if mine is None or theirs is None:
        raise Refused(f"error: can't compare shipmill {cli.version!r} on PATH with the plugin's {plugin!r}")
    if mine == theirs:
        return None
    fix = UV_UPGRADE if mine < theirs else update
    return Row("SHIPMILL_OUTDATED", PATH_CLI, f"{cli.path} is {cli.version}, the plugin is {plugin}; {fix}", fix)


def plugin_rows(
    plugins: object,
    marketplaces: object,
    latest: str,
    folders: list[Path],
    gates: list[Path] | None = None,
    session: Path | None = None,
    cli: Callable[[], PathCli | None] | None = None,
) -> list[Row]:
    """The plugin's installs that apply to the repo, against the latest release: from `claude
    plugin list --json` and `claude plugin marketplace list --json`, parsed (None when claude
    isn't on PATH). An install applies at user scope, or at local or project scope in one of
    the folders (the projects Claude Code loads). Each install behind the release is its own
    SHIPMILL_OUTDATED row, with the fix to run in its folder (S-031-15). An install keyed on
    one of the gates that isn't one of the folders (a gate checkout that is a linked worktree,
    which Claude Code keys installs of their own on, #233, but never loads, #485) is its own
    SHIPMILL_OUTDATED row too, at any version, whose fix deletes its entry by hand (S-031-16).
    session, the project a session in the gate's folder loads as, adds the install that
    session would load to SHIPMILL_VERSION, and says when it is behind; the gate reports it
    and still starts sessions (spec 031). cli, read only when a session loads an install, is
    the person's shipmill on PATH (path_cli), compared with that install's version (#583)"""
    newest = version_key(latest)
    if newest is None:
        raise Refused(f"error: {SHIPMILL_REPO}'s latest release {latest!r} is not a version tag")
    if plugins is None:
        return [Row("SHIPMILL_VERSION", "shipmill", f"latest {latest}; plugin: claude isn't on PATH, not read")]
    if not isinstance(plugins, list):
        raise Refused("error: claude plugin list --json: expected a JSON array")
    installs = []
    keyed = []  # every scope and folder an install of the plugin is keyed on
    unkeyed = []  # the user- and managed-scope installs: scope and version
    versions = {}
    for e in plugins:
        if not isinstance(e, dict) or e.get("id") != PLUGIN:
            continue
        if not isinstance(e.get("scope"), str) or not isinstance(e.get("version"), str):
            raise Refused(f"error: claude plugin list --json: {PLUGIN} install {e!r}")
        where = e.get("projectPath")
        if where is not None and not isinstance(where, str):
            raise Refused(f"error: claude plugin list --json: {PLUGIN} install {e!r}")
        if where is not None:
            keyed.append((e["scope"], Path(where)))
            versions[(e["scope"], Path(where))] = e["version"]
        elif e["scope"] in ("user", "managed"):
            unkeyed.append((e["scope"], e["version"]))
        if e["scope"] == "user" or (where is not None and (Path(where) in folders or Path(where) in (gates or []))):
            installs.append((e["scope"], e["version"], where))
    rows = []
    for scope, version, where in installs:
        key = version_key(f"v{version}")
        if key is None:
            raise Refused(f"error: {PLUGIN} {scope} install has version {version!r}")
        if where is not None and Path(where) not in folders:  # keyed on a gate checkout no session loads
            fix = unloaded_fix(where)
            detail = f"{version}, keyed on the gate's linked worktree {where}, which no session loads; {fix}"
            rows.append(Row("SHIPMILL_OUTDATED", f"plugin {scope}", detail, fix))
        elif key < newest:
            fix = plugin_fix(scope, where, keyed)
            rows.append(Row("SHIPMILL_OUTDATED", f"plugin {scope}", f"{version}, latest {latest}; {fix}", fix))
    found = ", ".join(f"{scope} {version}" + (f" ({where})" if where else "") for scope, version, where in installs)
    detail = f"latest {latest}; plugin: {found or 'not installed for this repo on this host'}"
    if session is not None:
        loads = session_install(keyed, unkeyed, versions, session)
        if loads is None:
            detail += f"; a session loads none ({session})"
        else:
            key = version_key(f"v{loads[1]}")
            if key is None:
                raise Refused(f"error: {PLUGIN} {loads[0]} install has version {loads[1]!r}")
            behind = f", older than {latest}" if key < newest else ""
            detail += f"; a session loads {loads[0]} {loads[1]} ({session}){behind}"
            person = None if cli is None else cli()
            if person is not None:
                where = str(session) if loads[0] in ("local", "project") else None
                row = path_cli_row(person, loads[1], plugin_fix(loads[0], where, keyed))
                rows += [] if row is None else [row]
    market = PLUGIN.partition("@")[2]
    for m in marketplaces if isinstance(marketplaces, list) else []:
        origin = m.get("repo") if isinstance(m, dict) and m.get("name") == market else None
        if isinstance(origin, str) and origin.lower() != SHIPMILL_REPO:
            detail += f"; marketplace source {origin}, now {SHIPMILL_REPO}"
    return [Row("SHIPMILL_VERSION", "shipmill", detail), *rows]


def claude_json(claude: str, *args: str) -> object:
    out = run([claude, *args, "--json"])
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise Refused(f"error: claude {' '.join(args)} --json printed no JSON: {exc}") from None


def main_checkout(folder: Path, common_dir: str) -> Path:
    """The project Claude Code keys a folder's local and project installs on: a linked git
    worktree's main checkout, given `git rev-parse --git-common-dir` (#198); the folder itself
    otherwise"""
    common = Path(common_dir.strip())
    return common.parent if common.name == ".git" else folder


def project_folder(folder: Path) -> Path:
    """main_checkout() of a folder on disk; a missing folder, or one outside git, is its own"""
    if not folder.is_dir():
        return folder
    cmd = ["git", "-C", str(folder), "rev-parse", "--path-format=absolute", "--git-common-dir"]
    # LC_ALL=C: the "not a git repository" check reads git's message, which a localized git translates
    env = {**os.environ, "LC_ALL": "C"}
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if proc.returncode != 0 and "not a git repository" in proc.stderr:
        return folder
    if proc.returncode != 0:
        sys.stderr.write(f"error: git rev-parse in {folder}: {proc.stderr.strip()}\n")
        raise SystemExit(2)
    return main_checkout(folder, proc.stdout)


def plugin_folders(repo_dir: Path, workdir: Path | None) -> tuple[list[Path], list[Path]]:
    """The projects Claude Code loads for the checkout and the gate's working directory, and
    the gate's checkouts, keyed apart from them (#233): the conventional tmp/shipmill-gate,
    the working directory, and the checkout itself when either is a linked worktree. A
    tmp/shipmill-gate that is a clone of its own is a project too, whose installs its sessions
    load"""
    main = project_folder(repo_dir)
    folders, gates = [main], [main / GATE_CHECKOUT]
    conventional = main / GATE_CHECKOUT
    if conventional.is_dir() and project_folder(conventional) == conventional:  # a clone of its own, not a worktree
        folders.append(conventional)
    for folder in [repo_dir] if workdir is None else [repo_dir, workdir]:
        project = project_folder(folder)
        if project not in folders:
            folders.append(project)
        if folder != project and folder not in gates:
            gates.append(folder)
    return folders, gates


def latest_release(execute: Callable[[list[str]], str] = run) -> str:
    """shipmill's latest release tag: the ref of the marketplace entry on shipmill/shipmill's
    default branch (S-031-2), never `gh release view`: an install can only be updated to what
    the marketplace serves"""
    return marketplace_release(execute(READ_MARKETPLACE))


def shipmill_rows(repo: str, repo_dir: Path) -> list[Row]:
    """The host's shipmill plugin against shipmill's latest release, the marketplace's (S-031-2)"""
    latest = latest_release()
    plist = gate_plist(repo)
    workdir = plist.get("WorkingDirectory") if plist else None
    folders, gates = plugin_folders(repo_dir, Path(workdir) if isinstance(workdir, str) else None)
    session = project_folder(gate_folder(repo_dir, workdir if isinstance(workdir, str) else None))
    claude = shutil.which("claude")
    if claude is None:
        return plugin_rows(None, None, latest, folders, gates)
    plugins = claude_json(claude, "plugin", "list")
    market = claude_json(claude, "plugin", "marketplace", "list")
    return plugin_rows(plugins, market, latest, folders, gates, session, path_cli)


def gate_folder(repo_dir: Path, workdir: str | None) -> Path:
    """The folder the gate starts its sessions in: launchd's working directory, else the
    conventional tmp/shipmill-gate beside the main checkout when it exists, else the checkout"""
    if workdir is not None:
        return Path(workdir)
    beside = project_folder(repo_dir) / GATE_CHECKOUT
    return beside if beside.is_dir() else repo_dir


def skill_names() -> list[str]:
    """shipmill's skills: the folders beside this skill's that hold a SKILL.md"""
    return sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))


def shadow_rows(home: Path, names: list[str]) -> list[Row]:
    """The links and copies of shipmill's skills, named in names, in the home folder's user
    skills (~/.claude/skills, ~/.agents/skills): a prompt's /<name> loads one of them in place
    of the plugin's (#236). A link into the plugin's cache is the plugin's own. A person's fix
    in their home folder, never an agent's. Only a folder with a SKILL.md loads as a skill, so
    a broken link or a plain file of that name shadows nothing"""
    cache = (home / PLUGIN_CACHE).resolve()
    rows = []
    for folder in USER_SKILLS:
        for name in names:
            path = home / folder / name
            if not (path / "SKILL.md").is_file():
                continue
            target = path.resolve()
            if target == cache or cache in target.parents:
                continue
            what, remove = (f"a link to {target}", f"rm {path}") if path.is_symlink() else ("a copy", f"rm -r {path}")
            fix = f"remove it ({remove}) or call the skill as /shipmill:{name}"
            rows.append(
                Row("SKILL_SHADOWED", name, f"{path} is {what}: /{name} loads it, not the plugin's; {fix}", fix)
            )
    return rows


# -- repository settings -------------------------------------------------------------------


def settings_rows(repo: str, delete_on_merge: object) -> list[Row]:
    """The repo settings the pipeline relies on, from `gh repo view`; a value that isn't a
    boolean is refused, never guessed"""
    if not isinstance(delete_on_merge, bool):
        raise Refused(f"error: gh repo view {repo}: deleteBranchOnMerge is {delete_on_merge!r}, not a boolean")
    if delete_on_merge:
        return []
    fix = f"gh repo edit {repo} --delete-branch-on-merge"
    return [Row("BRANCH_DELETE_OFF", repo, f"merged PR branches stay on GitHub; turn it on: {fix}", fix)]


# -- workflows -----------------------------------------------------------------------------


def active_rows(runs: list[ActiveRun], now: dt.datetime) -> list[Row]:
    """The queued and running workflow runs, oldest first"""
    return [
        Row("RUNS_ACTIVE", r.workflow, f"{r.status} {ago(now - r.created)}: {r.event} on {r.branch}, {r.url}")
        for r in sorted(runs, key=lambda r: r.created)
        if r.status in ACTIVE
    ]


def fetch_active(repo: str) -> list[ActiveRun]:
    """The repo's newest runs of every workflow; a run still active is among them"""
    fields = "workflowName,status,event,headBranch,createdAt,url"
    out = run(["gh", "run", "list", "-R", repo, "-L", "100", "--json", fields])
    return [
        ActiveRun(r["workflowName"], r["status"], r["event"], r["headBranch"], parse_time(r["createdAt"]), r["url"])
        for r in json.loads(out)
    ]


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--repo-dir", default=".", help="local checkout (default: cwd)")
    parser.add_argument("--releases", type=int, default=3, help="newest version tags to check")
    parser.add_argument("--grace", type=int, default=20, help="minutes a run or an upload may take")
    parser.add_argument(
        "--tool", help="where uvx gets shipmill (default: shipmill==<the version in the plugin's plugin.json>)"
    )
    parser.add_argument("--incident-label", help="the label incidents carry (default: the config's)")
    parser.add_argument("--json", action="store_true", help="JSON lines instead of a table")
    parser.add_argument("--bot-login", help="the login shipmill's sessions write as, such as <slug>[bot]")
    parser.add_argument(
        "--trusted-only", action="store_true", help="leave untrusted issues and fork pull requests to UNTRUSTED (D-16)"
    )
    parser.add_argument(
        "--role",
        action="append",
        default=[],
        metavar="NAME=FILLER[,FILLER...]",
        help="a role's resolved fillers, passed to triage_state.py; one per role, maintainer included (spec 036)",
    )
    return parser


def main() -> int:
    parser = arguments()
    args = parser.parse_args()
    if args.incident_label is not None and not args.incident_label.strip():
        parser.error("--incident-label must not be empty")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login must not be empty")
    if args.role:  # checked by triage_state.py's rule before any read, so a bad flag reads nothing
        try:
            TRIAGE.parse_roles(args.role)
        except ValueError as exc:
            parser.error(str(exc))
    if "/" not in args.repo:
        parser.error("repo must be owner/name")
    if not 1 <= args.releases <= 20:
        parser.error("--releases must be 1..20")
    repo_dir = Path(args.repo_dir).resolve()
    if policy_file(repo_dir) is not None:  # first, as shipmill checks it before the config's other keys
        check_requires((repo_dir / POLICY).read_text(encoding="utf-8"), POLICY)
    now = dt.datetime.now(dt.timezone.utc)  # noqa: UP017 (dt.UTC needs 3.11)
    grace = dt.timedelta(minutes=args.grace)

    view = json.loads(run(["gh", "repo", "view", args.repo, "--json", "defaultBranchRef,deleteBranchOnMerge"]))
    policy = policy_file(repo_dir)
    config_text = None if policy is None else (repo_dir / policy).read_text(encoding="utf-8")
    branch = landing_branch(config_text, POLICY, view["defaultBranchRef"]["name"])
    run(["git", "fetch", "-q", "--force", "--tags", "origin", branch], cwd=repo_dir)

    rows: list[Row] = settings_rows(args.repo, view["deleteBranchOnMerge"])
    bot = bot_workflow(repo_dir)
    if bot is None or policy is None:
        rows.append(Row("BOT_NONE", args.repo, 'no release policy: releases by "tag X"'))
    else:
        workflow, shipmill = bot
        due, failed = bot_plan(args.repo, repo_dir, policy, branch, args.tool, workflow) if shipmill else (None, [])
        rows += failed
        # the branches before the runs: a run that ends between the two reads deleted its branch
        branches = work_branches(repo_dir) if shipmill else {}
        runs = fetch_runs(args.repo, workflow)
        rows += bot_rows(runs, due, now, grace, workflow, args.repo)
        # an older run can still own the branch behind newer finished ones, so the owners
        # are asked by status; only with a branch, so a normal pass makes no extra call
        owners = fetch_unfinished(args.repo, workflow) if branches else []
        rows += work_branch_rows(branches, owners, workflow, args.repo)
        if shipmill:  # after the plan, whose own worktree is gone by then
            rows += stale_worktrees(repo_dir, args.tool, branch)
            rows += milestones(repo_dir, policy, args.tool)

    tags = version_tags(repo_dir)
    package = package_name(repo_dir)
    project = pypi_json(package) if package is not None else None
    registered = project is not None
    first = first_upload(project, package) if package is not None and project is not None else None
    asked: dict[int, None] = {}  # the issues a pre-release told, whose requester may have answered
    for i, tag in enumerate(tags[: args.releases]):
        listed = on_pypi(f"{package}/{tag.name[1:]}") if registered else None
        row = publish_row(
            tag,
            package if registered else None,
            listed,
            now,
            grace,
            first,
            repo=args.repo,
            runs_on=lambda name: fetch_tag_runs(args.repo, name),
        )
        rows.append(row)
        if row.state in {"PUBLISHED", "NO_REGISTRY"} and i + 1 < len(tags):
            issues, told = shipped_plan(args.repo, repo_dir, tags[i + 1].name, tag.name)
            if issues:
                rows.append(unannounced_row(args.repo, tag.name, tags[i + 1].name, issues))
            if pre_release(tag.name):
                asked.update((int(n.lstrip("#")), None) for n in told)
    rows += answers_rows(
        args.repo, list(asked), now, lambda n: fetch_view(args.repo, n), lambda url: fetch_reactions(args.repo, url)
    )

    table = None
    upgrades = None
    home = None
    text = None
    land = None  # the effective [autonomy] land level, None without [agents]: no gate lands anything
    if policy is not None:
        text = (repo_dir / policy).read_text(encoding="utf-8")
        table = agents_table(text, policy)
        # shipmill asks for the direction only in a repo with [agents] (spec 034)
        direction = direction_state(table, args.repo, repo_dir, branch, args.tool, args.bot_login)
        # read before the triage mode, which names the levels under the hold, and listed after it
        holds = hold_rows(fetch_issues(args.repo, "--label", HOLD_LABEL), now, args.repo)
        rows.append(triage_mode_row(text, policy, direction.declined, bool(holds)))
        rows += direction.rows
        home = product_home(text, policy)
        rows += gate_app_rows(table)
        read = config(text, policy, args.incident_label)
        rows += holds
        land = None if table is None else held_land(read.land, bool(holds))
        closed = fetch_issues(args.repo, "--label", read.incident_label, state="closed")
        if closed:  # the postmortems are read only once an incident has closed
            texts = postmortem_texts(args.repo, branch)
            rows += postmortem_rows(closed, read.incident_label, texts, args.repo, now)
        if read.environments:
            names, label = [t.name for t in tags], read.incident_label
            rows += operations_rows(args.repo, repo_dir, read.environments, bool(holds), label, now, names)
        upgrades = upgrade_rows(
            fetch_issues(args.repo, "--label", UPGRADE_LABEL),
            read.upgrade,
            bool(holds),
            lambda n: pr_comments(args.repo, n),
            lambda name: declined_prs(args.repo, name),
            args.repo,
            args.bot_login,
        )  # its rows come with the intake's, which knows which issues triage_state.py trusts

    plans = Plans([], frozenset())
    unplanned = None  # PyPI's wait for the plans' pinned shipmill (#597)
    if (repo_dir / DIRECTION).is_file():  # a goal's plan needs goals (spec 028)
        try:
            lines = plans_run(args.repo, repo_dir, args.tool, args.bot_login, plan_wip(table, POLICY))
            plans = plans_rows(lines, args.repo, args.bot_login, args.trusted_only)
        except PypiWait as wait:
            unplanned = wait
    rows += plans.rows
    if unplanned is not None and args.trusted_only:
        # the plan issues the --bot-login didn't open are unknown, so no issue or pull request
        # is read either: one of them could start a session (D-16)
        rows.append(pypi_wait_row(unplanned.version, "plans, issues, and pull requests"))
    else:
        rows += [] if unplanned is None else [pypi_wait_row(unplanned.version, "plans")]
        code, triage = triage_run(args.repo, args.bot_login, args.trusted_only, home, args.role)
        # the open direction issues, from triage_state.py's lines: no gh call of their own (spec 034)
        directions = triage_directions(triage) if table is not None else frozenset()
        rows += intake_rows(
            args.repo,
            code,
            triage,
            args.bot_login,
            args.trusted_only,
            land,
            upgrades,
            plans.untrusted,
            now,
            directions,
        )
        rows += chain_rows(args.repo, triage, args.bot_login)
    rows += coordinator_rows(text, policy, args.repo, repo_dir, args.bot_login)
    rows += active_rows(fetch_active(args.repo), now)
    rows += agent_rows(args.repo, repo_dir, now)
    rows += shipmill_rows(args.repo, repo_dir)
    rows += shadow_rows(Path.home(), skill_names())
    rows = merged_waits(rows)
    for row in ordered(rows):
        print(json.dumps(row.json(), sort_keys=True) if args.json else row.text())
    return 1 if any(r.state in ACTION for r in rows) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as refused:
        sys.stderr.write(f"{refused}\n")
        raise
