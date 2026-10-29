"""shipmill: release lanes driven by a hand-written CHANGELOG.

  settle-minutes  how long to wait after a push for more merges
  plan            decide whether a lane releases now; JSON on stdout
  propose         open or update the issue for each release a plan proposed
  prepare         stamp a planned release into the checkout, optionally commit and push it
  land            push, tag, sync main, and publish a release commit that passed CI
  close-proposal  close the lane's proposal issue once land released it
  cleanup         delete a release commit's work branch
  sync            bring a stable release made off main into main's CHANGELOG (recovery)
  notes           print a release's notes
  operate         check environment health, promote after the bake, roll back; approve a proposal
  doctor          check that the repository is ready for the bot
  decide          the decision policy (spec 030): levels prints every zone with its level, its floor,
                  and where the level comes from (default, config, autonomy, or fixed), from the working
                  tree's config or --ref's; classify prints the zones code detects for --pr N or --files
                  PATH..., each with its level and reason, the strictest level, and the D-n candidates,
                  the levels read at --ref (default origin/HEAD), never from the change; --json for both
  autonomy        every stage's [autonomy] level (spec 040): triage, fix, land, release, each deploy
                  environment, rollback, intake, and upgrade, each configured, under the shipmill-hold
                  stop switch, and its source (default, config, prompt, or hold), from the config at --ref
                  (default origin/HEAD); --json for one JSON object with the open hold issues
  review          REVIEW.md, the review rubric (spec 024): check exits 1 naming the file, line, and rule
                  a structured section breaks; show prints the rubric for the files given with --path,
                  the root's and their directories' merged, as Markdown or --json; add-rule, protect,
                  set-cap, and retire edit one line (--dir DIR: DIR/REVIEW.md) and print it
  status          say whether the factory works or is stuck: a verdict, then a short summary with
                  a line per reason and a direct link per item, this host's machinery summed up
                  on one factory line; --rows for github-ship-watch's table, --json for its JSON
                  lines and an AUTONOMY line with every stage's level
  factory         read-only: this host's machinery for the repo, one line per check (gate,
                  sessions, github app, shipmill, checkout, worktrees), each run on its own;
                  --json for one JSON object (spec 044)
  milestones      read-only: with a lane that sets milestone = true, print MILESTONE_WAITING for a goal's
                  milestone waiting on its specs and MILESTONE_OVERTAKEN for an open milestone a stable
                  tag took, with the version to rename it to and the `gh api` rename, run through
                  shipmill gh; --json for one JSON object (spec 022)
  upgrade         list the config upgrades this repo hasn't decided or declined (spec 014); --apply <id>
                  makes one's edit in the checkout and commits nothing; --propose opens or updates
                  one shipmill-upgrade issue per pending upgrade, as land.yml runs it after a release
  roles           print who receives each step an agent can't do (spec 036): [agents.roles] resolved,
                  maintainer first (its listed users and teams, else the host's gh login), a role
                  nobody fills marked fallback with the maintainer's; --json for one JSON object,
                  --flags for triage_state.py's --role arguments
  init            write a starting policy, the calling workflow, and changelog.d/README.md for changelog
                  fragments (--no-fragments: no fragments; --operate: only the operate workflow,
                  adding rollback and each deploy.<env> to the existing policy's [autonomy];
                  --downstream: only the downstream tests workflow, for a policy with [downstream];
                  --caller: only the calling workflow, from the existing policy; --runs-on: the
                  release jobs' runner, a label or a JSON list of labels); the calling workflow's
                  schedule is the one the policy's triggers need
  gate            start a Claude Code session for the repo only when its state needs one; each tick,
                  held or not, prunes the worktrees that landed, as `worktrees --prune` does
  worktrees       list the repository's worktrees, each REMOVABLE once its work landed, or KEPT and why;
                  --prune removes the REMOVABLE ones and their local branches
  app-token       print a GitHub App installation token limited to one repo, cached while it has
                  10 minutes left (in the checkout, else under $XDG_CACHE_HOME/shipmill);
                  --git-credential answers as git's credential helper; --product, in the
                  product's home repo, prints the coordinator's token over the listed repos of
                  the repo's owner (spec 038)
  gh              run gh with the arguments that follow, as the repo's GitHub App when
                  [agents] app_id is set (the token limited to gh's -R/--repo, else origin's
                  repo); exits with gh's code. Without app_id a read runs as the host's gh
                  login and a write exits 2 unless [agents] identity = "host" or a leading
                  --as-host allows it (spec 037). Every gh call that writes in an agent
                  session goes through it. A leading --product OWNER/NAME runs it with the
                  coordinator's token, refusing commands that write code or pull requests (D-47)
  app-create      create the gate's GitHub App in one click: owner and visibility planned from the
                  repos holding .github/shipmill.toml, the key saved with mode 0600
  app-install     guide installing the App on more repos: the App's Install App page and what to pick
  product         read the product's direction, docs/product.md (spec 024): check its grammar, show it
                  or one section (--section, --json), list its ids; add, edit, and retire an item,
                  printing its line, an added one with an id its history never held; write,
                  replace, or clear a goal's measure line (measure, spec 027)
  evals           the agents' eval suite, evals/ (spec 025): check exits 1 naming each case and the
                  rule it breaks, without a model; a repository with no case under evals/ passes;
                  check --gate also exits 1 while the suite is short of 8 verdict, 4 decision,
                  4 finding, and 4 fix cases, the counts the gate turns on at; compare judges
                  a pull request's run against the default branch's (D-37)
  downstream      the downstream repositories' tests on a pull request (spec 032): start writes a
                  check per [downstream] repository on the head and dispatches each one's workflow
                  as the App; a fork's pull request waits for a person's workflow_dispatch,
                  pinned with --sha to the head they read; collect finds each run by its
                  shipmill-id and concludes its check

Exit codes: 0 done (a plan may skip); 1 doctor found a failure, status found a row that needs
action, factory found a problem or a check that failed to run, app-create or app-install left
a repo without the App, product check found a broken rule, review check found a malformed
REVIEW.md, evals check found a malformed case (or, with --gate, a suite short of the gate's
counts), evals compare found a regression or a run stopped at its budget, or downstream
start's --sha is no longer the pull request's head; 2 bad input or a refused state, such as an
edit of a file its check refuses, a malformed evals/cases.toml, or a missing or malformed
aggregate-result.json.
"""

import argparse
import dataclasses
import datetime as dt
import importlib.metadata
import json
import os
import re
import shlex
import shutil
import sys
import time
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import TextIO

from shipmill import (
    agent_as_person,
    cli_command,
    decide,
    evals,
    factory,
    fragments,
    plugin_clean,
    product,
    requires,
    review,
    roles,
    status,
)
from shipmill.agents import AgentsConfig, Credit, GhIdentity, ProductConfig, WriteAs, app_id_of, gh_identity_of
from shipmill.app import (
    CACHE,
    HELPERS,
    Api,
    Identity,
    NotInstalled,
    Openssl,
    Signer,
    UrllibApi,
    app_check,
    app_login,
    app_token,
    availability,
    cache_outside,
    check_key,
    credential,
    default_key,
    is_plain_repo,
    prepare_session,
    product_cache,
    product_token,
    require_key,
    resolve_gh,
    session_key,
)
from shipmill.app_create import (
    FLOW_SECONDS,
    accounts,
    check_key_dir,
    config_lines,
    convert,
    create,
    free_name,
    gated_repos,
    given_repos,
    host_token,
    owner_menu,
    pick_owner,
    plan,
)
from shipmill.app_gh import (
    GhRunner,
    Merge,
    MergeReader,
    MergeReads,
    as_app,
    as_host,
    bundled_repo_flag,
    find_gh,
    is_read,
    merge_flags,
    merge_of,
    named_repo,
    product_refusal,
    pull_url,
    repo_value,
    run_gh,
    with_body,
)
from shipmill.app_install import WAIT_SECONDS, guide
from shipmill.autonomy import Autonomy, AutonomyPolicy, EnvironmentName, Hold
from shipmill.classify import DEFAULT_REF, Base, Pulls, RepoPath, classify_paths, classify_pull, policy_at
from shipmill.claude_auth import ClaudeAuth, preflight_auth
from shipmill.claude_token import FLAG as TOKEN_FLAG
from shipmill.claude_token import Credential, Kind, Token, TokenSource, inspect, read_token
from shipmill.config import CONFIG_PATH, Table, config_path
from shipmill.config import read as read_config
from shipmill.credit import CreditReader, CreditReads, credited_body, deciders, default_body
from shipmill.doctor import CALLER, DOWNSTREAM_CALLER, OPERATE_CALLER, doctor, product_on_host, read_plugin_rows
from shipmill.downstream import (
    AppDispatcher,
    AppRuns,
    GhLibrary,
    GhReader,
    HeadMoved,
    Library,
    Reader,
    app_on_host,
    collect,
    dispatched_sha,
    key_problem,
    start,
)
from shipmill.errors import ReleaseError
from shipmill.gate import (
    PRUNE,
    Action,
    ClaudeCli,
    Decision,
    StateRead,
    StateRunner,
    WatchState,
    check_checkout,
    gate,
    host_login,
    load_prune,
    pruner,
    refresh,
    run_command,
    run_state,
    state_dir,
    state_failed,
    tick_lines,
    tick_record,
    watch_command,
)
from shipmill.github import UPGRADE_LABEL, GhCli, GitHub
from shipmill.gitrepo import Git
from shipmill.hooks import HookTest, run_hook, self_test
from shipmill.init import RunsOn, init, init_caller, init_downstream, init_operate
from shipmill.land import ActionsRun, Prepared, Stop, Waiting, cleanup, land, prepare, work_branch
from shipmill.launchd import DEFAULT_EVERY, DEFAULT_TOOL, build, gate_cli, install, job_arguments, read_job, remove
from shipmill.lineedit import LineText
from shipmill.notify import Desktop
from shipmill.operate import Http, Unreachable, UrllibHttp, approve, approve_rollback, operate, summary
from shipmill.planner import Actor, Event, Hotfix, Planner, Proposal
from shipmill.plugin import CLI_RECORD, MARKERS, GateCli, PluginHost, Runner, load_cli
from shipmill.policy import Lane, Policy
from shipmill.product import DIRECTION, GitRef, ItemId, Measure, Section
from shipmill.product import check as check_product
from shipmill.product import read as read_product
from shipmill.propose import close_released, propose, run_url
from shipmill.roles import LoginReader
from shipmill.stamp import notes, sync
from shipmill.upgrades import UpgradeId, apply, find, offers, pending
from shipmill.upgrades import propose as propose_upgrades
from shipmill.version import Version
from shipmill.worktrees import ClaudeSessions, Sessions, judge, prune, table
from shipmill.worktrees import report as worktrees_report


def _outputs(path: Path | None, values: Mapping[str, str]) -> None:
    """Append key=value lines for $GITHUB_OUTPUT; newlines are flattened so a value (which
    may quote an issue title) can't set another output"""
    if path is None:
        return
    with path.open("a", encoding="utf-8") as out:
        out.writelines(f"{k}={' '.join(v.splitlines())}\n" for k, v in values.items())


def _ints(text: str) -> tuple[int, ...]:
    parts = [p for p in text.replace(",", " ").split() if p]
    try:
        return tuple(int(p.lstrip("#")) for p in parts)
    except ValueError:
        raise ReleaseError(f"pull request numbers are integers, such as 12,15; got {text!r}") from None


def _proposals(text: str) -> tuple[Proposal, ...]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"--proposals is the plan's proposals output, a JSON list: {exc}") from None
    if not isinstance(raw, list) or not raw:
        raise ReleaseError(f"--proposals is a non-empty JSON list; got {text!r}")
    return tuple(Proposal.from_dict(item) for item in raw)


