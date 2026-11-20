#!/usr/bin/env python3
"""Read a red default branch, and the merges that may have turned it red (spec 079).

    base_red.py <owner/repo> [--branch B] [--bot-login L] [--limit K] [--json]

It reads GitHub only (D-6), through `gh api`: the branch (the repo's default branch, or
--branch), its head's checks as pr_gate.py reads the base (D-75, its head_checks: the newest
run per check, every attempt), and, for a red head, the runs and merges behind it. Its first
line is `<STATE> <branch>@<sha7>`:

- GREEN: no completed check on the head failed; a queued, running, cancelled, skipped,
  neutral, or stale check is not red
- PENDING: none failed, and a check is rerunning after a failed attempt on the head, which
  pr_gate.py reads as `base: pending` (#1310): never GREEN while the merge gate waits on the
  rerun. A line `pending: <run URL>` names each such run
- RERUN_DUE: a failed check is an Actions job whose workflow run is on its first attempt. A
  line `rerun: <run URL>` names each such run, re-run once before any merge is blamed
- CULPRIT, CANDIDATES: every failed check was re-run, or can't be (a commit status, a check
  run of another app). For each failed check it walks the branch's first-parent history back
  from the head, at most --limit commits (default 30, at least 2), reading that check's
  newest run on each commit (an Actions job: the job of that name in a run of the head's
  workflow; another check run: its name and app; a commit status: its context). The last
  green is the newest commit where it completed green; the first red, the oldest commit after
  the last green where it failed. The candidates are the commits after the last green up to
  and including the first red: the first red, and the commits before it on which the check
  never completed (unjudged). The union over the failed checks; one candidate is CULPRIT,
  several are CANDIDATES
- NO_GREEN: a failed check completed green on none of the --limit commits; the candidates
  the other failed checks found are still listed

Each candidate is one line, oldest first, its parts joined by `; `: `candidate: <sha7> #N`
(the pull request whose merge commit it is, or `candidate: <sha7> no pull request` for a
direct push or a release commit), then `revertable` or `not revertable: <reason>` (`no pull
request`, `merged by a person`: anyone but --bot-login, or any merger without it, or
`released in <tag>`: the oldest tag holding the commit, read from the newest 100 tags), then,
for a commit a failed check never completed on, `unjudged, rerun: <run URL>` when the newest
run of that check's workflow there was cancelled, else `unjudged`.

Then `repair: #R` for each open pull request whose body has a `Repairs:` line naming a failed
check of the head (pr_gate.py's repairs_of and repaired), and `asked: #Q` for each open issue
the --bot-login opened whose first line is `<!-- shipmill:base-red <branch> -->`. The lines
name numbers, SHAs, logins, tags, and URLs only, never a title or a body (D-16).

--json prints one object: state, branch, sha (in full), failed (each failed check's name and
run URL), pending (the same for a rerunning one), rerun (URLs), candidates (sha, pull, merged
by the bot, revertable, reason, unjudged, rerun), repair and asked (numbers).

Exit codes: 0 a reading, whatever its state; 2 a read that fails or answers what this can't
read, a --limit below 2, a repo that isn't owner/name, or a branch the repo doesn't have,
with nothing on stdout (Q-1).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType

PR_GATE = Path(__file__).resolve().parent / "pr_gate.py"
DEFAULT_LIMIT = 30
TAGS_READ = 100  # the newest tags by their commit's date a candidate is checked against
REPO = re.compile(r"(?:[^/\s]+/)?([^/\s]+)/([^/\s]+)")
ASKED = "<!-- shipmill:base-red {branch} -->"
TAGS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    refs(refPrefix: "refs/tags/", first: 100, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      nodes {
        name
        target {
          __typename
          oid
          ... on Commit { committedDate }
          ... on Tag { target { __typename oid ... on Commit { committedDate } } }
        }
      }
    }
  }
}
"""

GREEN, RED = "green", "red"


class BaseRedError(Exception):
    """A read that fails or can't be judged: exit 2, no reading"""


