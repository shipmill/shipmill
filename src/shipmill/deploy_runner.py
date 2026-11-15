"""Spec 063's `deploy runner` doctor row: a job whose plain actions/checkout runs on a
self-hosted runner a deploy job deploys from cleans the workspace the deploy left (#1165)

A text reading, not a YAML parse, as doctor reads workflows: under the top-level `jobs:` key a
job starts at a line `  <id>:` and runs to the next one; its keys sit at the indent of its
first key line"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

ROW = "deploy runner"
WARN = "WARN"
PASS = "PASS"
_HOSTED = ("ubuntu-", "windows-", "macos-")  # GitHub-hosted labels: a hosted runner starts clean for each job
_JOBS = re.compile(r"^jobs:[ \t]*(?:#.*)?$(?P<body>(?:\n(?:[ \t#].*)?)*)", re.MULTILINE)
_JOB = re.compile(r"^  (?P<id>[\w-]+):[ \t]*(?:#.*)?$", re.MULTILINE)
_CHECKOUT = re.compile(r"actions/checkout@\S+")


@dataclass(frozen=True, slots=True)
class Job:
    file: str  # the workflow's path, relative to the checkout
    id: str
    labels: tuple[str, ...] | None  # its runs-on labels; None: not compared (${{, a group only, none)
    deploys: bool  # a deploy job: it sets environment:, or a workflow [environments] names holds it
    bare_checkout: bool  # a step uses actions/checkout@<ref> and its with: sets no path:

    def shared(self) -> bool:
        """Whether it runs on a self-hosted runner, which keeps its workspace between jobs"""
        return self.labels is not None and not any(label.lower().startswith(_HOSTED) for label in self.labels)

    def fits(self, other: Job) -> bool:
        """Whether any runner that takes the other job can take this one: its labels are a
        subset of the other's (GitHub matches labels without case)"""
        if self.labels is None or other.labels is None:
            return False
        return {label.lower() for label in self.labels} <= {label.lower() for label in other.labels}


def check(root: Path, environment_workflows: Collection[str]) -> list[tuple[str, str]]:
    """The `deploy runner` rows as (status, detail): a WARN per job that breaks a deploy job's
    checkout, else one PASS naming the deploy jobs checked; none when no deploy job runs on a
    self-hosted runner (D-9). Never a FAIL (spec 063)"""
    jobs = [job for path in _workflows(root) for job in read(root, path, environment_workflows)]
    deploys = [job for job in jobs if job.deploys and job.shared()]
    if not deploys:
        return []
    rows = []
    for job in jobs:
        if not job.bare_checkout:
            continue
        target = next((d for d in deploys if d != job and job.fits(d)), None)
        if target is None:
            continue
        labels = ", ".join(job.labels or ())
        rows.append(
            (
                WARN,
                f"{job.file} job {job.id} runs actions/checkout without path: on [{labels}], a runner"
                f" {target.file} job {target.id} deploys from; its checkout cleans the workspace the deploy"
                " left: set with: path: to a folder of its own, or run it on another runner",
            )
        )
    if rows:
        return rows
    checked = ", ".join(f"{d.file} job {d.id}" for d in deploys)
    return [(PASS, f"no plain actions/checkout shares a self-hosted runner with a deploy job; checked {checked}")]


def _workflows(root: Path) -> list[Path]:
    folder = root / ".github" / "workflows"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix in (".yml", ".yaml") and p.is_file())


def read(root: Path, path: Path, environment_workflows: Collection[str]) -> list[Job]:
    """The jobs of one workflow file"""
    text = path.read_text(encoding="utf-8")
    named = path.name in environment_workflows
    found = _JOBS.search(text)
    if found is None:
        return []
    body = found["body"]
    starts = list(_JOB.finditer(body))
    jobs = []
    for start, end in zip(starts, [*starts[1:], None], strict=True):
        block = body[start.end() : len(body) if end is None else end.start()]
        keys = _keys(block.splitlines())
        runs_on = keys.get("runs-on")
        jobs.append(
            Job(
                file=path.relative_to(root).as_posix(),
                id=start["id"],
                labels=None if runs_on is None else _labels(*runs_on),
                deploys=named or "environment" in keys,
                bare_checkout="steps" in keys and _bare_checkout(keys["steps"][1]),
            )
        )
    return jobs


def _code(line: str) -> str:
    """The line with its comment cut: a # at the line's start or after a space"""
    return re.sub(r"(?:^|\s)#.*$", "", line).rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _keys(lines: list[str]) -> dict[str, tuple[str, list[str]]]:
    """A block's keys at its first key's indent: each key's inline value and the lines under it"""
    code = [line for line in map(_code, lines) if line.strip()]
    if not code:
        return {}
    indent = _indent(code[0])
    keys: dict[str, tuple[str, list[str]]] = {}
    current: list[str] | None = None
    for line in code:
        if _indent(line) == indent and (m := re.match(r"\s*([\w-]+):(.*)$", line)):
            current = []
            keys[m[1]] = (m[2].strip(), current)
        elif current is not None and (_indent(line) > indent or line.lstrip().startswith("-")):
            # a block list may sit at its key's own indent
            current.append(line)
        else:
            current = None
    return keys


def _scalar(value: str) -> str:
    return value.strip().strip("'\"")


def _flow(value: str) -> tuple[str, ...]:
    return tuple(item for item in (_scalar(v) for v in value.strip()[1:-1].split(",")) if item)


def _labels(inline: str, under: list[str]) -> tuple[str, ...] | None:
    """runs-on's labels: a scalar, a flow list, a block list, or a mapping's labels:; None when
    it holds ${{ or names only a group:"""
    if "${{" in inline or any("${{" in line for line in under):
        return None
    if inline.startswith("["):
        return _flow(inline) or None
    if inline.startswith("{"):
        found = re.search(r"\blabels\s*:\s*(\[[^\]]*\]|[^,}]+)", inline)
        if found is None:
            return None
        value = found[1].strip()
        return (_flow(value) if value.startswith("[") else (_scalar(value),)) or None
    if inline:
        return (_scalar(inline),)
    items = [line.strip() for line in under]
    if items and items[0].startswith("-"):
        return tuple(_scalar(item[1:]) for item in items if item.startswith("-")) or None
    labels = _keys(under).get("labels")
    if labels is None:
        return None  # a group only
    return _labels(*labels)


def _bare_checkout(steps: list[str]) -> bool:
    """Whether a step uses actions/checkout@<ref> and its with: sets no path:"""
    return any(_is_bare_checkout(step) for step in _steps(steps))


def _steps(lines: list[str]) -> list[list[str]]:
    """The steps of a block list, each with its dash turned into a space so its keys align"""
    dashes = [_indent(line) for line in lines if line.lstrip().startswith("-")]
    if not dashes:
        return []
    indent = min(dashes)
    steps: list[list[str]] = []
    for line in lines:
        if _indent(line) == indent and line.lstrip().startswith("-"):
            steps.append([line[:indent] + " " + line[indent + 1 :]])
        elif steps and _indent(line) > indent:
            steps[-1].append(line)
    return steps


def _is_bare_checkout(step: list[str]) -> bool:
    keys = _keys(step)
    uses = keys.get("uses")
    if uses is None or not _CHECKOUT.fullmatch(_scalar(uses[0])):
        return False
    inputs = keys.get("with")
    if inputs is None:
        return True
    inline, under = inputs
    if inline.startswith("{"):
        return re.search(r"[{,]\s*path\s*:", inline) is None
    return "path" not in _keys(under)