def _now(text: str | None) -> dt.datetime:
    if text is None:
        return dt.datetime.now(dt.UTC)
    now = dt.datetime.fromisoformat(text)
    if now.tzinfo is None:
        raise ReleaseError(f"--now needs a UTC offset, such as 2026-10-05T07:10:00+00:00; got {text!r}")
    return now


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shipmill", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="the repository checkout (default: .)")
    parser.add_argument(  # S-031-25: what watch_state.py asks a shipmill on PATH (#583)
        "--version", action="version", version=f"shipmill {importlib.metadata.version('shipmill')}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("settle-minutes", help="print the longest quiet_minutes in the policy, 0 when its mode is off")

    p = sub.add_parser("plan", help="decide whether a lane releases now")
    p.add_argument("--event", choices=[e.value for e in Event], help="default: $GITHUB_EVENT_NAME, else manual")
    p.add_argument("--lane", choices=[ln.value for ln in Lane], help="release this lane by hand")
    p.add_argument("--dry-run", action="store_true", help="plan as dry-run whatever the policy's mode")
    p.add_argument("--hotfix-prs", default="", help="hotfix: merged pull requests, such as 12,15")
    p.add_argument("--hotfix-from", default="", help="hotfix: the stable tag to fix (default: the latest)")
    p.add_argument("--now", help="ISO time with offset (default: now)")
    p.add_argument(
        "--actor",
        default=os.environ.get("GITHUB_TRIGGERING_ACTOR", ""),
        help="who started the run; a breaking stable release started by hand needs a person"
        " (default: $GITHUB_TRIGGERING_ACTOR)",
    )
    p.add_argument("--github-output", type=Path)

    p = sub.add_parser("propose", help="open or update the issue for each release a plan proposed")
    p.add_argument("--proposals", required=True, help="the plan's proposals output, a JSON list")

    p = sub.add_parser("prepare", help="stamp a planned release into the checkout")
    _release_args(p)
    p.add_argument("--base", required=True)
    p.add_argument("--merges", default="", help="hotfix: merge commits, space-separated")
    p.add_argument("--prs", default="", help="hotfix: pull request numbers, for the commit message")
    p.add_argument("--date", type=dt.date.fromisoformat, help="YYYY-MM-DD (default: today, UTC)")
    p.add_argument("--commit", action="store_true", help="commit the stamp as the release commit")
    p.add_argument("--push", action="store_true", help="also push the commit to its work branch")
    p.add_argument("--github-output", type=Path)
    p.add_argument(
        "--workflow-ref",
        default=os.environ.get("GITHUB_WORKFLOW_REF", ""),
        help="the release workflow, whose other active runs may own a work branch (default: $GITHUB_WORKFLOW_REF)",
    )
    p.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID", ""),
        help="this run, never an owner of a work branch (default: $GITHUB_RUN_ID)",
    )
    p.add_argument(
        "--step-summary",
        type=Path,
        default=os.environ.get("GITHUB_STEP_SUMMARY") or None,
        help="also report a stop or a recovery here (default: $GITHUB_STEP_SUMMARY)",
    )

    p = sub.add_parser("land", help="push, tag, sync, and publish a release commit that passed CI")
    _release_args(p)
    p.add_argument("--sha", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--date", type=dt.date.fromisoformat, help="YYYY-MM-DD (default: today, UTC)")

    p = sub.add_parser("close-proposal", help="close the lane's proposal issue once land released it")
    _release_args(p)

    p = sub.add_parser("cleanup", help="delete a release commit's work branch")
    p.add_argument("--version", required=True, type=Version.parse)

    p = sub.add_parser("sync", help="bring a stable release made off main into the checkout of main")
    p.add_argument("--version", required=True, type=Version.parse)
    p.add_argument("--date", type=dt.date.fromisoformat, help="YYYY-MM-DD (default: today, UTC)")

    p = sub.add_parser("notes", help="print a release's notes, from its tag")
    p.add_argument("--version", required=True, type=Version.parse)

    p = sub.add_parser("operate", help="check environment health, promote after the bake")
    p.add_argument("--dry-run", action="store_true", help="report what it would do; write and start nothing")
    approving = p.add_mutually_exclusive_group()
    approving.add_argument(
        "--approve", metavar="ENVIRONMENT", help="deploy the tag proposed for this environment, once"
    )
    approving.add_argument(
        "--approve-rollback", metavar="ENVIRONMENT", help="start the rollback an incident proposes for it, once"
    )
    p.add_argument("--now", help="ISO time with offset (default: now)")
    p.add_argument(
        "--step-summary",
        type=Path,
        default=os.environ.get("GITHUB_STEP_SUMMARY") or None,
        help="also append the report here (default: $GITHUB_STEP_SUMMARY)",
    )

    p = sub.add_parser("doctor", help="check that the repository is ready for the bot")
    p.add_argument(
        "--app-key",
        type=Path,
        help="with [downstream]: the App's private key, to check its installation on each downstream"
        " (default: ~/.config/shipmill/app-<app_id>.pem when it exists)",
    )

    p = sub.add_parser("decide", help="the decision policy's zones and levels, and the zones of a change (spec 030)")
    deciding = p.add_subparsers(dest="decide", required=True)
    q = deciding.add_parser("levels", help="print every zone with its level, its floor, and where the level comes from")
    q.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")
    q.add_argument("--ref", help="read the config at this git ref (default: the working tree's)")
    q.add_argument("--json", action="store_true", help="print the levels as one JSON object")
    q = deciding.add_parser(
        "classify", help="print the zones code detects for a change, their strictest level, and the D-n candidates"
    )
    q.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")
    q.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help="read the levels, REVIEW.md, and the decisions log at this git ref, never from the change"
        f" (default: {DEFAULT_REF})",
    )
    changed = q.add_mutually_exclusive_group(required=True)
    changed.add_argument("--pr", type=int, metavar="N", help="the pull request, its files and diff read through gh")
    changed.add_argument("--files", nargs="+", metavar="PATH", help="changed paths; the diff rules don't apply")
    q.add_argument("--json", action="store_true", help="print the classification as one JSON object")

    p = sub.add_parser(
        "autonomy",
        help="print every stage's [autonomy] level: configured, under the hold, and where it comes from (spec 040)",
    )
    p.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")
    p.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"read the config at this git ref, never from a change (default: {DEFAULT_REF}); exit 2 when the checkout"
        " lacks it",
    )
    p.add_argument("--json", action="store_true", help="print the hold and the stages as one JSON object")

    p = sub.add_parser("review", help="check, show, or edit REVIEW.md, the review rubric (spec 024)")
    reviews = p.add_subparsers(dest="review_command", required=True)
    for name, about in (
        ("check", "exit 1 naming the file, line, and rule when a REVIEW.md's structured sections break"),
        ("show", "print the rubric that applies to the changed files: the root's and their directories' merged"),
        ("add-rule", "append `- I-n: <text>` to Important, n one above any id the file's history held"),
        ("protect", "append a Protected areas item, ``- `<glob>`: <why>``; refuses a glob already listed"),
        ("set-cap", "set Nits' `cap: N` line, the most nits a review raises"),
        ("retire", "remove an Important rule by its id (I-n) or a Protected areas item by its glob"),
    ):
        q = reviews.add_parser(name, help=about)
        q.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")
        if name == "show":
            q.add_argument("--path", action="append", default=[], metavar="FILE", help="a changed file (repeatable)")
            q.add_argument("--json", action="store_true", help="print the rubric as JSON")
        if name in ("check", "show"):
            continue
        q.add_argument(
            "--dir",
            metavar="DIR",
            help="edit DIR/REVIEW.md instead of the root's, creating it with only the touched section",
        )
        if name == "add-rule":
            q.add_argument("text", help="the rule, one line")
        elif name == "protect":
            q.add_argument("glob", help="the path pattern, such as src/shipmill/land.py or skills/**")
            q.add_argument("--why", required=True, help="why a change to it needs the maintainer, one line")
        elif name == "set-cap":
            q.add_argument("cap", type=int, metavar="N", help="the cap, a whole number from 0")
        else:
            q.add_argument("target", metavar="I-n|GLOB", help="the rule's id or the protected glob")

    p = sub.add_parser("status", help="say whether the factory works or is stuck (specs 008, 009)")
    p.add_argument(
        "slug", nargs="?", metavar="owner/name", help="the GitHub repo (default: origin's); --repo is its checkout"
    )
    shown = p.add_mutually_exclusive_group()
    shown.add_argument("--rows", action="store_true", help="print github-ship-watch's table instead")
    shown.add_argument(
        "--json",
        action="store_true",
        help="print github-ship-watch's JSON lines instead, then an AUTONOMY line with every stage's level",
    )

    p = sub.add_parser("factory", help="print this host's machinery for the repo, one line per check (spec 044)")
    p.add_argument(
        "slug", nargs="?", metavar="owner/name", help="the GitHub repo (default: origin's); --repo is its checkout"
    )
    p.add_argument("--json", action="store_true", help="print the checks as one JSON object")

    p = sub.add_parser(
        "milestones",
        help="print the milestones a lane with milestone = true waits on or a stable tag overtook (spec 022)",
    )
    p.add_argument("--json", action="store_true", help="print the rows and the read's error as one JSON object")
    p.add_argument("--now", help="ISO time with offset (default: now)")

    p = sub.add_parser("roles", help="print who receives each step an agent can't do, [agents.roles] (spec 036)")
    shown = p.add_mutually_exclusive_group()
    shown.add_argument("--json", action="store_true", help="print the roles as one JSON object")
    shown.add_argument("--flags", action="store_true", help="print the --role arguments triage_state.py takes")

    p = sub.add_parser("upgrade", help=f"list the config upgrades {CONFIG_PATH} hasn't decided (spec 014)")
    acts = p.add_mutually_exclusive_group()
    acts.add_argument(
        "--apply",
        metavar="ID",
        help="make the upgrade's edit in the checkout: the config line and its files; no commit",
    )
    acts.add_argument(
        "--propose",
        action="store_true",
        help="open or update one shipmill-upgrade issue per pending upgrade (none under observe), taking"
        " shipmill-upgrade-later off one whose upgrade is newer than its marker's version, and close the issue"
        " of each upgrade the config decided",
    )
    p.add_argument("--json", action="store_true", help="print the result as JSON")

    p = sub.add_parser("init", help=f"write {CONFIG_PATH} and {CALLER}")
    p.add_argument("--ci", default="ci.yml", help="the CI workflow a release commit must pass (default: ci.yml)")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.add_argument(
        "--no-fragments",
        action="store_true",
        help="leave [changelog] fragments unset and write no changelog.d/README.md: each PR edits the CHANGELOG",
    )
    p.add_argument(
        "--operate",
        action="store_true",
        help=f"write {OPERATE_CALLER}, which runs shipmill operate every 10 minutes, and add to the policy's"
        " [autonomy] rollback and each deploy.<env> it doesn't set, at their defaults",
    )
    p.add_argument(
        "--downstream",
        action="store_true",
        help=f"write only {DOWNSTREAM_CALLER}, which runs the [downstream] repositories' tests on each pull request",
    )
    p.add_argument(
        "--caller",
        action="store_true",
        help=f"write only {CALLER}, from the existing {CONFIG_PATH}: its schedule follows the policy's triggers",
    )
    p.add_argument(
        "--runs-on",
        metavar="RUNNER",
        help=f"the runner shipmill's release jobs run on, written into {CALLER}: a label, such as self-hosted,"
        ' or a JSON list of labels, such as \'["self-hosted", "linux"]\' (default: ubuntu-latest)',
    )

    p = sub.add_parser(
        "gate",
        help=(
            f"start a Claude Code session only when the repo's state needs one ([agents] in {CONFIG_PATH}); "
            "every tick prunes the worktrees that landed"
        ),
    )
    p.add_argument("slug", metavar="owner/name", help="the GitHub repo; --repo is its checkout")
    p.add_argument("--claude-arg", action="append", default=[], help="extra flag for the session (repeatable)")
    p.add_argument(
        "--refresh",
        action="store_true",
        help="move this detached, clean gate checkout to origin's default branch before reading it",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="decide and print; start, stop, move, or prune nothing (lists what it would prune when due)",
    )
    p.add_argument("--json", action="store_true", help="print the decision, with the pruned worktrees, as JSON")
    p.add_argument("--walk", action="store_true", help="walk the work tiers whether or not anything changed (spec 046)")
    p.add_argument("--sweep", action="store_true", help="read the timed sections whether or not a sweep is due")
    p.add_argument(
        "--app-key",
        type=Path,
        help="the private key of the App in [agents] app_id (default: ~/.config/shipmill/app-<app_id>.pem)",
    )
    p.add_argument(
        TOKEN_FLAG,
        type=Path,
        help=(
            "the file holding the long-lived token `claude setup-token` printed, mode 600, for the sessions"
            " (default: ~/.config/shipmill/claude-token; without it, the interactive login)"
        ),
    )

    p = sub.add_parser(
        "worktrees", help="list every worktree of the repository as REMOVABLE once its work landed, or KEPT and why"
    )
    p.add_argument(
        "--prune",
        action="store_true",
        help="remove each REMOVABLE worktree (never forced) and the local branch it held; print them REMOVED",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="with --prune: print the REMOVABLE ones as WOULD_REMOVE, remove nothing"
    )
    p.add_argument("--json", action="store_true", help="print the worktrees as one JSON object")

    p = sub.add_parser(
        "app-token",
        help=(
            "print an installation token of a GitHub App, limited to one repo; cached in the checkout, "
            "else in $XDG_CACHE_HOME/shipmill/<owner>/<repo>/ (default ~/.cache)"
        ),
    )
    p.add_argument(
        "slug", metavar="owner/name", nargs="?", help="the GitHub repo the token is limited to; --repo is its checkout"
    )
    p.add_argument("--app-id", type=int, help="the App's id, as [agents] app_id names it; needed but with --check")
    p.add_argument(
        "--app-key",
        type=Path,
        help="the App's private key (default: $SHIPMILL_APP_KEY when set, else ~/.config/shipmill/app-<app_id>.pem)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help=(
            "say whether the App is available to this session, as the delivery hook tests it, and nothing more: "
            "exit 0 with [agents] app_id set and a non-empty SHIPMILL_APP_KEY or a key file at "
            "~/.config/shipmill/app-<app_id>.pem, else exit 2 naming why; mints, prints, and reads no token or "
            "key (spec 033)"
        ),
    )
    p.add_argument(
        "--git-credential",
        metavar="OPERATION",
        help=(
            "answer git's credential protocol on stdin: get prints username=x-access-token and the token "
            "as password for https://github.com; store, erase, and other operations print nothing"
        ),
    )
    p.add_argument(
        "--product",
        action="store_true",
        help=(
            "in the product's home repo: the coordinator's token over every repo [product] repos lists under "
            "owner (owner/name must be listed), with contents read, issues write, pull requests read, and "
            "metadata read, cached in app-token-product-<owner>.json (spec 038, D-47)"
        ),
    )

    sub.add_parser(
        "gh",
        add_help=False,  # `shipmill gh --help` is gh's help: every argument after gh goes to gh
        help=(
            "run gh with the arguments that follow, as [agents] app_id's GitHub App when set (spec 012); "
            "without it, a read runs as the host's gh login and a write exits 2 unless [agents] identity = "
            '"host" or the call passes --as-host (spec 037); use it for every gh call that writes from an agent '
            "session. Only a leading --app-key PATH (default: ~/.config/shipmill/app-<app_id>.pem), --product "
            "OWNER/NAME, and --as-host are shipmill's; --product runs gh with the coordinator's token for OWNER's "
            "listed repos and refuses the commands that write code or pull requests (spec 038, D-47)"
        ),
    )

    p = sub.add_parser(
        "plugin-clean",
        help=(
            "list the project- and local-scope installs of shipmill@shipmill that shadow the user install;"
            " with --apply, remove them (spec 039)"
        ),
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help=(
            "uninstall each in its folder, restoring the folder's .claude/settings.json and settings.local.json;"
            " only from a terminal, and only with a user-scope install on the host"
        ),
    )

    p = sub.add_parser("app-create", help="create the gate's GitHub App in one click (spec 006)")
    p.add_argument(
        "--owner", help="the personal account or org that owns the App (default: asked, else your personal account)"
    )
    visibility = p.add_mutually_exclusive_group()
    visibility.add_argument(
        "--public", dest="public", action="store_const", const=True, help="installable on any account"
    )
    visibility.add_argument(
        "--private", dest="public", action="store_const", const=False, help="installable on the owner only"
    )
    p.add_argument("--name", help="the App's name, unique on GitHub (default: shipmill-<owner>, then shipmill-<login>)")
    p.add_argument("--repos", help="the gated repos as owner/name,...; skips looking for them")
    p.add_argument("--dry-run", action="store_true", help="print the plan; create nothing")
    p.add_argument("--json", action="store_true", help="print the plan and the result as one JSON object")
    p.add_argument("--no-browser", action="store_true", help="print the URLs instead of opening them")

    p = sub.add_parser("app-install", help="guide installing the gate's GitHub App on more repos (spec 007)")
    p.add_argument("repos", nargs="*", metavar="owner/name", help="the repos the App should cover (default: origin's)")
    p.add_argument("--app-id", type=int, help="the App's id (default: [agents] app_id)")
    p.add_argument("--app-key", type=Path, help="the App's private key (default: ~/.config/shipmill/app-<app_id>.pem)")
    p.add_argument("--no-browser", action="store_true", help="print the page instead of opening it")
    p.add_argument("--json", action="store_true", help="print the result as one JSON object")

    p = sub.add_parser("product", help=f"read or edit the product's direction, {DIRECTION} (spec 024)")
    acting = p.add_subparsers(dest="product", required=True)
    checking = acting.add_parser("check", help=f"exit 1 naming the file, line, and rule {DIRECTION} breaks")
    checking.add_argument(
        "--ref",
        help=f"read {DIRECTION} and its moved sections' files as committed at this git ref, not the working tree "
        "(spec 034); exit 2 when git can't resolve it",
    )
    showing = acting.add_parser("show", help="print the direction, or some sections, moved ones resolved")
    showing.add_argument(
        "--section",
        action="append",
        default=[],
        choices=[s.option for s in Section],
        help="print only this section (repeatable)",
    )
    showing.add_argument("--json", action="store_true", help="print it as one JSON object")
    listing = acting.add_parser("ids", help="list every item's id with its text, one per line")
    adding = acting.add_parser(
        "add", help="append an item with the next id, one above any the direction's history held; print it"
    )
    adding.add_argument("section", choices=[s.option for s in Section if s.prefix is not None])
    adding.add_argument("text", help="the item's text, one line")
    editing = acting.add_parser("edit", help="rewrite one item's text; its id stays")
    editing.add_argument("id", help="the item's id, such as G-3")
    editing.add_argument("text", help="the item's new text, one line")
    retiring = acting.add_parser("retire", help="remove one item; its id is never handed out again")
    retiring.add_argument("id", help="the item's id, such as G-3")
    measuring = acting.add_parser(
        "measure", help="write or replace a goal's measure line, or remove it with --clear (spec 027); print it"
    )
    measuring.add_argument("id", help="the goal's id, such as G-3")
    measured = measuring.add_mutually_exclusive_group(required=True)
    measured.add_argument("measure", nargs="?", help='"<metric> <comparison> <target>", such as "human_touch <= 20%%"')
    measured.add_argument("--clear", action="store_true", help="remove the goal's measure line")
    for each in (
        checking,
        showing,
        listing,
        adding,
        editing,
        retiring,
        measuring,
    ):  # also after it: `product check --repo DIR`
        each.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")

    p = sub.add_parser("evals", help="check the agents' eval suite, evals/, and compare its runs (spec 025)")
    evaluating = p.add_subparsers(dest="evals", required=True)
    q = evaluating.add_parser("check", help="exit 1 naming each case of evals/ and the rule it breaks; no case passes")
    q.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")
    q.add_argument(
        "--gate",
        action="store_true",
        help="also exit 1 naming each kind short of the first suite's counts (8 verdict, 4 decision, 4 finding, 4 fix)",
    )
    q = evaluating.add_parser(
        "compare", help="exit 1 when the head's eval results regress against the base's (D-37), naming the cases"
    )
    q.add_argument("--base", type=Path, required=True, help="the default branch run's aggregate-result.json")
    q.add_argument("--head", type=Path, required=True, help="the pull request run's aggregate-result.json")
    q.add_argument(
        "--tolerance",
        type=_tolerance,
        default=evals.TOLERANCE,
        help="how far the suite's pass rate may drop, from 0 to 1 (default: 0.05); a dispatched run's only",
    )
    q.add_argument(
        "--changed",
        type=_case_path,
        action="append",
        default=[],
        metavar="CASE",
        help="a case whose directory the pull request changed, relative to evals/; judged on its own (repeatable)",
    )

    p = sub.add_parser("downstream", help="run the downstream repositories' tests on a pull request (spec 032)")
    acting = p.add_subparsers(dest="downstream", required=True)
    q = acting.add_parser(
        "start", help="write a check per downstream on the pull request's head and dispatch each one's workflow"
    )
    q.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")
    q.add_argument("--pr", required=True, type=int, help="the library's pull request")
    q.add_argument("--app-key", required=True, type=Path, help="the private key of the App in [downstream] app_id")
    q.add_argument(
        "--actor",
        help="who started a workflow_dispatch run ($GITHUB_TRIGGERING_ACTOR); omitted on pull_request_target",
    )
    q.add_argument(
        "--sha",
        help="with --actor: the full head SHA the person read; start refuses any other head with exit 1",
    )
    q = acting.add_parser(
        "collect", help="read each downstream run start dispatched back into its check, once it ends or times out"
    )
    q.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="the repository checkout (default: .)")
    q.add_argument("--pr", required=True, type=int, help="the library's pull request")
    q.add_argument("--head", required=True, help="the full head SHA start wrote the checks on")
    q.add_argument("--app-key", required=True, type=Path, help="the private key of the App in [downstream] app_id")

    p = sub.add_parser("launchd", help="run the gate for a dedicated checkout every few minutes (macOS)")
    p.add_argument("slug", metavar="owner/name", help="the GitHub repo; --repo is its gate checkout")
    p.add_argument("--every", type=int, default=DEFAULT_EVERY, help="minutes between runs (default: 15)")
    p.add_argument("--tool", default=DEFAULT_TOOL, help=f"where uvx gets shipmill (default: {DEFAULT_TOOL})")
    p.add_argument("--claude-arg", action="append", default=[], help="extra flag for the session (repeatable)")
    p.add_argument(
        "--app-key",
        type=Path,
        help="pass the private key of the App in [agents] app_id to the job's gate (made absolute)",
    )
    p.add_argument(
        TOKEN_FLAG,
        type=Path,
        help="pass the Claude token file's path (never the token) to the job's gate (made absolute)",
    )
    p.add_argument("--print", action="store_true", help="print the job's plist; install nothing")
    p.add_argument("--remove", action="store_true", help="unload and delete the repo's job")
    return parser


