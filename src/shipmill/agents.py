"""The [agents] section of the config: what `shipmill gate` starts a Claude Code session
for, and with which prompt. The prompt carries the scope the user grants ("merge when
green" or not), so it is a reviewed, committed decision like [autonomy]. Where the session
runs (which machine, which scheduler) is not here: that belongs to the host"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from shipmill.app import is_plain_repo
from shipmill.autonomy import AutonomyPolicy
from shipmill.config import CONFIG_PATH, Table, config_path, loads_unchecked, read, read_unchecked
from shipmill.errors import ReleaseError

_MAX_HOURS = 7 * 24  # a week
_PRUNE_HOURS = 6  # the gate's prune runs this often by default (spec 045, D-56)
_SWEEP_HOURS = 6  # the gate reads the timed sections this often by default (spec 046, D-57)
_REMIND_HOURS = 4
_MAX_WAIT_MINUTES = 15
_MAX_WIP = 100
# deprecated and ignored in 0.60.0 (S-031-21), refused since (S-031-22, as D-32 set for [roadmap])
_PLUGIN_UPDATE = "plugin_update"
PLUGIN_UPDATE_REMOVED = f"[agents] {_PLUGIN_UPDATE} was removed (spec 031); delete it"
_PRS = "prs"
# S-040-9: deprecated in 0.78.0 and ignored for one minor release (D-32), refused since (#735)
PRS_REMOVED = (
    f"[agents] {_PRS} was removed (spec 040): [autonomy] land decides whether the gate works on open pull"
    f" requests; delete {_PRS}"
)


class Mode(StrEnum):
    """How a gate session meets a decision for the user (spec 005)"""

    INTERACTIVE = "interactive"  # `claude --bg`: it asks you and waits
    HEADLESS = "headless"  # `claude -p`: it asks on GitHub and ends (D-17)


class Plugin(StrEnum):
    """Where the shipmill plugin is turned on (spec 033): per person, or for the whole repo"""

    HOST = "host"  # each person installs it on their own host; nothing in the repo turns it on
    REPO = "repo"  # .claude/settings.json enables it, so every session in the repo loads it


def plugin_of(table: Table) -> Plugin:
    """[agents] plugin: "host" when absent; any other value, or one that isn't a string, exits 2"""
    value = table.raw.get("plugin", Plugin.HOST.value)
    if not isinstance(value, str) or value not in {p.value for p in Plugin}:
        raise ReleaseError(f'{CONFIG_PATH}: [agents] plugin must be "host" (the default) or "repo", got {value!r}')
    return Plugin(value)


class WriteAs(StrEnum):
    """[agents] identity: whom a write through `shipmill gh` goes as (spec 037)"""

    APP = "app"  # the App, when app_id is set; refused when it isn't
    HOST = "host"  # the host's gh login, as the repo chose; never with app_id (D-14)


