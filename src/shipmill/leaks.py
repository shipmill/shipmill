"""Spec 081: the leak check, which refuses text that would leave the machine holding a private
term or a secret, before it is sent.

The terms and the secret files live in one file on the machine, `~/.config/shipmill/private.toml`
(D-94), never in a repo; no environment variable, flag, config key, or marker in the text names
another file or turns a detector off. Three detectors refuse:

- `term`: a term of the private file, in a write to a public repo
- `secret-value`: the exact value of a secret from the checkout's untracked `.env` files or the
  private file's `secret_files`, in any repo
- `secret-format`: a known token format, in any repo

A finding names a term, but a secret only by its variable and file, or by its format and its
first 4 characters: no line this module writes holds a secret's value (S-081-14). The callers
(`shipmill gh`, and later `leaks push`, `leaks check`, `spec open`, `review record`) gather the
texts and the destination and print `refusal`'s lines.
"""

import os
import pwd
import re
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from shipmill.errors import ReleaseError

PRIVATE_FILE = Path(".config") / "shipmill" / "private.toml"
TERM_MIN = 3  # a term's least length, trimmed
SECRET_MIN = 8  # a secret value's least length, and a URL password's
SHOWN_PREFIX = 4  # a format's characters a finding may name
LISTED = 10  # the findings a refusal names before `and N more`
_KEYS = frozenset({"terms", "secret_files"})
# a dotenv name holding one of these, in any case, gives a secret
_SECRET_WORDS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "PWD",
    "CREDENTIAL",
    "AUTH",
    "COOKIE",
    "SESSION",
    "DSN",
)
_DOTENV_LINE = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(.*)")
_URL_PASSWORD = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]*:([^\s/@]+)@")
_TEMPLATED = frozenset("${<*")  # a password holding one is a placeholder, such as ${TOKEN}
_EDGE = r"[^\W_]"  # a letter or a digit, in any script


def account_home() -> Path:
    """The home folder of the account this process runs as, from the password database: $HOME
    names no other private file, since a session can set it (D-94)"""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


class Detector(StrEnum):
    TERM = "term"
    SECRET_VALUE = "secret-value"
    SECRET_FORMAT = "secret-format"


@dataclass(frozen=True, slots=True)
class Term:
    """A private term: its text as listed, and the pattern that finds it case-insensitively at
    word boundaries, any run of whitespace matching a space in it"""

    text: str
    pattern: re.Pattern[str]

    @classmethod
    def of(cls, text: str) -> Term:
        words = text.split()
        body = r"\s+".join(re.escape(word) for word in words)
        return cls(text, re.compile(rf"(?<!{_EDGE}){body}(?!{_EDGE})", re.IGNORECASE))


@dataclass(frozen=True, slots=True)
class Private:
    """The private file as loaded: where it is, whether it exists, its terms, and the secret
    files it names (`~` expanded), each kept with its path as written for the findings"""

    path: Path
    present: bool
    terms: tuple[Term, ...]
    secret_files: tuple[tuple[str, Path], ...]

    @classmethod
    def load(cls, home: Path) -> Private:
        """The private file under home; one with no file holds nothing. An unknown key, a wrong
        type, a term under 3 characters, or a file that isn't TOML exits 2 naming the key and
        the file (Q-1)"""
        path = home / PRIVATE_FILE
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return cls(path, False, (), ())
        except OSError as exc:
            raise ReleaseError(
                f"{path} can't be read ({exc.strerror}); the leak check reads it before any write"
            ) from None
        try:
            data = tomllib.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ReleaseError(
                f"{path} isn't valid TOML ({exc}); fix it, the leak check refuses every write until then"
            ) from None
        unknown = sorted(set(data) - _KEYS)
        if unknown:
            raise ReleaseError(
                f"{path} has the unknown key {unknown[0]!r}; it takes only terms and secret_files (spec 081)"
            )
        listed = _strings(data, "terms", path)
        short = next((text for text in listed if len(text.strip()) < TERM_MIN), None)
        if short is not None:
            raise ReleaseError(
                f"{path}'s terms holds a term under {TERM_MIN} characters ({len(short.strip())}); "
                "list a longer one, since a short one matches common words"
            )
        terms = tuple(Term.of(text.strip()) for text in listed)
        files = tuple((given, Path(given).expanduser()) for given in _strings(data, "secret_files", path))
        return cls(path, True, terms, files)


