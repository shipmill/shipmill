"""Spec 060: the gate's sweep files one item per installation for the App's owner when an
optional permission (D-77) a repo of the installation needs is one the installation lacks.

The notice reads the installation with a token of its own, over every repo of it and asking
only metadata, contents, and issues read (S-060-14): it lists the repos, reads each one's
`.github/shipmill.toml` and its `shipmill-permission` issues. That token is held here alone,
cached nowhere, handed to no session and used to write nothing. Every write goes through the
gate's own token, limited to its repo (D-14): the issue it files in its own repo when that repo
is the carrier, and the verified comment and close of an issue its own repo holds once the
installation grants the permission.

The carrier is the same for every gate of the installation (S-060-12): among the repos whose
config parses, sets this App's `[agents] app_id`, and needs the permission, a product's home
(`[product] repos`, spec 038) when exactly one is among them, else the first by full name with
case ignored. An issue with the permission's marker in any repo of the installation, open or
closed, means none is filed again (S-060-4).

A failure of the notice is its line's, never the tick's, as an upgrade proposal's is (S-060-8,
S-060-15)."""

import json
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from shipmill.agents import MAINTAINER
from shipmill.app import (
    OPTIONAL_PERMISSIONS,
    Api,
    AppRecord,
    Clock,
    Identity,
    Installation,
    OptionalPermission,
    Signer,
    app_record,
    check_key,
    contents,
    installed,
    jwt,
    mint_installation,
    missing,
    utc_now,
)
from shipmill.config import CONFIG_PATH, loads
from shipmill.errors import ReleaseError
from shipmill.policy import Policy

LABEL = "shipmill-permission"  # the label the gate finds the item by
ROLE_LABEL = f"role:{MAINTAINER}"  # a person's item, the maintainer role's (spec 036)
VERIFIED = "<!-- shipmill:verified -->"  # the check's comment, first line (spec 017)
PAGE = 100  # GitHub's largest page


@dataclass(frozen=True, slots=True)
class Filed:
    """An issue of the installation carrying a permission's marker on its first line"""

    repo: str
    number: int
    marker: str
    open: bool

    @property
    def name(self) -> str:
        return f"{self.repo}#{self.number}"


class Reads(Protocol):
    """What the notice reads of the App's installation, through its installation-wide token"""

    @property
    def app(self) -> AppRecord:
        """The App's slug and owner (GET /app)"""
        ...

    @property
    def installation(self) -> Installation:
        """The installation on the gate's repo: its permissions and page"""
        ...

    def repos(self) -> tuple[str, ...]:
        """Every repo of the installation, as owner/name"""
        ...

    def issues(self, repo: str) -> tuple[Filed, ...]:
        """The repo's issues labelled shipmill-permission whose first line is a marker, any state"""
        ...

    def config(self, repo: str) -> str | None:
        """The repo's .github/shipmill.toml on its default branch; None without one"""
        ...


class Writer(Protocol):
    """GitHub as the App, with the gate's token limited to its repo (D-14)"""

    def create_issue(self, title: str, body: str, labels: Sequence[str] = (), assignees: Sequence[str] = ()) -> int: ...

    def close_issue(self, number: int, comment: str) -> None: ...


def _answer(api: Api, path: str, token: str) -> Any:
    answer = api.get(path, token)
    if answer.status != 200:
        raise ReleaseError(f"GET {path} answered {answer.status}: {answer.body.strip()[:300]}")
    try:
        return json.loads(answer.body)
    except json.JSONDecodeError:
        raise ReleaseError(f"GET {path} answered {answer.status} without JSON") from None


def _first_line(body: object) -> str:
    text = body if isinstance(body, str) else ""
    lines = text.splitlines()
    return lines[0].strip() if lines else ""


@dataclass(frozen=True, slots=True)
class ApiReads:
    """Reads over GitHub's API with the installation-wide token; repr leaves the token out"""

    app: AppRecord
    installation: Installation
    token: str = field(repr=False)
    api: Api = field(repr=False)

    def repos(self) -> tuple[str, ...]:
        found: list[str] = []
        page = 1
        while True:
            path = f"/installation/repositories?per_page={PAGE}&page={page}"
            data = _answer(self.api, path, self.token)
            listed = data.get("repositories") if isinstance(data, dict) else None
            if not isinstance(listed, list):
                raise ReleaseError(f"GET {path} gave no repositories list")
            for each in listed:
                full = each.get("full_name") if isinstance(each, dict) else None
                if not isinstance(full, str) or "/" not in full:
                    raise ReleaseError(f"GET {path} gave a repository with no full_name")
                found.append(full)
            if len(listed) < PAGE:
                return tuple(found)
            page += 1

    def issues(self, repo: str) -> tuple[Filed, ...]:
        found: list[Filed] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"labels": LABEL, "state": "all", "per_page": PAGE, "page": page})
            path = f"/repos/{repo}/issues?{query}"
            data = _answer(self.api, path, self.token)
            if not isinstance(data, list):
                raise ReleaseError(f"GET {path} gave no list of issues")
            for each in data:
                if not isinstance(each, dict) or "pull_request" in each:
                    continue
                number, state = each.get("number"), each.get("state")
                if not isinstance(number, int) or isinstance(number, bool) or state not in ("open", "closed"):
                    raise ReleaseError(f"GET {path} gave an issue without its number and state")
                found.append(Filed(repo, number, _first_line(each.get("body")), state == "open"))
            if len(data) < PAGE:
                return tuple(found)
            page += 1

    def config(self, repo: str) -> str | None:
        return contents(repo, CONFIG_PATH.as_posix(), self.token, self.api)


