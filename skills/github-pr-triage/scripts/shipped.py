#!/usr/bin/env python3
"""Find the issues a release fixed, and optionally tell each one it shipped.

Usage: shipped.py <owner/repo> <prev-tag> <tag> [--repo-dir PATH] [--install TEXT]
                  [--environment NAME] [--post]

Walks `git log <prev-tag>..<tag>` in the local checkout and collects issue numbers from:
  - closing trailers in commit messages ("Fixes #N" at the start of a line)
  - the merged PRs those commits belong to (merge, squash, or rebase merges): GitHub's
    closingIssuesReferences in the repo, a closing keyword in the title, or one that starts
    a line of the body outside a code fence: github-issue-triage's triage_state.py
    keyword_closes, the one rule triage links a PR to an issue by (#416). A keyword quoted
    mid-line or in backticks names nothing (#368)
A stable tag also reads the range from the newest stable tag below it (or, when only
pre-release tags are below it, its whole history), so a stable release that promotes an
rc tells every issue the rc held even when <prev-tag> is a later rc and <prev-tag>..<tag> holds only the stamp
commit (spec 021, D-25). Keeps only issues that are closed, and skips any already told at
the tag's stage, so a second run posts nothing. A number that resolves to no issue or pull
request of the repo is skipped with a note on stderr (#368).

Each notice is for one stage (spec 021): `pre-release` for a dev, a, b, or rc tag, and
`stable` for any other. Its first line is the marker `<!-- shipmill:available: <stage>
<tag> -->`, and its second starts "Released in <tag> (pre-release)." or "Released in
<tag>.". An issue is told at the stable stage by a notice for that tag, and at the
pre-release stage by a pre-release notice no stable notice followed, so a fix is told once
per stage; a comment that starts "Released in <tag>" (the form before spec 021) counts as
told at its tag's stage.

With --environment NAME the notices are for that environment's stage instead (S-021-4):
<tag> succeeded deploying there, and <prev-tag> is what the environment ran before it, so
only <prev-tag>..<tag> is read. The notice is the marker `<!-- shipmill:available: NAME
<tag> -->` then "Deployed to NAME in <tag>.", with no command, and an issue with any NAME
notice is told, so each issue hears of an environment once. NAME is an environment's name
from the config's [environments]; "pre-release" and "stable" are refused (exit 2), since
their notices are the release stages'.

Without --post it prints the plan (one line per issue) and posts nothing. With --post it
posts the notices; the command a notice carries comes from the config's [notices]: `pin`
for a pre-release, `install` for a stable release, each taking {version}, {tag}, and
{name}. Without the policy's command, --install text is used, as before spec 021, except
that a pre-release gets no command when the policy sets only `install`. When the
checkout's .github/shipmill.toml sets [agents] app_id, each comment posts through
`uvx shipmill==<version> gh`, as the App (spec 012), the version in the plugin's own
.claude-plugin/plugin.json (spec 031); without it, plain gh posts as the host's login. Reads
always use plain gh.

Exit 0 on success (including nothing to do), 2 on bad input, a config github-ship-watch's
watch_state.py refuses, a missing or malformed plugin.json with app_id set, or a [notices]
section with --post that isn't the one the policy
accepts, or a git/gh failure (a `shipmill gh` exit 2 among them: the comment
is never retried with plain gh). Needs git and an authenticated gh CLI, and uvx with app_id
set. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

# github-ship-watch's watch_state.py: one reading of the config's [agents] for every skill script
WATCH_STATE = Path(__file__).resolve().parents[2] / "github-ship-watch" / "scripts" / "watch_state.py"
PRE_RELEASE, STABLE = "pre-release", "stable"
ENVIRONMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # shipmill's environments._NAME
# a version tag as shipmill cuts it: X.Y.Z with an optional a, b, or rc pre-release and .devN
VERSION_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?(?:\.dev(\d+))?$")
PRE_RANK = {"a": 1, "b": 2, "rc": 3}
# a notice's first line (spec 021), and the form every notice had before it
MARKER = re.compile(r"^<!-- shipmill:available: (\S+) (\S+) -->\s*$")
OLD_NOTICE = re.compile(r"^Released in (\S+?)(?: \(pre-release\))?\.(?:\s|$)")
PRE_RELEASE_LINES = (
    "A plain install gets it with the next stable release.",
    "If you filed this: react 👍 on this comment once it works for you, or reply if it doesn't.",
)
NOTICE_KEYS = ("install", "pin")
PLACEHOLDERS = ("name", "tag", "version")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
NOTICES_ANYWHERE = re.compile(r"^\s*[\"']?notices[\"']?\s*[.=]", re.MULTILINE)  # a dotted key or inline table
PLAIN_KEY = re.compile(r"^\s*(\w+)\s*=\s*(\"[^\"\\]*\"|'[^']*')\s*(?:#.*)?$")
# github-issue-triage's triage_state.py: one reading of a PR's closing keywords for both (#416)
TRIAGE_STATE = Path(__file__).resolve().parents[2] / "github-issue-triage" / "scripts" / "triage_state.py"
KEYWORDS = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
TRAILER = re.compile(rf"^\s*(?:[-*]\s*)?{KEYWORDS}:?\s+#(\d+)\b", re.IGNORECASE | re.MULTILINE)
# gh's answer for a number with no issue or pull request behind it, and only that (#368)
NOT_FOUND = re.compile(r"Could not resolve to an issue or pull request with the number of (\d+)\b")
PULLS = """query($owner: String!, $name: String!, $oid: GitObjectID!) {
  repository(owner: $owner, name: $name) {
    object(oid: $oid) {
      ... on Commit {
        associatedPullRequests(first: 20) {
          nodes {
            number title body mergedAt
            closingIssuesReferences(first: 50) { nodes { number repository { nameWithOwner } } }
          }
        }
      }
    }
  }
}"""


class NotFound(Exception):
    """`gh issue view` of a number the repo has no issue or pull request for"""

    def __init__(self, number: int) -> None:
        super().__init__(f"#{number} resolves to no issue or pull request")
        self.number = number


def run(cmd: list[str], cwd: str | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if missing(cmd, proc.stderr):
            raise NotFound(int(cmd[3]))
        sys.stderr.write(f"error: {' '.join(cmd[:3])}...: {proc.stderr.strip()}\n")
        raise SystemExit(2)
    return proc.stdout


def missing(cmd: list[str], stderr: str) -> bool:
    """A failed `gh issue view N` that says N has no issue or pull request behind it; narrow,
    so auth, network, and every other failure still stop the run (#368)"""
    found = NOT_FOUND.search(stderr)
    return cmd[:3] == ["gh", "issue", "view"] and found is not None and found.group(1) == cmd[3]


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
    owner, _, name = repo.partition("/")
    # -f, not -F: -F would turn a numeric owner or name such as 2048 into a number GraphQL refuses
    cmd = ["gh", "api", "graphql", "-f", f"query={PULLS}", "-f", f"owner={owner}", "-f", f"name={name}"]
    out = json.loads(gh([*cmd, "-f", f"oid={sha}"]))
    commit = out["data"]["repository"]["object"]
    if commit is None:
        sys.stderr.write(f"error: {repo} has no commit {sha}\n")
        raise SystemExit(2)
    prs: list[dict[str, Any]] = commit["associatedPullRequests"]["nodes"]
    return prs


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


def watch_module() -> ModuleType:
    return load("shipmill_watch_state", WATCH_STATE)


TRIAGE = load("shipmill_triage_state", TRIAGE_STATE)


def writer(repo_dir: Path, ws: ModuleType) -> list[str]:
    """The comment's gh: `shipmill gh` with [agents] app_id set, else plain gh (spec 012)"""
    try:
        found: list[str] = ws.gh_writer(repo_dir)
    except ws.Refused as refused:
        sys.stderr.write(f"{refused}\n")
        raise SystemExit(2) from None
    return found


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


def notices_on(comments: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Each notice among the comments, oldest first, as (stage, tag): by its marker, or a
    "Released in <tag>" first line, the form before spec 021, at its tag's stage"""
    found = []
    for comment in comments:
        body = comment["body"]
        marker = MARKER.match(body.partition("\n")[0])
        if marker is not None:
            found.append((marker.group(1), marker.group(2)))
            continue
        old = OLD_NOTICE.match(body)
        if old is not None:
            found.append((stage_of(old.group(1)), old.group(1)))
    return found


def told(comments: list[dict[str, Any]], tag: str) -> bool:
    """Whether the issue was told at tag's stage: stable by a notice for tag itself; a
    pre-release by a pre-release notice that no stable notice followed, so a fix reopened
    and fixed again after a stable release is told of its next pre-release"""
    stage = stage_of(tag)
    if stage == STABLE:
        return (STABLE, tag) in notices_on(comments)
    since_stable = False
    for seen, _ in notices_on(comments):
        if seen == PRE_RELEASE:
            since_stable = True
        elif seen == STABLE:
            since_stable = False
    return since_stable


def told_in(comments: list[dict[str, Any]], environment: str) -> bool:
    """Whether the issue was told of the environment, by a notice for it at any tag: an
    issue hears of each environment once (S-021-4)"""
    return any(stage == environment for stage, _ in notices_on(comments))


def deployed_notice(environment: str, tag: str) -> str:
    """The comment for the environment's stage: the marker line, then "Deployed to" (S-021-4)"""
    return f"<!-- shipmill:available: {environment} {tag} -->\nDeployed to {environment} in {tag}."


def environment_name(value: str) -> str:
    """--environment: an environment's name as shipmill's config allows it, and not a release
    stage's, whose notices would read as told by it"""
    if ENVIRONMENT.fullmatch(value) is None or value in (PRE_RELEASE, STABLE):
        raise argparse.ArgumentTypeError(f"not an environment's name: {value!r}")
    return value


def notice(tag: str, command: str) -> str:
    """The comment for tag's stage: the marker line, then "Released in", then for a
    pre-release what a plain install does and what the requester may answer"""
    stage = stage_of(tag)
    words = f"Released in {tag} (pre-release)." if stage == PRE_RELEASE else f"Released in {tag}."
    lines = [f"<!-- shipmill:available: {stage} {tag} -->", f"{words}{(' ' + command) if command else ''}"]
    if stage == PRE_RELEASE:
        lines.extend(PRE_RELEASE_LINES)
    return "\n".join(lines)


def tell(
    repo: str,
    issues: dict[int, set[str]],
    tag: str,
    command: str,
    write: list[str] | None,
    gh: Callable[[list[str]], str] = run,
    environment: str | None = None,
) -> None:
    """One line per issue; with write (the --post gh), comment on each closed one not yet told
    at tag's stage, with command after its "Released in" sentence, or with environment, each
    one not yet told of that environment, "Deployed to" it. Reads are plain gh; a failed
    write stops the run, never retried another way"""
    for number in sorted(issues):
        source = ", ".join(sorted(issues[number]))
        try:
            out = gh(["gh", "issue", "view", str(number), "-R", repo, "--json", "state,title,comments,url"])
        except NotFound:
            # one bad reference must not stop the notices after it, or the watch (#368)
            sys.stderr.write(f"note: #{number} [{source}] is no issue or pull request of {repo}, skipped\n")
            continue
        view = json.loads(out)
        if "/pull/" in view["url"]:
            continue
        if view["state"] != "CLOSED":
            print(f"#{number:<5} SKIP open         {view['title'][:60]}  [{source}]")
            continue
        already = told(view["comments"], tag) if environment is None else told_in(view["comments"], environment)
        if already:
            print(f"#{number:<5} SKIP notified     {view['title'][:60]}")
            continue
        if write is not None:
            body = notice(tag, command) if environment is None else deployed_notice(environment, tag)
            gh([*write, "issue", "comment", str(number), "-R", repo, "--body", body])
            print(f"#{number:<5} POSTED            {view['title'][:60]}  [{source}]")
        else:
            print(f"#{number:<5} WOULD POST        {view['title'][:60]}  [{source}]")


def collect(repo: str, pairs: list[tuple[str, str]], gh: Callable[[list[str]], str] = run) -> dict[int, set[str]]:
    """Each issue the commits close, by commit trailer or merged PR, with where it was named"""
    issues: dict[int, set[str]] = {}
    seen_prs: set[int] = set()
    for sha, body in pairs:
        for n in TRAILER.findall(body):
            issues.setdefault(int(n), set()).add(sha[:7])
        for pr in prs_for(repo, sha, gh):
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


@dataclass(frozen=True)
class Notices:
    """The config's [notices] commands, as written, and its top-level name for {name}"""

    pin: str | None = None
    install: str | None = None
    name: str | None = None


def refuse(message: str) -> NoReturn:
    sys.stderr.write(f"{message}\n")
    raise SystemExit(2)


def notices_config(repo_dir: Path, ws: ModuleType) -> Notices:
    """[notices] of the checkout's config, read as watch_state.py reads [agents]: tomllib on
    3.11+, plain one-line keys on 3.10. Any key but pin and install, a value that isn't a
    non-empty string, or a placeholder but {version}, {tag}, and {name} exits 2, as the
    policy refuses it"""
    here = repo_dir.resolve()
    top = next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), here)
    path = top / ws.POLICY
    if not path.is_file():
        return Notices()
    text = path.read_text(encoding="utf-8")
    if ws.tomllib is None:
        table, name = notices_310(text, path, ws)
    else:
        try:
            raw = ws.tomllib.loads(text)
        except ws.tomllib.TOMLDecodeError as exc:
            refuse(f"error: {path}: {exc}")
        table, name = raw.get("notices"), raw.get("name")
    if table is None:
        return Notices()
    if not isinstance(table, dict):
        refuse(f"error: {path}: notices must be a table")
    unknown = sorted(set(table) - set(NOTICE_KEYS))
    if unknown:
        refuse(f"error: {path} [notices]: unknown keys {unknown}; allowed: {list(NOTICE_KEYS)}")
    for key, value in table.items():
        if not isinstance(value, str) or not value.strip():
            refuse(f"error: {path} [notices]: {key} must be a non-empty string, got {value!r}")
        bad = sorted(set(PLACEHOLDER.findall(value)) - set(PLACEHOLDERS))
        if bad:
            refuse(f"error: {path} [notices]: {key} takes {{version}}, {{tag}}, and {{name}}; got {bad}")
    if not isinstance(name, str) and any("{name}" in v for v in table.values()):
        refuse(f"error: {path}: [notices] uses {{name}}, but the config sets no name")
    return Notices(table.get("pin"), table.get("install"), name if isinstance(name, str) else None)


