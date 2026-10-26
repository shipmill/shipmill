#!/usr/bin/env python3
"""Keep a repo's decisions log: numbered rules the user settled, which triage and review
check every change against.

Usage:
  decisions.py check [--file F]
  decisions.py find [--file F] [--all] TERM...
  decisions.py add [--file F] --title T --rule R --why W --applies A --enforced E
                   --source owner/repo#N [--supersedes D-N] [--date YYYY-MM-DD]
                   [--zone ZONE [--config C] [--decided-at TIME]]

The log is DECISIONS.md or docs/decisions.md, whichever exists (docs/decisions.md is
created by the first add). Each entry is:

  ## D-7: <title>

  - Decided: 2026-10-03, in owner/repo#123
  - Rule: <one testable sentence>
  - Why: <the reason, so a later change can tell whether it still holds>
  - Applies to: <paths or globs, comma-separated, or areas such as "CLI flags">
  - Enforced by: <a test, lint, or audit rule; or "review">
  - Zone: interpretation (notify, veto until 2026-10-04T14:00:00Z)   (optional)
  - Supersedes: D-3            (optional)
  - Superseded by: D-9         (written by add, on the old entry)

check   every entry is well formed, ids run 1..n, supersede links agree both ways, and a
        Zone names a zone id of the decision policy (spec 030)
find    active entries whose Applies to matches a TERM (a path matches a glob or a
        prefix; a word matches as a substring of Applies to, Rule, or title). --all
        includes superseded entries. `find $(git diff --name-only origin/main...)`
        lists what a diff must respect
add     append the next entry and mark the one it supersedes; prints the new id. --zone
        records a rule an agent set at the notify level (spec 030, D-48): it writes
        `- Zone: <id> (notify, veto until <time>)`, the time being --decided-at (pass the
        decided comment's post time, so both name one time; default now) plus veto_hours
        from the [decisions] table of C (default .github/shipmill.toml; 24 without the
        file, the table, or the key), in UTC. A zone whose level there isn't notify, or
        a malformed [decisions] table, exits 2

The decision policy's zones, their default levels, and their floors (spec 030) live here,
in ZONES, the one copy the skill scripts read: retro.py loads this file for them.

Exit 0 on success (find: at least one match), 1 when check finds a problem or find
matches nothing, 2 on bad input. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: the [decisions] table is read line by line instead
    tomllib = None

CANDIDATES = (Path("DECISIONS.md"), Path("docs/decisions.md"))
HEADING = re.compile(r"^## D-(\d+): (\S.*)$")
FIELD = re.compile(r"^- ([A-Z][a-z]+(?: [a-z]+)?): (\S.*)$")
REQUIRED = ("Decided", "Rule", "Why", "Applies to", "Enforced by")
OPTIONAL = ("Zone", "Supersedes", "Superseded by")
DECIDED = re.compile(r"^\d{4}-\d\d-\d\d, in [\w.-]+/[\w.-]+#\d+$")
REF = re.compile(r"^D-(\d+)$")

# -- the decision policy (spec 030, D-48) -----------------------------------------------------
# Levels from the least to the most human involvement
LEVELS = ("act", "notify", "ask", "never")
# Each zone an agent's decision falls in: its default level and its floor, the level the
# config can't set it below (None: no floor). A zone id is never renamed or reused
ZONES: dict[str, tuple[str, str | None]] = {
    "direction": ("never", "ask"),
    "decision-policy": ("never", "never"),
    "scope": ("ask", "ask"),
    "rule-departure": ("ask", "ask"),
    "contract-change": ("ask", None),
    "contract-addition": ("notify", None),
    "security": ("ask", "notify"),
    "protected": ("ask", None),
    "interpretation": ("notify", None),
    "triage-verdict": ("notify", None),
    "implementation": ("act", None),
    "unknown": ("ask", "ask"),
}
# The release side's zones and the agent stages (spec 040), which [autonomy] or a decision
# sets, never [decisions]; the package's ReleaseZone, in its order
RELEASE_ZONES = {
    "release": "release is set in [autonomy] release",
    "deploy": "deploy is set in [autonomy] deploy",
    "rollback": "rollback is set in [autonomy] rollback",
    "intake": "intake is set in [autonomy] intake",
    "upgrade": "upgrade is set in [autonomy] upgrade",
    "breaking-release": "a breaking stable release waits for a person's hand start (D-39)",
    "triage": "triage is set in [autonomy] triage",
    "fix": "fix is set in [autonomy] fix",
    "land": "land is set in [autonomy] land",
}
VETO_HOURS = 24
CONFIG = Path(".github/shipmill.toml")
ZONE_LINE = re.compile(r"^([a-z][a-z-]*) \(notify, veto until (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)\)$")
UNTIL = "%Y-%m-%dT%H:%M:%SZ"
UTC = dt.timezone.utc  # noqa: UP017 (dt.UTC is 3.11+)
PREAMBLE = """# Decisions

