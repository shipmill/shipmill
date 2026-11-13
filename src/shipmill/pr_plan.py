"""Spec 055: the plan is written when the pull request opens (S-055-17).

`shipmill gh pr create` as the App reads the body it would send with `pr_gate.py`'s
`plan_problems` and the ids its `direction_ids` reads from the default branch, so a body the
merge gate would refuse for its plan never opens. The wheel's `pr_gate.py` is the one reading:
nothing here parses a plan or the direction itself.
"""

import functools
import importlib.util
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from shipmill.app_gh import created_body, other_body
from shipmill.bundle import skills_dir
from shipmill.classify import DEFAULT_REF
from shipmill.errors import ReleaseError
from shipmill.gitrepo import REMOTE, Git

_GATE = ("github-pr-triage", "scripts", "pr_gate.py")
_NAME = "shipmill_pr_gate"
_SYMREF = re.compile(r"^ref: refs/heads/(\S+)\tHEAD$", re.MULTILINE)  # `git ls-remote --symref origin HEAD`


@functools.cache
def _gate() -> ModuleType:
    """The wheel's pr_gate.py, loaded once"""
    script = skills_dir().joinpath(*_GATE)
    found = importlib.util.spec_from_file_location(_NAME, script)
    if found is None or found.loader is None:
        raise ReleaseError(f"can't load {script}")
    module = importlib.util.module_from_spec(found)
    sys.modules[_NAME] = module  # its dataclasses look their module up by name
    found.loader.exec_module(module)
    return module


def _commit(git: Git, ref: str) -> bool:
    return git.ok("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")


def default_ref(top: Path, direction: str) -> str:
    """The ref the default branch is read at: origin/HEAD when set; else origin/<branch>, the
    branch `git ls-remote --symref origin HEAD` names, fetched when the checkout lacks it (a
    checkout made by `git fetch` or actions/checkout sets no origin/HEAD). No gh call, no token;
    git never prompts for credentials. Raises naming what failed when the branch can't be had"""
    git = Git(top)
    git.env = {"GIT_TERMINAL_PROMPT": "0"}
    if _commit(git, DEFAULT_REF):
        return DEFAULT_REF
    why = f"so whether the default branch holds {direction}, which the body's plan is checked by (spec 055), is unknown"
    try:
        listed = git.run("ls-remote", "--symref", REMOTE, "HEAD")
    except ReleaseError as exc:
        raise ReleaseError(
            f"gh pr create is refused: {DEFAULT_REF} is not set in {top}, and origin's default branch can't be read: "
            f"{exc}; {why}"
        ) from None
    named = _SYMREF.search(listed)
    if named is None:
        raise ReleaseError(
            f"gh pr create is refused: {DEFAULT_REF} is not set in {top}, and `git ls-remote --symref origin HEAD` "
            f"names no default branch; {why}"
        )
    branch = named.group(1)
    ref = f"{REMOTE}/{branch}"
    if not _commit(git, ref):
        try:
            git.run("fetch", "--quiet", REMOTE, f"+refs/heads/{branch}:refs/remotes/{ref}")
        except ReleaseError as exc:
            raise ReleaseError(f"gh pr create is refused: {ref} can't be fetched: {exc}; {why}") from None
    return ref


def hold_plan(top: Path, gh_args: Sequence[str], repo: str) -> None:
    """S-055-17: exit 2, before gh runs, when `gh pr create`'s args (once `marked_args` made
    them, so the body is the one --body gh gets) send a body whose plan `plan_problems` doesn't
    accept, by the ids of docs/product.md on the default branch (`default_ref`), printing each
    problem. Not checked: a body with a `Spec for #N` line of repo, which needs no plan (spec
    053), and a repo whose default branch has no docs/product.md, as pr_gate.py doesn't check
    it. Refused besides: a default branch that can't be resolved or fetched, whose direction
    can't be read, and a flag by which gh may send another body than the one checked"""
    gate = _gate()
    direction: str = gate.DIRECTION
    body = created_body(gh_args)
    if any(owner is None or owner.lower() == repo.lower() for owner, _ in gate.spec_refs(body)):
        return
    ref = default_ref(top, direction)
    git = Git(top)
    if git.show(ref, direction) is None:
        return
    flag = other_body(gh_args)
    if flag is not None:
        raise ReleaseError(
            f"gh pr create {flag} is refused: gh may send a body from it rather than the one whose plan shipmill gh "
            "checks (spec 055); write the body, with its `## Plan`, to a file and pass --body-file"
        )
    try:
        ids: frozenset[str] = gate.direction_ids(lambda path: git.show(ref, path))
    except gate.GateError as exc:
        raise ReleaseError(f"gh pr create is refused: the plan can't be checked: {exc}") from None
    problems: list[str] = gate.plan_problems(body, ids)
    if problems:
        listed = "\n".join(f"  {problem}" for problem in problems)
        raise ReleaseError(
            "gh pr create is refused: the body's plan doesn't hold, and the merge gate would refuse it (spec 055); "
            f"fix the body's `## Plan` and open it again:\n{listed}"
        )
