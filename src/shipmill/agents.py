"""The [agents] section of the config: what `shipmill gate` starts a Claude Code session
for, and with which prompt. The prompt carries the scope the user grants ("merge when
green" or not), so it is a reviewed, committed decision like [autonomy]. Where the session
runs (which machine, which scheduler) is not here: that belongs to the host"""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from shipmill.app import is_plain_repo
from shipmill.config import CONFIG_PATH, Table, config_path, read, read_unchecked
from shipmill.errors import ReleaseError

_MAX_HOURS = 7 * 24  # a week
_REMIND_HOURS = 4
_MAX_WAIT_MINUTES = 15
_MAX_WIP = 100
# deprecated and ignored in 0.60.0 (S-031-21), refused since (S-031-22, as D-32 set for [roadmap])
_PLUGIN_UPDATE = "plugin_update"
PLUGIN_UPDATE_REMOVED = f"[agents] {_PLUGIN_UPDATE} was removed (spec 031); delete it"


class Mode(StrEnum):
    """How a gate session meets a decision for the user (spec 005)"""

    INTERACTIVE = "interactive"  # `claude --bg`: it asks you and waits
    HEADLESS = "headless"  # `claude -p`: it asks on GitHub and ends (D-17)


ROLES = "[agents.roles]"
MAINTAINER = "maintainer"  # the role every step an agent can't do falls back to (spec 036)
_ROLE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,44}")  # its label, role:<name>, stays within GitHub's 50
_LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
_TEAM = re.compile(rf"@(?P<org>{_LOGIN})/(?P<slug>[A-Za-z0-9][A-Za-z0-9_-]{{0,99}})")  # as triage_state.py


class RolesError(ReleaseError):
    """A malformed [agents.roles] (S-036-2): every reader of the config exits 2 with it, and
    doctor too, rather than reporting it as a failed check"""


