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
  review          REVIEW.md, the review rubric (spec 024): check exits 1 naming the file, line, and rule
                  a structured section breaks; show prints the rubric for the files given with --path,
                  the root's and their directories' merged, as Markdown or --json; add-rule, protect,
                  set-cap, and retire edit one line (--dir DIR: DIR/REVIEW.md) and print it
  status          say whether the factory works or is stuck: a verdict, then a short summary with
                  a line per reason and a direct link per item; --rows for github-ship-watch's
                  table, --json for its JSON lines
  milestones      read-only: with a lane that sets milestone = true, print MILESTONE_WAITING for a goal's
                  milestone waiting on its specs and MILESTONE_OVERTAKEN for an open milestone a stable
                  tag took, with the version to rename it to and the `gh api` rename, run through
                  shipmill gh; --json for one JSON object (spec 022)
  upgrade         list the config upgrades this repo hasn't decided or declined (spec 014); --apply <id>
                  makes one's edit in the checkout and commits nothing; --propose opens or updates
                  one shipmill-upgrade issue per pending upgrade, as land.yml runs it after a release
  init            write a starting policy, the calling workflow, and changelog.d/README.md for changelog
                  fragments (--no-fragments: no fragments; --operate: only the operate workflow;
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
                  --git-credential answers as git's credential helper
  gh              run gh with the arguments that follow, as the repo's GitHub App when
                  [agents] app_id is set (the token limited to gh's -R/--repo, else origin's
                  repo), else as the host's gh login; exits with gh's code. Every gh call that
                  writes in an agent session goes through it
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
                  as the App; a fork's pull request waits for a person's workflow_dispatch;
                  collect finds each run by its shipmill-id and concludes its check

Exit codes: 0 done (a plan may skip); 1 doctor found a failure, status found a row that needs
action, app-create or app-install left a repo without the App, product check found a broken
rule, review check found a malformed REVIEW.md, evals check found a malformed case (or, with
--gate, a suite short of the gate's counts), or evals compare found a regression or a run
stopped at its budget; 2 bad input or a refused state, such as an edit of a file its check
refuses, a malformed evals/cases.toml, or a missing or malformed aggregate-result.json.
"""

import argparse
import dataclasses
import datetime as dt
import importlib.metadata
import json
import os
import re
import shutil
import sys
import time
import webbrowser
from collections.abc import Callable, Mapping
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import TextIO

from shipmill import agent_as_person, cli_command, evals, fragments, product, requires, review, status
from shipmill.agents import AgentsConfig, app_id_of
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
    cache_outside,
    check_key,
    credential,
    default_key,
    prepare_session,
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
from shipmill.app_gh import GhRunner, as_app, as_host, find_gh, named_repo, run_gh
from shipmill.app_install import WAIT_SECONDS, guide
from shipmill.autonomy import Autonomy, AutonomyPolicy, Hold
from shipmill.claude_auth import ClaudeAuth, claude_auth, run_auth
from shipmill.config import CONFIG_PATH, Table, config_path
from shipmill.config import read as read_config
from shipmill.doctor import CALLER, DOWNSTREAM_CALLER, OPERATE_CALLER, doctor, read_plugin_rows
from shipmill.downstream import (
    AppDispatcher,
    AppRuns,
    GhLibrary,
    GhReader,
    Library,
    Reader,
    app_on_host,
    collect,
    key_problem,
    start,
)
from shipmill.errors import ReleaseError
from shipmill.gate import (
    ClaudeCli,
    StateRead,
    StateRunner,
    check_checkout,
    gate,
    host_login,
    pruner,
    refresh,
    run_command,
    run_state,
    state_dir,
    state_failed,
    tick_lines,
    tick_record,
    watch,
    watch_command,
)
from shipmill.github import UPGRADE_LABEL, GhCli, GitHub
from shipmill.gitrepo import Git
from shipmill.hooks import HookTest, run_hook, self_test
from shipmill.init import RunsOn, init, init_caller, init_downstream, init_operate
from shipmill.land import ActionsRun, Prepared, Stop, cleanup, land, prepare, work_branch
from shipmill.launchd import DEFAULT_EVERY, DEFAULT_TOOL, build, cli_fix, install, read_job, remove
from shipmill.lineedit import LineText
from shipmill.notify import Desktop
from shipmill.operate import Http, Unreachable, UrllibHttp, approve, approve_rollback, operate, summary
from shipmill.planner import Actor, Event, Hotfix, Planner, Proposal
from shipmill.plugin import CLI_RECORD, MARKERS, GateCli, PluginHost, load_cli
from shipmill.policy import Lane, Policy
from shipmill.product import DIRECTION, ItemId, Measure, Section
from shipmill.product import check as check_product
from shipmill.product import read as read_product
from shipmill.propose import close_released, propose, run_url
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
    shown.add_argument("--json", action="store_true", help="print github-ship-watch's JSON lines instead")

    p = sub.add_parser(
        "milestones",
        help="print the milestones a lane with milestone = true waits on or a stable tag overtook (spec 022)",
    )
    p.add_argument("--json", action="store_true", help="print the rows and the read's error as one JSON object")
    p.add_argument("--now", help="ISO time with offset (default: now)")

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
        help=f"write only {OPERATE_CALLER}, which runs shipmill operate every 10 minutes",
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
        help="decide and print; start, stop, move, or prune nothing (lists the worktrees it would prune)",
    )
    p.add_argument("--json", action="store_true", help="print the decision, with the pruned worktrees, as JSON")
    p.add_argument(
        "--app-key",
        type=Path,
        help="the private key of the App in [agents] app_id (default: ~/.config/shipmill/app-<app_id>.pem)",
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
    p.add_argument("slug", metavar="owner/name", help="the GitHub repo the token is limited to; --repo is its checkout")
    p.add_argument("--app-id", type=int, required=True, help="the App's id, as [agents] app_id names it")
    p.add_argument("--app-key", type=Path, help="the App's private key (default: ~/.config/shipmill/app-<app_id>.pem)")
    p.add_argument(
        "--git-credential",
        metavar="OPERATION",
        help=(
            "answer git's credential protocol on stdin: get prints username=x-access-token and the token "
            "as password for https://github.com; store, erase, and other operations print nothing"
        ),
    )

    sub.add_parser(
        "gh",
        add_help=False,  # `shipmill gh --help` is gh's help: every argument after gh goes to gh
        help=(
            "run gh with the arguments that follow, as [agents] app_id's GitHub App when set, else as the "
            "host's gh login (spec 012); use it for every gh call that writes from an agent session. "
            "Only a leading --app-key PATH is shipmill's (default: ~/.config/shipmill/app-<app_id>.pem)"
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
) -> int:
    """github stands in for gh, http for the health checks, sessions for `claude agents`, api
    for GitHub's REST API, signer for openssl, stdin for git's credential request, state for
    watch_state.py (and doctor's AGENT_AS_PERSON read), environ for this process's env, home
    for the user's home, gh_runner for running `shipmill gh`'s gh, library for the library's
    repository `downstream start` and `collect` write checks on, and downstream_reader for
    what doctor reads of the secrets and the downstream workflows, as tests pass fakes"""
    head, passed = _split_gh(argv)
    args = _parser().parse_args(head)
    root: Path = args.repo.resolve()
    env = environ if environ is not None else os.environ
    user_home = home if home is not None else Path.home()
    if args.command == "gh":
        if passed is None:  # such as `shipmill -- gh ...`
            raise ReleaseError("only --repo PATH may come before gh, as in `shipmill --repo PATH gh pr list`")
        return _gh(root, passed, api or UrllibApi(), signer or Openssl(), env, user_home, gh_runner or run_gh)
    if args.command == "app-token":
        return _app_token(root, args, api or UrllibApi(), signer or Openssl(), stdin or sys.stdin, env, user_home)
    if args.command == "app-install":
        return _app_install(root, args, api or UrllibApi(), signer or Openssl())
    if args.command == "app-create":
        ask = input if sys.stdin.isatty() and not args.owner else None
        return _app_create(root, args, api or UrllibApi(), signer or Openssl(), ask=ask)
    if args.command == "status":
        return _status(root, args, state or run_state, api or UrllibApi(), signer or Openssl())
    if args.command == "milestones":
        return _milestones(root, args, github)
    if args.command == "upgrade":
        return _upgrade(root, args, github or GhCli(root))
    if args.command == "product":
        return _product(root, args)
    if args.command == "review":
        return _review(root, args)
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
                raise ReleaseError(f"--runs-on sets {CALLER}'s runner; --operate writes only {OPERATE_CALLER}")
            print(f"wrote {init_operate(root, args.force).relative_to(root)}")
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
        checks = doctor(
            root,
            github or (GhCli(root) if has_gh else None),
            plugins,
            people,
            slug,
            hooks=hooks,
            auth=_claude_auth(env),
            downstream=downstream_reader or (GhReader(root) if has_gh else None),
            app=app_on_host(key, user_home, signer or Openssl(), api or UrllibApi(), lambda: dt.datetime.now(dt.UTC)),
            gate_cli=None if slug is None else (lambda: _gate_cli(root, slug, user_home)),
            pypi=lambda url: _pypi_status(url, http),
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
        landed = land(git, policy, hub, Lane(args.lane), args.version, args.sha, args.base, args.date or today)
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


def _claude_auth(environ: Mapping[str, str]) -> Callable[[], ClaudeAuth]:
    """#500's preflight, with claude looked up on environ's PATH"""
    program = shutil.which("claude", path=environ.get("PATH", ""))
    return lambda: claude_auth(run_auth, program)


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
    return None if version is None else GateCli(version, cli_fix(read_job(repo, home), repo))


def _gate(root: Path, args: argparse.Namespace, github: GitHub, sessions: Sessions) -> int:
    git = Git(root)
    path = os.environ.get("PATH", "")

    def session_env(identity: Identity) -> dict[str, str]:
        """The helpers go in the checkout's state folder and run this very shipmill"""
        return prepare_session(identity, state_dir(git) / HELPERS, Path(sys.executable), root, args.slug, path)

    decision, launched, waiting, pruned = gate(
        git,
        args.slug,
        lambda: AgentsConfig.load(root),
        ClaudeCli(args.claude_arg),
        lambda read: watch(args.slug, root, read),
        dt.datetime.now(dt.UTC),
        lambda: Hold.read(GhCli(root)),
        Desktop.detect(),
        pruner(git, github, sessions),
        args.refresh,
        args.dry_run,
        app_check(args.slug, args.app_key, Path.home(), Openssl(), UrllibApi()),
        args.app_key is not None,
        session_env,
        lambda: host_login(root),
        plugin=PluginHost(
            run_command,
            GateCli(requires.running(), cli_fix(read_job(args.slug, Path.home()), args.slug)),
            _pypi_status,
            Path.home() / MARKERS,
            lambda: requires.check(read_config(config_path(root))),
        ),
        hooks=_hook_test(root, os.environ, Path.home()),
        auth=_claude_auth(os.environ),
    )
    if args.json:
        print(json.dumps(tick_record(decision, launched, waiting, pruned, args.dry_run), indent=2))
        return 0
    print("\n".join(tick_lines(decision, launched, waiting, pruned, args.dry_run)))
    return 0


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
    app_id: int = args.app_id
    if app_id < 1:
        raise ReleaseError(f"--app-id must be 1 or more, got {app_id}")
    key: Path = args.app_key if args.app_key is not None else default_key(app_id, home)
    cache = _cache(root, args.slug, environ, home)

    def token() -> str:
        return app_token(cache, args.slug, app_id, key, dt.datetime.now(dt.UTC), signer, api)

    if args.git_credential is None:
        print(token())
        return 0
    sys.stdout.write(credential(args.git_credential, stdin.read(), token))
    return 0


def _app_key(passed: list[str]) -> tuple[Path | None, list[str]]:
    """A leading --app-key PATH (or --app-key=PATH) is shipmill's, since gh has no such flag
    before its command; the rest goes to gh untouched"""
    if passed[:1] == ["--app-key"]:
        if len(passed) < 2:
            raise ReleaseError("--app-key needs the App's private key, such as ~/.config/shipmill/app-123.pem")
        return Path(passed[1]).expanduser(), passed[2:]
    if passed and passed[0].startswith("--app-key="):
        return Path(passed[0].removeprefix("--app-key=")).expanduser(), passed[1:]
    return None, passed


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
) -> int:
    """Spec 012: gh as the App when the checkout's config sets [agents] app_id, else as the
    host's login; gh's exit code. With app_id set any failure to get the token exits 2 and gh
    never runs (D-14); GH_TOKEN is never set but empty"""
    key, gh_args = _app_key(passed)
    if not root.is_dir():  # a mistyped --repo must not read as a repo with no App
        raise ReleaseError(f"--repo {root} is not a folder")
    git = Git(root)
    readable = git.ok("rev-parse", "--show-toplevel")
    top = Path(git.run("rev-parse", "--show-toplevel").strip()) if readable else _unreadable_top(root)
    app_id = None if top is None else app_id_of(top)
    if top is None or app_id is None:
        if key is not None:
            raise ReleaseError(f"--app-key names an App's key, but no [agents] app_id is set in {CONFIG_PATH}")
        return runner([str(find_gh(environ)), *gh_args], as_host(environ))
    if not readable:
        raise ReleaseError(
            f"git can't read the checkout at {top}, which sets [agents] app_id, so the App's token can't be had; "
            f"`git -C {top} status` names why"
        )
    repo = named_repo(gh_args) or _origin_repo(top)
    if repo is None:
        raise ReleaseError(f"{top}'s origin isn't a GitHub repo; name the repo with gh's -R owner/name")
    binary = find_gh(environ)
    cache = state_dir(Git(top)) / CACHE
    try:
        token = app_token(cache, repo, app_id, key or default_key(app_id, home), dt.datetime.now(dt.UTC), signer, api)
    except NotInstalled as exc:
        raise ReleaseError(f"{exc}; install it with `{cli_command()} app-install {repo}`") from None
    return runner([str(binary), *gh_args], as_app(environ, token))


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
    home: Path | None = None,
    platform: str = sys.platform,
    now: dt.datetime | None = None,
) -> int:
    """Specs 008 and 009: the factory's picture for the checkout's repo, or with --rows or
    --json github-ship-watch's report passed through; exit 1 when a row needs action, 2 when
    the script failed rather than reported"""
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
    home = home if home is not None else Path.home()
    when = now if now is not None else dt.datetime.now(dt.UTC)

    def check(app_id: int, key: Path) -> Identity:
        return app_check(slug, key, home, signer, api)(app_id, when)

    def bot_login(app_id: int, key: Path) -> str | None:
        try:
            return app_login(signer, api)(app_id, key, when)
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
        gate = dataclasses.replace(gate, cli=_gate_cli(top, slug, home))
    login = None if gate is None else gate.login
    if login is None:  # #311: --rows, --json, or a failed check still count the App's questions
        login = status.read_login(slug, top, home, platform, bot_login)
    proc = run(watch_command(slug, top, StateRead(bot_login=login), json=not args.rows))
    sys.stderr.write(proc.stderr)  # S-008-10: warnings on 0 and 1, the whole traceback on a failure
    if state_failed(proc):
        print(f"shipmill: watch_state.py failed (exit {proc.returncode})", file=sys.stderr)
        return 2
    if gate is None:
        sys.stdout.write(proc.stdout)
        return proc.returncode
    # S-012-7, S-012-8: read only when agents write as an App
    people = agent_as_person.read(slug, run, when) if gate.agents is not None and gate.agents.app_id else None
    git = Git(top)
    main = status.read_main(git, status.read_branch(slug, run))
    facts = status.Facts(
        repo=slug,
        rows=status.parse_rows(proc.stdout),  # spec 022's milestone rows among them (#475)
        issues=status.read_issues(slug, run, login),
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
    )
    sys.stdout.write(status.report(facts).text(slug))
    return proc.returncode  # S-009-14: spec 008's code, whatever the verdict


def _milestones(root: Path, args: argparse.Namespace, github: GitHub | None) -> int:
    """#475, spec 022: the milestone rows of the lanes with milestone = true, read with the
    release's planner at origin's default branch, fetched first; without such a lane nothing
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
        branch = checkout.default_branch()
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
    config = Policy.load(config_path(root)).downstream
    if config is None:
        raise ReleaseError(f"{CONFIG_PATH} has no [downstream] section, so no downstream repository to test")

    def clock() -> dt.datetime:
        return dt.datetime.now(dt.UTC)

    dispatcher = AppDispatcher(config.app_id, args.app_key, signer, api, clock)
    key = key_problem(config.app_id, args.app_key, signer, api, clock)
    for line in start(config, library, dispatcher, key, args.pr, actor, _doctor_repo(root), clock):
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
                "line": upgrade.line if applied.added else None,
                "removed": upgrade.removes,
                "created": [p.as_posix() for p in applied.created],
                "kept": [p.as_posix() for p in applied.kept],
            }
            print(json.dumps(record, indent=2))
            return 0
        if upgrade.removes is not None:
            print(f"removed {upgrade.removes} from [{upgrade.table}] in {CONFIG_PATH}")
        if applied.added:
            print(f"added {upgrade.line} to [{upgrade.table}] in {CONFIG_PATH}")
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
            records = [{"id": str(d.upgrade.id), "issue": d.issue, "outcome": str(d.outcome)} for d in done]
            print(json.dumps(records, indent=2))
            return 0
        for d in done:
            print(f"{d.outcome} #{d.issue}: {d.upgrade.id}")
        if level is Autonomy.OBSERVE:
            print("upgrade autonomy is observe: no upgrade issue opened or updated")
        elif not done:
            print("no pending upgrades")
        return 0
    # GitHub is read only when an upgrade is pending, to leave out the declined ones
    found = offers(raw, github.labelled_issues(UPGRADE_LABEL)) if pending(raw) else ()
    if args.json:
        print(json.dumps([o.upgrade.record() | {"issue": o.issue} for o in found], indent=2))
        return 0
    if not found:
        print("no pending upgrades")
    for offer in found:
        upgrade = offer.upgrade
        print(f"{upgrade.id} (shipmill {upgrade.version}): {upgrade.changes}")
        if upgrade.removes is not None:
            print(f"  removes: [{upgrade.table}] {upgrade.removes}")
        if upgrade.adds(raw):
            print(f"  adds: [{upgrade.table}] {upgrade.line}")
        print(f"  off: {upgrade.off}")
        if offer.issue is not None:
            print(f"  proposed: #{offer.issue}")
        print(f"  apply: `{cli_command()} upgrade --apply {upgrade.id}`")
    return 0


def _product(root: Path, args: argparse.Namespace) -> int:
    """Spec 024: check exits 1 naming each broken rule; show and ids refuse a broken direction"""
    if args.product == "check":
        problems = check_product(root)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        direction = read_product(root)
        print(f"{DIRECTION}: well formed, {len(direction.all_items())} items")
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
    job = build(args.slug, root, args.every, args.tool, args.claude_arg, home, os.environ.get("PATH", ""), app_key=key)
    if args.print:
        sys.stdout.write(job.document.decode())
        return 0
    refresh(git)  # a dedicated checkout, at the default branch's head; strict: one on a branch is refused
    agents = AgentsConfig.load(root)  # the job would fail on every run without it
    if key is not None:  # as would a key for no App, or one the gate refuses
        if agents.app_id is None:
            raise ReleaseError(f"--app-key names an App's key, but [agents] in {CONFIG_PATH} sets no app_id")
        check_key(key)
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