def _release_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lane", required=True, choices=[ln.value for ln in Lane])
    p.add_argument("--version", required=True, type=Version.parse)


def main(
    argv: list[str],
    github: GitHub | None = None,
    http: Http | None = None,
    sessions: Sessions | None = None,
    api: Api | None = None,
    signer: Signer | None = None,
    stdin: TextIO | None = None,
    state: StateRunner | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    gh_runner: GhRunner | None = None,
    library: Library | None = None,
    downstream_reader: Reader | None = None,
    pulls: Pulls | None = None,
    merge_reader: MergeReader | None = None,
    credit_reader: CreditReader | None = None,
    login: LoginReader | None = None,
    claude: Runner | None = None,
) -> int:
    """github stands in for gh, http for the health checks, sessions for `claude agents`, api
    for GitHub's REST API, signer for openssl, stdin for git's credential request, state for
    watch_state.py (and doctor's AGENT_AS_PERSON read), environ for this process's env, home
    for the user's home, gh_runner for running `shipmill gh`'s gh, library for the library's
    repository `downstream start` and `collect` write checks on, downstream_reader for
    what doctor reads of the secrets and the downstream workflows, pulls for the pull
    request `decide classify --pr` reads, merge_reader for the pull request a `shipmill
    gh` merge reads, credit_reader for what its credit reads (spec 049), login for the
    host's gh login `roles` reads, and claude for the `claude plugin` and `gh api` commands
    plugin-clean runs, as tests pass fakes; stdin is also a `shipmill gh` merge's --body-file -"""
    head, passed = _split_gh(argv)
    args = _parser().parse_args(head)
    root: Path = args.repo.resolve()
    env = environ if environ is not None else os.environ
    user_home = home if home is not None else Path.home()
    if args.command == "gh":
        if passed is None:  # such as `shipmill -- gh ...`
            raise ReleaseError("only --repo PATH may come before gh, as in `shipmill --repo PATH gh pr list`")
        readers = _GhReaders(merge_reader or _gh_reader, credit_reader or _credit_reader, stdin or sys.stdin)
        return _gh(root, passed, api or UrllibApi(), signer or Openssl(), env, user_home, gh_runner or run_gh, readers)
    if args.command == "plugin-clean":  # needs no --repo and no config (spec 039)
        where = stdin or sys.stdin
        return plugin_clean.clean(claude or run_command, user_home, args.apply, where.isatty(), print)
    if args.command == "app-token":
        return _app_token(root, args, api or UrllibApi(), signer or Openssl(), stdin or sys.stdin, env, user_home)
    if args.command == "app-install":
        return _app_install(root, args, api or UrllibApi(), signer or Openssl())
    if args.command == "app-create":
        ask = input if sys.stdin.isatty() and not args.owner else None
        return _app_create(root, args, api or UrllibApi(), signer or Openssl(), ask=ask)
    if args.command == "status":
        host = login or (lambda: host_login(root))
        return _status(root, args, state or run_state, api or UrllibApi(), signer or Openssl(), host)
    if args.command == "factory":
        hub_api, hub_signer = api or UrllibApi(), signer or Openssl()
        return _factory(root, args, state or run_state, hub_api, hub_signer, github, sessions, user_home)
    if args.command == "milestones":
        return _milestones(root, args, github)
    if args.command == "roles":
        resolved = roles.resolve(roles.configured(root), login or (lambda: host_login(root)))
        render = roles.as_json if args.json else roles.flags if args.flags else roles.text
        sys.stdout.write(render(resolved))
        return 0
    if args.command == "upgrade":
        return _upgrade(root, args, github or GhCli(root))
    if args.command == "product":
        return _product(root, args)
    if args.command == "review":
        return _review(root, args)
    if args.command == "decide":
        return _decide(root, args, pulls or GhCli(root))
    if args.command == "autonomy":
        return _autonomy(root, args.ref, args.json, github or GhCli(root))
    if args.command == "evals":
        if args.evals == "compare":
            return _evals_compare(args.base, args.head, frozenset(args.changed), args.tolerance)
        return _evals(root, gate=args.gate)
    if args.command == "downstream":
        if args.downstream == "collect":
            return _downstream_collect(root, args, library or GhLibrary(root), api or UrllibApi(), signer or Openssl())
        return _downstream_start(root, args, library or GhLibrary(root), api or UrllibApi(), signer or Openssl())
    hub = github or GhCli(root)
    if args.command == "init":
        # checked before any write, on every path (spec 015)
        runs_on = None if args.runs_on is None else RunsOn.parse(args.runs_on)
        if args.downstream:
            others = (
                ("--caller", args.caller),
                ("--operate", args.operate),
                ("--no-fragments", args.no_fragments),
                ("--runs-on", runs_on is not None),
            )
            for flag, given in others:
                if given:
                    raise ReleaseError(f"--downstream writes only {DOWNSTREAM_CALLER}; drop {flag}")
            print(f"wrote {init_downstream(root, args.force).relative_to(root)}")
            print(f"next: add the App's key as the SHIPMILL_DOWNSTREAM_KEY secret, then run `{cli_command()} doctor`")
            return 0
        if args.caller:
            for flag, given in (("--operate", args.operate), ("--no-fragments", args.no_fragments)):
                if given:
                    raise ReleaseError(f"--caller writes only {CALLER}, from the existing policy; drop {flag}")
            print(f"wrote {init_caller(root, args.ci, args.force, runs_on).relative_to(root)}")
            print(f"next: run `{cli_command()} doctor`")
            return 0
        if args.operate:
            if runs_on is not None:
                raise ReleaseError(
                    f"--runs-on sets {CALLER}'s runner; --operate leaves {CALLER} alone and writes"
                    f" {OPERATE_CALLER}, which takes no runner"
                )
            for path in init_operate(root, args.force):
                print(f"wrote {path.relative_to(root)}")
            print(f"next: run `{cli_command()} doctor`")
            return 0
        initialized = init(root, args.ci, args.force, fragments=not args.no_fragments, runs_on=runs_on)
        for path in initialized.written:
            print(f"wrote {path.relative_to(root)}")
        print(f"next: review the policy, then run `{cli_command()} doctor`")
        return 0
    if args.command == "doctor":
        slug = _doctor_repo(root)
        plugins = None if slug is None else (lambda: read_plugin_rows(slug, root))
        people = (
            None if slug is None else (lambda: agent_as_person.read(slug, state or run_state, dt.datetime.now(dt.UTC)))
        )
        hooks = _hook_test(root, env, user_home)
        has_gh = shutil.which("gh") is not None
        key: Path | None = None if args.app_key is None else args.app_key.expanduser()
        hub_api, hub_signer = api or UrllibApi(), signer or Openssl()
        job = None if slug is None or sys.platform != "darwin" else read_job(slug, user_home)
        source = TokenSource.of_job(None if job is None else job_arguments(job), user_home)
        checks = doctor(
            root,
            github or (GhCli(root) if has_gh else None),
            plugins,
            people,
            slug,
            hooks=hooks,
            auth=_claude_auth(env),
            credential=lambda: inspect(source),
            launchd_job=job is not None,
            downstream=downstream_reader or (GhReader(root) if has_gh else None),
            app=app_on_host(key, user_home, hub_signer, hub_api, lambda: dt.datetime.now(dt.UTC)),
            gate_cli=None if slug is None else (lambda: _gate_cli(root, slug, user_home)),
            pypi=lambda url: _pypi_status(url, http),
            product=product_on_host(
                key,
                user_home,
                lambda owner: state_dir(Git(root)) / product_cache(owner),
                hub_signer,
                hub_api,
                lambda: dt.datetime.now(dt.UTC),
            ),
            home_reader=GhReader(root) if has_gh else None,
            home=user_home,
        )
        for check in checks:
            print(f"{check.status} {check.name}: {check.detail}")
        return 1 if any(c.status == "FAIL" for c in checks) else 0
    if args.command == "gate":
        return _gate(root, args, hub, sessions or ClaudeSessions(root))
    if args.command == "launchd":
        return _launchd(root, args)
    if args.command == "worktrees":
        if args.dry_run and not args.prune:
            raise ReleaseError("--dry-run goes with --prune")
        git = Git(root)
        judged = judge(git, hub, sessions or ClaudeSessions(root), dt.datetime.now(dt.UTC))
        if args.prune:
            judged = prune(git, judged, args.dry_run)
        sys.stdout.write(json.dumps(worktrees_report(judged), indent=2) + "\n" if args.json else table(judged))
        return 0

    policy = Policy.load(config_path(root))
    if github is None:  # a body cut to fit links the policy's changelog (#499)
        hub = GhCli(root, changelog=policy.changelog)
    git = Git(root, policy.bot_name, policy.bot_email)
    today = dt.datetime.now(dt.UTC).date()
    if args.command == "settle-minutes":
        print(policy.settle_minutes)
    elif args.command == "plan":
        event = Event(args.event or os.environ.get("GITHUB_EVENT_NAME") or Event.MANUAL.value)
        lane = Lane(args.lane) if args.lane else None
        hotfix = Hotfix(_ints(args.hotfix_prs), args.hotfix_from or None) if lane is Lane.HOTFIX else None
        if hotfix is None and (args.hotfix_prs or args.hotfix_from):
            raise ReleaseError("--hotfix-prs and --hotfix-from go with --lane hotfix")
        actor = Actor(args.actor) if args.actor else None
        decision = Planner(git, policy, hub, _now(args.now)).plan(event, lane, args.dry_run, hotfix, actor)
        outputs = decision.outputs()
        print(json.dumps(outputs, indent=2))
        _outputs(args.github_output, outputs)
    elif args.command == "propose":
        for done in propose(git, policy, hub, _proposals(args.proposals)):
            print(f"{done.outcome} #{done.issue}: {done.proposal.lane} {done.proposal.version}, {done.proposal.cause}")
    elif args.command == "prepare":
        prepared = prepare(
            git,
            policy,
            Lane(args.lane),
            args.version,
            args.base,
            args.date or today,
            tuple(args.merges.split()),
            _ints(args.prs),
            commit=args.commit or args.push,
            push=args.push,
            github=hub,
            run=ActionsRun.parse(args.workflow_ref, args.run_id) if args.push else None,
        )
        for changed in prepared.changed:
            print(f"stamped {changed}")
        if args.push:
            _report_work_branch(prepared, work_branch(args.version), args.workflow_ref, args.step_summary)
        sha = prepared.sha if (prepared.pushed or not args.push) else ""
        _outputs(args.github_output, {"sha": sha})
    elif args.command == "land":
        landed = land(
            git,
            policy,
            hub,
            Lane(args.lane),
            args.version,
            args.sha,
            args.base,
            args.date or today,
            waiting=Waiting(pypi=_pypi_status),
        )
        print(
            json.dumps(
                {
                    "tag": landed.tag,
                    "placed": landed.placed,
                    "synced": landed.synced,
                    "published": list(landed.published),
                },
                indent=2,
            )
        )
    elif args.command == "close-proposal":
        print(close_released(policy, hub, Lane(args.lane), args.version, run_url(os.environ)))
    elif args.command == "cleanup":
        print("deleted the work branch" if cleanup(git, args.version) else "no work branch to delete")
    elif args.command == "sync":
        released = git.show(args.version.tag, policy.changelog)
        if released is None:
            raise ReleaseError(f"no {policy.changelog} at {args.version.tag}")
        newest = all(t.version <= args.version for t in git.tags() if t.version.is_stable)
        for changed in sync(git, policy, args.version, released, args.date or today, newest):
            print(f"synced {changed}")
    elif args.command == "operate":
        if args.approve:
            report = approve(policy, hub, args.approve, args.dry_run) + "\n"
        elif args.approve_rollback:
            report = approve_rollback(policy, hub, args.approve_rollback, args.dry_run) + "\n"
        else:
            reports = operate(policy, git.tags(), hub, http or UrllibHttp(), _now(args.now), args.dry_run)
            report = summary(reports, args.dry_run)
        sys.stdout.write(report)
        if args.step_summary is not None:
            with args.step_summary.open("a", encoding="utf-8") as out:
                out.write(report)
    elif args.command == "notes":
        text = git.show(args.version.tag, policy.changelog)
        if text is None:
            raise ReleaseError(f"no {policy.changelog} at {args.version.tag}")
        stable = [t.version for t in git.tags() if t.version.is_stable and t.version < args.version]
        pending = [] if args.version.is_stable else fragments.at_revision(git, policy, args.version.tag)
        since = max(stable) if stable else None
        sys.stdout.write(notes(policy, text, args.version, since, fragments.entries(pending)))
    return 0


