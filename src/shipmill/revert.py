"""`revert open` (spec 079): back out the merges that turned the default branch red.

Every check runs before the first write, and any failure raises with nothing written (Q-1):
`[autonomy] revert` at origin's default branch is propose or act, the App is available and
names its bot, `--run` names a failed completed check of the default head (`pr_gate.py`'s
`head_checks` and `repaired`), origin's default branch is that head, each pull request is
revertable by `base_red.py`'s rule (merged into the default branch by the App's bot, its merge
commit on the branch's first-parent history, in no tag), no open pull request has a `Repairs:`
line naming the run, the reverts apply, and the body's plan holds by `plan_problems`.

Then the branch `revert/<N>-<sha7>` (N the oldest reverted pull request, sha7 the red head)
holding one revert commit per pull request, newest first, is pushed; the pull request opens
labelled `revert`; and each issue a reverted pull request closed as completed is reopened with
one `<!-- shipmill:reverted #N by #R -->` comment. The reverts are built from git objects
alone (`git merge-tree`, `git commit-tree`), so the checkout's working tree, index, and branch
stay as they were. The wheel's `base_red.py` and its `pr_gate.py` are the one reading of a red
head and of a revertable merge: nothing here judges a check or a merge on its own.
"""

import functools
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol

from shipmill.app_gh import pull_url
from shipmill.autonomy import Autonomy
from shipmill.bundle import skills_dir
from shipmill.classify import policy_at
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.gitrepo import REMOTE, Git
from shipmill.spec_open import Leaks

_SCRIPT = ("github-pr-triage", "scripts", "base_red.py")
_NAME = "shipmill_base_red"
LABEL = "revert"
LABEL_COLOR = "b60205"
LABEL_DESCRIPTION = "Backs out merges that turned the default branch red (spec 079)"
LIMIT = 100  # the newest first-parent commits a reverted merge commit is looked for in
QUALITY_BAR = "quality bar"
MARKER = "<!-- shipmill:reverted #{pull} by #{revert} -->"  # triage_state.py's REVERTED_MARKER
_IDS = re.compile(r"\b[GQ]-[1-9][0-9]*\b")
_SERVES = re.compile(r"^\s*(?:[-*]\s+)?Serves:(.*)$")
CLOSING_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 100) {
        nodes { number state stateReason repository { nameWithOwner } }
      }
    }
  }
}
"""


@functools.cache
def _base_red() -> ModuleType:
    """The wheel's base_red.py, loaded once; it loads its pr_gate.py beside it"""
    script = skills_dir().joinpath(*_SCRIPT)
    found = importlib.util.spec_from_file_location(_NAME, script)
    if found is None or found.loader is None:
        raise ReleaseError(f"can't load {script}")
    module = importlib.util.module_from_spec(found)
    sys.modules[_NAME] = module  # its dataclasses look their module up by name
    found.loader.exec_module(module)
    return module


class Reads(Protocol):
    """GitHub's reads, each a `gh api` call through `shipmill gh`"""

    def text(self, args: list[str]) -> str:
        """gh api's output for args, `{owner}/{repo}` filled in with the checkout's repo;
        raises ReleaseError when gh fails"""
        ...


class Writes(Protocol):
    """GitHub's writes, each one `shipmill gh` makes as the App"""

    def create_label(self, name: str, color: str, description: str) -> None: ...

    def open_pull(self, title: str, body: str, head: str, base: str, label: str) -> str:
        """Open the pull request with the label; its URL"""
        ...

    def comment(self, number: int, body: str) -> None: ...

    def reopen(self, number: int) -> None: ...


@dataclass(frozen=True, slots=True)
class Request:
    """`revert open`'s arguments: the pull requests to revert, in the order given, and --run"""

    pulls: tuple[int, ...]
    run: str

    def __post_init__(self) -> None:
        if not self.pulls:
            raise ReleaseError("revert open names one pull request or more to revert")
        odd = [n for n in self.pulls if n < 1]
        if odd:
            raise ReleaseError(f"a pull request's number is 1 or more; got {odd[0]}")
        if len(set(self.pulls)) != len(self.pulls):
            raise ReleaseError("each pull request is named once")
        if not self.run.strip() or any(c.isspace() for c in self.run):
            raise ReleaseError(f"--run is the URL of the failed run on the default branch's head; got {self.run!r}")