def _strings(data: dict[str, object], key: str, path: Path) -> list[str]:
    """data's key as a list of strings, [] without it; any other type exits 2 naming the key"""
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ReleaseError(f"{path}'s {key} must be a list of strings")
    return [item for item in value if isinstance(item, str)]


@dataclass(frozen=True, slots=True)
class Secret:
    """A secret value from a dotenv file: its variable, the file as a finding names it, and the
    value, which no repr, message, or finding holds"""

    name: str
    source: str
    value: str = field(repr=False)


def _secret_name(name: str) -> bool:
    upper = name.upper()
    return any(word in upper for word in _SECRET_WORDS)


def _unquoted(raw: str) -> str:
    """A dotenv value without its quotes, or, unquoted, without a trailing ` #` comment"""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value.split(" #", 1)[0].rstrip()


def dotenv_secrets(text: str, source: str) -> list[Secret]:
    """The secrets a dotenv text gives: a `NAME=value` line (an optional `export`, quotes
    stripped) whose value has 8 characters or more and whose name holds a secret word, and the
    password of a URL value with `user:password@` of 8 characters or more, whatever the name.
    A line that isn't `NAME=value` gives none"""
    found: list[Secret] = []
    for line in text.splitlines():
        stripped = line.strip()
        matched = _DOTENV_LINE.fullmatch(stripped) if stripped and not stripped.startswith("#") else None
        if matched is None:
            continue
        name, value = matched.group(1), _unquoted(matched.group(2))
        if len(value) >= SECRET_MIN and _secret_name(name):
            found.append(Secret(name, source, value))
        url = _URL_PASSWORD.search(value)
        if url is not None and len(url.group(1)) >= SECRET_MIN:
            found.append(Secret(name, source, url.group(1)))
    return found


def _read_dotenv(path: Path, shown: str, why: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) else "it isn't UTF-8"
        raise ReleaseError(f"{shown} can't be read ({reason}); {why}") from None


def checkout_dotenvs(top: Path, tracked: Iterable[str]) -> list[str]:
    """The names of the dotenv files in the checkout's root, `.env` and `.env.*`, that git
    doesn't track (tracked: the names among them git does), sorted"""
    kept = set(tracked)
    names = [
        entry.name
        for entry in top.iterdir()
        if (entry.name == ".env" or entry.name.startswith(".env.")) and not entry.is_dir()
    ]
    return sorted(name for name in names if name not in kept)


def secrets(top: Path | None, tracked: Iterable[str], private: Private) -> tuple[Secret, ...]:
    """The secrets of the checkout at top (its untracked `.env` and `.env.*`; none without a
    checkout) and of the private file's secret_files. A file that can't be read exits 2 naming
    it, and a secret_files path the key too"""
    found: list[Secret] = []
    if top is not None:
        for name in checkout_dotenvs(top, tracked):
            text = _read_dotenv(top / name, str(top / name), "the leak check reads the checkout's .env files")
            found.extend(dotenv_secrets(text, name))
    for given, path in private.secret_files:
        why = f"fix secret_files in {private.path}; the leak check refuses every write until then"
        found.extend(dotenv_secrets(_read_dotenv(path, f"secret_files' {given}", why), given))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class _Format:
    name: str  # as a finding names it, such as `a GitHub token`
    pattern: re.Pattern[str]


_NOT_TOKEN = r"(?<![A-Za-z0-9_])"
_FORMATS = (
    _Format(
        "a GitHub token", re.compile(rf"{_NOT_TOKEN}(?:gh[pousr]_[A-Za-z0-9]{{36,}}|github_pat_[A-Za-z0-9_]{{22,}})")
    ),
    _Format("an Anthropic key", re.compile(rf"{_NOT_TOKEN}sk-ant-[A-Za-z0-9_-]{{20,}}")),
    _Format("an AWS access key id", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    _Format("a Slack token", re.compile(rf"{_NOT_TOKEN}xox[a-z]-[A-Za-z0-9-]{{10,}}")),
    # a block: its BEGIN line, any headers, then key material, not a mention of the header alone
    _Format(
        "a PEM private key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----\s+(?:[A-Za-z-]+:[^\n]*\n\s*)*[A-Za-z0-9+/=]{20,}"),
    ),
)
URL_PASSWORD = "a URL with a password"


