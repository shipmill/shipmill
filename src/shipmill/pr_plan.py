"""Spec 055: the plan is written when the pull request opens (S-055-17).

`shipmill gh pr create` as the App reads the body it would send with `pr_gate.py`'s
`plan_problems` and the ids its `direction_ids` reads from the default branch, so a body the
merge gate would refuse for its plan never opens. The wheel's `pr_gate.py` is the one reading:
nothing here parses a plan or the direction itself.
"""

import functools
import importlib.util
import sys
from collections.abc import Sequence
from types import ModuleType

from shipmill.app_gh import created_body, other_body
from shipmill.bundle import skills_dir
from shipmill.classify import DEFAULT_REF
from shipmill.errors import ReleaseError
from shipmill.gitrepo import Git

_GATE = ("github-pr-triage", "scripts", "pr_gate.py")
_NAME = "shipmill_pr_gate"


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


def hold_plan(git: Git, gh_args: Sequence[str], repo: str) -> None:
    """S-055-17: exit 2, before gh runs, when `gh pr create`'s args (once `marked_args` made
    them, so the body is the one --body gh gets) send a body whose plan `plan_problems` doesn't
    accept, by the ids of docs/product.md on the default branch (origin/HEAD), printing each
    problem. Not checked: a body with a `Spec for #N` line of repo, which needs no plan (spec
    053), and a repo whose default branch has no docs/product.md, as pr_gate.py doesn't check
    it. Refused besides: an unset origin/HEAD, whose direction can't be read, and a flag by
    which gh may send another body than the one checked"""
    gate = _gate()
    direction: str = gate.DIRECTION
    body = created_body(gh_args)
    if any(owner is None or owner.lower() == repo.lower() for owner, _ in gate.spec_refs(body)):
        return
    if not git.ok("rev-parse", "--verify", "--quiet", f"{DEFAULT_REF}^{{commit}}"):
        raise ReleaseError(
            f"gh pr create is refused: {DEFAULT_REF} is not set in {git.root}, so whether the default branch holds "
            f"{direction}, by which the body's plan is checked (spec 055), can't be read; run "
            f"`git -C {git.root} remote set-head origin --auto`"
        )
    if git.show(DEFAULT_REF, direction) is None:
        return
    flag = other_body(gh_args)
    if flag is not None:
        raise ReleaseError(
            f"gh pr create {flag} is refused: gh may send a body from it rather than the one whose plan shipmill gh "
            "checks (spec 055); write the body, with its `## Plan`, to a file and pass --body-file"
        )
    try:
        ids: frozenset[str] = gate.direction_ids(lambda path: git.show(DEFAULT_REF, path))
    except gate.GateError as exc:
        raise ReleaseError(f"gh pr create is refused: the plan can't be checked: {exc}") from None
    problems: list[str] = gate.plan_problems(body, ids)
    if problems:
        listed = "\n".join(f"  {problem}" for problem in problems)
        raise ReleaseError(
            "gh pr create is refused: the body's plan doesn't hold, and the merge gate would refuse it (spec 055); "
            f"fix the body's `## Plan` and open it again:\n{listed}"
        )