@dataclass(frozen=True, slots=True)
class RoleName:
    """A role's name, such as infra: lowercase letters, digits, and '-', at most 45 characters"""

    value: str

    def __post_init__(self) -> None:
        if not _ROLE_NAME.fullmatch(self.value):
            raise RolesError(
                f"{ROLES} {self.value!r}: a role name is lowercase letters, digits, and '-', starting with a "
                "letter or digit, at most 45 characters"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Login:
    """A GitHub user's login, such as octocat; never an App's bot, name[bot]"""

    value: str

    def __post_init__(self) -> None:
        if self.value.lower().endswith("[bot]"):
            raise ReleaseError(f"{self.value!r} is an App's bot; a role is filled by people")
        if not re.fullmatch(_LOGIN, self.value):
            raise ReleaseError(f"{self.value!r} is neither a GitHub login nor a team as @org/team")

    @property
    def key(self) -> str:
        """Logins compare case-insensitively"""
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Team:
    """A GitHub team, written @org/team-slug: mentioned, since a team can't be assigned"""

    org: str
    slug: str

    @classmethod
    def parse(cls, text: str) -> Team:
        m = _TEAM.fullmatch(text)
        if m is None:
            raise ReleaseError(f"{text!r} is neither a GitHub login nor a team as @org/team")
        return cls(m["org"], m["slug"])

    @property
    def key(self) -> str:
        """Teams compare case-insensitively"""
        return f"@{self.org}/{self.slug}".lower()

    def __str__(self) -> str:
        return f"@{self.org}/{self.slug}"


type Filler = Login | Team


def filler(text: str) -> Filler:
    """A role's filler as the config writes it: a login, or a team as @org/team"""
    return Team.parse(text) if text.startswith("@") else Login(text)


@dataclass(frozen=True, slots=True)
class Role:
    """A role as [agents.roles] lists it; no fillers: nobody fills it yet"""

    name: RoleName
    fillers: tuple[Filler, ...]

    @property
    def users(self) -> tuple[Login, ...]:
        return tuple(f for f in self.fillers if isinstance(f, Login))

    @property
    def teams(self) -> tuple[Team, ...]:
        return tuple(f for f in self.fillers if isinstance(f, Team))

    @classmethod
    def parse(cls, key: str, value: object) -> Role:
        name = RoleName(key)
        if isinstance(value, dict):
            raise RolesError(
                f"{ROLES} {key}: agent-filled roles aren't supported yet; list GitHub logins and @org/team entries"
            )
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise RolesError(f"{ROLES} {key} must be an array of logins and @org/team entries, got {value!r}")
        fillers: list[Filler] = []
        for text in value:
            try:
                found = filler(text)
            except ReleaseError as exc:
                raise RolesError(f"{ROLES} {key}: {exc}") from None
            if any(found.key == f.key for f in fillers):
                raise RolesError(f"{ROLES} {key} lists {found} twice")
            fillers.append(found)
        role = cls(name, tuple(fillers))
        if key == MAINTAINER and role.fillers and not role.users:
            raise RolesError(
                f"{ROLES} {MAINTAINER} lists only teams; the maintainer's steps are assigned at once and a team "
                "can't be assigned, so list at least one login"
            )
        return role


@dataclass(frozen=True, slots=True)
class RolesConfig:
    """The [agents.roles] table (spec 036): each role's fillers, in the table's order. The
    table is optional; with none, the only role is maintainer, the host's gh login"""

    roles: tuple[Role, ...] = ()

    @classmethod
    def parse(cls, raw: object) -> RolesConfig:
        if not isinstance(raw, dict):
            raise RolesError(f"{ROLES} must be a table of role = [logins and @org/team entries], got {raw!r}")
        return cls(tuple(Role.parse(str(key), value) for key, value in raw.items()))

    def get(self, name: str) -> Role | None:
        return next((r for r in self.roles if r.name.value == name), None)


@dataclass(frozen=True, slots=True)
class AgentsConfig:
    prompt: str  # the session's prompt; {repo} becomes owner/name
    prs: bool  # open pull requests count as work, for a prompt that lands them
    retry_hours: int  # unchanged findings start a new session after this
    notify: bool = True  # a desktop notification when a session waits on you
    remind_hours: int = _REMIND_HOURS  # repeat it while the session still waits
    max_wait_minutes: int = _MAX_WAIT_MINUTES  # stop a session that waited this long; 0: never
    app_id: int | None = None  # sessions write as this GitHub App (spec 004, D-14); None: the host's gh login
    mode: Mode = Mode.INTERACTIVE  # headless: `claude -p` (spec 005); either mode asks via needs-decision (D-21)
    wip: int | None = None  # at most this many issues in progress at once, read by triage (D-32); None: no limit
    roles: RolesConfig = RolesConfig()  # [agents.roles]: who receives a step an agent can't do (spec 036)

    @classmethod
    def parse(cls, table: Table) -> AgentsConfig:
        if _PLUGIN_UPDATE in table.raw:  # whatever its value, before the unknown-keys error
            raise ReleaseError(PLUGIN_UPDATE_REMOVED)
        table.allow(
            "prompt",
            "prs",
            "retry_hours",
            "notify",
            "remind_hours",
            "max_wait_minutes",
            "app_id",
            "mode",
            "wip",
            "roles",
        )
        roles = RolesConfig.parse(table.raw["roles"]) if "roles" in table.raw else RolesConfig()
        prompt = table.string("prompt").strip()
        if not prompt:
            raise ReleaseError(f"{table.where}: prompt must not be empty")
        retry = table.integer("retry_hours", default=24, low=1, high=_MAX_HOURS)
        remind = table.integer("remind_hours", default=_REMIND_HOURS, low=1, high=_MAX_HOURS)
        max_wait = table.integer("max_wait_minutes", default=_MAX_WAIT_MINUTES, low=0, high=_MAX_HOURS * 60)
        assert retry is not None and remind is not None and max_wait is not None  # defaults were given
        return cls(
            prompt=prompt,
            prs=table.boolean("prs", default=False),
            retry_hours=retry,
            notify=table.boolean("notify", default=True),
            remind_hours=remind,
            max_wait_minutes=max_wait,
            app_id=table.integer("app_id", default=None, low=1, high=None),
            mode=table.enum("mode", Mode, default=Mode.INTERACTIVE),
            wip=table.integer("wip", default=None, low=1, high=_MAX_WIP),
            roles=roles,
        )

    @classmethod
    def load(cls, root: Path, repo: str | None = None) -> AgentsConfig:
        """The [agents] section alone: a repo may use the gate without the release keys. repo,
        the gate's, must not be named in its own [product] (S-038-3)"""
        if not (root / CONFIG_PATH).is_file():
            raise ReleaseError(f"no {CONFIG_PATH} in {root}; add an [agents] section with a prompt to use the gate")
        path = config_path(root)
        raw = read(path)
        if "agents" not in raw:
            raise ReleaseError(f"{path} has no [agents] section; add one with a prompt to use the gate")
        agents = cls.parse(Table(raw, path.name).table("agents"))
        product = ProductConfig.read(Table(raw, path.name), agents.app_id)  # the gate refuses a bad [product] too
        if product is not None:
            product.refuse_self(repo)
        return agents


def app_id_of(root: Path) -> int | None:
    """The checkout's [agents] app_id, or None with no config file, no [agents] section, or no
    app_id; a malformed [agents] section still fails"""
    if not (root / CONFIG_PATH).is_file():
        return None
    path = config_path(root)
    raw = read(path)
    if "agents" not in raw:
        return None
    return AgentsConfig.parse(Table(raw, path.name).table("agents")).app_id


@dataclass(frozen=True, slots=True)
class ProductConfig:
    """The [product] table (spec 038, D-47): a component names its home repo, the home repo
    names its components; never both. Each repo is owner/name"""

    home: str | None = None  # in a component: the product's home repo
    repos: tuple[str, ...] = ()  # in the home repo: its component repos, none twice

    @property
    def component(self) -> bool:
        return self.home is not None

    @classmethod
    def parse(cls, table: Table, app_id: int | None) -> ProductConfig:
        """app_id is the same file's [agents] app_id: `repos` needs it"""
        table.allow("home", "repos")
        if "home" in table.raw and "repos" in table.raw:
            raise ReleaseError(
                f"{table.where}: home and repos can't both be set; a repo is the product's home (repos) "
                "or one of its components (home)"
            )
        if "home" in table.raw:
            return cls(home=_repo(table, "home", table.string("home")))
        if "repos" not in table.raw:
            raise ReleaseError(f"{table.where}: set home (in a component) or repos (in the product's home repo)")
        repos = tuple(_repo(table, "repos", r) for r in table.strings("repos"))
        if not repos:
            raise ReleaseError(f"{table.where}: repos must list at least one repo")
        seen: set[str] = set()
        for repo in repos:
            if repo.lower() in seen:
                raise ReleaseError(f"{table.where}: repos lists {repo} twice")
            seen.add(repo.lower())
        if app_id is None:
            raise ReleaseError(
                f"{table.where}: repos needs [agents] app_id; the coordinator is the home repo's gate, "
                "and its token over the product's repos comes from that App (D-47)"
            )
        return cls(repos=repos)

    @classmethod
    def read(cls, top: Table, app_id: int | None) -> ProductConfig | None:
        """The config's [product] table, or None without one"""
        return cls.parse(top.table("product"), app_id) if "product" in top.raw else None

    @classmethod
    def load(cls, root: Path) -> ProductConfig | None:
        """The checkout's [product] alone, as `app_id_of` reads [agents]: None with no config
        file or no [product] table; a malformed one, a malformed [agents], or a TOML syntax error
        still fails. The config's requires isn't checked here (S-038-4): the credential helpers
        read this on every call, and never read the config before spec 038"""
        if not (root / CONFIG_PATH).is_file():
            return None
        path = config_path(root)
        raw = read_unchecked(path)
        if "product" not in raw:
            return None
        top = Table(raw, path.name)
        app_id = AgentsConfig.parse(top.table("agents")).app_id if "agents" in raw else None
        return cls.read(top, app_id)

    def refuse_outside(self, repo: str, origin: str | None, what: str) -> None:
        """S-038-10: in a component, what (a gh call, a token) names only the checkout's origin
        repo; another repo, or an origin that can't be told, exits 2 naming D-47"""
        if self.home is None or (origin is not None and repo.lower() == origin.lower()):
            return
        own = "the checkout's origin" if origin is None else origin
        raise ReleaseError(
            f"{what} names {repo}, but this repo is a component of {self.home} ([product] home), "
            f"so its session reads and writes only {own} (D-47); report work for another repo in "
            "this repo, labelled upstream"
        )

    def refuse_self(self, repo: str | None) -> None:
        """S-038-3: a repo never names itself, as its home or as one of its components; None (a
        repo that can't be told) has nothing to compare"""
        if repo is None:
            return
        if self.home is not None and self.home.lower() == repo.lower():
            raise ReleaseError(f"[product] home names {self.home}, this checkout's own repo; a repo never names itself")
        if any(listed.lower() == repo.lower() for listed in self.repos):
            raise ReleaseError(f"[product] repos lists {repo}, this checkout's own repo; a repo never names itself")

    def coordinated(self, repo: str, what: str) -> tuple[str, ...]:
        """S-038-5, S-038-9: the listed repos of repo's owner, which one product token covers;
        exits 2 when the config lists no repos (not the home repo) or doesn't list repo"""
        if not self.repos:
            raise ReleaseError(f"{what} needs [product] repos in {CONFIG_PATH}; only the product's home repo has them")
        if not any(listed.lower() == repo.lower() for listed in self.repos):
            raise ReleaseError(f"{what} names {repo}, which [product] repos doesn't list: {', '.join(self.repos)}")
        owner = repo.partition("/")[0].lower()
        return tuple(listed for listed in self.repos if listed.partition("/")[0].lower() == owner)

    def refuse_product(self) -> None:
        """S-038-10: `--product` is the coordinator's, so in a component it exits 2 naming D-47"""
        if self.home is not None:
            raise ReleaseError(
                f"--product is the coordinator's, in the product's home repo {self.home}; this repo is a "
                "component ([product] home), so its session gets no token over other repos (D-47)"
            )


def _repo(table: Table, key: str, value: str) -> str:
    if not is_plain_repo(value):
        raise ReleaseError(
            f"{table.where}: {key} holds {value!r}; each repo is owner/name of letters, digits, '.', '-', or '_'"
        )
    return value
