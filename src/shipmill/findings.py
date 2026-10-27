"""watch_state.py's rows as the gate reads them: a finding, and its fingerprint"""

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from shipmill.errors import ReleaseError

NEEDS_DECISION = "NEEDS_DECISION"  # watch_state.py's items waiting on a reply, `#N` only (S-005-9)
PRS_OPEN = "PRS_OPEN"  # watch_state.py's open pull requests: work unless [autonomy] land is observe (S-040-9)
HEAD_SHA = re.compile(r"[0-9a-f]{40}")  # a PRS_OPEN row's head SHA, as --json prints it (#546)
ISSUES = "ISSUES"  # triage's work; in a tier read, one row per triage state, `STATE #N ...` (spec 046)
TRIAGE_STATE = re.compile(r"[A-Z][A-Z_]*")


@dataclass(frozen=True, slots=True)
class Finding:
    """One watch_state.py row; agent is its own verdict that the row needs an agent. heads,
    on a PRS_OPEN row only, is each listed pull request's head SHA by number (#546), so a
    push to one is new work; () for every other row and for a watch_state.py before it. fix
    is the one line that clears it (spec 011), built from trusted values only, None without"""

    state: str
    subject: str
    detail: str
    agent: bool
    heads: tuple[tuple[int, str], ...] = ()
    fix: str | None = None

    @property
    def kind(self) -> str:
        """The state, and for an ISSUES row its triage state, the first word of its detail
        (spec 046): what places it in a tier"""
        first = self.detail.split(" ", 1)[0]
        return f"{ISSUES} {first}" if self.state == ISSUES and TRIAGE_STATE.fullmatch(first) else self.state

    def line(self) -> str:
        return f"{self.state} {self.subject}: {self.detail}" if self.detail else f"{self.state} {self.subject}"

    def brief(self) -> str:
        """Kind and subject only: a detail can carry text anyone who edits an issue controls"""
        return f"{self.kind} {self.subject}"


def fingerprint(work: Iterable[Finding]) -> str:
    """A finding's heads join its line only when it has some (#546), so a row without them
    hashes as it did before"""
    lines = sorted(f"{f.state}\x00{f.subject}\x00{f.detail}{heads_part(f.heads)}" for f in work)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def heads_part(heads: tuple[tuple[int, str], ...]) -> str:
    return "".join(f"\x00#{number}={sha}" for number, sha in heads)


def parse_findings(text: str) -> list[Finding]:
    """watch_state.py --json's rows; a row without a boolean agent is refused, never guessed"""
    findings = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReleaseError(f"watch_state.py printed {line[:200]!r}, not JSON: {exc}") from None
        if not isinstance(row, dict):
            raise ReleaseError(f"watch_state.py printed {line[:200]!r}, not a row")
        texts = [row.get(key) for key in ("state", "subject", "detail")]
        if not all(isinstance(t, str) for t in texts) or not isinstance(row.get("agent"), bool):
            raise ReleaseError(
                f"watch_state.py printed {line[:200]!r}: a row needs string state, subject, and detail,"
                " and a boolean agent"
            )
        heads = parse_heads(row, line) if "heads" in row else ()
        fix = row.get("fix")
        if fix is not None and not isinstance(fix, str):
            raise ReleaseError(f"watch_state.py printed {line[:200]!r}: a row's fix must be a string or null")
        findings.append(Finding(row["state"], row["subject"], row["detail"], row["agent"], heads, fix))
    return findings


def parse_heads(row: Mapping[str, object], line: str) -> tuple[tuple[int, str], ...]:
    """A PRS_OPEN row's heads (#546): an object mapping each pull request its detail lists, as
    a number string, to its 40-hex head SHA, and nothing else; anything else is refused"""
    found = row["heads"]
    shown = f"watch_state.py printed {line[:200]!r}"
    if row["state"] != PRS_OPEN:
        raise ReleaseError(f"{shown}: only a {PRS_OPEN} row has heads")
    if not isinstance(found, dict):
        raise ReleaseError(f"{shown}: heads must be an object of pull request numbers to head SHAs")
    heads = []
    for key, sha in found.items():
        if re.fullmatch(r"[1-9][0-9]*", key) is None or not isinstance(sha, str) or HEAD_SHA.fullmatch(sha) is None:
            raise ReleaseError(f"{shown}: heads maps {key[:50]!r} to {str(sha)[:50]!r}, not a number to a head SHA")
        heads.append((int(key), sha))
    listed = re.fullmatch(r"#[0-9]+(?: #[0-9]+)*", str(row["detail"]))
    numbers = {int(n) for n in re.findall(r"#([0-9]+)", str(row["detail"]))} if listed else None
    if numbers != {number for number, _ in heads}:
        raise ReleaseError(f"{shown}: heads must name exactly the pull requests its detail lists")
    return tuple(sorted(heads))