def _annotation(text: str) -> str:
    """text as a workflow command's message: GitHub reads %, CR, and LF as escapes"""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _report_work_branch(prepared: Prepared, work: str, workflow_ref: str, step_summary: Path | None) -> None:
    """Make a stop at a work branch on origin, or its recovery, visible: an annotation, a
    step-summary line, and stderr; the run stays green either way (D-18)"""
    if not prepared.found:
        return
    workflow = workflow_ref.partition("@")[0].rsplit("/", 1)[-1] or "the release workflow"
    at = f"{work} is on origin at {prepared.found[:12]}"
    if prepared.stop is None:
        level, title = "notice", "Orphaned work branch replaced"
        text = f"{at}, and no other run of {workflow} is queued or in progress: deleted it and pushed this run's own"
    else:
        level, title = "warning", "Work branch held"
        why = {
            Stop.OWNED: f"another queued or in-progress run of {workflow} may own it",
            Stop.FORBIDDEN: (
                f"this run can't list the runs of {workflow} to tell whether one owns it: grant `actions: read`"
                f" to the prepare job in {CALLER}, so a run deletes a work branch no run owns"
            ),
            Stop.OUTSIDE: "outside a GitHub Actions run nothing tells whether a run owns it",
        }[prepared.stop]
        text = f"{at}; {why}. This run releases nothing; delete the branch if no run uses it"
    print(text, file=sys.stderr)
    print(f"::{level} title={title}::{_annotation(text)}")
    if step_summary is not None:
        with step_summary.open("a", encoding="utf-8") as out:
            out.write(f"{title}: {text}\n\n")


def _hook_test(root: Path, environ: Mapping[str, str], home: Path) -> Callable[[], HookTest]:
    """Spec 026's self-test for a session in root, looking programs up on environ's PATH"""
    path = environ.get("PATH", "")

    def which(name: str) -> str | None:
        return shutil.which(name, path=path)

    return lambda: self_test(root, run_command, run_hook, which, home, environ)


def _claude_auth(environ: Mapping[str, str]) -> Callable[[Token | None], ClaudeAuth]:
    """#500's preflight, with claude looked up on environ's PATH; with a token, spec 035's"""
    program = shutil.which("claude", path=environ.get("PATH", ""))
    return preflight_auth(environ, program)


PYPI_TIMEOUT = 15.0  # seconds the gate waits for PyPI's answer (S-031-24)


def _pypi_status(url: str, http: Http | None = None) -> int:
    """PyPI's HTTP status for url; ReleaseError when no answer comes back"""
    try:
        return (http or UrllibHttp()).get(url, PYPI_TIMEOUT).status
    except Unreachable as exc:
        raise ReleaseError(f"{url}: {exc}") from None


def _gate_cli(root: Path, repo: str, home: Path) -> GateCli | None:
    """S-031-17: the version the repo's gate last ran as (None before one recorded it), with the
    fix for its install: its launchd job's, else uv's"""
    git = Git(root)
    if not git.ok("rev-parse", "--git-common-dir"):
        return None
    version = load_cli(state_dir(git) / CLI_RECORD)
    return None if version is None else gate_cli(version, read_job(repo, home), repo)


def _gate(root: Path, args: argparse.Namespace, github: GitHub, sessions: Sessions) -> int:
    git = Git(root)
    path = os.environ.get("PATH", "")

    def session_env(identity: Identity) -> dict[str, str]:
        """The helpers go in the checkout's state folder and run this very shipmill"""
        return prepare_session(identity, state_dir(git) / HELPERS, Path(sys.executable), root, args.slug, path)

    now = dt.datetime.now(dt.UTC)
    decision, launched, waiting, pruned = gate(
        git,
        args.slug,
        lambda: AgentsConfig.load(root, args.slug),
        ClaudeCli(args.claude_arg),
        lambda read: WatchState(args.slug, root, read, state_dir(git), now),
        now,
        lambda: Hold.read(GhCli(root)),
        Desktop.detect(),
        pruner(git, github, sessions),
        args.refresh,
        args.dry_run,
        app_check(args.slug, args.app_key, Path.home(), Openssl(), UrllibApi(), lambda: _product_repos(root)),
        args.app_key is not None,
        session_env,
        lambda: host_login(root),
        plugin=PluginHost(
            run_command,
            gate_cli(requires.running(), read_job(args.slug, Path.home()), args.slug),
            _pypi_status,
            Path.home() / MARKERS,
            lambda: requires.check(read_config(config_path(root))),
        ),
        hooks=_hook_test(root, os.environ, Path.home()),
        auth=_claude_auth(os.environ),
        roles=roles.resolve,
        credential=lambda: _credential(args.claude_token, Path.home()),
        prune_hours=lambda: AgentsConfig.load(root, args.slug).prune_hours,
        walk_now=args.walk,
        sweep_now=args.sweep,
    )
    if args.json:
        print(json.dumps(tick_record(decision, launched, waiting, pruned, args.dry_run), indent=2))
    else:
        print("\n".join(tick_lines(decision, launched, waiting, pruned, args.dry_run)))
    return _gate_exit(decision)