def open_reads(identity: Identity, repo: str, signer: Signer, api: Api, clock: Clock) -> ApiReads:
    """The App's JWT, its record, its installation on repo (read alone: nothing is required of
    it), then the installation-wide token asking NOTICE_PERMISSIONS (S-060-14)"""
    bearer = jwt(identity.app_id, check_key(identity.key), clock(), signer)
    record = app_record(identity.app_id, bearer, api)
    found = installed(identity.app_id, record.slug, repo, bearer, api, ())
    return ApiReads(record, found, mint_installation(identity.app_id, found.id, bearer, api), api)


@dataclass(frozen=True, slots=True)
class Seams:
    """What the notice reads and writes with, as tests pass fakes: the installation's reads,
    opened with the App's key, and GitHub as the App with the gate's repo-limited token"""

    reads: Callable[[Identity], Reads]
    writer: Callable[[Identity], Writer]


@dataclass(frozen=True, slots=True)
class Candidate:
    """A repo whose config turns the permission on: its name, and whether it is a product's home"""

    repo: str
    home: bool


def carrier(candidates: Sequence[Candidate]) -> Candidate:
    """S-060-12: the one home among the candidates, else the first by full name, case ignored"""
    homes = [c for c in candidates if c.home]
    if len(homes) == 1:
        return homes[0]
    return min(candidates, key=lambda c: (c.repo.lower(), c.repo))


def configured(text: str | None, repo: str, app_id: int) -> Policy | None:
    """The repo's config when it parses and sets this App's [agents] app_id; else None, since
    such a repo runs no gate of this App (S-060-13)"""
    if text is None:
        return None
    try:
        policy = Policy.parse(loads(text, f"{repo}:{CONFIG_PATH}"), str(CONFIG_PATH))
    except ReleaseError:  # a config that doesn't parse runs no gate: no candidate
        return None
    return policy if policy.agents is not None and policy.agents.app_id == app_id else None


def title(permission: OptionalPermission) -> str:
    return f"Grant the App {permission.named()} and accept it on its installation"


def body(permission: OptionalPermission, app: AppRecord, page: str, candidates: Sequence[Candidate], repo: str) -> str:
    """S-060-3: the permission, what it serves, each candidate with the config that needs it, the
    two steps with their links, and the check"""
    repos = "\n".join(f"- `{c.repo}`: its `{permission.by}`" for c in candidates)
    return (
        f"{permission.marker}\n"
        f"The App `{app.slug}` asks for **{permission.named()}** as an optional permission, and its installation"
        f" doesn't grant it yet: {permission.serves}. These repos of the installation turn it on:\n\n"
        f"{repos}\n\n"
        "One accept covers every repo of the installation.\n\n"
        f"1. In the App's settings, set {permission.label} to {permission.access}: {app.permissions_page}\n"
        f"2. Accept the new permission on the installation's page: {page}\n\n"
        "## Check\n\n"
        f"`shipmill doctor` in `{repo}` shows the `app` row as PASS for {permission.named()}, not WARN.\n"
    )


def verified(permission: OptionalPermission) -> str:
    return f"{VERIFIED}\nThe App's installation grants {permission.named()} now, so this item's check holds."


def _same(one: str, other: str) -> bool:
    return one.lower() == other.lower()


@dataclass(frozen=True, slots=True)
class Notice:
    """What a sweep's notice did (spec 060), as sweep.json's permissions keeps it: each part of
    its line, or the first line of the error that stopped it"""

    parts: tuple[str, ...] = ()
    error: str | None = None

    def line(self) -> str:
        """The swept tick's decision line's part"""
        if self.error is not None:
            return f"permissions failed: {self.error}"
        return f"permissions: {', '.join(self.parts) or 'none missing'}"

    def record(self) -> dict[str, object]:
        return {"error": self.error} if self.error is not None else {"parts": list(self.parts)}

    @classmethod
    def of(cls, data: object) -> Notice:
        """sweep.json's permissions; anything but one of the two shapes raises ValueError"""
        if not isinstance(data, dict) or set(data) not in ({"error"}, {"parts"}):
            raise ValueError(f"permissions needs exactly error or parts, got {data!r}")
        if "error" in data:
            if not isinstance(data["error"], str) or not data["error"]:
                raise ValueError(f"permissions' error must be a non-empty string: {data!r}")
            return cls(error=data["error"])
        parts = data["parts"]
        if not isinstance(parts, list) or not all(isinstance(p, str) and p for p in parts):
            raise ValueError(f"permissions' parts must be a list of non-empty strings: {data!r}")
        return cls(tuple(parts))


def notice(
    reads: Reads,
    writer: Callable[[], Writer],
    repo: str,
    app_id: int,
    maintainers: Sequence[str],
    dry_run: bool,
    table: tuple[OptionalPermission, ...] = OPTIONAL_PERMISSIONS,
) -> Notice:
    """One sweep's notice for the gate of repo, as spec 060's Later sweeps and The carrier say.
    writer is asked for only to write, and never on a dry run"""
    gone = missing(reads.installation.permissions, table)
    lacking = [p for p in table if p in gone]
    own = reads.issues(repo)
    parts: list[str] = []
    for permission in table:
        if permission in lacking:
            continue
        for item in own:  # S-060-6: granted now, and its item open here
            if item.open and item.marker == permission.marker:
                if not dry_run:
                    writer().close_issue(item.number, verified(permission))
                parts.append(f"{'would close' if dry_run else 'closed'} #{item.number}")
    if not lacking:
        return Notice(tuple(parts))
    names = reads.repos()
    filed = [*own, *(f for r in names if not _same(r, repo) for f in reads.issues(r))]
    policies: dict[str, Policy | None] = {}

    def policy(name: str) -> Policy | None:
        if name not in policies:
            policies[name] = configured(reads.config(name), name, app_id)
        return policies[name]

    for permission in lacking:
        existing = sorted((f for f in filed if f.marker == permission.marker), key=lambda f: (f.repo.lower(), f.number))
        if existing:  # S-060-4: open or closed, here or in another repo
            first = existing[0]
            parts.append(f"{permission.named()} in {first.name}{'' if first.open else ' (closed)'}")
            continue
        candidates = [
            Candidate(name, found.product is not None and bool(found.product.repos))
            for name in sorted(names, key=str.lower)
            if (found := policy(name)) is not None and permission.needed(found)
        ]
        if not candidates:  # S-060-5, D-9
            parts.append(f"{permission.named()} needed by no repo")
            continue
        chosen = carrier(candidates)
        if not _same(chosen.repo, repo):  # S-060-12
            parts.append(f"carried by {chosen.repo}")
            continue
        if dry_run:
            parts.append(f"would file {permission.named()}")
            continue
        number = writer().create_issue(
            title(permission),
            body(permission, reads.app, reads.installation.settings, candidates, repo),
            (LABEL, ROLE_LABEL),
            tuple(maintainers),
        )
        parts.append(f"filed #{number} {permission.named()}")
    return Notice(tuple(parts))


@dataclass(frozen=True, slots=True)
class SweptPermissions:
    """What a sweep's notice did: the decision line's part, and what sweep.json keeps, None for
    a gate without an App and for a dry run, which write nothing"""

    line: str
    stored: Notice | None


NO_APP = "permissions: none read, [agents] sets no app_id"


def _first(exc: ReleaseError) -> str:
    """The error's first line, as the gate's error_line gives it"""
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def sweep_permissions(
    seams: Seams, identity: Identity | None, repo: str, maintainers: Sequence[str], dry_run: bool
) -> SweptPermissions:
    """Spec 060 on a tick that sweeps: without the App it reads and writes nothing (D-54); a
    shipmill error, a refused token, read, or write, is the result's, never the tick's"""
    if identity is None:
        return SweptPermissions(NO_APP, None)
    try:
        reads = seams.reads(identity)
        done = notice(reads, lambda: seams.writer(identity), repo, identity.app_id, maintainers, dry_run)
    except ReleaseError as exc:
        failed = Notice(error=_first(exc))
        return SweptPermissions(failed.line(), None if dry_run else failed)
    return SweptPermissions(done.line(), None if dry_run else done)


def api_reads(repo: str, signer: Signer, api: Api, clock: Clock = utc_now) -> Callable[[Identity], Reads]:
    """The CLI's reads: opened with the App's key on each sweep, as open_reads does"""

    def opened(identity: Identity) -> Reads:
        return open_reads(identity, repo, signer, api, clock)

    return opened