Rules the maintainers settled, numbered in order. Triage designs and code reviews check
every change against the entries whose "Applies to" it touches. Change a rule by adding an
entry that supersedes it, never by editing an old one.
"""


@dataclass
class Entry:
    number: int
    title: str
    line: int
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return "Superseded by" not in self.fields

    def applies(self) -> list[str]:
        return [a.strip() for a in self.fields.get("Applies to", "").split(",") if a.strip()]


class LogError(Exception):
    pass


@dataclass(frozen=True)
class Policy:
    """Each zone's level and the notify window, as a repo's [decisions] table sets them"""

    levels: dict[str, str]
    veto_hours: int = VETO_HOURS


def policy(path: Path) -> Policy:
    """The [decisions] table of the config at path, every zone at its default without the
    file or the table; a malformed table raises LogError naming the key and the fix"""
    if not path.is_file():
        return Policy({zone: default for zone, (default, _) in ZONES.items()})
    text = path.read_text(encoding="utf-8")
    if tomllib is None:
        return policy_from(decisions_table_310(text, path), path)
    try:
        table = tomllib.loads(text).get("decisions", {})
    except tomllib.TOMLDecodeError as exc:
        raise LogError(f"{path}: {exc}") from None
    if not isinstance(table, dict):
        raise LogError(f"{path}: decisions must be a table")
    return policy_from(table, path)


def policy_from(table: dict[str, object], path: Path) -> Policy:
    levels = {zone: default for zone, (default, _) in ZONES.items()}
    hours = table.get("veto_hours", VETO_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 168:
        raise LogError(f"{path}: [decisions] veto_hours must be an integer from 1 to 168, not {hours!r}")
    for key, value in table.items():
        if key == "veto_hours":
            continue
        if key in RELEASE_ZONES:
            raise LogError(f"{path}: [decisions] {key}: {RELEASE_ZONES[key]}")
        if key == "decision-policy":
            raise LogError(f"{path}: [decisions] decision-policy is fixed at never; remove the key")
        if key not in ZONES:
            raise LogError(f"{path}: [decisions] {key} is no zone id; zone ids: {', '.join(ZONES)}")
        if value not in LEVELS:
            raise LogError(f"{path}: [decisions] {key} = {value!r}: a level is one of {', '.join(LEVELS)}")
        floor = ZONES[key][1]
        if floor is not None and LEVELS.index(str(value)) < LEVELS.index(floor):
            raise LogError(f"{path}: [decisions] {key} = {value!r} is below its floor {floor}")
        levels[key] = str(value)
    return Policy(levels, hours)


def decisions_table_310(text: str, path: Path) -> dict[str, object]:
    """[decisions] on Python 3.10, without tomllib: plain `key = "level"` and `veto_hours = N`
    lines in a plain [decisions] table; any other form is refused rather than misread"""
    unreadable = f"{path}: can't read [decisions] on Python 3.10: use 3.11+, or plain key = value lines in it"
    table: dict[str, object] = {}
    current = ""
    seen = False
    for line in text.splitlines():
        header = re.match(r"^\s*(\[\[?)\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$", line)
        if header:
            current = re.sub(r"\s*\.\s*", ".", header.group(2).strip())
            if current.startswith("decisions.") or current.strip("\"'") != current:
                raise LogError(unreadable)
            if current == "decisions":
                # an array of tables, or the table declared twice, is no table tomllib reads
                if header.group(1) == "[[" or seen:
                    raise LogError(unreadable)
                seen = True
            continue
        if current == "" and re.match(r"^\s*[\"']?decisions[\"']?\s*[.=]", line):
            raise LogError(unreadable)
        if current != "decisions" or not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=\s*(?:\"([^\"\\]*)\"|'([^']*)'|(-?(?:0|[1-9]\d*)))\s*(?:#.*)?$", line)
        if item is None or item.group(1) in table:
            raise LogError(unreadable)
        word = item.group(2) if item.group(2) is not None else item.group(3)
        table[item.group(1)] = word if word is not None else int(item.group(4))
    return table


def zone_problem(value: str) -> str | None:
    """What is wrong with a Zone field's value, or None"""
    line = ZONE_LINE.match(value)
    if line is None:
        return "Zone must read '<zone id> (notify, veto until YYYY-MM-DDTHH:MM:SSZ)'"
    if line.group(1) not in ZONES:
        return f"Zone names no zone id '{line.group(1)}'; zone ids: {', '.join(ZONES)}"
    try:
        dt.datetime.strptime(line.group(2), UNTIL)
    except ValueError:
        return f"Zone's veto time {line.group(2)} is no date and time"
    return None