def _credential(given: Path | None, home: Path) -> Credential:
    """Spec 035: the token file --claude-token names, else the default one"""
    return inspect(TokenSource.of(given, home))


def _gate_exit(decision: Decision) -> int:
    """Spec 035, Q-1: a tick whose token file, or the token in it, fails exits 2 after printing
    CLAUDE_AUTH; every other tick, #500's login preflight's CLAUDE_AUTH included, exits 0"""
    failed = decision.action is Action.CLAUDE_AUTH and decision.credential is Kind.TOKEN_FILE
    return 2 if failed else 0


def _product_repos(root: Path) -> tuple[str, ...]:
    """S-038-7: the repos the gate's App check covers with the product permissions: the config's
    [product] repos in the home repo, none elsewhere"""
    found = ProductConfig.load(root)
    return () if found is None else found.repos


def _split_gh(argv: list[str]) -> tuple[list[str], list[str] | None]:
    """argv up to and including the gh command, and the arguments after it, which go to gh
    untouched (spec 012); None when the command isn't gh. Before a command only --repo PATH
    (or an abbreviation of it) takes a value"""
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "gh":
            return argv[: index + 1], argv[index + 1 :]
        if not arg.startswith("-") or arg == "--":
            return argv, None
        index += 2 if len(arg) > 2 and "--repo".startswith(arg) else 1
    return argv, None


def _cache(root: Path, repo: str, environ: Mapping[str, str], home: Path) -> Path:
    """Spec 004's cache in a checkout's state folder; spec 012's under XDG_CACHE_HOME with none"""
    if not root.is_dir():
        raise ReleaseError(f"--repo {root} is not a folder")
    git = Git(root)
    if git.ok("rev-parse", "--git-common-dir"):
        return state_dir(git) / CACHE
    return cache_outside(repo, environ, home)


def _app_token(
    root: Path,
    args: argparse.Namespace,
    api: Api,
    signer: Signer,
    stdin: TextIO,
    environ: Mapping[str, str],
    home: Path,
) -> int:
    """Specs 004 and 012, Tokens. Never falls back to the host's gh login (D-14): any failure exits 2"""
    if args.check:
        return _app_check(root, args, environ, home)
    if args.slug is None or args.app_id is None:
        raise ReleaseError("app-token needs owner/name and --app-id, or --check alone")
    app_id: int = args.app_id
    if app_id < 1:
        raise ReleaseError(f"--app-id must be 1 or more, got {app_id}")
    key: Path = args.app_key if args.app_key is not None else session_key(app_id, environ, home)
    if args.product:
        if args.git_credential is not None:
            raise ReleaseError(
                "--product's token never goes to git: the coordinator's pushes reach only the home repo, "
                "through the session's own token (D-47)"
            )
        top, repos = _coordinator(root, args.slug, f"app-token {args.slug} --product")
        configured = app_id_of(top)
        if configured != app_id:
            raise ReleaseError(
                f"--app-id {app_id} isn't the App the product's token comes from, [agents] app_id {configured}"
            )
        cache = state_dir(Git(top)) / product_cache(args.slug.partition("/")[0])
        print(product_token(cache, repos, app_id, key, dt.datetime.now(dt.UTC), signer, api))
        return 0
    cache = _cache(root, args.slug, environ, home)
    _component_token(root, args.slug)

    def token() -> str:
        return app_token(cache, args.slug, app_id, key, dt.datetime.now(dt.UTC), signer, api)

    if args.git_credential is None:
        print(token())
        return 0
    sys.stdout.write(credential(args.git_credential, stdin.read(), token))
    return 0


def _app_check(root: Path, args: argparse.Namespace, environ: Mapping[str, str], home: Path) -> int:
    """S-033-16: whether the App is available to the session, by the delivery hook's test: the
    checkout's [agents] app_id, then a non-empty SHIPMILL_APP_KEY or a key file at the default
    path. One line either way; exit 2 (ReleaseError) when it isn't. It reads the config and
    stats one path: no token, no network, no key's bytes"""
    passed = {
        "owner/name": args.slug,
        "--app-id": args.app_id,
        "--app-key": args.app_key,
        "--git-credential": args.git_credential,
        "--product": args.product or None,
    }
    given = [flag for flag, value in passed.items() if value is not None]
    if given:
        raise ReleaseError(f"app-token --check takes no {', '.join(given)}: it reads [agents] app_id from the checkout")
    if not root.is_dir():
        raise ReleaseError(f"--repo {root} is not a folder")
    git = Git(root)
    top = Path(git.run("rev-parse", "--show-toplevel").strip()) if git.ok("rev-parse", "--show-toplevel") else None
    top = top or _unreadable_top(root) or root
    app_id = app_id_of(top)
    if app_id is None:
        raise ReleaseError(f"the App isn't available here: no [agents] app_id in {top / CONFIG_PATH}")
    found = availability(app_id, environ, home)
    if not found.available:
        raise ReleaseError(found.reason)
    print(found.reason)
    return 0


def _component_token(root: Path, repo: str) -> None:
    """S-038-10: a checkout whose config sets [product] home gets a token only for its origin
    repo (D-47). Outside a checkout there is no config, so nothing to refuse; a checkout git
    can't read still has its config, as `shipmill gh` reads it"""
    git = Git(root)
    readable = git.ok("rev-parse", "--show-toplevel")
    top = Path(git.run("rev-parse", "--show-toplevel").strip()) if readable else _unreadable_top(root)
    product = None if top is None else ProductConfig.load(top)
    if top is None or product is None or not product.component:
        return
    if not readable:
        raise ReleaseError(
            f"git can't read the checkout at {top}, a component of {product.home}, so its origin repo "
            f"can't be told; `git -C {top} status` names why"
        )
    product.refuse_outside(repo, _origin_repo(top), f"app-token {repo}")


def _coordinator(root: Path, repo: str, what: str) -> tuple[Path, tuple[str, ...]]:
    """Spec 038: the home repo's checkout and the listed repos of repo's owner, which one
    product token covers. Exits 2 in a component (S-038-10), in a repo its own [product] names
    (S-038-3), and without [product] repos or with repo not listed (S-038-5, S-038-9); all
    before any token is minted"""
    if not is_plain_repo(repo):
        raise ReleaseError(f"{what} needs owner/name of letters, digits, '.', '-', or '_'; got {repo!r}")
    if not root.is_dir():
        raise ReleaseError(f"--repo {root} is not a folder")
    git = Git(root)
    if not git.ok("rev-parse", "--show-toplevel"):
        raise ReleaseError(
            f"{what} needs the product's home checkout, and git can't read {root}; `git -C {root} status` names why"
        )
    top = Path(git.run("rev-parse", "--show-toplevel").strip())
    product = ProductConfig.load(top)
    if product is None:
        raise ReleaseError(f"{what} needs [product] repos in {CONFIG_PATH}; {top} has no [product] table")
    product.refuse_product()
    product.refuse_self(_known_origin(top))
    return top, product.coordinated(repo, what)


@dataclass(frozen=True, slots=True)
class _Leading:
    """shipmill's own options before gh's first argument, and gh's arguments"""

    key: Path | None  # --app-key
    product: str | None  # --product
    as_host: bool  # --as-host (spec 037)
    gh_args: list[str]


def _leading(passed: list[str]) -> _Leading:
    """A leading --app-key PATH, --product OWNER/NAME (or --flag=value), and --as-host, in any
    order, are shipmill's, since gh has no such flags before its command; the rest goes to gh
    untouched, an --as-host after gh's first argument included"""
    key: Path | None = None
    product: str | None = None
    host = False
    rest = passed
    while rest:
        if rest[0] == AS_HOST:
            if host:
                raise ReleaseError(f"{AS_HOST} is given twice")
            host, rest = True, rest[1:]
            continue
        flag, equals, value = rest[0].partition("=")
        if flag not in ("--app-key", "--product"):
            break
        if not equals:
            if len(rest) < 2:
                need = "the App's private key, such as ~/.config/shipmill/app-123.pem"
                raise ReleaseError(f"--app-key needs {need}" if flag == "--app-key" else "--product needs OWNER/NAME")
            value, rest = rest[1], rest[2:]
        else:
            rest = rest[1:]
        if flag == "--app-key":
            if key is not None:
                raise ReleaseError("--app-key is given twice")
            key = Path(value).expanduser()
        else:
            if product is not None:
                raise ReleaseError("--product is given twice")
            product = value
    if host and key is not None:
        raise ReleaseError(
            f"{AS_HOST} runs gh as the host's login and --app-key names an App's key: pass one of them, not both"
        )
    if host and product is not None:
        raise ReleaseError(f"{AS_HOST} can't go with --product: the product's token comes from [agents] app_id's App")
    return _Leading(key, product, host, rest)


AS_HOST = "--as-host"


def _host_write_refused(
    root: Path, top: Path | None, origin: str | None, config: bool, gh_args: list[str]
) -> ReleaseError:
    """S-037-1, S-037-2: the exit 2 of a write with no [agents] app_id, which neither the repo
    ([agents] identity = "host") nor the call (--as-host) allows, naming the repo and both fixes"""
    repo = repo_value(gh_args) or origin or (str(top) if top is not None else f"the folder {root} (no git checkout)")
    if top is None:
        why = f"the folder {root} is in no git checkout, so it has no {CONFIG_PATH} and no [agents] app_id"
    elif not config:
        why = f"{top} has no {CONFIG_PATH}, so no [agents] app_id"
    else:
        why = f"{CONFIG_PATH} sets no [agents] app_id"
    command = cli_command()  # #236: the form the person can run, as every hint names it
    return ReleaseError(
        f"refusing a write to {repo} as the host's gh login: {why}\n"
        f'allow it for this repo: give it an App ({command} app-create), or set [agents] identity = "host" in '
        f"{CONFIG_PATH}\n"
        f"allow this one call: {command} gh {AS_HOST} {shlex.join(gh_args)}"
    )


def _unreadable_top(root: Path) -> Path | None:
    """The nearest folder at or above root holding a .git that git couldn't read (a worktree
    whose repo is gone, a checkout of dubious ownership); None outside any checkout. Its config
    still decides gh's identity, so git failing never reads as "no App" (D-14)"""
    return next((folder for folder in (root, *root.parents) if (folder / ".git").exists()), None)