def load_gate() -> ModuleType:
    """pr_gate.py, whose reading of the base this shares (D-75, #1310)"""
    spec = importlib.util.spec_from_file_location("shipmill_pr_gate", PR_GATE)
    if spec is None or spec.loader is None:
        raise BaseRedError(f"can't load {PR_GATE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


gate = load_gate()


class GitHub:
    """`gh api` for one repo: {owner}/{repo} filled in from GH_REPO, as pr_gate.py's api does"""

    def __init__(self, repo: str) -> None:
        found = REPO.fullmatch(repo)
        if found is None:
            raise BaseRedError(f"{repo!r} is not owner/name")
        self.repo = repo
        self.owner, self.name = found.groups()

    def text(self, args: list[str]) -> str:
        cmd, env = gate.api(args, self.repo)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise BaseRedError(f"gh api {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    def json(self, args: list[str]) -> object:
        out = self.text(args)
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise BaseRedError(f"gh api {' '.join(args)} printed no JSON: {exc}") from None

    def lines(self, path: str, jq: str) -> list[dict]:
        """Every page's items, one JSON object a line, as gh --paginate --jq prints them"""
        found = []
        for line in self.text(["--paginate", path, "--jq", jq]).splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BaseRedError(f"gh api {path} printed no JSON: {exc}") from None
            if not isinstance(item, dict):
                raise BaseRedError(f"gh api {path} printed {item!r}, not an object")
            found.append(item)
        return found


def value_of(data: object, key: str, what: str) -> object:
    value = data.get(key) if isinstance(data, dict) else None
    if value is None:
        raise BaseRedError(f"{what} has no {key}: {str(data)[:200]}")
    return value


def int_of(data: object, key: str, what: str) -> int:
    """data[key], an integer; anything else is a read this can't judge"""
    value = value_of(data, key, what)
    if not isinstance(value, int) or isinstance(value, bool):
        raise BaseRedError(f"{what}'s {key} is not a number: {value!r}")
    return value


def str_of(data: object, key: str, what: str) -> str:
    value = value_of(data, key, what)
    if not isinstance(value, str):
        raise BaseRedError(f"{what}'s {key} is not a string: {value!r}")
    return value


def list_of(data: object, key: str, what: str) -> list[object]:
    value = value_of(data, key, what)
    if not isinstance(value, list):
        raise BaseRedError(f"{what}'s {key} is not a list: {str(value)[:200]}")
    return value


@dataclass(frozen=True)
class Failed:
    """A check on the head: its name, its run's URL, and what identifies it on another commit"""

    name: str
    url: str
    entry: dict = field(compare=False, hash=False)
    status: bool = False  # a commit status, by its context
    app: int | None = None  # a check run's app
    workflow: int | None = None  # an Actions job's workflow
    attempt: int | None = None  # its workflow run's attempt


@dataclass
class Verdict:
    """A check's newest run on one commit: green, red, or None (it never completed there),
    and the URL of a cancelled run of its workflow to re-run"""

    state: str | None
    rerun: str | None = None


@dataclass
class Candidate:
    sha: str
    index: int  # its place on the first-parent path, 0 the head
    unjudged: bool = False
    rerun: list[str] = field(default_factory=list)
    pull: int | None = None
    merged_by: str | None = None
    reason: str | None = None

    def record(self) -> dict[str, object]:
        return {
            "sha": self.sha,
            "pull": self.pull,
            "merged_by": self.merged_by,
            "revertable": self.reason is None,
            "reason": self.reason,
            "unjudged": self.unjudged,
            "rerun": self.rerun,
        }

    def line(self) -> str:
        parts = [f"candidate: {self.sha[:7]} " + (f"#{self.pull}" if self.pull is not None else "no pull request")]
        parts.append("revertable" if self.reason is None else f"not revertable: {self.reason}")
        if self.unjudged:
            parts.append("unjudged" + "".join(f", rerun: {url}" for url in self.rerun))
        return "; ".join(parts)


@dataclass
class Reading:
    state: str
    branch: str
    sha: str
    failed: list[Failed] = field(default_factory=list)
    pending: list[tuple[str, str]] = field(default_factory=list)
    rerun: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    repair: list[int] = field(default_factory=list)
    asked: list[int] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"{self.state} {self.branch}@{self.sha[:7]}"]
        lines += [f"pending: {url}" for _, url in self.pending]
        lines += [f"rerun: {url}" for url in self.rerun]
        lines += [c.line() for c in self.candidates]
        lines += [f"repair: #{n}" for n in self.repair]
        lines += [f"asked: #{n}" for n in self.asked]
        return "\n".join(lines) + "\n"

    def record(self) -> dict[str, object]:
        return {
            "state": self.state,
            "branch": self.branch,
            "sha": self.sha,
            "failed": [{"check": f.name, "url": f.url} for f in self.failed],
            "pending": [{"check": name, "url": url} for name, url in self.pending],
            "rerun": self.rerun,
            "candidates": [c.record() for c in self.candidates],
            "repair": self.repair,
            "asked": self.asked,
        }


def actions_run(entry: dict) -> int | None:
    """The workflow run an Actions job's check run belongs to, from its URLs"""
    for url in entry.get("urls") or ():
        found = gate._ACTIONS_URL.fullmatch(url)
        if found is not None:
            return int(found.group(1))
    return None


def failed_check(gh: GitHub, entry: dict) -> Failed:
    """A failed check of the head, with its run's attempt and workflow for an Actions job"""
    check = gate.check_of(entry)
    if "status" not in entry:  # a commit status
        return Failed(check.name, str((entry.get("urls") or [""])[0]), entry, status=True)
    run = actions_run(entry)
    app = entry.get("app") if isinstance(entry.get("app"), int) else None
    if run is None:  # another app's check run: nothing here re-runs it
        return Failed(check.name, str((entry.get("urls") or [""])[0]), entry, app=app)
    data = gh.json([f"repos/{{owner}}/{{repo}}/actions/runs/{run}"])
    what = f"workflow run {run}"
    attempt = int_of(data, "run_attempt", what)
    workflow = int_of(data, "workflow_id", what)
    url = str_of(data, "html_url", what)
    return Failed(check.name, url, entry, app=app, workflow=workflow, attempt=attempt)


def rerunning_url(entry: dict) -> str:
    """The run a rerunning check belongs to: an Actions job's workflow run, else its own URL"""
    for url in entry.get("urls") or ():
        if gate._ACTIONS_URL.fullmatch(url):
            return re.sub(r"/(?:job|attempts)/[0-9]+/?$", "", url).rstrip("/")
    return str((entry.get("urls") or [""])[0])


class History:
    """The branch's first-parent history from the head, read a page at a time as the walk needs"""

    def __init__(self, gh: GitHub, head: str, limit: int) -> None:
        self.gh = gh
        self.limit = limit
        self.commits: dict[str, dict] = {}
        self.path = [head]
        self.read_from(head)

    def read_from(self, sha: str) -> None:
        path = f"repos/{{owner}}/{{repo}}/commits?sha={sha}&per_page={min(self.limit, 100)}"
        listed = self.gh.json([path])
        if not isinstance(listed, list) or not listed:
            raise BaseRedError(f"the commits from {sha[:7]} are not a list: {str(listed)[:200]}")
        for commit in listed:
            self.commits[str_of(commit, "sha", "a commit")] = commit

    def at(self, index: int) -> str | None:
        """The index-th commit back from the head on the first-parent path, None past the
        branch's first commit or the limit"""
        while len(self.path) <= index < self.limit:
            last = self.path[-1]
            if last not in self.commits:
                self.read_from(last)
            parents = list_of(self.commits[last], "parents", f"commit {last[:7]}")
            if not parents:
                return None
            parent = str_of(parents[0], "sha", f"commit {last[:7]}'s parent")
            self.path.append(parent)
        return self.path[index] if index < len(self.path) else None

    def date(self, sha: str) -> datetime:
        commit = self.commits.get(sha)
        inner = commit.get("commit") if isinstance(commit, dict) else None
        committer = inner.get("committer") if isinstance(inner, dict) else None
        raw = committer.get("date") if isinstance(committer, dict) else None
        try:
            return gate.moment(raw, f"commit {sha[:7]}'s date")
        except gate.GateError as exc:
            raise BaseRedError(str(exc)) from None


def judge(gh: GitHub, failed: Failed, sha: str, branch: str) -> Verdict:
    """The check's newest run on a commit, as pr_gate.py reads a run: green, red, or never
    completed there, with a cancelled run of its workflow to re-run"""
    if failed.status:
        combined = gh.json([f"repos/{{owner}}/{{repo}}/commits/{sha}/status?per_page=100"])
        statuses = list_of(combined, "statuses", f"the status of {sha[:7]}")
        if len(statuses) < int_of(combined, "total_count", f"the status of {sha[:7]}"):
            raise BaseRedError(f"{sha[:7]} has more than 100 commit statuses; no partial list is judged")
        entries = [gate.status_entry(s, branch) for s in statuses]
        entries = [e for e in entries if e["context"] == failed.name]
        return Verdict(verdict_of(entries))
    name = urllib.parse.quote(failed.name, safe="")
    runs = gh.lines(
        f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?check_name={name}&filter=all&per_page=100",
        ".check_runs[]",
    )
    entries = [gate.run_entry(r, branch) for r in runs]
    entries = [e for e in entries if failed.app is None or e.get("app") == failed.app]
    if failed.workflow is None:
        return Verdict(verdict_of(entries))
    workflow_runs = [
        w
        for w in gh.lines(f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={sha}&per_page=100", ".workflow_runs[]")
        if w.get("workflow_id") == failed.workflow
    ]
    suites = {f"suite {w.get('check_suite_id')}" for w in workflow_runs}
    state = verdict_of([e for e in entries if e["workflowName"] in suites])
    rerun = None
    if state is None and workflow_runs:
        newest = max(workflow_runs, key=lambda w: int_of(w, "id", "a workflow run"))
        if newest.get("status") == "completed" and newest.get("conclusion") == "cancelled":
            rerun = str_of(newest, "html_url", "a workflow run")
    return Verdict(state, rerun)


def verdict_of(entries: list[dict]) -> str | None:
    """The newest of one check's runs: green, red, or None when it didn't complete"""
    if not entries:
        return None
    try:
        [newest] = gate.newest_entries([{**e, "workflowName": "one check"} for e in entries])
    except gate.GateError as exc:
        raise BaseRedError(str(exc)) from None
    check = gate.check_of(newest)
    if not check.done or check.conclusion in gate.NOT_RED - gate.GREEN:
        return None
    return GREEN if check.conclusion in gate.GREEN else RED


def walk(gh: GitHub, history: History, failed: Failed, branch: str) -> tuple[list[tuple[int, Verdict]], bool]:
    """The check's candidates as (index, verdict) on the first-parent path, oldest first, and
    whether it completed green on any of the --limit commits"""
    verdicts: list[Verdict] = [Verdict(RED)]  # it failed on the head
    green = None
    index = 1
    while True:
        sha = history.at(index)
        if sha is None:
            break
        verdict = judge(gh, failed, sha, branch)
        if verdict.state == GREEN:
            green = index
            break
        verdicts.append(verdict)
        index += 1
    if green is None:
        return [], False
    first_red = max(i for i, v in enumerate(verdicts) if v.state == RED)
    return [(i, verdicts[i]) for i in range(len(verdicts) - 1, first_red - 1, -1)], True


def merged_pull(gh: GitHub, sha: str) -> tuple[int | None, str | None]:
    """The pull request whose merge commit the commit is, and who merged it"""
    pulls = gh.json([f"repos/{{owner}}/{{repo}}/commits/{sha}/pulls"])
    if not isinstance(pulls, list):
        raise BaseRedError(f"the pull requests of {sha[:7]} are not a list: {str(pulls)[:200]}")
    for pull in pulls:
        if isinstance(pull, dict) and pull.get("merged_at") and pull.get("merge_commit_sha") == sha:
            number = int_of(pull, "number", "a pull request")
            full = gh.json([f"repos/{{owner}}/{{repo}}/pulls/{number}"])
            merger = full.get("merged_by") if isinstance(full, dict) else None
            login = merger.get("login") if isinstance(merger, dict) else None
            return number, login if isinstance(login, str) else None
    return None, None


class Tags:
    """The newest tags by their commit's date, read once, in one GraphQL query"""

    def __init__(self, gh: GitHub) -> None:
        self.gh = gh
        self.read: list[tuple[str, str, datetime]] | None = None

    def all(self) -> list[tuple[str, str, datetime]]:
        if self.read is None:
            args = [
                "graphql",
                "-f",
                f"query={TAGS_QUERY}",
                "-f",
                f"owner={self.gh.owner}",
                "-f",
                f"name={self.gh.name}",
            ]
            data = self.gh.json(args)
            nodes: object = data
            for key in ("data", "repository", "refs", "nodes"):
                nodes = nodes.get(key) if isinstance(nodes, dict) else None
            if not isinstance(nodes, list):
                raise BaseRedError(f"the tags query answered {str(data)[:200]}")
            found = []
            for node in nodes:
                target = node.get("target") if isinstance(node, dict) else None
                if isinstance(target, dict) and target.get("__typename") == "Tag":
                    target = target.get("target")
                if not isinstance(target, dict) or target.get("__typename") != "Commit":
                    continue
                name = str_of(node, "name", "a tag")
                try:
                    when = gate.moment(target.get("committedDate"), f"tag {name}'s commit date")
                except gate.GateError as exc:
                    raise BaseRedError(str(exc)) from None
                found.append((name, str_of(target, "oid", f"tag {name}"), when))
            self.read = found
        return self.read

    def holding(self, candidate: Candidate, history: History) -> str | None:
        """The oldest tag holding the candidate's commit: a tag on the walked path at or after
        it, or another tag no older than it that GitHub's compare finds ahead of it"""
        since = history.date(candidate.sha)
        tags = self.all()
        newer = [t for t in tags if t[2] >= since]
        if len(tags) >= TAGS_READ and len(newer) == len(tags):
            raise BaseRedError(f"more than {TAGS_READ} tags are newer than {candidate.sha[:7]}; none is judged")
        held = None
        for name, sha, _ in newer:  # newest first: the last one found is the oldest
            if sha in history.path:
                if history.path.index(sha) <= candidate.index:
                    held = name
                continue
            compared = self.gh.json([f"repos/{{owner}}/{{repo}}/compare/{candidate.sha}...{sha}"])
            status = compared.get("status") if isinstance(compared, dict) else None
            if not isinstance(status, str):
                raise BaseRedError(f"the compare of {candidate.sha[:7]} and {name} has no status")
            if status in ("ahead", "identical"):
                held = name
        return held


def judge_candidate(gh: GitHub, candidate: Candidate, bot: str | None, tags: Tags, history: History) -> None:
    candidate.pull, candidate.merged_by = merged_pull(gh, candidate.sha)
    if candidate.pull is None:
        candidate.reason = "no pull request"
        return
    if bot is None or (candidate.merged_by or "").lower() != bot.lower():
        candidate.reason = "merged by a person"
        return
    tag = tags.holding(candidate, history)
    if tag is not None:
        candidate.reason = f"released in {tag}"


def open_items(gh: GitHub) -> list[dict]:
    return gh.lines("repos/{owner}/{repo}/issues?state=open&per_page=100", ".[]")


def repairs(items: list[dict], failed: list[Failed]) -> list[int]:
    """The open pull requests whose Repairs: line names a failed check of the head (D-75)"""
    found = []
    for item in items:
        if "pull_request" not in item:
            continue
        named = gate.repairs_of(str(item.get("body") or ""))
        if named and any(gate.repaired(f.entry, named) for f in failed):
            found.append(int_of(item, "number", "an open pull request"))
    return sorted(found)


def asked(items: list[dict], bot: str | None, branch: str) -> list[int]:
    """The open issues the --bot-login opened whose first line is the branch's base-red marker"""
    if bot is None:
        return []
    marker = ASKED.format(branch=branch)
    found = []
    for item in items:
        user = item.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        lines = str(item.get("body") or "").splitlines()
        if "pull_request" in item or not isinstance(login, str) or login.lower() != bot.lower():
            continue
        if lines and lines[0].strip() == marker:
            found.append(int_of(item, "number", "an open issue"))
    return sorted(found)


def read(gh: GitHub, branch: str | None, bot: str | None, limit: int) -> Reading:
    if branch is None:
        branch = str_of(gh.json(["repos/{owner}/{repo}"]), "default_branch", gh.repo)
    try:
        sha, entries = gate.head_checks(branch, gh.text)
    except gate.GateError as exc:
        raise BaseRedError(str(exc)) from None
    except json.JSONDecodeError as exc:
        raise BaseRedError(f"the checks of {branch}'s head are not JSON: {exc}") from None
    red = [e for e in entries if gate.check_of(e).done and gate.check_of(e).conclusion not in gate.NOT_RED]
    failed = [failed_check(gh, e) for e in red]
    reading = Reading("GREEN", branch, sha, failed)
    if not failed:
        reading.pending = [(gate.check_of(e).name, rerunning_url(e)) for e in entries if e.get("rerunning")]
        reading.state = "PENDING" if reading.pending else "GREEN"
    else:
        reading.rerun = sorted({f.url for f in failed if f.attempt == 1})
        if reading.rerun:
            reading.state = "RERUN_DUE"
        else:
            reading.state, reading.candidates = blame(gh, sha, failed, branch, bot, limit)
    if failed or bot is not None:
        items = open_items(gh)
        reading.repair = repairs(items, failed)
        reading.asked = asked(items, bot, branch)
    return reading


def blame(
    gh: GitHub, sha: str, failed: list[Failed], branch: str, bot: str | None, limit: int
) -> tuple[str, list[Candidate]]:
    history = History(gh, sha, limit)
    found: dict[int, Candidate] = {}
    no_green = False
    for check in failed:
        walked, green = walk(gh, history, check, branch)
        no_green = no_green or not green
        for index, verdict in walked:
            candidate = found.setdefault(index, Candidate(history.path[index], index))
            if verdict.state is None:
                candidate.unjudged = True
                if verdict.rerun is not None and verdict.rerun not in candidate.rerun:
                    candidate.rerun.append(verdict.rerun)
    candidates = [found[i] for i in sorted(found, reverse=True)]  # oldest first
    tags = Tags(gh)
    for candidate in candidates:
        judge_candidate(gh, candidate, bot, tags, history)
    if no_green:
        return "NO_GREEN", candidates
    return ("CULPRIT" if len(candidates) == 1 else "CANDIDATES"), candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--branch", help="the branch to read (default: the repo's default branch)")
    parser.add_argument("--bot-login", help="the login the gate merges as, such as <slug>[bot]")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help="commits walked back per failed check (default 30)"
    )
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args()
    if args.limit < 2:
        parser.error(f"--limit is at least 2, got {args.limit}")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login names a login, such as <slug>[bot]")
    if args.branch is not None and not args.branch.strip():
        parser.error("--branch names a branch")
    try:
        reading = read(GitHub(args.repo), args.branch, args.bot_login, args.limit)
    except (BaseRedError, gate.GateError) as exc:
        print(f"base_red: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(reading.record(), indent=2) + "\n" if args.json else reading.text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