def locate(given: str | None, create: bool = False) -> Path:
    if given:
        return Path(given)
    for path in CANDIDATES:
        if path.is_file():
            return path
    if create:
        return CANDIDATES[1]
    raise LogError("no DECISIONS.md or docs/decisions.md: nothing has been decided yet")


def parse(text: str) -> tuple[list[Entry], list[str]]:
    """The entries, and every format problem found"""
    entries: list[Entry] = []
    problems: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        heading = HEADING.match(line)
        if heading:
            entries.append(Entry(int(heading.group(1)), heading.group(2).strip(), n))
            continue
        if line.startswith("## "):
            problems.append(f"line {n}: a heading that isn't '## D-<n>: <title>'")
            continue
        item = FIELD.match(line)
        if item and entries:
            name, value = item.group(1), item.group(2).strip()
            if name not in REQUIRED + OPTIONAL:
                problems.append(f"line {n}: D-{entries[-1].number} has an unknown field '{name}'")
            elif name in entries[-1].fields:
                problems.append(f"line {n}: D-{entries[-1].number} repeats '{name}'")
            else:
                entries[-1].fields[name] = value
        elif line.startswith("- ") and entries:
            problems.append(f"line {n}: D-{entries[-1].number} has a malformed field line")
    return entries, problems


def check(entries: list[Entry]) -> list[str]:
    problems = []
    by_number = {e.number: e for e in entries}
    for i, entry in enumerate(entries, 1):
        tag = f"D-{entry.number} (line {entry.line})"
        if entry.number != i:
            problems.append(f"{tag}: expected D-{i}; ids run 1..n in order")
        for name in REQUIRED:
            if name not in entry.fields:
                problems.append(f"{tag}: missing '{name}'")
        decided = entry.fields.get("Decided")
        if decided is not None and not DECIDED.match(decided):
            problems.append(f"{tag}: Decided must read 'YYYY-MM-DD, in owner/repo#N'")
        zone = entry.fields.get("Zone")
        wrong = zone_problem(zone) if zone is not None else None
        if wrong is not None:
            problems.append(f"{tag}: {wrong}")
        for name, back in (("Supersedes", "Superseded by"), ("Superseded by", "Supersedes")):
            ref = entry.fields.get(name)
            if ref is None:
                continue
            match = REF.match(ref)
            other = by_number.get(int(match.group(1))) if match else None
            if other is None:
                problems.append(f"{tag}: {name} {ref} names no entry")
            elif other.fields.get(back) != f"D-{entry.number}":
                problems.append(f"{tag}: {name} {ref}, but {ref} lacks '{back}: D-{entry.number}'")
    return problems


def matches(entry: Entry, term: str) -> bool:
    for scope in entry.applies():
        if fnmatch.fnmatch(term, scope) or term.startswith(scope.rstrip("*").rstrip("/") + "/") or term == scope:
            return True
    if "/" in term or "." in term:
        return False
    text = f"{entry.title} {entry.fields.get('Rule', '')} {entry.fields.get('Applies to', '')}".lower()
    return term.lower() in text


def render(entry: Entry) -> str:
    lines = [f"## D-{entry.number}: {entry.title}", ""]
    lines += [f"- {name}: {entry.fields[name]}" for name in REQUIRED + OPTIONAL if name in entry.fields]
    return "\n".join(lines) + "\n"