def _gh(
    root: Path,
    passed: list[str],
    api: Api,
    signer: Signer,
    environ: Mapping[str, str],
    home: Path,
    runner: GhRunner,
    readers: _GhReaders,
) -> int:
    """Spec 012: gh as the App when the checkout's config sets [agents] app_id; gh's exit code.
    With app_id set any failure to get the token exits 2 and gh never runs (D-14), and so does
    --as-host. Without it (spec 037), a read runs as the host's login, and a write too when
    [agents] identity = "host" or the call passes --as-host; any other write exits 2 and gh
    never runs. GH_TOKEN is never set but empty. As the App, a merge of a pull request with a
    `never` zone exits 2 and gh never runs (S-030-13), and with [agents] credit = "decider" it
    names who decided it (spec 049)"""
    leading = _leading(passed)
    key, gh_args = leading.key, leading.gh_args
    if leading.product is not None:
        return _gh_product(root, leading.product, key, gh_args, api, signer, environ, home, runner)
    if not root.is_dir():  # a mistyped --repo must not read as a repo with no App
        raise ReleaseError(f"--repo {root} is not a folder")
    git = Git(root)
    readable = git.ok("rev-parse", "--show-toplevel")
    top = Path(git.run("rev-parse", "--show-toplevel").strip()) if readable else _unreadable_top(root)
    identity = GhIdentity(config=False) if top is None else gh_identity_of(top)
    app_id = identity.app_id
    if app_id is not None and leading.as_host:  # S-037-10: before any token, App or not (D-14)
        raise ReleaseError(
            f"{AS_HOST} is refused: {CONFIG_PATH} sets [agents] app_id, so a write here goes as the App or not at "
            "all (D-14); drop --as-host, or, without the App's key on this host, run plain gh as yourself (spec 033)"
        )
    product = None if top is None else ProductConfig.load(top)
    if top is not None and product is not None and readable:  # S-038-3: before any token, App or not
        product.refuse_self(_known_origin(top))
    if top is not None and product is not None and product.component:  # S-038-10: before any token, App or not
        if not readable:
            raise ReleaseError(
                f"git can't read the checkout at {top}, a component of {product.home}, so its origin repo "
                f"can't be told; `git -C {top} status` names why"
            )
        bundled = bundled_repo_flag(gh_args)
        if bundled is not None:
            raise ReleaseError(
                f"gh's {bundled} bundles -R with another flag, and this repo is a component of {product.home} "
                "([product] home), whose session reaches only its origin repo (D-47); write -R owner/name on its "
                "own, so the repo it names can be checked"
            )
        named = named_repo(gh_args)
        if named is not None:
            product.refuse_outside(named, _origin_repo(top), f"gh's -R {named}")
    if top is None or app_id is None:
        if key is not None:
            raise ReleaseError(f"--app-key names an App's key, but no [agents] app_id is set in {CONFIG_PATH}")
        if not (is_read(gh_args) or identity.identity is WriteAs.HOST or leading.as_host):
            origin = _known_origin(top) if top is not None and readable else None
            raise _host_write_refused(root, top, origin, identity.config, gh_args)
        return runner([str(find_gh(environ)), *gh_args], as_host(environ))
    if not readable:
        raise ReleaseError(
            f"git can't read the checkout at {top}, which sets [agents] app_id, so the App's token can't be had; "
            f"`git -C {top} status` names why"
        )
    repo = named_repo(gh_args) or _origin_repo(top)
    if repo is None:
        raise ReleaseError(f"{top}'s origin isn't a GitHub repo; name the repo with gh's -R owner/name")
    merge = merge_of(gh_args)
    if merge is not None and gh_args[0] == "api" and identity.credit is Credit.DECIDER:  # S-049-10, before any token
        raise ReleaseError(
            f'{merge.command} is refused: [agents] credit = "decider" in {CONFIG_PATH}, and a merge through the API '
            f"leaves out who decided it (spec 049); run `{cli_command()} gh pr merge {merge.number} --squash` instead"
        )
    binary = find_gh(environ)
    cache = state_dir(Git(top)) / CACHE
    # S-033-11: the key at --app-key, else SHIPMILL_APP_KEY, else the default path; none there
    # exits 2 before any token, cached or not, and gh never runs (D-14)
    path = require_key(key or session_key(app_id, environ, home))
    try:
        token = app_token(cache, repo, app_id, path, dt.datetime.now(dt.UTC), signer, api)
    except NotInstalled as exc:
        raise ReleaseError(f"{exc}; install it with `{cli_command()} app-install {repo}`") from None
    if merge is not None:
        pull = _hold_never(top, merge, as_app(environ, token), binary, readers.merge)
        if identity.credit is Credit.DECIDER:
            gh_args = _credit(top, pull, gh_args, as_app(environ, token), binary, readers)
    return runner([str(binary), *gh_args], as_app(environ, token))


@dataclass(frozen=True, slots=True)
class _GhReaders:
    """What `shipmill gh` reads besides gh's arguments: the pull request a merge names (spec
    030), its deciders (spec 049), and stdin, for a `--body-file -`"""

    merge: MergeReader
    credit: CreditReader
    stdin: TextIO


def _credit_reader(top: Path, binary: Path, env: Mapping[str, str]) -> CreditReads:
    """The records a merge's credit reads, through the gh shipmill runs, with its env"""
    return GhCli(top, gh=str(binary), env=env)


def _credit(
    top: Path, pull: tuple[str, int], gh_args: list[str], env: Mapping[str, str], binary: Path, readers: _GhReaders
) -> list[str]:
    """Spec 049: gh's arguments for `gh pr merge` of the pull request (repo, number) with one
    `--body` in place of any given, the body it would have had followed by a Co-authored-by
    trailer for each decider it doesn't name yet, and one stderr line per decider; unchanged
    when no record names one, for a rebase (spec 026 refuses it), and for --disable-auto"""
    repo, number = pull
    flags = merge_flags(gh_args)
    if flags.disable_auto or flags.method == "rebase":
        return gh_args
    reads = readers.credit(top, binary, {**env, "GH_REPO": repo})
    record = reads.credit_pull(number)
    found = deciders(reads, record)
    if not found:
        return gh_args
    if flags.body is not None:
        base = flags.body
    elif flags.body_file is not None:
        base = readers.stdin.read() if flags.body_file == "-" else _body_file(flags.body_file)
    elif flags.method is None:
        raise ReleaseError(
            f'gh pr merge names no method, and [agents] credit = "decider" in {CONFIG_PATH} needs it to write the '
            f"body GitHub would: add --squash (or --merge for a stack's base, D-33)"
        )
    else:
        squash = flags.method == "squash"
        messages = reads.credit_messages()
        setting = messages.squash if squash else messages.merge
        base = default_body(setting, record, reads.credit_commits(number), squash)
    accounts = [reads.credit_account(named.person.login) for named in found]
    for named in found:  # S-049-9: a code span, so no email goes out for it (D-61)
        print(f"credit: `@{named.person.login}` {named.why}", file=sys.stderr)
    body = credited_body(base, accounts)
    return gh_args if body is None else with_body(gh_args, body)


def _body_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseError(f"gh pr merge's --body-file {path} can't be read: {exc.strerror}") from None


def _gh_reader(top: Path, binary: Path, env: Mapping[str, str]) -> MergeReads:
    """The pull request a merge names, read through the gh shipmill runs, with its env"""
    return GhCli(top, gh=str(binary), env=env)


def _hold_never(top: Path, merge: Merge, env: Mapping[str, str], binary: Path, reader: MergeReader) -> tuple[str, int]:
    """S-030-13: a merge of a pull request whose classification, by the levels at origin/HEAD,
    has a `never` zone exits 2, naming the zone and the maintainer's hand merge; approval in
    chat changes nothing, since nothing here reads it (D-48). Read with the App's token, in the
    checkout's own repo only, whose levels it holds. The pull request held, repo and number"""
    origin = _origin_repo(top)
    if origin is None:
        raise ReleaseError(f"{top}'s origin isn't a GitHub repo, so {merge.command}'s pull request can't be classified")
    gh_repo = env.get("GH_REPO")  # [HOST/]OWNER/REPO, as gh reads it
    target = merge.target(origin if not gh_repo else named_repo(["-R", gh_repo]) or origin)
    reads: MergeReads = reader(top, binary, {**env, "GH_REPO": target})
    number = merge.number
    if number is None:
        target, number = pull_url(reads.pull_of(merge.selector))
    if target.lower() != origin.lower():
        raise ReleaseError(
            f"{merge.command} names a pull request in {target}, and the levels that decide who merges it are "
            f"{target}'s: merge it from a checkout of {target}, whose origin it is (spec 030); this one's is {origin}"
        )
    git = Git(top)
    if not git.ok("rev-parse", "--verify", "--quiet", f"{DEFAULT_REF}^{{commit}}"):
        raise ReleaseError(
            f"{DEFAULT_REF} is not set in {top}, so the levels that decide who merges #{number} can't be read: run "
            f"`git -C {top} remote set-head origin --auto`"
        )
    if git.show(DEFAULT_REF, CONFIG_PATH.as_posix()) is None:
        raise ReleaseError(
            f"{DEFAULT_REF} has no {CONFIG_PATH}, so the levels that decide who merges #{number} can't be read: land "
            f"the config on the default branch through a pull request the maintainer merges, then run "
            f"`git -C {top} fetch origin`"
        )
    found = classify_pull(Base.read(git, DEFAULT_REF), reads, number)
    never = [z for z in found.zones if z.level is decide.Level.NEVER]
    if never:
        zones = "; ".join(f"{z.zone.value}: {z.reason}" for z in never)
        raise ReleaseError(
            f"{merge.command} is refused: #{number} in {target} has a never zone ({zones}), so only the maintainer "
            "merges it, by hand; an approval in chat doesn't change that (spec 030, D-48). Assign it to the "
            "maintainer and leave it"
        )
    return target, number


def _gh_product(
    root: Path,
    coordinated: str,
    key: Path | None,
    gh_args: list[str],
    api: Api,
    signer: Signer,
    environ: Mapping[str, str],
    home: Path,
    runner: GhRunner,
) -> int:
    """S-038-9: gh with the coordinator's token over the listed repos of coordinated's owner.
    Before any token is minted it exits 2 in a component, without [product] repos, for a repo
    not listed, for a -R naming a repo not listed or of another owner, and for a command that
    writes code or pull requests (D-47). gh works on -R's repo, else on coordinated, never on
    the checkout's origin: GH_REPO names it"""
    what = f"gh --product {coordinated}"
    top, repos = _coordinator(root, coordinated, what)
    refused = product_refusal(gh_args)
    if refused is not None:
        raise ReleaseError(
            f"{refused} under --product is refused: the coordinator never changes files, pushes, opens, edits, "
            "or merges a pull request, or runs a workflow outside the home repo (D-47); name the gh command "
            "first and its subcommand right after it, from the ones that read"
        )
    bundled = bundled_repo_flag(gh_args)
    if bundled is not None:
        raise ReleaseError(
            f"gh's {bundled} bundles -R with another flag; under --product write -R owner/name on its own, so the "
            "repo it names can be checked against [product] repos (D-47)"
        )
    named = named_repo(gh_args)
    target = coordinated if named is None else named
    if named is not None and named.lower() not in {r.lower() for r in repos}:
        raise ReleaseError(
            f"gh's -R {named} isn't a listed repo of {coordinated.partition('/')[0]}, which the token for "
            f"{coordinated} covers: {', '.join(repos)}; name it with --product (D-47)"
        )
    app_id = app_id_of(top)
    if app_id is None:
        raise ReleaseError(f"{what} needs [agents] app_id in {CONFIG_PATH}; the product's token comes from that App")
    # In the coordinator's session the session's gh helper comes first on PATH, and would put
    # the session's token over the product token: skip it, as the helper itself does
    binary = resolve_gh(state_dir(Git(top)) / HELPERS, environ.get("PATH", ""))
    cache = state_dir(Git(top)) / product_cache(coordinated.partition("/")[0])
    now = dt.datetime.now(dt.UTC)
    try:
        token = product_token(cache, repos, app_id, key or session_key(app_id, environ, home), now, signer, api)
    except NotInstalled as exc:
        raise ReleaseError(f"{exc}; install it with `{cli_command()} app-install {' '.join(repos)}`") from None
    return runner([str(binary), *gh_args], {**as_app(environ, token), "GH_REPO": target})


def _app_create(
    root: Path,
    args: argparse.Namespace,
    api: Api,
    signer: Signer,
    token: str | None = None,
    browser: Callable[[str], None] | None = None,
    key_dir: Path | None = None,
    install_seconds: float = FLOW_SECONDS,
    out: TextIO | None = None,
    ask: Callable[[str], str] | None = None,
) -> int:
    """Spec 006: discover, plan, create, install. Exit 1 when an installation is still missing"""
    host = token if token is not None else host_token()
    keys = key_dir if key_dir is not None else Path.home() / ".config" / "shipmill"
    stream = out if out is not None else (sys.stderr if args.json else sys.stdout)

    def say(line: str) -> None:
        print(line, file=stream, flush=True)  # S-006-19: each line as it happens, piped or not

    say("looking for the accounts you administer and their repos with .github/shipmill.toml...")
    found = accounts(api, host)
    repos = given_repos(args.repos.split(","), found) if args.repos else gated_repos(api, host, found)
    owner = args.owner
    if owner is None and ask is not None and not args.dry_run and not args.json:
        for line in owner_menu(found, repos):
            say(line)
        owner = pick_owner(found, ask(f"Owner [1-{len(found)}, Enter for {found[0].login}]: "))
    planned = plan(found, repos, owner, args.public, args.name)
    name, note = free_name(api, host, planned, found[0].login, args.name is not None)
    planned = dataclasses.replace(planned, name=name)
    if note is not None:
        say(f"note: {note}")
    record: dict[str, object] = planned.record()
    for line in planned.lines():
        say(line)
    if args.dry_run:
        if args.json:
            print(json.dumps(record, indent=2))
        return 0
    check_key_dir(keys)

    def open_url(url: str) -> None:
        say(f"open {url}")
        if browser is not None:
            browser(url)
        elif not args.no_browser:
            webbrowser.open(url)

    created = convert(create(planned, open_url), api, host, keys)
    say(f"created {created.slug} (App ID {created.app_id}), key in {created.key}")
    targets = planned.installable
    guided = guide(created.app_id, created.key, targets, api, signer, say, open_url, seconds=install_seconds)
    installed = guided.installed
    for line in config_lines(created):
        say(line)
    missing = [r for r in targets if r not in installed]
    for repo in missing:
        say(f"not installed on {repo}; install it at {guided.page}")
    record |= {"app_id": created.app_id, "slug": created.slug, "key": str(created.key), "installed": list(installed)}
    if args.json:
        print(json.dumps(record, indent=2))
    return 1 if missing else 0