def notices_310(text: str, path: Path, ws: ModuleType) -> tuple[dict[str, str] | None, str | None]:
    """[notices] as a plain table of one-line string keys, and the top-level name; any other
    form is refused rather than misread"""
    unreadable = f"error: {path}: can't read [notices] on Python 3.10: use 3.11+ or a plain [notices] table"
    tables = ws.toml_tables(text)
    if any(n.startswith("notices.") for n in tables) or NOTICES_ANYWHERE.search(text):
        refuse(unreadable)
    name = ws.toml_string(tables.get("", ""), "name")
    headers = re.findall(r"^\s*\[+\s*[\"']?notices\b", text, re.MULTILINE)
    if "notices" not in tables:
        if headers:
            refuse(unreadable)  # a malformed header such as "[notices"
        return None, name
    if len(headers) > 1:
        refuse(f"error: {path}: [notices] is declared twice")
    found = {}
    for line in tables["notices"].splitlines():
        if ws.blank(line):
            continue
        key = PLAIN_KEY.match(line)
        if key is None:
            refuse(f"{unreadable} ({line.strip()!r})")
        if key.group(1) in found:
            refuse(f"error: {path} [notices]: {key.group(1)} is set twice")
        found[key.group(1)] = key.group(2)[1:-1]
    return found, name


def code(text: str) -> str:
    """text as inline code, its fence longer than any backtick run inside it"""
    fence = "`" * (max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def render(template: str, tag: str, name: str | None) -> str:
    """{version}, {tag}, and {name} filled in; notices_config refused any other placeholder"""
    version = tag[1:] if tag.startswith("v") else tag
    return code(template.replace("{version}", version).replace("{tag}", tag).replace("{name}", name or ""))


def command_for(tag: str, notices: Notices, install: str) -> str:
    """The command tag's notice carries: [notices] pin for a pre-release, install for a stable
    release; else --install text, unless the policy names only the stable command"""
    template = notices.pin if stage_of(tag) == PRE_RELEASE else notices.install
    if template is not None:
        return render(template, tag, notices.name)
    return "" if notices.install is not None else install


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("prev_tag")
    parser.add_argument("tag")
    parser.add_argument("--repo-dir", default=".", help="local checkout (default: cwd)")
    parser.add_argument(
        "--install", default="", help='appended to the notice without [notices] install, e.g. "`uv add pkg==X`"'
    )
    parser.add_argument(
        "--environment",
        type=environment_name,
        help="tell of a successful deployment of <tag> to this environment, which ran <prev-tag> before",
    )
    parser.add_argument("--post", action="store_true", help="post the comments (default: print the plan)")
    args = parser.parse_args()
    if "/" not in args.repo:
        parser.error("repo must be owner/name")

    # before any gh call, so a config that can't be read stops the run with nothing posted
    write, notices = None, Notices()
    if args.post:
        ws = watch_module()
        write = writer(Path(args.repo_dir), ws)
        if args.environment is None:  # a deployment's notice carries no command
            notices = notices_config(Path(args.repo_dir), ws)
    run(["git", "fetch", "-q", "--force", "--tags", "origin"], cwd=args.repo_dir)  # a bot moves major tags such as v0
    if args.environment is not None:
        # only what the environment didn't run before: a fix the earlier tag held was told then
        issues = collect(args.repo, commits(args.repo_dir, args.prev_tag, args.tag))
        tell(args.repo, issues, args.tag, "", write, environment=args.environment)
        return 0
    issues = collect(args.repo, release_commits(args.repo_dir, args.prev_tag, args.tag))
    tell(args.repo, issues, args.tag, command_for(args.tag, notices, args.install), write)
    return 0


if __name__ == "__main__":
    sys.exit(main())