def decided_at(given: str | None) -> dt.datetime:
    """--decided-at, an ISO 8601 time with its zone, else now"""
    if given is None:
        return dt.datetime.now(UTC)
    try:
        moment = dt.datetime.fromisoformat(given.replace("Z", "+00:00"))
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        raise LogError(f"--decided-at {given} must be an ISO 8601 time with its zone, such as 2026-10-03T14:00:00Z")
    return moment


def zone_field(zone: str, config: Path, now: dt.datetime) -> str:
    """The Zone field of a rule set at notify: its veto window ends veto_hours after now"""
    if zone not in ZONES:
        raise LogError(f"--zone {zone} is no zone id; zone ids: {', '.join(ZONES)}")
    found = policy(config)
    level = found.levels[zone]
    if level != "notify":
        raise LogError(
            f"--zone {zone} is at {level} in {config}, not notify: only a rule an agent set at notify "
            "carries a Zone line; record a maintainer's answer without --zone"
        )
    until = now.astimezone(UTC).replace(microsecond=0) + dt.timedelta(hours=found.veto_hours)
    return f"{zone} (notify, veto until {until.strftime(UNTIL)})"


def add(path: Path, args: argparse.Namespace) -> int:
    text = path.read_text(encoding="utf-8") if path.is_file() else PREAMBLE
    entries, problems = parse(text)
    problems += check(entries)
    if problems:
        raise LogError(f"{path} must pass check before an add: {problems[0]}")
    number = len(entries) + 1
    fields = {
        "Decided": f"{args.date}, in {args.source}",
        "Rule": args.rule,
        "Why": args.why,
        "Applies to": args.applies,
        "Enforced by": args.enforced,
    }
    if args.zone is not None:
        fields["Zone"] = zone_field(args.zone, Path(args.config), decided_at(args.decided_at))
    if args.supersedes:
        match = REF.match(args.supersedes)
        old = next((e for e in entries if match and e.number == int(match.group(1))), None)
        if old is None:
            raise LogError(f"--supersedes {args.supersedes} names no entry")
        if not old.active:
            raise LogError(f"{args.supersedes} is already superseded by {old.fields['Superseded by']}")
        fields["Supersedes"] = args.supersedes
        lines = text.splitlines()
        end = next((e.line - 1 for e in entries if e.number == old.number + 1), len(lines))
        while end > old.line and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, f"- Superseded by: D-{number}")
        text = "\n".join(lines) + "\n"
    new = Entry(number, args.title, 0, fields)
    if not DECIDED.match(fields["Decided"]):
        raise LogError("--source must be owner/repo#N and --date YYYY-MM-DD")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n\n" + render(new), encoding="utf-8")
    print(f"D-{number}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "find", "add"):
        p = sub.add_parser(name)
        p.add_argument("--file", help="the log (default: DECISIONS.md or docs/decisions.md)")
        if name == "find":
            p.add_argument("--all", action="store_true", help="include superseded entries")
            p.add_argument("terms", nargs="+", metavar="TERM")
        if name == "add":
            for flag in ("title", "rule", "why", "applies", "enforced", "source"):
                p.add_argument(f"--{flag}", required=True)
            p.add_argument("--supersedes")
            p.add_argument("--date", default=dt.date.today().isoformat())
            p.add_argument("--zone", help="the zone of a rule set at notify (spec 030); writes its Zone line")
            p.add_argument("--config", default=str(CONFIG), help="with --zone: the config holding [decisions]")
            p.add_argument(
                "--decided-at", help="with --zone: when it was decided, ISO 8601 with its zone (default: now)"
            )
    args = parser.parse_args()
    try:
        if args.command == "add":
            return add(locate(args.file, create=True), args)
        path = locate(args.file)
        entries, problems = parse(path.read_text(encoding="utf-8"))
        if args.command == "check":
            problems += check(entries)
            for problem in problems:
                print(f"{path}: {problem}")
            return 1 if problems else 0
        found = [e for e in entries if (args.all or e.active) and any(matches(e, t) for t in args.terms)]
        for entry in found:
            print(f"D-{entry.number}: {entry.title}\n  Rule: {entry.fields.get('Rule', '')}")
        return 0 if found else 1
    except (LogError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
