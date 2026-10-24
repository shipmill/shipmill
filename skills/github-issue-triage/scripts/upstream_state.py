#!/usr/bin/env python3
"""Read every open upstream report of a product for its coordinator (spec 038, D-47).

The coordinator, the home repo's gate, routes each report to the repos that own it and closes
it once they are done; this script says which reports need that now.

Usage: upstream_state.py <owner/home> [--bot-login LOGIN] [--json]

Run in the home repo's checkout: its .github/shipmill.toml's [product] repos lists the
product's component repos (read with github-ship-watch's watch_state.py config reader). It
reads the open issues labelled upstream of the home repo, through plain gh (the session's),
and of every listed repo, through `shipmill gh --product <repo>` run as `uvx
shipmill==<version>`, the version in the plugin's .claude-plugin/plugin.json (spec 031), with
the coordinator's product token. One line per report, `owner/repo#N STATE note`:

  ROUTE_DUE   no children and no needs-decision label: find the owning repos and route it.
              A "Stands in for owner/repo#N" line of its body puts "link owner/repo#N" in
              the note, the issue to make its child; without one the note is "no children"
  ASKED       labelled needs-decision and its question has no reply: it waits on the
              maintainer (triage_state.py's NEEDS_DECISION rule, with the --bot-login)
  ANSWERED    labelled needs-decision and its question has a reply: route it by the answer
  ROUTED      a child is still open; the note starts "children K/N closed", then each child
              as owner/repo#N:state
  CLOSE_DUE   every child closed; the note starts "completed", or "not_planned" when any
              child closed as not planned (or is a pull request closed unmerged), then each
              child as owner/repo#N:state
  UNTRUSTED   its author is neither an OWNER, MEMBER, or COLLABORATOR of its repo nor the
              --bot-login (D-16): its text, labels, children, and comments are never read,
              and it is never ROUTE_DUE, ANSWERED, or CLOSE_DUE

needs-decision is read first, then the children. A report's children are its sub-issues
and the issues and pull requests the "Depends on" lines of its body name, as triage_state.py
reads holds (so a link the forge refused, "text only:", still counts), each once however its
owner and repo are cased. A child the sub-issues don't give a state for is read through the
reader of its repo: plain gh for the home repo and any repo the product doesn't list, the
product token for a listed one.

--json prints one JSON object per line: ref, state, and note.

Exit 0 when nothing needs the coordinator, 1 when any report reads ROUTE_DUE, ANSWERED, or
CLOSE_DUE, 2 on a gh failure (any GraphQL error, a `shipmill gh` that exits 2, a child that
can't be read), a report with more than 100 labels or sub-issues, or a config it refuses: no
.github/shipmill.toml, no [product] repos, a [product] repos listing the home repo, or one
the reader refuses. Never a partial report. Needs the gh CLI, authenticated, and uvx for
`shipmill gh`. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn

# The coordinator's runner and config reader, as chains.py link writes through them
from chains import Execute, Runner, Variables, capture, checkout_top, gh_runner, watch_module

# Holds and trust as triage_state.py reads them: one rule for a report and for its waiting issue
from triage_state import (
    DECISION_LABEL,
    UPSTREAM,
    UPSTREAM_LABEL,
    dependency_refs,
    fold,
    home_repo,
    login,
    native_holds,
    question,
    ref_state,
    replies,
    trusted,
    waits_on_decision,
)

Ref = tuple[str, str, int]
# The runner that reads a repo, owner/name, as the config spells it
Readers = Callable[[str], Runner]

ACTION = ("ROUTE_DUE", "ANSWERED", "CLOSE_DUE")
STATES = (*ACTION, "ASKED", "ROUTED", "UNTRUSTED")
# A child that holds nothing: closed in any way, a pull request merged or closed unmerged
CLOSED = frozenset({"CLOSED", "NOT_PLANNED", "MERGED", "CLOSED_UNMERGED"})
# A child whose work never landed: the report closes as not planned, so the agent decides again
NOT_LANDED = frozenset({"NOT_PLANNED", "CLOSED_UNMERGED"})
# A stand-in's "Stands in for owner/repo#N" line: the other repo's issue it waits on
STANDS_IN = re.compile(r"^[ \t]*(?:[-*][ \t]+)?stands in for\b:?(?P<refs>.*)$", re.IGNORECASE | re.MULTILINE)
PAGE = 100  # a page of reports, comments, labels, and sub-issues (GitHub caps sub-issues at 100)
CHUNK = 20  # the children read in one query, each under its own alias
CONFIG = Path(".github/shipmill.toml")

REPORTS = (
    """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, labels: ["""
    + json.dumps(UPSTREAM_LABEL)
    + """], first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number author { __typename login } authorAssociation }
    }
  }
}
"""
)
# A trusted report's own fields: only these are ever read of it, and only once it is trusted
REPORT = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number body
      labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
      comments(last: 100) {
        pageInfo { hasPreviousPage startCursor } nodes { body author { __typename login } authorAssociation }
      }
      subIssues(first: 100) {
        pageInfo { hasNextPage } nodes { number state stateReason closedAt repository { nameWithOwner } }
      }
    }
  }
}
"""
COMMENTS = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(last: 100, before: $cursor) {
        pageInfo { hasPreviousPage startCursor } nodes { body author { __typename login } authorAssociation }
      }
    }
  }
}
"""


def children_query(count: int) -> str:
    """One query reading count items, the i-th under alias c<i> with $o<i>, $n<i>, $k<i>"""
    params = ", ".join(f"$o{i}: String!, $n{i}: String!, $k{i}: Int!" for i in range(count))
    aliases = "\n".join(
        f"  c{i}: repository(owner: $o{i}, name: $n{i}) {{ issueOrPullRequest(number: $k{i}) "
        "{ __typename ... on Issue { state stateReason } ... on PullRequest { state } } }"
        for i in range(count)
    )
    return f"query({params}) {{\n{aliases}\n}}\n"


def fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise SystemExit(2)


def first_error(errors: list[Any]) -> str:
    error = errors[0] if errors and isinstance(errors[0], dict) else {}
    message = str(error.get("message") or json.dumps(errors))
    return (message.strip().splitlines() or [message])[0]


def answered(run: Runner, query: str, variables: Variables, what: str) -> dict[str, Any]:
    """The data of one query; any GraphQL error fails the run, so a report is never partial"""
    response = run(query, variables)
    errors = response.get("errors")
    if errors:
        fail(f"reading {what}: {first_error(list(errors))}")
    data = response.get("data")
    if not isinstance(data, dict):
        fail(f"reading {what}: no data in the GraphQL response")
    return data


def repository(run: Runner, query: str, variables: Variables, what: str) -> dict[str, Any]:
    found = answered(run, query, variables, what).get("repository")
    if not isinstance(found, dict):
        fail(f"reading {what}: no repository {variables['owner']}/{variables['name']} in the GraphQL response")
    return found


def split(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    return owner, name


def reports(run: Runner, repo: str) -> list[dict[str, Any]]:
    """The repo's open upstream reports, oldest first: their numbers and authors only"""
    owner, name = split(repo)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    variables: Variables = {"owner": owner, "name": name}
    while True:
        page = repository(run, REPORTS, variables, f"the upstream reports of {repo}")["issues"]
        found += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return found
        cursor = page["pageInfo"]["endCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more upstream reports of {repo}, but the page cursor did not advance")
        seen.add(cursor)
        variables = {**variables, "cursor": cursor}


