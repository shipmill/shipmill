#!/usr/bin/env python3
"""Find the closed issues a release fixed, and report them; it never comments on them.

Usage: shipped.py <owner/repo> <prev-tag> <tag> [--repo-dir PATH] [--environment NAME] [--json]

Walks `git log <prev-tag>..<tag>` in the local checkout and collects issue numbers from:
  - closing trailers in commit messages ("Fixes #N" at the start of a line)
  - the merged PRs those commits belong to (merge, squash, or rebase merges): GitHub's
    closingIssuesReferences in the repo, a closing keyword in the title, or one that starts
    a line of the body outside a code fence: github-issue-triage's triage_state.py
    keyword_closes, the one rule triage links a PR to an issue by (#416). A keyword quoted
    mid-line or in backticks names nothing (#368)
A stable tag also reads the range from the newest stable tag below it (or, when only
pre-release tags are below it, its whole history), so a stable release that promotes an
rc reports every issue the rc held even when <prev-tag> is a later rc and <prev-tag>..<tag>
holds only the stamp commit (spec 021, D-25). Keeps only issues that are closed. A number
that resolves to no issue or pull request of the repo is skipped with a note on stderr
(#368).

Each issue is reported at one stage (spec 021): `pre-release` for a dev, a, b, or rc tag,
and `stable` for any other. With --environment NAME the stage is that environment's
instead: <tag> succeeded deploying there, and <prev-tag> is what the environment ran before
it, so only <prev-tag>..<tag> is read. NAME is an environment's name from the config's
[environments]; "pre-release" and "stable" are refused (exit 2), since they name the release
stages.

shipmill posts no notice on a fixed issue (D-69, #921): this script reads and prints, and a
layer outside shipmill's core may deliver the link from an issue to its release. The table
prints one line per issue, `#N FIXED <title> [source]` for a closed one and `#N SKIP open`
for an open one. --json prints one JSON object per closed issue instead, a line each:
number (an int), tag, stage, and source (the commits and pull requests that named it, as
"abc1234" and "PR #12", sorted).

Exit 0 on success (including nothing fixed), 2 on bad input or a git/gh failure. Reads use
plain gh, the commits' pull requests and the issues each in batched GraphQL queries (#754).
Needs git and an authenticated gh CLI. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

PRE_RELEASE, STABLE = "pre-release", "stable"
ENVIRONMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # shipmill's environments._NAME
# a version tag as shipmill cuts it: X.Y.Z with an optional a, b, or rc pre-release and .devN
VERSION_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?(?:\.dev(\d+))?$")
PRE_RANK = {"a": 1, "b": 2, "rc": 3}
# github-issue-triage's triage_state.py: one reading of a PR's closing keywords for both (#416)
TRIAGE_STATE = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
KEYWORDS = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
TRAILER = re.compile(rf"^\s*(?:[-*]\s*)?{KEYWORDS}:?\s+#(\d+)\b", re.IGNORECASE | re.MULTILINE)
# reads are batched in aliased GraphQL queries (#754); GitHub refuses a query that may ask for
# more than 500,000 nodes, so each batch is sized from what one alias can cost
PRS_READ, CLOSERS_READ = 20, 50  # a commit's pull requests, and each one's closing links
COMMITS_PER_QUERY = 50  # 50 * (20 + 20 * 50) = 51,000 nodes
ISSUES_PER_QUERY = 50
NODE_LIMIT = 500_000
PULL_FIELDS = (
    f"associatedPullRequests(first: {PRS_READ}) {{ nodes {{ number title body mergedAt"
    f" closingIssuesReferences(first: {CLOSERS_READ}) {{ nodes {{ number repository {{ nameWithOwner }} }} }} }} }}"
)
# an issue's state and title, and a pull request's url, which tells one from the other
ISSUE_FIELDS = "... on Issue { url state title } ... on PullRequest { url }"


def run(cmd: list[str], cwd: str | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if partial(cmd, proc.stdout):
            return proc.stdout  # graphql() decides which of its NOT_FOUND errors are a skip
        sys.stderr.write(f"error: {' '.join(cmd[:3])}...: {proc.stderr.strip()}\n")
        raise SystemExit(2)
    return proc.stdout


def partial(cmd: list[str], stdout: str) -> bool:
    """A failed `gh api graphql` whose answer is data with only NOT_FOUND errors, as GitHub gives
    for an aliased number with no issue or pull request behind it; narrow, so auth, network,
    rate limits, and every other failure still stop the run (#368)"""
    if cmd[:3] != ["gh", "api", "graphql"]:
        return False
    try:
        out = json.loads(stdout)
    except ValueError:
        return False
    errors = out.get("errors") if isinstance(out, dict) else None
    return (
        isinstance(errors, list)
        and bool(errors)
        and out.get("data") is not None
        and all(isinstance(e, dict) and e.get("type") == "NOT_FOUND" for e in errors)
    )


def graphql(
    repo: str,
    variables: list[tuple[str, str, str]],
    body: str,
    gh: Callable[[list[str]], str],
    may_miss: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """The repository of one query on repo, each variable a (name, GraphQL type, value). An
    error stops the run (exit 2) unless it is NOT_FOUND for a field named in may_miss, whose
    value is then null"""
    owner, _, name = repo.partition("/")
    declared = "".join(f", ${n}: {t}" for n, t, _ in variables)
    query = f"query($owner: String!, $name: String!{declared}) {{"
    query += f" repository(owner: $owner, name: $name) {{ {body} }} }}"
    # -f, not -F: -F would turn a numeric owner or name such as 2048 into a number GraphQL refuses
    cmd = ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]
    for n, t, value in variables:
        cmd += ["-F" if t == "Int!" else "-f", f"{n}={value}"]
    out = json.loads(gh(cmd))
    refused = [e for e in out.get("errors") or [] if not missed(e, may_miss)]
    repository = (out.get("data") or {}).get("repository")
    if refused or repository is None:
        messages = "; ".join(str(e.get("message", e)) for e in refused) or f"no repository {repo}"
        sys.stderr.write(f"error: gh api graphql...: {messages}\n")
        raise SystemExit(2)
    found: dict[str, Any] = repository
    return found


def missed(error: dict[str, Any], may_miss: frozenset[str]) -> bool:
    """GraphQL's NOT_FOUND for one of the repository's aliased fields in may_miss, and only that"""
    path = error.get("path")
    return (
        error.get("type") == "NOT_FOUND"
        and isinstance(path, list)
        and len(path) == 2
        and path[0] == "repository"
        and path[1] in may_miss
    )


def commits(repo_dir: str, prev: str, tag: str) -> list[tuple[str, str]]:
    return log(repo_dir, f"{prev}..{tag}")


def log(repo_dir: str, revisions: str) -> list[tuple[str, str]]:
    """(sha, message) of each commit git log lists for revisions"""
    out = run(["git", "log", "--format=%H%x00%B%x1e", revisions], cwd=repo_dir)
    pairs = []
    for record in out.split("\x1e"):
        if record.strip():
            sha, _, body = record.strip().partition("\x00")
            pairs.append((sha, body))
    return pairs


def prs_for(repo: str, sha: str, gh: Callable[[list[str]], str] = run) -> list[dict[str, Any]]:
    """The PRs a commit belongs to, with GitHub's closing links"""
    return prs_of(repo, [sha], gh)[sha]


def prs_of(repo: str, shas: list[str], gh: Callable[[list[str]], str] = run) -> dict[str, list[dict[str, Any]]]:
    """The PRs each commit belongs to, with GitHub's closing links, COMMITS_PER_QUERY commits a
    query (#754); no commits, no call"""
    found: dict[str, list[dict[str, Any]]] = {}
    unique = list(dict.fromkeys(shas))
    for start in range(0, len(unique), COMMITS_PER_QUERY):
        batch = unique[start : start + COMMITS_PER_QUERY]
        variables = [(f"o{i}", "GitObjectID!", sha) for i, sha in enumerate(batch)]
        body = " ".join(f"c{i}: object(oid: $o{i}) {{ ... on Commit {{ {PULL_FIELDS} }} }}" for i in range(len(batch)))
        repository = graphql(repo, variables, body, gh)
        for i, sha in enumerate(batch):
            commit = repository[f"c{i}"]
            if commit is None:
                sys.stderr.write(f"error: {repo} has no commit {sha}\n")
                raise SystemExit(2)
            found[sha] = commit["associatedPullRequests"]["nodes"]
    return found


def views(repo: str, numbers: list[int], gh: Callable[[list[str]], str] = run) -> dict[int, dict[str, Any] | None]:
    """Each number's issue (url, state, title) or a pull request's url; None for a number with
    no issue or pull request behind it (#368). ISSUES_PER_QUERY numbers a query (#754); no
    numbers, no call"""
    found: dict[int, dict[str, Any] | None] = {}
    unique = list(dict.fromkeys(numbers))
    for start in range(0, len(unique), ISSUES_PER_QUERY):
        batch = unique[start : start + ISSUES_PER_QUERY]
        variables = [(f"n{i}", "Int!", str(n)) for i, n in enumerate(batch)]
        body = " ".join(f"i{i}: issueOrPullRequest(number: $n{i}) {{ {ISSUE_FIELDS} }}" for i in range(len(batch)))
        aliases = frozenset(f"i{i}" for i in range(len(batch)))
        repository = graphql(repo, variables, body, gh, may_miss=aliases)
        for i, number in enumerate(batch):
            found[number] = repository[f"i{i}"]
    return found


def pr_closes(repo: str, pr: dict[str, Any]) -> set[int]:
    """The issues a merged PR closes: GitHub's links in the repo, a closing keyword in the
    title, or one starting a line of the body outside a code fence (#368)"""
    found = {
        int(n["number"])
        for n in pr["closingIssuesReferences"]["nodes"]
        if n["repository"]["nameWithOwner"].lower() == repo.lower()
    }
    keywords: set[int] = TRIAGE.keyword_closes(pr.get("title") or "", pr.get("body") or "")
    return found | keywords


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        sys.stderr.write(f"error: can't load {path}\n")
        raise SystemExit(2)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


TRIAGE = load("shipmill_triage_state", TRIAGE_STATE)


def version_key(tag: str) -> tuple[int, ...] | None:
    """A version tag's PEP 440 order, as shipmill's version.py sorts it; None for another tag"""
    found = VERSION_TAG.match(tag)
    if found is None:
        return None
    major, minor, patch, pre, pre_n, dev = found.groups()
    phase, n = (PRE_RANK[pre], int(pre_n)) if pre else ((0, 0) if dev else (4, 0))
    return (int(major), int(minor), int(patch), phase, n, int(dev) if dev else 2**62)


def stage_of(tag: str) -> str:
    """pre-release for a dev, a, b, or rc version tag; stable for any other tag"""
    found = VERSION_TAG.match(tag)
    return PRE_RELEASE if found is not None and (found.group(4) or found.group(6)) else STABLE


def environment_name(value: str) -> str:
    """--environment: an environment's name as shipmill's config allows it, and not a release
    stage's, which would read as the release's own"""
    if ENVIRONMENT.fullmatch(value) is None or value in (PRE_RELEASE, STABLE):
        raise argparse.ArgumentTypeError(f"not an environment's name: {value!r}")
    return value


def report(
    repo: str,
    issues: dict[int, set[str]],
    tag: str,
    stage: str,
    as_json: bool,
    gh: Callable[[list[str]], str] = run,
) -> None:
    """One line per issue: the closed ones as fixed at stage, as a table or JSON records, and
    the open ones, in the table only, as skipped. Reads are batched (#754); nothing is written"""
    numbers = sorted(issues)
    read = views(repo, numbers, gh)
    for number in numbers:
        sources = sorted(issues[number])
        view = read[number]
        if view is None:
            # one bad reference must not stop the report after it, or the watch (#368)
            sys.stderr.write(f"note: #{number} [{', '.join(sources)}] is no issue or pull request of {repo}, skipped\n")
            continue
        if "/pull/" in view["url"]:
            continue
        closed = view["state"] == "CLOSED"
        if as_json:
            if closed:
                print(json.dumps({"number": number, "tag": tag, "stage": stage, "source": sources}))
            continue
        what = "FIXED" if closed else "SKIP open"
        print(f"#{number:<5} {what:<10} {view['title'][:60]}  [{', '.join(sources)}]")


def collect(repo: str, pairs: list[tuple[str, str]], gh: Callable[[list[str]], str] = run) -> dict[int, set[str]]:
    """Each issue the commits close, by commit trailer or merged PR, with where it was named"""
    issues: dict[int, set[str]] = {}
    seen_prs: set[int] = set()
    prs = prs_of(repo, [sha for sha, _ in pairs], gh)
    for sha, body in pairs:
        for n in TRAILER.findall(body):
            issues.setdefault(int(n), set()).add(sha[:7])
        for pr in prs[sha]:
            number = int(pr["number"])
            if number in seen_prs or not pr.get("mergedAt"):
                continue
            seen_prs.add(number)
            for n in pr_closes(repo, pr):
                issues.setdefault(n, set()).add(f"PR #{number}")
    return issues


def own_range(repo_dir: str, tag: str) -> str | None:
    """A stable tag's own range for git log: from the newest stable version tag below it, or
    with only pre-release tags below it its whole history, so the fixes its oldest rc held
    count; None for a pre-release tag, another tag, or a first tag"""
    key = version_key(tag)
    if key is None or stage_of(tag) != STABLE:
        return None
    keyed = [(version_key(t), t) for t in run(["git", "tag", "--list"], cwd=repo_dir).split()]
    below = sorted((k, t) for k, t in keyed if k is not None and k < key)
    stable = [t for _, t in below if stage_of(t) == STABLE]
    if stable:
        return f"{stable[-1]}..{tag}"
    return tag if below else None


def release_commits(repo_dir: str, prev: str, tag: str) -> list[tuple[str, str]]:
    """prev..tag, and for a stable tag its own range too, so a stable release that promotes an
    rc covers every fix the rc held when prev is a later rc (spec 021, D-25)"""
    pairs = commits(repo_dir, prev, tag)
    revisions = own_range(repo_dir, tag)
    if revisions is not None and revisions != f"{prev}..{tag}":
        seen = {sha for sha, _ in pairs}
        pairs += [(sha, body) for sha, body in log(repo_dir, revisions) if sha not in seen]
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("prev_tag")
    parser.add_argument("tag")
    parser.add_argument("--repo-dir", default=".", help="local checkout (default: cwd)")
    parser.add_argument(
        "--environment",
        type=environment_name,
        help="the fixes a successful deployment of <tag> brought to this environment, which ran <prev-tag> before",
    )
    parser.add_argument(
        "--json", action="store_true", help="one JSON object per closed issue: number, tag, stage, source"
    )
    args = parser.parse_args()
    if "/" not in args.repo:
        parser.error("repo must be owner/name")

    run(["git", "fetch", "-q", "--force", "--tags", "origin"], cwd=args.repo_dir)  # a bot moves major tags such as v0
    if args.environment is not None:
        # only what the environment didn't run before
        issues = collect(args.repo, commits(args.repo_dir, args.prev_tag, args.tag))
        report(args.repo, issues, args.tag, args.environment, args.json)
        return 0
    issues = collect(args.repo, release_commits(args.repo_dir, args.prev_tag, args.tag))
    report(args.repo, issues, args.tag, stage_of(args.tag), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
