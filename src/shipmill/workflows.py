"""A GitHub Actions workflow's jobs, read from its text, not by a YAML parse (spec 063)

Under the top-level `jobs:` key, a job starts at a line `  <id>:` (two spaces, the job id, a
colon) and runs to the next such line or the next top-level key. A job's display name is its
`name:` value when that is a plain scalar holding no `${{`, else its id: the name GitHub gives
the job in a run's record.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

WORKFLOWS_DIR = ".github/workflows"
SUFFIXES = (".yml", ".yaml")

_JOBS = re.compile(r"^jobs:[ \t]*(?:#.*)?$")
_JOB = re.compile(r"^  (?P<id>[\w-]+):[ \t]*(?:#.*)?$")
_TOP = re.compile(r"^[^\s#]")  # a top-level key, or anything else at column 0 but a comment
_NAME = re.compile(r"^name:[ \t]*(?P<value>.*)$")
_ENVIRONMENT = re.compile(r"^environment:")
_COMMENT = re.compile(r"[ \t]+#.*$")
_NOT_PLAIN = tuple("\"'|>[{&*!%@`")
_EXPRESSION = "${{"


def is_workflow(path: str) -> bool:
    """A file `.github/workflows/<name>.yml` or `.yaml`, as GitHub runs them (none in a subfolder)"""
    pure = PurePosixPath(path)
    return pure.parent.as_posix() == WORKFLOWS_DIR and pure.suffix in SUFFIXES


@dataclass(frozen=True, slots=True)
class Job:
    """A job of a workflow: its id, its display name, whether it has an `environment:` key, and
    its block, the lines from its `  <id>:` line (start, 1-based) up to end, not included"""

    id: str
    name: str
    environment: bool
    start: int
    end: int

    def holds(self, line: int) -> bool:
        """Whether the 1-based line sits in the job's block"""
        return self.start <= line < self.end


def jobs(text: str) -> tuple[Job, ...]:
    """The jobs of a workflow's text, in its order; none without a top-level `jobs:` key"""
    lines = text.splitlines()
    found: list[Job] = []
    inside = False
    start: int | None = None
    job_id = ""
    for number, line in enumerate(lines, start=1):
        if not inside:
            inside = _JOBS.match(line) is not None
            continue
        job = _JOB.match(line)
        ends = _TOP.match(line) is not None
        if start is not None and (job is not None or ends):
            found.append(_job(job_id, lines[start : number - 1], start, number))
            start = None
        if ends:
            inside = _JOBS.match(line) is not None
            continue
        if job is not None:
            start, job_id = number, job.group("id")
    if start is not None:
        found.append(_job(job_id, lines[start:], start, len(lines) + 1))
    return tuple(found)


def _job(job_id: str, body: list[str], start: int, end: int) -> Job:
    """A job from the lines under its `  <id>:` line: its keys are those at the indent of its
    first key"""
    keys = [line for line in body if line.strip() and not line.lstrip().startswith("#")]
    indent = len(keys[0]) - len(keys[0].lstrip(" ")) if keys else 0
    own = [line[indent:] for line in keys if len(line) - len(line.lstrip(" ")) == indent]
    name = job_id
    for key in own:
        named = _NAME.match(key)
        if named is not None:
            name = _display(named.group("value"), job_id)
            break
    environment = any(_ENVIRONMENT.match(key) for key in own)
    return Job(job_id, name, environment, start, end)


def _display(value: str, job_id: str) -> str:
    """A `name:` value as GitHub shows it: a plain scalar holding no `${{`; else the job's id"""
    plain = _COMMENT.sub("", value).strip()
    if not plain or plain.startswith(_NOT_PLAIN) or _EXPRESSION in plain:
        return job_id
    return plain


@dataclass(frozen=True, slots=True)
class Step:
    """A step of a job (spec 080): its `run:` script, a block's lines without their indentation,
    or its `uses:` action, as written; and the `working-directory` its `run:` runs in, its own,
    else the job's or the workflow's `defaults: run:` one (None: the repository's root)"""

    run: str | None
    uses: str | None
    working_directory: str | None