def _status(
    root: Path,
    args: argparse.Namespace,
    run: StateRunner,
    api: Api,
    signer: Signer,
    login: LoginReader,
    home: Path | None = None,
    platform: str = sys.platform,
    now: dt.datetime | None = None,
) -> int:
    """Specs 008 and 009: the factory's picture for the checkout's repo, or with --rows or
    --json github-ship-watch's report passed through; exit 1 when a row needs action, 2 when
    the script failed rather than reported. Both reads pass the resolved roles as the gate's
    do (S-036-5), the maintainer the host's login (login) when the config lists nobody; a
    malformed [agents.roles] or an unreadable login needed for it exits 2 before any read"""
    git = Git(root)
    if not git.ok("rev-parse", "--show-toplevel"):  # S-008-9: first, before any other git call
        raise ReleaseError(f"{root} is not a git checkout; run status in a checkout of the repo, or pass --repo PATH")
    top = Path(git.run("rev-parse", "--show-toplevel").strip())
    slug: str | None = args.slug
    if slug is None:
        slug = _origin_repo(top)
        if slug is None:
            raise ReleaseError(f"{top}'s origin isn't a GitHub repo; name the repo, such as owner/name")
    else:
        check_checkout(Git(top), slug)
    picture = not (args.rows or args.json)
    resolved = roles.resolve(roles.configured(top), login)
    # S-040-10: the picture and --json show the levels; a malformed [autonomy] exits 2 first
    autonomy, environments = status.read_autonomy(top) if not args.rows else (AutonomyPolicy(), ())
    home = home if home is not None else Path.home()
    when = now if now is not None else dt.datetime.now(dt.UTC)

    def check(app_id: int, key: Path) -> Identity:
        return app_check(slug, key, home, signer, api)(app_id)  # signed at the call (#694)

    def bot_login(app_id: int, key: Path) -> str | None:
        try:
            return app_login(signer, api)(app_id, key)
        except ReleaseError as exc:  # the picture shows the App check's own failure instead
            if not picture:
                print(
                    f"shipmill: the App's bot login is unknown, so its questions read unanswered: {exc}",
                    file=sys.stderr,
                )
            return None

    # the picture reads as the gate's App, whose needs-decision questions are its own (spec 005)
    gate = status.read_gate(slug, top, home, platform, run, check, os.getuid()) if picture else None
    if gate is not None:  # S-031-17: the gate's own CLI against the latest release
        try:
            gate = dataclasses.replace(gate, cli=_gate_cli(top, slug, home))
        except status.CHECK_FAILURES as exc:  # S-044-4: the shipmill check's error, not the report's end
            gate = dataclasses.replace(gate, cli_error=status.first_line(exc))
        try:  # S-045-11: the gate's last prune, counted on the factory line
            gate = dataclasses.replace(gate, prune=load_prune(state_dir(Git(top)) / PRUNE))
        except status.CHECK_FAILURES as exc:
            gate = dataclasses.replace(gate, prune_error=status.first_line(exc))
    bot = None if gate is None else gate.login
    if bot is None:  # #311: --rows, --json, or a failed check still count the App's questions
        bot = status.read_login(slug, top, home, platform, bot_login)
    read = StateRead(bot_login=bot, roles=resolved)
    # #745: the picture reads the host's sections on their own, as factory does, so a failing
    # claude or marketplace read is its check's error; --rows and --json keep the full run
    proc = run(watch_command(slug, top, read, json=not args.rows, host=gate is None))
    sys.stderr.write(proc.stderr)  # S-008-10: warnings on 0 and 1, the whole traceback on a failure
    if state_failed(proc):
        print(f"shipmill: watch_state.py failed (exit {proc.returncode})", file=sys.stderr)
        return 2
    if gate is None:
        sys.stdout.write(proc.stdout)
        if args.json:  # S-040-10: one more line, after watch_state.py's, its hold from their HOLD rows
            rows = status.parse_rows(proc.stdout)
            record = status.autonomy_record(slug, autonomy, environments, rows, cli_command())
            sys.stdout.write(json.dumps(record) + "\n")
        return proc.returncode
    rows = status.parse_rows(proc.stdout)  # spec 022's milestone rows among them (#475)
    code = proc.returncode
    failed: dict[str, str] = {}
    for section in ("sessions", "shipmill"):  # S-044-4: a section that fails to run is its check's error
        try:
            found = factory.read_section(slug, top, section, run, wide=False)  # the repo's shadowing row (#764)
        except status.CHECK_FAILURES as exc:
            failed[section] = status.first_line(exc)
            continue
        rows += found.rows
        code = max(code, found.code)  # spec 008: 1 when a row needs action, theirs as before
    gate = dataclasses.replace(gate, sessions_error=failed.get("sessions"), shipmill_error=failed.get("shipmill"))
    # S-012-7, S-012-8: read only when agents write as an App
    people = agent_as_person.read(slug, run, when) if gate.agents is not None and gate.agents.app_id else None
    git = Git(top)
    main = status.read_main(git, status.landing_branch(slug, top, run))
    facts = status.Facts(
        repo=slug,
        rows=rows,
        issues=status.read_issues(slug, run, bot, resolved),
        pulls=status.read_pulls(slug, run),
        main=main,
        version=status.describe(git, main.remote),
        gate=gate,
        cli=importlib.metadata.version("shipmill"),
        now=when,
        checkout=top,
        command=cli_command(),
        agent_as_person=people,
        upgrades=status.read_upgrades(slug, top, run),
        autonomy=autonomy,
        environments=environments,
    )
    sys.stdout.write(status.report(facts).text(slug))
    return code  # S-009-14: spec 008's code, whatever the verdict


def _checkout(root: Path, slug: str | None, command: str) -> tuple[Path, str]:
    """The checkout's top level and its repo: origin's, or slug checked against it (S-008-9)"""
    git = Git(root)
    if not git.ok("rev-parse", "--show-toplevel"):
        where = "in a checkout of the repo, or pass --repo PATH"
        raise ReleaseError(f"{root} is not a git checkout; run {command} {where}")
    top = Path(git.run("rev-parse", "--show-toplevel").strip())
    if slug is None:
        slug = _origin_repo(top)
        if slug is None:
            raise ReleaseError(f"{top}'s origin isn't a GitHub repo; name the repo, such as owner/name")
    else:
        check_checkout(Git(top), slug)
    return top, slug