@dataclass(frozen=True, slots=True)
class Reverted:
    """A revertable pull request: its number, title, and body, its merge commit, and that
    commit's place on the first-parent path, 0 the head"""

    number: int
    title: str
    body: str
    sha: str
    index: int


@dataclass(frozen=True, slots=True)
class Opened:
    """What revert open wrote: the pull request's URL and the issues it reopened"""

    url: str
    reopened: tuple[int, ...]

    def text(self) -> str:
        return "".join([f"{self.url}\n", *(f"reopened: #{n}\n" for n in self.reopened)])


class _Api:
    """base_red.py's GitHub (text, json, lines, and the repo's owner and name) on Reads"""

    def __init__(self, reads: Reads, repo: str) -> None:
        self._reads = reads
        self.repo = repo
        self.owner, _, self.name = repo.partition("/")

    def text(self, args: list[str]) -> str:
        return self._reads.text(args)

    def json(self, args: list[str]) -> object:
        out = self.text(args)
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise ReleaseError(f"gh api {' '.join(args)} printed no JSON: {exc}") from None

    def lines(self, path: str, jq: str) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        for line in self.text(["--paginate", path, "--jq", jq]).splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReleaseError(f"gh api {path} printed no JSON: {exc}") from None
            if not isinstance(item, dict):
                raise ReleaseError(f"gh api {path} printed {item!r}, not an object")
            found.append(item)
        return found


def open_revert(
    top: Path, repo: str, request: Request, reads: Reads, writes: Writes, app: Callable[[], str], leaks: Leaks
) -> Opened:
    """S-079-8 to S-079-11: every check, then the writes. app returns the App's bot login, or
    raises when the App isn't available. Any failure before the push raises with nothing
    written: no branch pushed, no label, no pull request, no issue reopened"""
    git = Git(top)
    base = git.default_branch()
    tracking = f"refs/remotes/{REMOTE}/{base}"
    git.run("fetch", "-q", REMOTE, f"+refs/heads/{base}:{tracking}")
    level = _level(git, tracking, base)
    if level is Autonomy.OBSERVE:
        raise ReleaseError(
            f"[autonomy] revert is observe on {base}, so shipmill only reports a red {base} (spec 079); set it to "
            "propose or act on the default branch to open reverts. Nothing was written"
        )
    bot = app()
    module = _base_red()
    gate = module.gate
    api = _Api(reads, repo)
    try:
        prepared = _prepare(git, api, module, request, base, tracking, bot)
    except (ReleaseError, module.BaseRedError, gate.GateError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"{exc}\nnothing was written") from None
    return _write(git, api, writes, leaks, prepared, repo, base, request.run, bot)


@dataclass(frozen=True, slots=True)
class _Prepared:
    head: str
    check: str
    branch: str
    commit: str
    title: str
    body: str
    label_missing: bool
    reverted: tuple[Reverted, ...]  # newest first
    closes: tuple[tuple[int, int], ...]  # (pull request, issue it closed as completed), newest pull first


def _level(git: Git, ref: str, base: str) -> Autonomy:
    """[autonomy] revert in the config at origin's default branch, never the working tree's;
    no config there reads observe. The hold only reads act as propose (D-15), and both open the
    revert: pr_gate.py holds its merge (S-079-12)"""
    if git.show(ref, str(CONFIG_PATH)) is None:
        return Autonomy.OBSERVE
    return policy_at(git, ref).autonomy.revert