def report(run: Runner, repo: str, number: int) -> dict[str, Any]:
    """A trusted report's body, labels, every comment (oldest first), and sub-issues"""
    owner, name = split(repo)
    base: Variables = {"owner": owner, "name": name, "number": number}
    issue = repository(run, REPORT, base, f"{repo}#{number}").get("issue")
    if not isinstance(issue, dict):
        fail(f"reading {repo}#{number}: no such issue")
    for field in ("labels", "subIssues"):
        if issue[field]["pageInfo"]["hasNextPage"]:
            fail(f"bad input: {repo}#{number} has more than {PAGE} {field}, which upstream_state.py does not page")
    comments = issue["comments"]
    seen: set[str] = set()
    while comments["pageInfo"]["hasPreviousPage"]:
        cursor = comments["pageInfo"]["startCursor"]
        if not cursor or cursor in seen:
            fail(f"GitHub reported more comments on {repo}#{number}, but the page cursor did not advance")
        seen.add(cursor)
        older = repository(run, COMMENTS, {**base, "cursor": cursor}, f"the comments of {repo}#{number}")
        page = (older.get("issue") or {}).get("comments")
        if not isinstance(page, dict):
            fail(f"{repo}#{number} vanished while paging its comments")
        comments = {"pageInfo": page["pageInfo"], "nodes": page["nodes"] + comments["nodes"]}
    issue["comments"] = comments
    return issue


def stand_ins(body: str) -> list[str]:
    """The issues a stand-in's "Stands in for owner/repo#N" lines name, each once, as written"""
    found = (
        f"{m['owner']}/{m['name']}#{m['num']}"
        for line in STANDS_IN.finditer(body)
        for m in UPSTREAM.finditer(line["refs"])
    )
    return list(dict.fromkeys(found))