@dataclass(frozen=True, slots=True)
class Text:
    """A text a write sends, with how a finding names where it is: `the body`, `the title`,
    `the field note`, `the --input file x.json`"""

    where: str
    text: str


@dataclass(frozen=True, slots=True)
class Finding:
    """What a detector found: the detector, where, the line (None in a text of one line), and
    what, as the refusal says it after `holds` or `names`; never a secret's value"""

    detector: Detector
    where: str
    line: int | None
    what: str

    def said(self) -> str:
        """As a refusal lists it: `term: the body, line 4, names the private term "Acme Rocket"`"""
        at = self.where if self.line is None else f"{self.where}, line {self.line},"
        verb = "names" if self.detector is Detector.TERM else "holds"
        return f"{self.detector.value}: {at} {verb} {self.what}"


def _line(text: str, at: int) -> int | None:
    return text.count("\n", 0, at) + 1 if "\n" in text.rstrip("\n") else None


def _formats(text: str) -> list[tuple[int, str]]:
    """The known formats in text: where each starts, and how a finding names it, with at most
    its first 4 characters"""
    found = [
        (m.start(), f"{f.name} ({m.group(0)[:SHOWN_PREFIX]}…)") for f in _FORMATS for m in f.pattern.finditer(text)
    ]
    for m in _URL_PASSWORD.finditer(text):
        password = m.group(1)
        if len(password) >= SECRET_MIN and not _TEMPLATED & set(password):
            found.append((m.start(), f"{URL_PASSWORD} ({m.group(0)[:SHOWN_PREFIX]}…)"))
    return sorted(found)


def scan(texts: Sequence[Text], terms: Sequence[Term], known: Sequence[Secret]) -> list[Finding]:
    """Every finding in texts, in order of the texts and then of where each starts: terms (pass
    none for a repo that isn't public), the exact values of known, and the known formats"""
    findings: list[Finding] = []
    for item in texts:
        text = item.text
        found: list[tuple[int, Finding]] = []
        for term in terms:
            for m in term.pattern.finditer(text):
                what = f'the private term "{term.text}"'
                found.append((m.start(), Finding(Detector.TERM, item.where, _line(text, m.start()), what)))
        for secret in known:
            at = text.find(secret.value)
            if at >= 0:
                what = f"the value of {secret.name} from {secret.source}"
                found.append((at, Finding(Detector.SECRET_VALUE, item.where, _line(text, at), what)))
        for at, what in _formats(text):
            found.append((at, Finding(Detector.SECRET_FORMAT, item.where, _line(text, at), what)))
        findings.extend(finding for _, finding in sorted(found, key=lambda pair: pair[0]))
    return findings


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class Destination:
    """Where a write goes: its repo (None for one that goes to no repo, such as a gist, or to a
    repo off github.com) and its visibility as read (None when it wasn't read or the read
    failed). Every one but a repo read as private or internal is checked as public"""

    repo: str | None
    visibility: Visibility | None

    @property
    def public(self) -> bool:
        return self.visibility not in (Visibility.PRIVATE, Visibility.INTERNAL)

    def said(self) -> str:
        if self.repo is None:
            return "it goes to no repo on github.com, so it is checked as public"
        if self.visibility is None:
            return f"{self.repo}, checked as public"
        return f"{self.repo} is {self.visibility.value}"


FIX = (
    "Rewrite the text in general terms: describe the case by its traits, never by the project,\n"
    "customer, or host it came from, and take the secret out. A person can post it with plain gh"
)


class LeakRefused(ReleaseError):
    """A write the leak check refused; its message is the whole stderr block, printed as it is"""


def refusal(command: str, destination: Destination, findings: Sequence[Finding]) -> LeakRefused:
    """The exit 2 of a write with findings: who refused and where it went, up to 10 findings,
    `and N more`, then the fix"""
    lines = [f"{command}: refused, nothing was sent ({destination.said()})"]
    lines.extend(f"  {finding.said()}" for finding in findings[:LISTED])
    if len(findings) > LISTED:
        lines.append(f"  and {len(findings) - LISTED} more")
    lines.append(FIX)
    return LeakRefused("\n".join(lines))