def identity_of(table: Table) -> WriteAs:
    """[agents] identity: "app" when absent; any other value, or one that isn't a string, exits 2"""
    value = table.raw.get("identity", WriteAs.APP.value)
    if not isinstance(value, str) or value not in {i.value for i in WriteAs}:
        raise ReleaseError(f'{CONFIG_PATH}: [agents] identity must be "app" (the default) or "host", got {value!r}')
    return WriteAs(value)


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
    retry_hours: int  # unchanged findings start a new session after this
    prune_hours: int = _PRUNE_HOURS  # the gate prunes landed worktrees this often; 0: every tick (spec 045)
    sweep_hours: int = _SWEEP_HOURS  # the gate reads the timed sections this often (spec 046)
    notify: bool = True  # a desktop notification when a session waits on you
    remind_hours: int = _REMIND_HOURS  # repeat it while the session still waits
    max_wait_minutes: int = _MAX_WAIT_MINUTES  # stop a session that waited this long; 0: never
    app_id: int | None = None  # sessions write as this GitHub App (spec 004, D-14); None: the host's gh login
    mode: Mode = Mode.INTERACTIVE  # headless: `claude -p` (spec 005); either mode asks via needs-decision (D-21)
    wip: int | None = None  # at most this many issues in progress at once, read by triage (D-32); None: no limit
    roles: RolesConfig = RolesConfig()  # [agents.roles]: who receives a step an agent can't do (spec 036)
    plugin: Plugin = Plugin.HOST  # [agents] plugin: per person, or committed for the repo (spec 033)
    identity: WriteAs = WriteAs.APP  # [agents] identity: who `shipmill gh` writes as without app_id (spec 037)
    # [autonomy], as `shipmill autonomy` reads it; load and Policy.parse set it, parse alone
    # can't, as it sees [agents] only
    autonomy: AutonomyPolicy = AutonomyPolicy()

    @classmethod
    def parse(cls, table: Table) -> AgentsConfig:
        if _PLUGIN_UPDATE in table.raw:  # whatever its value, before the unknown-keys error
            raise ReleaseError(PLUGIN_UPDATE_REMOVED)
        if _PRS in table.raw:  # S-040-9, as S-031-22 refuses plugin_update
            raise ReleaseError(PRS_REMOVED)
        table.allow(
            "prompt",
            "retry_hours",
            "prune_hours",
            "sweep_hours",
            "notify",
            "remind_hours",
            "max_wait_minutes",
            "app_id",
            "mode",
            "wip",
            "roles",
            "plugin",
            "identity",
        )
        roles = RolesConfig.parse(table.raw["roles"]) if "roles" in table.raw else RolesConfig()
        prompt = table.string("prompt").strip()
        if not prompt:
            raise ReleaseError(f"{table.where}: prompt must not be empty")
        app_id = table.integer("app_id", default=None, low=1, high=None)
        identity = identity_of(table)
        if identity is WriteAs.HOST and app_id is not None:
            raise ReleaseError(
                f'{CONFIG_PATH}: [agents] identity = "host" and [agents] app_id can\'t both be set: a repo with an '
                'App writes as the App or not at all (D-14); delete identity, or set it to "app"'
            )
        retry = table.integer("retry_hours", default=24, low=1, high=_MAX_HOURS)
        prune_hours = table.integer("prune_hours", default=_PRUNE_HOURS, low=0, high=_MAX_HOURS)
        sweep_hours = table.integer("sweep_hours", default=_SWEEP_HOURS, low=1, high=_MAX_HOURS)
        remind = table.integer("remind_hours", default=_REMIND_HOURS, low=1, high=_MAX_HOURS)
        max_wait = table.integer("max_wait_minutes", default=_MAX_WAIT_MINUTES, low=0, high=_MAX_HOURS * 60)
        assert retry is not None and prune_hours is not None and sweep_hours is not None  # defaults were given
        assert remind is not None and max_wait is not None
        return cls(
            prompt=prompt,
            retry_hours=retry,
            prune_hours=prune_hours,
            sweep_hours=sweep_hours,
            notify=table.boolean("notify", default=True),
            remind_hours=remind,
            max_wait_minutes=max_wait,
            app_id=app_id,
            mode=table.enum("mode", Mode, default=Mode.INTERACTIVE),
            wip=table.integer("wip", default=None, low=1, high=_MAX_WIP),
            roles=roles,
            plugin=plugin_of(table),
            identity=identity,
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
        top = Table(raw, path.name)
        agents = cls.parse(top.table("agents"))
        product = ProductConfig.read(top, agents.app_id)  # the gate refuses a bad [product] too
        if product is not None:
            product.refuse_self(repo)
        return agents.with_autonomy(AutonomyPolicy.parse(top.table("autonomy", optional=True)))

    def with_autonomy(self, autonomy: AutonomyPolicy) -> AgentsConfig:
        """The section with the config's [autonomy], so the gate's levels are the ones
        `shipmill autonomy` prints; the prompt's words raise no stage (S-040-6)"""
        return replace(self, autonomy=autonomy)


def app_id_of(root: Path) -> int | None:
    """The checkout's [agents] app_id, or None with no config file, no [agents] section, or no
    app_id; a malformed [agents] section still fails"""
    return gh_identity_of(root).app_id


@dataclass(frozen=True, slots=True)
class GhIdentity:
    """What `shipmill gh` reads of a checkout's config (spec 037): [agents] app_id and identity,
    and whether the config file exists, which the refusal names"""

    config: bool  # .github/shipmill.toml exists
    app_id: int | None = None
    identity: WriteAs = WriteAs.APP


def gh_identity_of(root: Path) -> GhIdentity:
    """The checkout's [agents] app_id and identity, parsed once; the defaults with no config
    file or no [agents] section. A malformed [agents] section still fails"""
    if not (root / CONFIG_PATH).is_file():
        return GhIdentity(config=False)
    path = config_path(root)
    raw = read(path)
    if "agents" not in raw:
        return GhIdentity(config=True)
    agents = AgentsConfig.parse(Table(raw, path.name).table("agents"))
    return GhIdentity(True, agents.app_id, agents.identity)


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
    def parse(cls, table: Table, app_id: int | None) -> ProductConfig | None:
        """app_id is the same file's [agents] app_id: `repos` needs it. None for a repo that
        stands alone, `standalone = true` (spec 043), which reads as no table"""
        table.allow("home", "repos", "standalone")
        if "standalone" in table.raw:
            cls._standalone(table)
            return None
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

    @staticmethod
    def _standalone(table: Table) -> None:
        """S-043-1: standalone takes only true, alone in the table; it needs no [agents] app_id"""
        if others := sorted(set(table.raw) - {"standalone"}):
            raise ReleaseError(
                f"{table.where}: standalone can't be set beside {others[0]}; a repo that stands alone sets "
                "standalone = true alone, a product's repo sets home or repos instead"
            )
        value = table.raw["standalone"]
        if value is not True:
            raise ReleaseError(
                f"{table.where}: standalone takes only true, got {value!r}; to join a product, replace it "
                "with home (in a component) or repos (in the product's home repo)"
            )

    @classmethod
    def read(cls, top: Table, app_id: int | None) -> ProductConfig | None:
        """The config's [product] table, or None without one or for `standalone = true`"""
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
        return cls._alone(read_unchecked(path), path.name)

    @classmethod
    def of_text(cls, text: str, where: str) -> ProductConfig | None:
        """Another repo's [product] alone, read as `load` reads the checkout's, from the text
        of its config; where names it in a refusal (spec 038's doctor, D-53)"""
        return cls._alone(loads_unchecked(text, where), where)

    @classmethod
    def _alone(cls, raw: Mapping[str, Any], where: str) -> ProductConfig | None:
        if "product" not in raw:
            return None
        top = Table(raw, where)
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
