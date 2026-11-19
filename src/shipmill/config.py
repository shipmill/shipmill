"""The config file, .github/shipmill.toml, and the strict reader every section parser uses:
one file, one section per layer (D-4)"""

import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from shipmill import requires
from shipmill.errors import ReleaseError

CONFIG_PATH = Path(requires.FILE)


def config_path(root: Path) -> Path:
    """The file shipmill reads its settings from: .github/shipmill.toml"""
    path = root / CONFIG_PATH
    if not path.is_file():
        raise ReleaseError(f"no release policy at {path}")
    return path


def read(path: Path) -> Mapping[str, Any]:
    """The file's TOML; a syntax error names the file"""
    return loads(path.read_text(encoding="utf-8"), str(path))


def read_unchecked(path: Path) -> Mapping[str, Any]:
    """The file's TOML with no requires check, for a reader of one table that a newer config
    must not stop (S-038-4: the credential helpers read [product] alone); a syntax error still
    names the file"""
    return loads_unchecked(path.read_text(encoding="utf-8"), str(path))


def loads_unchecked(text: str, where: str) -> Mapping[str, Any]:
    """text's TOML with no requires check, as `read_unchecked` reads a file: for another
    repo's config, read for one table (spec 038's doctor); a syntax error names where"""
    return _parse(text, where)


def loads(text: str, where: str) -> Mapping[str, Any]:
    """text's TOML; a syntax error names where it was read from. Its requires is checked
    first (spec 031): a CLI too old for the config says so before any reader of a section
    refuses a key it doesn't know"""
    raw = _parse(text, where)
    requires.check(raw)
    return raw


def policy_branch(root: Path) -> str | None:
    """The top-level `branch` the checkout's config sets, the branch releases land on, which
    the landing checks compare against (#694); None without a config or without the key. Read
    alone, with no requires check, as a reader of one key a newer config must not stop"""
    path = root / CONFIG_PATH
    if not path.is_file():
        return None
    return branch_in(path.read_text(encoding="utf-8"), str(path))


def branch_in(text: str, where: str) -> str | None:
    """The top-level `branch` a config's text sets, None without the key; where names the
    file, or the ref it was read at, in a refusal"""
    value = _parse(text, where).get("branch")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ReleaseError(f"{where}: branch must be a non-empty string, got {value!r}")
    return branch_name(value, where)


_BRANCH_FORBIDDEN = frozenset("~^:?*[\\ ")


def branch_name(value: str, where: str) -> str:
    """value when git's branch-name rules (`git check-ref-format --branch`) accept it, else a
    ReleaseError naming the key `branch` and where it was read: a configured branch reaches git,
    and one starting with - would read as an option (#889). Checked here, with no git call"""
    if why := _branch_refusal(value):
        raise ReleaseError(f"{where}: branch must be a git branch name, got {value!r}: {why}")
    return value


def _branch_refusal(name: str) -> str | None:
    if not name:
        return "it is empty"
    if name.startswith("-"):
        return "it starts with -"
    if name in {"@", "HEAD"}:
        return f"it is {name}"
    if bad := sorted({c for c in name if c in _BRANCH_FORBIDDEN or ord(c) < 32 or ord(c) == 127}):
        return f"it holds {''.join(bad)!r}"
    for part in ("..", "@{", "//"):
        if part in name:
            return f"it holds {part}"
    if name.startswith("/") or name.endswith("/"):
        return "it starts or ends with /"
    if name.endswith("."):
        return "it ends with ."
    for component in name.split("/"):
        if component.startswith("."):
            return "a component starts with ."
        if component.endswith(".lock"):
            return "a component ends with .lock"
    return None