def _prepare(
    git: Git, api: _Api, module: ModuleType, request: Request, base: str, tracking: str, bot: str
) -> _Prepared:
    gate = module.gate
    head, entries = gate.head_checks(base, api.text)
    failed = [e for e in entries if gate.check_of(e).done and gate.check_of(e).conclusion not in gate.NOT_RED]
    named = [e for e in failed if gate.repaired(e, [request.run]) and _same_repo(request.run, e)]
    if not named:
        listed = ", ".join(f"{gate.check_of(e).name} ({_url(e)})" for e in failed) or "none"
        raise ReleaseError(
            f"--run {request.run} names no failed completed check on {base}@{head[:7]}; failed there: {listed}"
        )
    check = str(gate.check_of(named[0]).name)
    tip = git.sha(tracking)
    if tip != head:
        raise ReleaseError(
            f"{REMOTE}/{base} is at {tip[:7]} but GitHub reads {base}'s head as {head[:7]}: the branch moved, so run "
            "revert open again on its new head"
        )
    items = module.open_items(api)
    repairing = sorted(
        int(item["number"])
        for item in items
        if "pull_request" in item and any(gate.repaired(e, gate.repairs_of(str(item.get("body") or ""))) for e in named)
    )
    if repairing:
        raise ReleaseError(
            f"#{repairing[0]} already has a Repairs: line naming {request.run}: that pull request repairs {base}, so "
            "no second revert opens"
        )
    history = module.History(api, head, LIMIT)
    tags = module.Tags(api)
    found = [_revertable(api, module, number, base, bot, history, tags) for number in request.pulls]
    reverted = tuple(sorted(found, key=lambda r: r.index))  # newest first
    branch = f"revert/{reverted[-1].number}-{head[:7]}"
    if git.remote_branch(branch) is not None:
        raise ReleaseError(f"{REMOTE} already has the branch {branch}: a revert of this head may be open")
    closes = tuple((r.number, issue) for r in reverted for issue in _closed_issues(api, r.number))
    commit, files = _reverts(git, head, reverted)
    by_number = {r.number: r for r in found}
    ordered = [by_number[n] for n in request.pulls]
    title = (
        f'Revert "{ordered[0].title}"' if len(ordered) == 1 else "Revert " + ", ".join(f"#{n}" for n in request.pulls)
    )
    ids = _direction(git, gate, tracking)
    body = _body(ordered, request.run, check, base, head, files, _serves(ordered, ids))
    if ids is not None:
        problems = gate.plan_problems(body, ids)
        if problems:
            raise ReleaseError("the revert's plan doesn't hold:\n" + "\n".join(f"  {p}" for p in problems))
    labels = api.lines("repos/{owner}/{repo}/labels?per_page=100", ".[]")
    missing = not any(str(label.get("name") or "").lower() == LABEL for label in labels)
    return _Prepared(head, check, branch, commit, title, body, missing, reverted, closes)


def _same_repo(run: str, entry: dict[str, object]) -> bool:
    """Whether run sits on the host and in the repo of one of the check's own URLs: pr_gate.py's
    `repaired` matches an Actions run by its id alone, whatever host and repo the URL names, and
    the URL is written into the pull request and each reopened issue"""
    urls = entry.get("urls")
    if not isinstance(urls, list):
        return False
    return _repo_of(run) in {_repo_of(str(u)) for u in urls if u}


def _repo_of(url: str) -> tuple[str, ...]:
    """A URL's scheme, host, owner, and name, lowercased"""
    return tuple(part.lower() for part in url.split("/", 5)[:5])


def _url(entry: dict[str, object]) -> str:
    urls = entry.get("urls")
    return next((str(u) for u in urls if u), "no URL") if isinstance(urls, list) else "no URL"


def _revertable(
    api: _Api, module: ModuleType, number: int, base: str, bot: str, history: _History, tags: object
) -> Reverted:
    """The pull request when base_red.py's rule reverts it: merged into base, its merge commit
    on base's first-parent history, merged by the App's bot, and in no tag"""
    data = api.json([f"repos/{{owner}}/{{repo}}/pulls/{number}"])
    if not isinstance(data, dict):
        raise ReleaseError(f"gh api answered no pull request for #{number}: {str(data)[:200]}")
    if not data.get("merged_at"):
        raise ReleaseError(f"#{number} isn't merged, so there is nothing of it to revert")
    into = data.get("base")
    ref = into.get("ref") if isinstance(into, dict) else None
    if ref != base:
        raise ReleaseError(f"#{number} merged into {ref}, not the default branch {base}")
    sha = data.get("merge_commit_sha")
    if not isinstance(sha, str) or not sha:
        raise ReleaseError(f"#{number} names no merge commit")
    index = next((i for i in range(LIMIT) if history.at(i) in (sha, None)), None)
    if index is None or history.at(index) != sha:
        raise ReleaseError(
            f"#{number}'s merge commit {sha[:7]} isn't on {base}'s first-parent history in its newest {LIMIT} commits"
        )
    candidate = module.Candidate(sha, index)
    module.judge_candidate(api, candidate, bot, tags, history)
    if candidate.reason is not None:
        raise ReleaseError(f"#{number} is not revertable: {candidate.reason}")
    if candidate.pull != number:
        raise ReleaseError(f"{sha[:7]} is the merge commit of #{candidate.pull}, not of #{number}")
    return Reverted(number, str(data.get("title") or ""), str(data.get("body") or ""), sha, index)


class _History(Protocol):
    """base_red.py's History: the branch's first-parent path from the head"""

    def at(self, index: int) -> str | None: ...


def _closed_issues(api: _Api, number: int) -> list[int]:
    """The issues of this repo the pull request closed as completed, by GitHub's closing references"""
    args = ["graphql", "-f", f"query={CLOSING_QUERY}", "-f", f"owner={api.owner}", "-f", f"name={api.name}"]
    data = api.json([*args, "-F", f"number={number}"])
    nodes: object = data
    for key in ("data", "repository", "pullRequest", "closingIssuesReferences", "nodes"):
        nodes = nodes.get(key) if isinstance(nodes, dict) else None
    if not isinstance(nodes, list):
        raise ReleaseError(f"the issues #{number} closes can't be read: {str(data)[:200]}")
    found: list[int] = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("number"), int):
            raise ReleaseError(f"a closing reference of #{number} is no issue: {str(node)[:200]}")
        where = node.get("repository")
        name = where.get("nameWithOwner") if isinstance(where, dict) else None
        if not isinstance(name, str) or name.lower() != api.repo.lower():
            continue
        if node.get("state") == "CLOSED" and node.get("stateReason") == "COMPLETED":
            found.append(node["number"])
    return sorted(found)


def _reverts(git: Git, head: str, reverted: Sequence[Reverted]) -> tuple[str, tuple[str, ...]]:
    """One revert commit per pull request on head, newest first, built from git objects alone
    (as `git revert`, with `-m 1` for a two-parent merge); the last commit and the files the
    reverts change. A revert that conflicts raises naming the conflicting files"""
    current = head
    for r in reverted:
        parents = git.run("rev-list", "--parents", "-n", "1", r.sha).split()[1:]
        if len(parents) not in (1, 2):
            raise ReleaseError(
                f"#{r.number}'s merge commit {r.sha[:7]} has {len(parents)} parents; git reverts one or two"
            )
        merged = subprocess.run(
            [
                "git",
                "-C",
                str(git.root),
                "merge-tree",
                "--write-tree",
                "--name-only",
                "--no-messages",
                f"--merge-base={r.sha}",
                current,
                parents[0],
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        lines = merged.stdout.splitlines()
        if merged.returncode == 1:
            conflicting = sorted(set(line for line in lines[1:] if line.strip()))
            raise ReleaseError(
                f"the revert of #{r.number} conflicts in {', '.join(conflicting)}: revert it by hand, or ask"
            )
        if merged.returncode != 0 or not lines:
            raise ReleaseError(f"git merge-tree for the revert of #{r.number} failed: {merged.stderr.strip()}")
        subject = git.run("log", "-1", "--format=%s", r.sha).strip()
        reverses = f", reversing\nchanges made to {parents[0]}" if len(parents) == 2 else ""
        message = f'Revert "{subject}"\n\nThis reverts commit {r.sha}{reverses}.'
        current = git.run("commit-tree", lines[0], "-p", current, "-m", message).strip()
    files = tuple(line for line in git.run("diff", "--name-only", head, current).splitlines() if line)
    if not files:
        raise ReleaseError("the reverts change nothing on the head: its changes are already undone")
    return current, files


def _direction(git: Git, gate: ModuleType, ref: str) -> frozenset[str] | None:
    """The ids docs/product.md lists at origin's default branch; None without it, where no plan
    is checked, as pr_gate.py checks none"""
    if git.show(ref, gate.DIRECTION) is None:
        return None
    ids: frozenset[str] = gate.direction_ids(lambda path: git.show(ref, path))
    return ids


def _serves(reverted: Sequence[Reverted], ids: frozenset[str] | None) -> str:
    """The ids the reverted pull requests' own `Serves:` lines name, in order, each once, those
    the direction still lists; `quality bar` when none names one"""
    found: list[str] = []
    for r in reverted:
        for line in _plan_lines(r.body):
            serves = _SERVES.match(line)
            if serves is None:
                continue
            for name in _IDS.findall(serves.group(1)):
                if name not in found and (ids is None or name in ids):
                    found.append(name)
    return ", ".join(found) or QUALITY_BAR


def _plan_lines(body: str) -> list[str]:
    gate = _base_red().gate
    plans = [lines for level, heading, lines in gate.sections(body) if level == 2 and heading == "Plan"]
    return [line for _, line in plans[0]] if plans else []


def _body(
    reverted: Sequence[Reverted], run: str, check: str, base: str, head: str, files: Sequence[str], serves: str
) -> str:
    """S-079-10: a `Reverts #N` line per pull request, `Repairs:`, and the plan"""
    merged = "it merged" if len(reverted) == 1 else "they merged"
    them = "it" if len(reverted) == 1 else "them, newest first"
    return "\n".join(
        [
            *(f"Reverts #{r.number}" for r in reverted),
            f"Repairs: {run}",
            "",
            f"`{check}` failed on {base}@{head[:7]} after {merged}; this backs {them} out so {base} can go green "
            "again (spec 079). It adds no changelog entry: a reverted change's entry goes with it.",
            "",
            "## Plan",
            "",
            f"- Serves: {serves}",
            f"- Files: {', '.join(f'`{f}`' for f in files)}",
            "- Order: this pull request first, then each reopened issue's change again",
            f"- Proof: `{check}` green on this pull request's head",
        ]
    )


def _write(
    git: Git,
    api: _Api,
    writes: Writes,
    leaks: Leaks,
    prepared: _Prepared,
    repo: str,
    base: str,
    run: str,
    bot: str,
) -> Opened:
    leaks.body(prepared.body)
    refspec = f"{prepared.commit}:refs/heads/{prepared.branch}"
    leaks.push(refspec)
    failed = git.push(refspec)
    if failed:
        raise ReleaseError(f"git push of {prepared.branch} to {REMOTE} failed: {failed}; nothing else was written")
    left = f"the branch {prepared.branch} is pushed"
    try:
        if prepared.label_missing:
            writes.create_label(LABEL, LABEL_COLOR, LABEL_DESCRIPTION)
        url = writes.open_pull(prepared.title, prepared.body, prepared.branch, base, LABEL)
        opened, number = pull_url(url)
    except ReleaseError as exc:
        raise ReleaseError(f"{exc}\n{left}, but its pull request may not be open") from None
    if opened.lower() != repo.lower():
        raise ReleaseError(f"gh opened the pull request {url}, not one of {repo}\n{left}")
    reopened: list[int] = []
    handled: set[int] = set()
    for pull, issue in prepared.closes:
        if issue in handled:
            continue
        handled.add(issue)
        marker = MARKER.format(pull=pull, revert=number)
        try:
            if _carries(api, issue, marker, bot):
                continue
            text = (
                f"{marker}\nReopened: #{pull}, which closed this, is being reverted in #{number}. `{prepared.check}` "
                f"failed on {base}@{prepared.head[:7]} after it merged: {run}"
            )
            writes.comment(issue, text)
            writes.reopen(issue)
        except ReleaseError as exc:
            done = ", ".join(f"#{n}" for n in reopened) or "none"
            raise ReleaseError(f"{exc}\nthe pull request {url} is open; issues reopened: {done}") from None
        reopened.append(issue)
    return Opened(url, tuple(reopened))


def _carries(api: _Api, issue: int, marker: str, bot: str) -> bool:
    """Whether the bot already commented the marker on the issue, as its first line"""
    for comment in api.lines(f"repos/{{owner}}/{{repo}}/issues/{issue}/comments?per_page=100", ".[]"):
        user = comment.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        lines = str(comment.get("body") or "").splitlines()
        if isinstance(login, str) and login.lower() == bot.lower() and lines and lines[0].strip() == marker:
            return True
    return False
