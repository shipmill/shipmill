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


def has_environment(text: str) -> bool:
    """Whether a job of the workflow has an `environment:` key, the key GitHub records a
    deployment for"""
    return any(job.environment for job in jobs(text))