def _parse(text: str, where: str) -> Mapping[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseError(f"{where}: {exc}") from None


class Table:
    """A TOML table read strictly: unknown keys and wrong types fail with the key's path"""

    def __init__(self, raw: Mapping[str, Any], where: str) -> None:
        self.raw = raw
        self.where = where

    def keys(self) -> list[str]:
        return list(self.raw)

    def allow(self, *keys: str) -> None:
        """Refuse keys outside these; a StrEnum's members name their plain values (#59)"""
        names = sorted(str(k) for k in keys)
        if unknown := sorted(set(self.raw) - set(names)):
            raise ReleaseError(f"{self.where}: unknown keys {unknown}; allowed: {names}")

    def _get(self, key: str, default: object, kind: type | tuple[type, ...], label: str) -> Any:
        if key not in self.raw:
            if default is _REQUIRED:
                raise ReleaseError(f"{self.where}: {key} is required")
            return default
        value = self.raw[key]
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise ReleaseError(f"{self.where}: {key} must be {label}, got {value!r}")
        return value

    def string(self, key: str, default: object = None) -> str:
        value: str = self._get(key, _REQUIRED if default is None else default, str, "a string")
        return value

    def boolean(self, key: str, default: bool) -> bool:
        value: bool = self._get(key, default, bool, "true or false")
        return value

    def integer(self, key: str, default: int | None, low: int, high: int | None) -> int | None:
        """high None: no upper bound"""
        value: int | None = self._get(key, default, int, "an integer")
        if value is not None and high is None and value < low:
            raise ReleaseError(f"{self.where}: {key} must be {low} or more, got {value}")
        if value is not None and high is not None and not low <= value <= high:
            raise ReleaseError(f"{self.where}: {key} must be in {low}..{high}, got {value}")
        return value

    def number(self, key: str, default: float) -> float:
        """A finite integer or float, never true or false, nan, or inf"""
        value = self._get(key, default, (int, float), "a number")
        if isinstance(value, bool) or not math.isfinite(value):
            raise ReleaseError(f"{self.where}: {key} must be a number, got {value!r}")
        return float(value)

    def strings(self, key: str, default: tuple[str, ...] | None = None) -> tuple[str, ...]:
        value = self._get(key, _REQUIRED if default is None else default, (list, tuple), "a list of strings")
        if not all(isinstance(v, str) and v for v in value):
            raise ReleaseError(f"{self.where}: {key} must be a list of non-empty strings")
        return tuple(value)

    def enum[E: StrEnum](self, key: str, kind: type[E], default: E | None = None) -> E:
        """default None: the key is required"""
        value = self.string(key) if default is None else self.string(key, default=default.value)
        try:
            return kind(value)
        except ValueError:
            raise ReleaseError(f"{self.where}: {key} must be one of {[e.value for e in kind]}, got {value!r}") from None

    def enums[E: StrEnum](self, key: str, kind: type[E], default: tuple[E, ...]) -> tuple[E, ...]:
        values = self.strings(key, default=tuple(default))
        try:
            return tuple(kind(v) for v in values)
        except ValueError:
            raise ReleaseError(f"{self.where}: {key} holds values outside {[e.value for e in kind]}") from None

    def table(self, key: str, optional: bool = False) -> Table:
        value = self._get(key, {} if optional else _REQUIRED, dict, "a table")
        return Table(value, f"{self.where} [{key}]")

    def tables(self, key: str) -> list[Table]:
        value = self._get(key, [], list, "an array of tables")
        if not all(isinstance(v, dict) for v in value):
            raise ReleaseError(f"{self.where}: {key} must be an array of tables, [[{key}]]")
        return [Table(v, f"{self.where} [[{key}]][{i}]") for i, v in enumerate(value)]


_REQUIRED = object()


class Series(StrEnum):
    """A series the drift report reads (spec 078)"""

    CI_PASS_RATE = "ci_pass_rate"
    FLAKY_RERUNS = "flaky_reruns"
    REVIEW_TIME = "review_time"
    LEAD_TIME = "lead_time"


# [trends]'s defaults (spec 078)
BUCKET_DAYS = 7
BASELINE = 8
LOG_SIGMA = 1.0
REPORT_SIGMA = 2.0


@dataclass(frozen=True, slots=True)
class TrendsConfig:
    """The [trends] section: the series trends.py compares, the bucket and baseline sizes, and
    the bands in sample standard deviations (spec 078). Off without the section"""

    series: tuple[Series, ...]
    bucket_days: int = BUCKET_DAYS
    baseline: int = BASELINE  # the buckets before the newest one
    log_sigma: float = LOG_SIGMA
    report_sigma: float = REPORT_SIGMA

    @classmethod
    def parse(cls, t: Table) -> TrendsConfig:
        t.allow("series", "bucket_days", "baseline", "log_sigma", "report_sigma")
        names = t.strings("series")
        allowed = [s.value for s in Series]
        if not names:
            raise ReleaseError(f"{t.where}: series must name at least one of {allowed}")
        if unknown := sorted(set(names) - set(allowed)):
            raise ReleaseError(f"{t.where}: series holds {unknown}, outside {allowed}")
        if len(set(names)) != len(names):
            raise ReleaseError(f"{t.where}: series names a series twice")
        bucket_days = t.integer("bucket_days", default=BUCKET_DAYS, low=1, high=None)
        baseline = t.integer("baseline", default=BASELINE, low=4, high=None)
        assert bucket_days is not None and baseline is not None  # defaults were given
        log_sigma = t.number("log_sigma", default=LOG_SIGMA)
        if log_sigma <= 0:
            raise ReleaseError(f"{t.where}: log_sigma must be above 0, got {log_sigma}")
        report_sigma = t.number("report_sigma", default=REPORT_SIGMA)
        if report_sigma < log_sigma:
            raise ReleaseError(f"{t.where}: report_sigma must be at least log_sigma ({log_sigma}), got {report_sigma}")
        return cls(tuple(Series(n) for n in names), bucket_days, baseline, log_sigma, report_sigma)

    def __str__(self) -> str:
        days = "1 day" if self.bucket_days == 1 else f"{self.bucket_days} days"
        return (
            f"series {', '.join(self.series)}; buckets of {days} against the {self.baseline} before;"
            f" log at {self.log_sigma:g}σ, report at {self.report_sigma:g}σ"
        )
