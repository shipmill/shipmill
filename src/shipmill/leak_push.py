"""Spec 081: what a `git push` would send, as the texts the leak check reads (`shipmill leaks
push`, S-081-9, S-081-10).

Only what the push sends is read, never the rest of the tree or history:

- the commits reachable from each pushed ref and from no remote-tracking ref of the remote,
  each read by itself against its first parent: its message, the paths it adds, changes, or
  renames to, and the lines it adds (binary files left out), so a line one commit adds and a
  later one removes is still read
- the destination ref names
"""

import fnmatch
import re
from collections.abc import Sequence
from dataclasses import dataclass

from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git
from shipmill.leaks import Finding, Text

SHORT = 7  # a commit's characters a finding names
COMMAND = "shipmill leaks push"  # the command a refusal names
# what `leaks push` says of a source ref that names no commit, such as a branch an earlier part
# of the same Bash command creates; hooks/delivery.py's LEAKS_MISSING_REF mirrors it (#1542)
MISSING_REF = "doesn't exist in this checkout yet"
PUSH_FIX = (
    "Instead: rewrite the unpushed commits without it (amend or rebase them, never a pushed one)\n"
    "and push again; describe a case by its traits, never by the project, customer, or host it\n"
    "came from, and take the secret out. A person can push it from their own terminal"
)
_HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GITHUB = re.compile(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$")
# `git show`'s options for a commit against its first parent, set whatever the git config says;
# --text, so no attributes file (`-diff`, `binary`) hides a text file's lines: a file is binary
# only by its content, a NUL byte in its added lines (D-94)
_DIFF = (
    "--no-show-signature",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--text",
    "--no-relative",
    "--submodule=short",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "-M",
    "-m",
    "--first-parent",
)


@dataclass(frozen=True, slots=True)
class Push:
    """A `git push`'s remote (None for the current branch's), its refspecs, and the flags that
    push many refs at once"""

    remote: str | None
    refspecs: tuple[str, ...]
    all_branches: bool = False
    tags: bool = False
    mirror: bool = False


@dataclass(frozen=True, slots=True)
class _Ref:
    """A ref the push sends: the source as git resolves it, and the destination ref name"""

    source: str
    destination: str


@dataclass(frozen=True, slots=True)
class Outgoing:
    """What a push sends: its remote's GitHub repo as owner/name (None off github.com), the
    texts the check reads, and for each text of added lines, the file line of each of its lines"""

    repo: str | None
    texts: tuple[Text, ...]
    lines: dict[str, tuple[int, ...]]

    def placed(self, findings: Sequence[Finding]) -> list[Finding]:
        """findings with a file's line numbers in place of their lines in its text of added lines"""
        out: list[Finding] = []
        for finding in findings:
            lines = self.lines.get(finding.where)
            if lines is None:
                out.append(finding)
                continue
            at = lines[(finding.line or 1) - 1]
            out.append(Finding(finding.detector, finding.where, at, finding.what))
        return out


def _branch(git: Git) -> str | None:
    """The current branch's short name, None on a detached HEAD"""
    if not git.ok("symbolic-ref", "--quiet", "HEAD"):
        return None
    return git.run("symbolic-ref", "--quiet", "--short", "HEAD").strip()


def _current_branch(git: Git) -> str:
    name = _branch(git)
    if name is None:
        raise ReleaseError("the push names no refspec and HEAD is no branch; name what to push")
    return name


def _config(git: Git, key: str) -> str | None:
    value = git.run("config", "--default", "", "--get", key).strip()
    return value or None


def _remote(git: Git, push: Push) -> str:
    """The remote a push goes to: the one it names, else git's choice for the current branch
    (its pushRemote, remote.pushDefault, its remote), else origin"""
    if push.remote is not None:
        return push.remote
    branch = _branch(git)
    keys = ["remote.pushDefault"]
    if branch is not None:
        keys = [f"branch.{branch}.pushRemote", *keys, f"branch.{branch}.remote"]
    for key in keys:
        found = _config(git, key)
        if found is not None:
            return found
    return "origin"


def _remote_repo(git: Git, remote: str) -> str | None:
    """remote's GitHub repo as owner/name: a configured remote's push URL, else remote as a URL"""
    names = git.run("remote").split()
    url = git.run("remote", "get-url", "--push", remote).strip() if remote in names else remote
    found = _GITHUB.search(url)
    return found.group(1) if found else None


def _refs(git: Git, pattern: str) -> list[str]:
    return git.run("for-each-ref", "--format=%(refname)", pattern).split()


def _expanded(git: Git, source: str, destination: str) -> list[_Ref]:
    """A refspec's source and destination, its `*` pattern expanded over the local refs"""
    if "*" not in source:
        return [_Ref(source, destination)]
    head, tail = source.split("*", 1)
    full = head if head.startswith("refs/") else f"refs/heads/{head}"
    found: list[_Ref] = []
    for ref in _refs(git, full.rsplit("/", 1)[0] if "/" in full else full):
        if fnmatch.fnmatchcase(ref, f"{full}*{tail}"):
            middle = ref[len(full) : len(ref) - len(tail) if tail else None]
            found.append(_Ref(ref, destination.replace("*", middle, 1)))
    return found


def _sent_refs(git: Git, push: Push) -> list[_Ref]:
    """The refs a push sends, each with its destination; a refspec that only deletes sends none"""
    refs: list[_Ref] = []
    if push.mirror:
        refs.extend(_Ref(ref, ref) for ref in _refs(git, "refs/") if not ref.startswith("refs/remotes/"))
    if push.all_branches:
        refs.extend(_Ref(ref, ref) for ref in _refs(git, "refs/heads/"))
    if push.tags:
        refs.extend(_Ref(ref, ref) for ref in _refs(git, "refs/tags/"))
    for spec in push.refspecs:
        given = spec.removeprefix("+")
        source, _, destination = given.partition(":")
        if not source:  # `:dst` deletes dst and sends no commit
            continue
        if source == "HEAD" and not destination:
            destination = _current_branch(git)
        refs.extend(_expanded(git, source, destination or source))
    if not (push.refspecs or push.mirror or push.all_branches or push.tags):
        branch = _current_branch(git)
        merge = _config(git, f"branch.{branch}.merge")
        refs.append(_Ref(f"refs/heads/{branch}", merge or branch))
    return refs


@dataclass(frozen=True, slots=True)
class _Commit:
    sha: str
    message: str
    paths: tuple[str, ...]
    added: dict[str, list[tuple[int, str]]]  # each file's added lines, with their line numbers


def _paths(raw: str) -> list[str | None]:
    """`--name-status -z`'s entries as each one's new path, None for a deletion, in order"""
    tokens = raw.split("\0")
    out: list[str | None] = []
    at = 0
    while at < len(tokens) and tokens[at]:
        status = tokens[at]
        if status[0] in "RC":
            out.append(tokens[at + 2])
            at += 3
        else:
            out.append(None if status[0] == "D" else tokens[at + 1])
            at += 2
    return out


def _added(diff: str, paths: Sequence[str | None]) -> dict[str, list[tuple[int, str]]]:
    """The lines a patch adds, by file: the k-th `diff --git` is the k-th entry of paths"""
    added: dict[str, list[tuple[int, str]]] = {}
    index = -1
    old_left = new_left = 0
    line_no = 0
    for line in diff.split("\n"):
        if old_left > 0 or new_left > 0:
            if line.startswith("+"):
                path = paths[index]
                if path is not None:
                    added.setdefault(path, []).append((line_no, line[1:]))
                line_no += 1
                new_left -= 1
            elif line.startswith("-"):
                old_left -= 1
            elif line.startswith("\\"):
                pass
            else:  # a context line
                line_no += 1
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("diff --git "):
            index += 1
            if index >= len(paths):
                raise ReleaseError("git's patch names more files than its name-status; the push can't be read")
            continue
        hunk = _HUNK.match(line)
        if hunk is not None:
            old_left = int(hunk.group(1)) if hunk.group(1) is not None else 1
            line_no = int(hunk.group(2))
            new_left = int(hunk.group(3)) if hunk.group(3) is not None else 1
    return added


def _commit(git: Git, sha: str) -> _Commit:
    """A commit read by itself against its first parent"""
    named = git.run_bytes("show", *_DIFF, "-z", "--name-status", "--format=%B%x00", sha).decode(
        "utf-8", errors="replace"
    )
    message, _, rest = named.partition("\0")
    paths = _paths(rest.lstrip("\0\n"))
    diff = git.run_bytes("show", *_DIFF, "-p", "--format=", sha).decode("utf-8", errors="replace")
    kept = tuple(path for path in paths if path is not None)
    added = {path: lines for path, lines in _added(diff, paths).items() if not any("\0" in t for _, t in lines)}
    return _Commit(sha, message.rstrip("\n"), kept, added)


def outgoing(git: Git, push: Push) -> Outgoing:
    """What push sends from git's checkout, as the texts the leak check reads"""
    remote = _remote(git, push)
    refs = _sent_refs(git, push)
    texts: list[Text] = []
    lines: dict[str, tuple[int, ...]] = {}
    sources = list(dict.fromkeys(ref.source for ref in refs))
    for source in sources:
        if not git.ok("rev-parse", "--verify", "--quiet", f"{source}^{{commit}}"):
            raise ReleaseError(
                f"the push's source `{source}` {MISSING_REF}: it names no commit, so the leak check"
                " can't read what the push sends"
            )
    shas = (
        git.run("rev-list", "--reverse", "--topo-order", *sources, "--not", f"--remotes={remote}").split()
        if sources
        else []
    )
    for sha in shas:
        commit = _commit(git, sha)
        short = sha[:SHORT]
        texts.append(Text(f"commit {short}'s message", commit.message))
        texts.extend(Text(f"commit {short}'s path", path) for path in commit.paths)
        for path, added in commit.added.items():
            where = f"commit {short}, {path}"
            texts.append(Text(where, "\n".join(text for _, text in added), path))
            lines[where] = tuple(number for number, _ in added)
    for destination in dict.fromkeys(ref.destination for ref in refs):
        texts.append(Text("the destination ref", destination))
    return Outgoing(_remote_repo(git, remote), tuple(texts), lines)
