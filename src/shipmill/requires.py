"""The config's top-level `requires` (spec 031): the oldest shipmill a .github/shipmill.toml is
written for, a lower bound ">=X.Y" or ">=X.Y.Z". A CLI that doesn't meet it stops with the
bound, its own version, and how to update, before any other key of the config is checked, so
an old CLI on a newer config says "update" instead of "unknown keys".

skills/github-ship-watch/scripts/watch_state.py holds the same check for the skills' scripts,
which can't import shipmill; its text must stay this module's (a test compares them)."""

import importlib.metadata
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from shipmill.errors import ReleaseError
from shipmill.version import Version

FILE = ".github/shipmill.toml"  # config.CONFIG_PATH, which config.py builds from this
KEY = "requires"
_BOUND = re.compile(r">=(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True, slots=True)
class Requires:
    """A lower bound on shipmill's version: X.Y, or X.Y.Z"""

    major: int
    minor: int
    patch: int | None = None

    @classmethod
    def parse(cls, value: object) -> Requires:
        found = _BOUND.fullmatch(value) if isinstance(value, str) else None
        if found is None:
            raise ReleaseError(invalid(value))
        return cls(int(found[1]), int(found[2]), None if found[3] is None else int(found[3]))

    @classmethod
    def at(cls, version: Version) -> Requires:
        """The bound a version needs: >=X.Y.Z"""
        return cls(version.major, version.minor, version.patch)

    @classmethod
    def series(cls, version: Version) -> Requires:
        """The bound of a version's series: >=X.Y"""
        return cls(version.major, version.minor)

    def __str__(self) -> str:
        return f">={self.major}.{self.minor}" + ("" if self.patch is None else f".{self.patch}")

    @property
    def floor(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch or 0)

    def met(self, version: Version) -> bool:
        """Whether the version meets the bound; a pre-release or a dev build meets the bound of
        the release it leads to, since it carries that release's keys"""
        return (version.major, version.minor, version.patch) >= self.floor


def invalid(value: object) -> str:
    return f'{FILE}: {KEY} must be ">=X.Y" or ">=X.Y.Z", the oldest shipmill it needs; got {value!r}'


def unmet(bound: str, version: str) -> str:
    """What a CLI or a script that doesn't meet the config's bound says, then exits 2"""
    return (
        f"{FILE} requires shipmill {bound}; this is {version}\n"
        "update the plugin: claude plugin marketplace update shipmill"
        " && claude plugin update shipmill@shipmill --scope <scope>\n"
        "or the CLI: uv tool upgrade shipmill"
    )


def running() -> Version:
    """The version of the shipmill that runs"""
    return Version.parse(importlib.metadata.version("shipmill"))


def check(raw: Mapping[str, Any], version: Version | None = None) -> Requires | None:
    """The config's bound, None without one; refuse a malformed one, and one the version (by
    default the running CLI's) doesn't meet"""
    if KEY not in raw:
        return None
    bound = Requires.parse(raw[KEY])
    have = running() if version is None else version
    if not bound.met(have):
        raise ReleaseError(unmet(str(bound), str(have)))
    return bound