def named(ref: Ref) -> str:
    return f"{ref[0]}/{ref[1]}#{ref[2]}"


class Product:
    """The home repo and its listed repos, each read through its own runner: a ref's repo
    picks it, case ignored; a repo the product doesn't list is read like the home repo"""

    def __init__(self, home: str, repos: Sequence[str], readers: Readers) -> None:
        self.home = home
        self.repos = list(repos)
        self.readers = readers
        self.spelled = {r.lower(): r for r in [home, *repos]}
        self.runners: dict[str, Runner] = {}

    def reader(self, repo: str) -> tuple[str, Runner]:
        """The repo as the config spells it (home's for one it doesn't list), and its runner"""
        key = self.spelled.get(repo.lower(), self.home)
        if key not in self.runners:
            self.runners[key] = self.readers(key)
        return key, self.runners[key]


def child_states(product: Product, refs: list[Ref]) -> dict[Ref, str]:
    """Each child's state as ref_state reads it (an issue or a pull request), grouped by the
    runner of its repo, CHUNK per query; a child that can't be read fails the run"""
    groups: dict[str, list[Ref]] = {}
    for ref in refs:
        key, _ = product.reader(f"{ref[0]}/{ref[1]}")
        groups.setdefault(key, []).append(ref)
    states: dict[Ref, str] = {}
    for key, group in groups.items():
        _, run = product.reader(key)
        for start in range(0, len(group), CHUNK):
            chunk = group[start : start + CHUNK]
            variables: Variables = {}
            for i, (owner, name, number) in enumerate(chunk):
                variables.update({f"o{i}": owner, f"n{i}": name, f"k{i}": number})
            what = "the children " + " ".join(named(r) for r in chunk)
            data = answered(run, children_query(len(chunk)), variables, what)
            for i, ref in enumerate(chunk):
                node = (data.get(f"c{i}") or {}).get("issueOrPullRequest")
                if not isinstance(node, dict):
                    fail(f"reading the child {named(ref)}: no such issue or pull request")
                states[ref] = ref_state(node)
    return states


def children(issue: dict[str, Any], repo: str) -> tuple[dict[Ref, str], list[Ref]]:
    """A report's children: its sub-issues with their states, and the "Depends on" refs no
    sub-issue already names (case ignored), whose states are still to read; never itself"""
    owner, name = split(repo)
    own = fold((owner, name, int(issue["number"])))
    known: dict[Ref, str] = {}
    keys: set[Ref] = {own}
    for ref, (_, state, _) in native_holds(issue).items():
        if fold(ref) not in keys:
            keys.add(fold(ref))
            known[ref] = state
    pending = []
    for ref in dependency_refs(issue, (owner, name)):
        if fold(ref) not in keys:
            keys.add(fold(ref))
            pending.append(ref)
    return known, pending


def decision(issue: dict[str, Any], bot_login: str | None) -> tuple[str, str] | None:
    """ASKED or ANSWERED for a report labelled needs-decision, by triage_state.py's rule"""
    labels = {n["name"] for n in issue["labels"]["nodes"]}
    if DECISION_LABEL not in labels:
        return None
    comments = [
        (login(c.get("author")), str(c.get("authorAssociation") or "NONE"), str(c["body"]))
        for c in issue["comments"]["nodes"]
    ]
    if waits_on_decision(comments, bot_login):
        return "ASKED", "waits on a reply" if question(comments, bot_login) is not None else "labelled, no question"
    reply = next(c for c in reversed(comments) if replies(c, bot_login))
    return "ANSWERED", f"answered by @{reply[0]}"


def classify(issue: dict[str, Any], kids: dict[Ref, str], bot_login: str | None) -> tuple[str, str]:
    """A trusted report's state from its labels, comments, and children with their states"""
    asked = decision(issue, bot_login)
    if asked is not None:
        return asked
    if not kids:
        links = " ".join(f"link {ref}" for ref in stand_ins(str(issue.get("body") or "")))
        return "ROUTE_DUE", links or "no children"
    shown = " ".join(f"{named(ref)}:{state.lower()}" for ref, state in sorted(kids.items(), key=lambda k: fold(k[0])))
    closed = sum(1 for state in kids.values() if state in CLOSED)
    if closed < len(kids):
        return "ROUTED", f"children {closed}/{len(kids)} closed {shown}"
    verdict = "not_planned" if any(state in NOT_LANDED for state in kids.values()) else "completed"
    return "CLOSE_DUE", f"{verdict}, children {closed}/{len(kids)} closed {shown}"


def upstream_rows(product: Product, bot_login: str | None) -> list[dict[str, str]]:
    """One row per open upstream report of the home repo, then of each listed repo, oldest
    first. An untrusted report is read for its author alone (D-16)"""
    found: list[tuple[str, dict[str, Any]]] = []  # (repo, a trusted report's fields)
    rows: dict[tuple[str, int], dict[str, str]] = {}
    order: list[tuple[str, int]] = []
    for repo in [product.home, *product.repos]:
        _, run = product.reader(repo)
        for item in reports(run, repo):
            number = int(item["number"])
            order.append((repo, number))
            author, association = login(item.get("author")), str(item.get("authorAssociation") or "NONE")
            if not trusted(author, association, bot_login):
                rows[(repo, number)] = {
                    "ref": f"{repo}#{number}",
                    "state": "UNTRUSTED",
                    "note": f"opened by @{author} ({association.lower()})",
                }
                continue
            found.append((repo, report(run, repo, number)))
    pending: dict[Ref, None] = {}
    known: dict[tuple[str, int], tuple[dict[Ref, str], list[Ref]]] = {}
    for repo, issue in found:
        kids, rest = children(issue, repo)
        known[(repo, int(issue["number"]))] = (kids, rest)
        pending.update(dict.fromkeys(rest))
    states = child_states(product, list(pending))
    for repo, issue in found:
        number = int(issue["number"])
        kids, rest = known[(repo, number)]
        state, note = classify(issue, {**kids, **{ref: states[ref] for ref in rest}}, bot_login)
        rows[(repo, number)] = {"ref": f"{repo}#{number}", "state": state, "note": note}
    return [rows[key] for key in order]


def checkout_repos(home: str, here: Path) -> list[str]:
    """[product] repos of the checkout's config, read as watch_state.py reads it; a config
    without them, or one listing the home repo, exits 2"""
    top = checkout_top(here)
    path = top / CONFIG
    if not path.is_file():
        fail(
            f"no {CONFIG} in {top}: run upstream_state.py in the home repo's checkout, whose [product] repos lists them"
        )
    ws = watch_module()
    try:
        repos: tuple[str, ...] | None = ws.product_repos(path.read_text(encoding="utf-8"), path)
    except ws.Refused as refused:
        sys.stderr.write(f"{refused}\n")
        raise SystemExit(2) from None
    if repos is None:
        fail(f"{path} has no [product] repos: only the product's home repo, the coordinator, reads its reports")
    if home.lower() in {r.lower() for r in repos}:
        fail(f"{path}: [product] repos lists the home repo {home} itself")
    return list(repos)


def default_readers(home: str, top: Path, execute: Execute = capture) -> Readers:
    """Plain gh for the home repo (the session's), `shipmill gh --product <repo>` for a listed
    one (the coordinator's product token), as the plugin's pinned release runs it; execute
    runs each command"""
    ws = watch_module()

    def readers(repo: str) -> Runner:
        if repo.lower() == home.lower():
            return gh_runner(("gh",), execute)
        try:
            shipmill: list[str] = ws.shipmill_cli()
        except ws.Refused as refused:
            sys.stderr.write(f"{refused}\n")
            raise SystemExit(2) from None
        return gh_runner((*shipmill, "--repo", str(top), "gh", "--product", repo), execute)

    return readers


def main(argv: Sequence[str] | None = None, readers: Readers | None = None, here: Path | None = None) -> int:
    """readers gives each repo's runner; None reads through gh and `shipmill gh --product`.
    here is the checkout's folder, the current one by default"""
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        epilog="States: " + " ".join(STATES) + ". The module docstring defines each.",
    )
    parser.add_argument("home", help="owner/name of the product's home repo, this checkout's")
    parser.add_argument("--bot-login", help="the login shipmill's sessions write as, such as <slug>[bot]")
    parser.add_argument("--json", action="store_true", help="JSON lines instead of text")
    args = parser.parse_args(argv)
    if not home_repo(args.home):
        parser.error(f"home must be owner/name of letters, digits, '.', '-', or '_', got {args.home!r}")
    if args.bot_login is not None and not args.bot_login.strip():
        parser.error("--bot-login must not be empty")
    folder = (here or Path.cwd()).resolve()
    repos = checkout_repos(args.home, folder)
    if readers is None:
        readers = default_readers(args.home, checkout_top(folder))
    rows = upstream_rows(Product(args.home, repos, readers), args.bot_login)
    for row in rows:
        print(json.dumps(row, sort_keys=True) if args.json else f"{row['ref']} {row['state']} {row['note']}".rstrip())
    return 1 if any(row["state"] in ACTION for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
