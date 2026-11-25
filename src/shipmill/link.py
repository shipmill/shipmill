"""Spec 041 (#1645): `shipmill link` and `shipmill unlink`, the one command that records a hold
between issues and pull requests, and removes it. It runs github-issue-triage's chains.py link or
unlink, the one implementation of a link's two forms (GitHub's native relation and a strict
Depends on line), its cycle refusal, and the product's routing (spec 038), from the checkout, so a
link written here and one a skill script writes are the same link. A reference is `#N`, the
checkout's own repo, or `owner/repo#N`."""

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shipmill.bundle import skills_dir
from shipmill.errors import ReleaseError

OWN = re.compile(r"#(?P<number>[1-9]\d*)")
FULL = re.compile(r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<number>[1-9]\d*)")

# Runs chains.py from the checkout, whose config decides whom its writes post as (D-14)
ChainsRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class LinkRef:
    """An issue or pull request as owner/name#N"""

    repo: str
    number: int

    @classmethod
    def parse(cls, text: str, origin: str | None) -> LinkRef:
        """`#N` of the checkout's origin, or `owner/repo#N`; anything else is refused, naming it"""
        given = text.strip()
        if (own := OWN.fullmatch(given)) is not None:
            if origin is None:
                raise ReleaseError(f"{text!r} names no repo and the checkout has no GitHub origin: write owner/repo#N")
            return cls(origin, int(own["number"]))
        if (full := FULL.fullmatch(given)) is not None:
            return cls(full["repo"], int(full["number"]))
        raise ReleaseError(f"{text!r} is no reference: write #N or owner/repo#N")

    def __str__(self) -> str:
        return f"{self.repo}#{self.number}"


@dataclass(frozen=True, slots=True)
class LinkRequest:
    """One link or unlink: the item that waits (or the parent), the item it waits on (or the
    child), and how"""

    remove: bool
    item: LinkRef
    other: LinkRef
    child: bool
    product: bool = False
    no_text: bool = False

    def command(self, python: str, script: Path) -> list[str]:
        how = "--child" if self.child else "--blocked-by"
        found = [python, str(script), "unlink" if self.remove else "link", str(self.item), how, str(self.other)]
        if self.product:
            found.append("--product")
        if self.no_text:
            found.append("--no-text")
        return found


def run_chains(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def chains_script() -> Path:
    return skills_dir() / "github-issue-triage" / "scripts" / "chains.py"


def run_link(request: LinkRequest, root: Path, runner: ChainsRunner = run_chains) -> int:
    """Runs chains.py's link or unlink from the checkout and passes its output and exit code
    on: 0 when the link is in place (or gone), 2 naming what was refused"""
    if request.remove and (request.product or request.no_text):
        raise ReleaseError("unlink takes neither --product nor --no-text")
    proc = runner(request.command(sys.executable, chains_script()), root)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode
