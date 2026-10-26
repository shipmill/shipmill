"""`shipmill roles` (spec 036): who receives each step an agent can't do. The checkout's
[agents.roles] resolved: the maintainer is its listed users and teams, or with none the host's
gh login; a role nobody fills yet falls back to the maintainer's fillers. Printed as lines, as
JSON, or as the `--role NAME=FILLER,...` flags triage_state.py takes"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from shipmill.agents import MAINTAINER, ROLES, AgentsConfig, Filler, Login, RoleName, RolesConfig, Team
from shipmill.config import CONFIG_PATH, Table, config_path, read
from shipmill.errors import ReleaseError

LoginReader = Callable[[], str]  # the host's gh login, `gh api user`, as gate.py's host_login reads it


@dataclass(frozen=True, slots=True)
class ResolvedRole:
    """A role and who fills it; fallback: nobody does yet, so the maintainer's fillers"""

    name: RoleName
    users: tuple[Login, ...]
    teams: tuple[Team, ...]
    fallback: bool

    @property
    def fillers(self) -> tuple[Filler, ...]:
        return (*self.users, *self.teams)

    def line(self) -> str:
        who = " ".join([*(f"@{u}" for u in self.users), *(str(t) for t in self.teams)])
        return f"{self.name}: {who}" + (" (fallback)" if self.fallback else "")

    @property
    def value(self) -> str:
        """The --role flag's value, NAME=FILLER[,FILLER...]"""
        return f"{self.name}={','.join(str(f) for f in self.fillers)}"

    def flag(self) -> str:
        return f"--role {self.value}"

    def record(self) -> dict[str, object]:
        return {"users": [str(u) for u in self.users], "teams": [str(t) for t in self.teams], "fallback": self.fallback}


def configured(root: Path) -> RolesConfig:
    """The checkout's [agents.roles]: none with no config file, no [agents], or no roles table;
    a malformed [agents] still fails"""
    if not (root / CONFIG_PATH).is_file():
        return RolesConfig()
    path = config_path(root)
    raw = read(path)
    if "agents" not in raw:
        return RolesConfig()
    return AgentsConfig.parse(Table(raw, path.name).table("agents")).roles


def resolve(config: RolesConfig, login: LoginReader) -> tuple[ResolvedRole, ...]:
    """maintainer first, then the table's other roles in its order. login is read only when
    the maintainer lists nobody; an unreadable one exits 2 (S-036-4)"""
    name = RoleName(MAINTAINER)
    listed = config.get(MAINTAINER)
    if listed is not None and listed.fillers:
        maintainer = ResolvedRole(name, listed.users, listed.teams, fallback=False)
    else:
        try:
            host = Login(login())
        except ReleaseError as exc:
            raise ReleaseError(
                f"{ROLES} {MAINTAINER} lists nobody, so the maintainer is the host's gh login, which can't be "
                f"read: {exc}"
            ) from None
        maintainer = ResolvedRole(name, (host,), (), fallback=False)
    others = tuple(
        ResolvedRole(r.name, r.users, r.teams, fallback=False)
        if r.fillers
        else ResolvedRole(r.name, maintainer.users, maintainer.teams, fallback=True)
        for r in config.roles
        if r.name.value != MAINTAINER
    )
    return (maintainer, *others)


def text(roles: tuple[ResolvedRole, ...]) -> str:
    return "".join(f"{r.line()}\n" for r in roles)


def as_json(roles: tuple[ResolvedRole, ...]) -> str:
    return json.dumps({"roles": {str(r.name): r.record() for r in roles}}, indent=2) + "\n"


def flags(roles: tuple[ResolvedRole, ...]) -> str:
    """One line: the --role arguments for triage_state.py, one per role, maintainer included"""
    return " ".join(r.flag() for r in roles) + "\n"


def arguments(roles: Sequence[ResolvedRole]) -> list[str]:
    """The --role flags as argv items, `--role` and its value apart, never through a shell"""
    return [item for r in roles for item in ("--role", r.value)]