_KEY = re.compile(r"^(?P<key>[\w-]+):(?:[ \t]+(?P<value>.*))?$")
_BLOCK = re.compile(r"^(?P<style>[|>])[-+0-9]*[ \t]*(?:#.*)?$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(lines: list[str]) -> list[str]:
    """The lines that hold something: neither blank nor a comment"""
    return [line for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _keys(lines: list[str]) -> dict[str, tuple[str, list[str]]]:
    """The keys of a mapping's lines, those at the indent of its first key, each with its inline
    value and the lines under it (a sequence's `- ` items at the key's own indent too)"""
    held = _content(lines)
    if not held:
        return {}
    indent = _indent(held[0])
    found: dict[str, tuple[str, list[str]]] = {}
    key: str | None = None
    for line in lines:
        at = _indent(line)
        if line.strip() and not line.lstrip().startswith("#") and at <= indent:
            if key is not None and at == indent and line.lstrip().startswith("-"):
                found[key][1].append(line)
                continue
            key = None
            if at == indent and (m := _KEY.match(line[indent:])) is not None:
                key = m["key"]
                found[key] = ((m["value"] or "").rstrip(), [])
            continue
        if key is not None:
            found[key][1].append(line)
    return found


def _scalar(value: str, under: list[str]) -> str:
    """A scalar's value: a `|` block's lines, a `>` block's folded, a quoted one unquoted, a plain
    one without its comment; a flow scalar's lines under it fold into it"""
    block = _BLOCK.match(value)
    if block is not None:
        return _block(under, block["style"] == ">")
    rest = [line.strip() for line in under if line.strip()]
    if value.startswith(("'", '"')):
        text = " ".join([value, *rest])
        quote = text[0]
        end = text.rfind(quote)
        inner = text[1:end] if end > 0 else text[1:]
        if quote == "'":
            return inner.replace("''", "'")
        return re.sub(r'\\(["\\/])', r"\1", inner)
    return " ".join([_COMMENT.sub("", value).strip(), *rest]).strip()


def _block(under: list[str], folded: bool) -> str:
    """A `|` or `>` block's text: its lines past the first one's indentation; a `>` block joins
    the lines at that indentation that follow one another"""
    held = [line for line in under if line.strip()]
    if not held:
        return ""
    indent = _indent(held[0])
    lines: list[str] = []
    for line in under:
        if line.strip() and _indent(line) < indent:  # a comment past the block's end
            break
        lines.append(line[indent:] if line.strip() else "")
    while lines and not lines[-1]:
        lines.pop()
    if not folded:
        return "\n".join(lines)
    out: list[str] = []
    for line in lines:
        if out and out[-1] and line and not line.startswith(" ") and not out[-1].startswith(" "):
            out[-1] += " " + line
        else:
            out.append(line)
    return "\n".join(out)


def _working_directory(keys: dict[str, tuple[str, list[str]]]) -> str | None:
    """The `working-directory` of a mapping's `defaults: run:`; None without one"""
    defaults = keys.get("defaults")
    run = _keys(defaults[1]).get("run") if defaults is not None else None
    found = _keys(run[1]).get("working-directory") if run is not None else None
    return _scalar(*found) if found is not None else None


def steps(text: str, job: Job) -> tuple[Step, ...]:
    """The steps of a workflow's job, in its order; none for a job without `steps:`, such as one
    that calls a reusable workflow"""
    lines = text.splitlines()
    keys = _keys(lines[job.start : job.end - 1])
    listed = keys.get("steps")
    if listed is None:
        return ()
    default = _working_directory(keys) or _working_directory(_keys(lines))
    found: list[Step] = []
    for item in _items(listed[1]):
        own = _keys(item)
        run, uses, where = own.get("run"), own.get("uses"), own.get("working-directory")
        found.append(
            Step(
                _scalar(*run) if run is not None else None,
                _scalar(*uses) if uses is not None else None,
                _scalar(*where) if where is not None else default,
            )
        )
    return tuple(found)


def _items(lines: list[str]) -> list[list[str]]:
    """A block sequence's items, each with its `- ` turned into indentation, so its first key
    sits at the indent of the rest"""
    held = _content(lines)
    if not held or not held[0].lstrip().startswith("-"):
        return []
    dash = _indent(held[0])
    items: list[list[str]] = []
    for line in lines:
        if _indent(line) == dash and line.lstrip().startswith("-"):
            items.append([line[:dash] + " " + line[dash + 1 :]])
        elif items:
            items[-1].append(line)
    return items


def has_environment(text: str) -> bool:
    """Whether a job of the workflow has an `environment:` key, the key GitHub records a
    deployment for"""
    return any(job.environment for job in jobs(text))