def _factory(
    root: Path,
    args: argparse.Namespace,
    run: StateRunner,
    api: Api,
    signer: Signer,
    github: GitHub | None,
    sessions: Sessions | None,
    home: Path,
    platform: str = sys.platform,
    now: dt.datetime | None = None,
) -> int:
    """Spec 044: this host's machinery for the checkout's repo, each check read on its own;
    exit 0 when every check passes, 1 when one finds a problem or fails to run"""
    top, slug = _checkout(root, args.slug, "factory")
    when = now if now is not None else dt.datetime.now(dt.UTC)
    git = Git(top)

    def check(app_id: int, key: Path) -> Identity:
        return app_check(slug, key, home, signer, api)(app_id)

    def main_branch() -> status.Main:
        branch = status.landing_branch(slug, top, run)
        git.run("fetch", "-q", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        return status.read_main(git, branch)

    def worktrees() -> factory.Worktrees:
        judged = judge(git, github or GhCli(top), sessions or ClaudeSessions(top), when)
        return factory.Worktrees(judged, judged[0].worktree.path.resolve(), git.landing_branch())

    host = factory.Host(
        gate=lambda: status.read_gate(slug, top, home, platform, run, check, os.getuid()),
        gate_cli=lambda: _gate_cli(top, slug, home),
        rows=lambda section: factory.read_rows(slug, top, section, run, wide=True),  # the host's (#764)
        main=main_branch,
        worktrees=worktrees,
        prune=lambda: load_prune(state_dir(git) / PRUNE),
    )
    found = factory.checks(slug, host, importlib.metadata.version("shipmill"), top, when, cli_command())
    sys.stdout.write(factory.as_json(found) if args.json else factory.text(found))
    return factory.exit_code(found)


def _milestones(root: Path, args: argparse.Namespace, github: GitHub | None) -> int:
    """#475, spec 022: the milestone rows of the lanes with milestone = true, read with the
    release's planner at the branch releases land on (the branch the config at origin's
    default branch names, else that default branch), fetched first; without such a lane nothing
    is fetched or read. It never writes GitHub: an overtaken milestone's rename is its row's
    fix. A read the planner fails (a goal, a policy, or GitHub) is printed as the error, and
    exits 0 as a report does; a checkout without a GitHub origin exits 2"""
    git = Git(root)
    if not git.ok("rev-parse", "--show-toplevel"):
        raise ReleaseError(
            f"{root} is not a git checkout; run milestones in a checkout of the repo, or pass --repo PATH"
        )
    top = Path(git.run("rev-parse", "--show-toplevel").strip())
    slug = _origin_repo(top)
    if slug is None:
        raise ReleaseError(f"{top}'s origin isn't a GitHub repo")
    rows: list[status.MilestoneRow] = []
    error = None
    if status.wants_milestones(top):
        checkout = Git(top)
        branch = checkout.landing_branch()  # the branch origin's default config names, else that default (#694, #697)
        # --force, as watch_state.py fetches: a moving major tag (v0) would refuse the fetch otherwise
        checkout.run("fetch", "-q", "--force", "--tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        head = checkout.sha(f"refs/remotes/origin/{branch}")
        hub = github or GhCli(top)
        rows, error = status.read_milestones(slug, top, head, hub, _now(args.now), cli_command())
    if args.json:
        print(json.dumps({"milestones": [r.record() for r in rows], "error": error}, indent=2))
        return 0
    for row in rows:
        print(row.text())
    if error is not None:
        print(f"not read: {error}")
    elif not rows:
        print("no milestone waits or was overtaken")
    return 0


def _downstream_start(root: Path, args: argparse.Namespace, library: Library, api: Api, signer: Signer) -> int:
    """Spec 032: `downstream start`, run by the reusable downstream.yml on the default branch's
    checkout, never the pull request's"""
    if args.pr < 1:
        raise ReleaseError(f"--pr is a pull request's number, got {args.pr}")
    actor: str | None = args.actor
    if actor is not None and not actor.strip():
        raise ReleaseError("--actor names who started the run; omit it on pull_request_target")
    # a person's start is pinned to the head they read (S-032-19); pull_request_target needs none
    pinned = dispatched_sha(args.sha) if actor is not None or args.sha is not None else None
    config = Policy.load(config_path(root)).downstream
    if config is None:
        raise ReleaseError(f"{CONFIG_PATH} has no [downstream] section, so no downstream repository to test")

    def clock() -> dt.datetime:
        return dt.datetime.now(dt.UTC)

    dispatcher = AppDispatcher(config.app_id, args.app_key, signer, api, clock)
    key = key_problem(config.app_id, args.app_key, signer, api, clock)
    try:
        lines = start(config, library, dispatcher, key, args.pr, actor, _doctor_repo(root), clock, pinned)
    except HeadMoved as exc:
        print(f"shipmill: {exc}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


def _downstream_collect(root: Path, args: argparse.Namespace, library: Library, api: Api, signer: Signer) -> int:
    """Spec 032: `downstream collect`, run by the reusable downstream.yml on the default
    branch's checkout once start has dispatched the downstream runs"""
    if args.pr < 1:
        raise ReleaseError(f"--pr is a pull request's number, got {args.pr}")
    config = Policy.load(config_path(root)).downstream
    if config is None:
        raise ReleaseError(f"{CONFIG_PATH} has no [downstream] section, so no downstream run to collect")

    def clock() -> dt.datetime:
        return dt.datetime.now(dt.UTC)

    runs = AppRuns(config.app_id, args.app_key, signer, api, clock)
    for line in collect(config, library, runs, args.pr, args.head, clock, time.sleep):
        print(line, flush=True)
    return 0


def _doctor_repo(root: Path) -> str | None:
    """The repo doctor reads the plugin's installs for: the origin's, or None without a GitHub
    origin, which doctor's remote check reports"""
    return _known_origin(root)


def _known_origin(root: Path) -> str | None:
    """The checkout's GitHub origin as owner/name, or None without an origin remote or one on
    GitHub"""
    try:
        return _origin_repo(root)
    except ReleaseError:  # no origin remote
        return None


def _origin_repo(root: Path) -> str | None:
    """The checkout's GitHub origin as owner/name, or None outside a GitHub checkout"""
    if not (root / ".git").exists():
        return None
    url = Git(root).run("remote", "get-url", "origin").strip()
    found = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return found.group(1) if found else None


def _app_install(
    root: Path,
    args: argparse.Namespace,
    api: Api,
    signer: Signer,
    browser: Callable[[str], None] | None = None,
    out: TextIO | None = None,
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    sleep: Callable[[float], None] = time.sleep,
    seconds: float = WAIT_SECONDS,
) -> int:
    """Spec 007: guide installing the App on the repos; exit 1 when one is still missing"""
    stream = out if out is not None else (sys.stderr if args.json else sys.stdout)

    def say(line: str) -> None:
        print(line, file=stream, flush=True)  # S-007-7

    repos: list[str] = list(args.repos)
    if not repos:
        origin = _origin_repo(root)
        if origin is None:
            raise ReleaseError(f"{root} is not a GitHub checkout; name the repos, such as owner/name")
        repos = [origin]
    app_id: int | None = args.app_id
    if app_id is None:
        app_id = AgentsConfig.load(root).app_id if (root / CONFIG_PATH).is_file() else None
    if app_id is None:
        raise ReleaseError("no [agents] app_id in this checkout's config; pass --app-id")
    key = check_key(args.app_key if args.app_key is not None else default_key(app_id, Path.home()))

    def browse(url: str) -> None:
        if browser is not None:
            browser(url)
        elif not args.no_browser:
            webbrowser.open(url)

    guided = guide(app_id, key, repos, api, signer, say, browse, clock, sleep, seconds)
    missing = [r for r in repos if r not in guided.installed]
    for repo in missing:
        say(f"not installed on {repo}; install it at {guided.page}")
    if args.json:
        print(json.dumps(guided.record(app_id, repos), indent=2))
    return 1 if missing else 0


def _decide(root: Path, args: argparse.Namespace, pulls: Pulls) -> int:
    """Spec 030: `decide levels` from the working tree's config or --ref's; `decide classify`
    by the levels at --ref, never the change's own"""
    git = Git(root)
    if args.decide == "levels":
        policy = Policy.load(config_path(root)) if args.ref is None else policy_at(git, args.ref)
        rows = decide.levels(policy.decisions, policy.autonomy)
        if args.json:
            record = {"veto_hours": int(policy.decisions.veto_hours), "zones": [r.record() for r in rows]}
            print(json.dumps(record, indent=2))
        else:
            print(f"veto_hours: {int(policy.decisions.veto_hours)}")
            for row in rows:
                print(row.text())
        return 0
    base = Base.read(git, args.ref)
    if args.pr is not None:
        if args.pr < 1:
            raise ReleaseError(f"--pr is a pull request's number, got {args.pr}")
        found = classify_pull(base, pulls, args.pr)
    else:
        found = classify_paths(base, [RepoPath.given(p) for p in args.files])
    sys.stdout.write(json.dumps(found.record(), indent=2) + "\n" if args.json else found.text())
    return 0


def _autonomy(root: Path, ref: str, as_json: bool, github: GitHub) -> int:
    """Spec 040: every stage's level at ref, never the working tree's, so a change that raises
    a level is read by the level it would replace; the hold read through gh, which stops it
    when it can't be read, as a level under an unknown hold is unknown"""
    policy = policy_at(Git(root), ref)
    hold = Hold.read(github)
    rows = policy.autonomy.levels(hold, [EnvironmentName(name) for name in policy.environments])
    if as_json:
        print(json.dumps({"hold": list(hold.issues), "stages": [row.record() for row in rows]}, indent=2))
        return 0
    for issue in hold.issues:
        print(f"hold: {issue}")
    width = max(18, *(len(row.stage) for row in rows))
    for row in rows:
        print(row.text(width))
    return 0


def _review(root: Path, args: argparse.Namespace) -> int:
    if args.review_command == "check":
        problems = review.check(root)
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    if args.review_command != "show":
        file = review.review_file(root, args.dir)
        if args.review_command == "add-rule":
            edited = review.add_rule(root, file, LineText(args.text))
        elif args.review_command == "protect":
            edited = review.protect(root, file, review.Glob(args.glob), LineText(args.why))
        elif args.review_command == "set-cap":
            edited = review.set_cap(root, file, args.cap)
        else:
            edited = review.retire(root, file, args.target)
        print(edited.text)  # the line written, or removed
        return 0
    rubric = review.show(root, args.path)
    sys.stdout.write(json.dumps(rubric.to_json(), indent=2) + "\n" if args.json else rubric.render())
    return 0


def _evals(root: Path, resolves: evals.Resolves | None = None, gate: bool = False) -> int:
    """Spec 025: one line per violation, exit 1 when any; a repository without evals/ passes,
    so CI runs the check before the suite exists. With gate, also exit 1 naming each kind
    short of the first suite's counts (S-025-16), an empty suite short of all"""
    report = evals.check(root, resolves)
    if report is None:
        print(f"no case under {evals.SUITE}/: nothing to check")
    else:
        for violation in report.violations:
            print(violation)
        if report.violations:
            return 1
        print(f"{evals.MANIFEST}: well formed, {report.cases} cases")
    if not gate:
        return 0
    short = evals.gate_short(report.entries if report is not None else ())
    if short:
        print(f"gate off: short of the first suite's counts, {', '.join(str(s) for s in short)}")
        return 1
    print("gate on: " + ", ".join(f"{need} {kind}" for kind, need in evals.GATE.items()) + " cases at least")
    return 0


def _tolerance(text: str) -> Fraction:
    if not re.fullmatch(r"0(\.[0-9]+)?|1(\.0+)?", text):
        raise argparse.ArgumentTypeError(f"a decimal from 0 to 1, such as 0.05; got {text!r}")
    return Fraction(text)


def _case_path(text: str) -> PurePosixPath:
    if not evals.case_path_ok(text):
        raise argparse.ArgumentTypeError(f"a case's path relative to evals/, such as <skill>/<case>; got {text!r}")
    return PurePosixPath(text)


def _evals_compare(base_file: Path, head_file: Path, changed: frozenset[PurePosixPath], tolerance: Fraction) -> int:
    """Spec 025, D-37: one line per case that moved, then both pass rates; exit 1 on a
    regression or on a run stopped at its budget, 2 on a missing or malformed result"""
    base, head = evals.read_result(base_file), evals.read_result(head_file)
    # the budget first: a run it stopped compares nothing, and a changed case it never
    # reached holds no runs, so naming that case would hide the budget line (S-025-14)
    stopped = evals.budget_reached(base, head)
    if stopped is not None:
        print(stopped)
        return 1
    unknown = sorted(changed - set(head.cases))
    if unknown:
        named = ", ".join(str(p) for p in unknown)
        raise ReleaseError(f"--changed {named}: {head_file} holds no such case")
    result = evals.compare(base, head, changed, tolerance)
    for moved in result.moved:
        print(moved)
    if result.suite_worse:
        print(f"suite got worse: the head's pass rate is more than {float(tolerance):g} below the base's")
    for side, rate in (("base", result.base), ("head", result.head)):
        shown = f"{float(rate.value):.3f}" if rate.runs else "none"
        print(f"{side} pass rate: {shown} ({rate} runs)")
    return 1 if result.failed else 0


def _upgrade(root: Path, args: argparse.Namespace, github: GitHub) -> int:
    """List the pending upgrades, apply one (its edit in the checkout, nothing committed), or
    propose them as issues; the list and the proposals leave out a declined upgrade"""
    if args.apply is not None:
        applied = apply(root, find(UpgradeId(args.apply)))
        upgrade = applied.upgrade
        if args.json:
            record = {
                "id": str(upgrade.id),
                "config": CONFIG_PATH.as_posix(),
                "line": "\n".join(applied.lines) if applied.added else None,
                "lines": list(applied.lines) if applied.added else [],
                "removed": upgrade.removes,
                "created": [p.as_posix() for p in applied.created],
                "kept": [p.as_posix() for p in applied.kept],
            }
            print(json.dumps(record, indent=2))
            return 0
        if upgrade.removes is not None:
            print(f"removed {upgrade.removes} from [{upgrade.table}] in {CONFIG_PATH}")
        if applied.added:
            for line in applied.lines:
                print(f"added {line} to [{upgrade.table}] in {CONFIG_PATH}")
        for path in applied.created:
            print(f"wrote {path.as_posix()}")
        for path in applied.kept:
            print(f"kept {path.as_posix()}: it already exists")
        print("next: review the diff, commit it on a branch, and open a pull request")
        return 0
    raw = read_config(config_path(root))
    if args.propose:
        autonomy = Table(raw, str(CONFIG_PATH)).table("autonomy", optional=True)
        level = AutonomyPolicy.parse(autonomy).upgrade
        fix = f"grant `issues: write` to the job in {CALLER} that calls shipmill's land.yml"
        done = propose_upgrades(raw, level, github, fix)
        if args.json:
            records = [{"id": str(d.id), "issue": d.issue, "outcome": str(d.outcome)} for d in done]
            print(json.dumps(records, indent=2))
            return 0
        for d in done:
            print(f"{d.outcome} #{d.issue}: {d.id}")
        if level is Autonomy.OBSERVE:
            print("upgrade autonomy is observe: no upgrade issue opened or updated")
        elif not done:
            print("no pending upgrades")
        return 0
    # GitHub is read only when an upgrade is pending, to leave out the declined ones
    found = offers(raw, github.labelled_issues(UPGRADE_LABEL)) if pending(raw) else ()
    if args.json:
        print(json.dumps([o.upgrade.record(raw) | {"issue": o.issue} for o in found], indent=2))
        return 0
    if not found:
        print("no pending upgrades")
    for offer in found:
        upgrade = offer.upgrade
        print(f"{upgrade.id} (shipmill {upgrade.version}): {upgrade.changes}")
        if upgrade.removes is not None:
            print(f"  removes: [{upgrade.table}] {upgrade.removes}")
        if upgrade.adds(raw):
            for line in upgrade.lines(raw):
                print(f"  adds: [{upgrade.table}] {line}")
        print(f"  off: {upgrade.off}")
        if offer.issue is not None:
            print(f"  proposed: #{offer.issue}")
        print(f"  apply: `{cli_command()} upgrade --apply {upgrade.id}`")
    return 0


def _product(root: Path, args: argparse.Namespace) -> int:
    """Spec 024: check exits 1 naming each broken rule; show and ids refuse a broken direction"""
    if args.product == "check":
        at = None if args.ref is None else GitRef.resolve(root, args.ref)  # S-034-1: an unknown ref exits 2
        problems = check_product(root, at)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        direction = read_product(root, at)
        where = "" if at is None else f" at {at}"
        print(f"{DIRECTION}{where}: well formed, {len(direction.all_items())} items")
        return 0
    if args.product in ("add", "edit", "retire"):
        if args.product == "add":
            edited = product.add(root, Section.named(args.section), LineText(args.text))
        elif args.product == "edit":
            edited = product.edit(root, ItemId.parse(args.id), LineText(args.text))
        else:
            edited = product.retire(root, ItemId.parse(args.id))
        print(edited.text)  # the line written, or removed
        return 0
    if args.product == "measure":
        goal = ItemId.parse(args.id)
        written = None if args.clear else Measure.parse(str(LineText(args.measure)))
        measured = product.measure(root, goal, written)
        print(f"{goal} has no measure line; nothing written" if measured is None else measured.text)
        return 0
    direction = read_product(root)
    if args.product == "ids":
        for item in direction.all_items():
            print(item)
        return 0
    sections = [Section.named(option) for option in args.section]
    if args.json:
        print(json.dumps(direction.record(sections), indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(direction.render(sections))
    return 0


def _launchd(root: Path, args: argparse.Namespace) -> int:
    home = Path.home()
    if args.remove:
        removed = remove(args.slug, home)
        print(f"removed {removed}" if removed else f"no launchd job for {args.slug}")
        return 0
    git = Git(root)
    check_checkout(git, args.slug)
    key: Path | None = None if args.app_key is None else args.app_key.expanduser().resolve()
    token: Path | None = None if args.claude_token is None else TokenSource.of(args.claude_token, home).path
    path = os.environ.get("PATH", "")
    job = build(args.slug, root, args.every, args.tool, args.claude_arg, home, path, app_key=key, claude_token=token)
    if args.print:
        sys.stdout.write(job.document.decode())
        return 0
    refresh(git)  # a dedicated checkout, at the default branch's head; strict: one on a branch is refused
    agents = AgentsConfig.load(root)  # the job would fail on every run without it
    if key is not None:  # as would a key for no App, or one the gate refuses
        if agents.app_id is None:
            raise ReleaseError(f"--app-key names an App's key, but [agents] in {CONFIG_PATH} sets no app_id")
        check_key(key)
    if token is not None:  # S-035-9: a token file the gate would refuse fails every tick
        read_token(TokenSource(token, named=True))
    install(job)
    print(f"installed {job.plist}: every {args.every} min, log {job.log}")
    print(f"prompt: {agents.prompt}")
    return 0


def run() -> None:
    try:
        code = main(sys.argv[1:])
    except ReleaseError as exc:
        print(f"shipmill: {exc}", file=sys.stderr)
        code = 2
    sys.exit(code)
