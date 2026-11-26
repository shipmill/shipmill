"""Spec 093, The tick's read token: an installation token of the gate's App that can only read,
over the gate's repo and the product's repos the watch reads there under its owner, which a
gate tick's own GitHub reads run with instead of the maintainer's login.

It is cached in the gate's state folder as `app-token-tick.json` (mode 0600 from creation),
apart from the session's `app-token.json` and every other token's file, and reused while the
same App minted it, it covers the same repos, and it has at least 10 minutes left. A dry run
reuses a cached one but writes none. The token is only ever returned: nothing here prints it,
logs it, writes it to a session's helpers or environment, or passes it in a process's
arguments, and a refusal never quotes it.

In a component the home's `[product] repos` is read from the home's config on its default
branch, with the cached token when it covers the gate's repo and the home, else with one minted
over those two; the home's list widens the token only while it lists the component (D-84).

A tick's reads take it through TickReads (S-093-1 to S-093-3): settled once, at the tick's
first GitHub read, as the App with the token or as the host saying why, each read command gets
its own environment from it, and the gate's own `os.environ` never holds the token."""

import datetime as dt
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from shipmill.agents import ProductConfig, app_id_of
from shipmill.app import (
    REUSE_FOR,
    TICK_CACHE,
    Api,
    OtherOwner,
    ProductToken,
    Signer,
    contents,
    default_key,
    load_product_token,
    mint_tick,
    save_product_token,
)
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError

NO_APP = "no [agents] app_id"  # the why of a tick that reads as the host because no App is configured
READS_AS_KEYS = {"identity", "why"}


class Reader(StrEnum):
    """Whose budget a tick's reads draw on"""

    APP = "app"
    HOST = "host"


@dataclass(frozen=True, slots=True)
class ReadsAs:
    """Whose budget a tick's reads drew on (spec 093, What the tick records): the App's, with no
    why, or the host's, with why: no [agents] app_id, a product repo of another owner, or the
    mint's error's first line"""

    identity: Reader
    why: str | None = None

    def __post_init__(self) -> None:
        if self.identity is Reader.APP and self.why is not None:
            raise ValueError("reads_as app has no why")
        if self.identity is Reader.HOST and not self.why:
            raise ValueError("reads_as host must say why")

    @property
    def fell_back(self) -> bool:
        """S-093-9: an App is configured, yet the reads went as the host"""
        return self.identity is Reader.HOST and self.why != NO_APP

    def record(self) -> dict[str, object]:
        return {"identity": self.identity.value, "why": self.why}

    @classmethod
    def of(cls, value: object) -> ReadsAs | None:
        """tick.json's reads_as, as record writes it, or null; a malformed one raises ValueError"""
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != READS_AS_KEYS:
            raise ValueError("reads_as: expected exactly identity and why, or null")
        identity, why = value["identity"], value["why"]
        if not isinstance(identity, str) or (why is not None and not isinstance(why, str)):
            raise ValueError("reads_as: identity must be a string, why a string or null")
        return cls(Reader(identity), why)  # Reader refuses anything but app or host


AS_APP = ReadsAs(Reader.APP)
WITHOUT_APP = ReadsAs(Reader.HOST, NO_APP)


Settle = Callable[[], tuple[ReadsAs, str | None]]  # whose the reads are, and the token as the App


class TickReads:
    """One tick's reads (S-093-1 to S-093-3): settled at the first call of env, once a tick,
    and the environment each read command runs with: as the App, the gate's own environment
    with GH_TOKEN the tick's read token; as the host, None, the gate's own as it is. The token
    lives here alone: no repr, record, or message shows it, and os.environ is never changed"""

    __slots__ = ("_environ", "_reads_as", "_settle", "_token")

    def __init__(self, settle: Settle, environ: Mapping[str, str] = os.environ) -> None:
        self._settle = settle
        self._environ = environ
        self._reads_as: ReadsAs | None = None
        self._token: str | None = None

    def __repr__(self) -> str:
        return f"TickReads(reads_as={self._reads_as!r})"

    @property
    def reads_as(self) -> ReadsAs | None:
        """None until the tick's first GitHub read (S-093-12)"""
        return self._reads_as

    def env(self) -> dict[str, str] | None:
        if self._reads_as is None:
            self._reads_as, self._token = self._settle()
        if self._token is None:
            return None
        return {**self._environ, "GH_TOKEN": self._token}


def settle(
    root: Path,
    repo: str,
    state: Path,
    key: Path | None,
    home: Path,
    clock: Callable[[], dt.datetime],
    signer: Signer,
    api: Api,
    write: bool,
) -> Settle:
    """The CLI's TickReads settle: with the checkout's [agents] app_id, the tick's read token
    (tick_token) with the key `shipmill gate` uses (key, else the App's default path under
    home), else the host, `no [agents] app_id`. Any shipmill error on the way, reading the
    config included, reads as the host with its first line as why and never fails the tick
    (S-093-9); a dry run passes write false"""

    def settled() -> tuple[ReadsAs, str | None]:
        try:
            app_id = app_id_of(root)
            if app_id is None:
                return WITHOUT_APP, None
            product = ProductConfig.load(root)
            path = key if key is not None else default_key(app_id, home)
            found = tick_token(state, repo, product, app_id, path, clock(), signer, api, write)
        except ReleaseError as exc:
            lines = str(exc).strip().splitlines()
            return ReadsAs(Reader.HOST, lines[0] if lines else type(exc).__name__), None
        return AS_APP, found.value

    return settled


def tick_repos(repo: str, product: ProductConfig | None, listed: tuple[str, ...] = ()) -> tuple[str, ...]:
    """S-093-5: the repos the tick's read token is asked for, the gate's repo first, each once
    with case ignored: repo alone without [product]; in the home repo, repo and its [product]
    repos; in a component, repo, its [product] home, and listed, the home's [product] repos.
    A repo of another owner than repo's raises OtherOwner naming it, before any request"""
    if product is None:
        named: tuple[str, ...] = ()
    elif product.home is not None:
        named = (product.home, *listed)
    else:
        named = product.repos
    owner = repo.partition("/")[0].lower()
    asked = [repo]
    for each in named:
        if each.partition("/")[0].lower() != owner:
            raise OtherOwner(each)
        if all(each.lower() != known.lower() for known in asked):
            asked.append(each)
    return tuple(asked)


def home_repos(home: str, component: str, token: str, api: Api) -> tuple[str, ...]:
    """The home's [product] repos, read from its config on its default branch with token; none
    when GitHub has no such file, its config has no [product] repos, or they don't list the
    component (D-84). A config that can't be read or parsed raises"""
    where = f"{home}:{CONFIG_PATH}"
    text = contents(home, str(CONFIG_PATH), token, api)
    found = None if text is None else ProductConfig.of_text(text, where)
    return found.repos if found is not None and found.lists(component) else ()


def _covers(token: ProductToken, repos: tuple[str, ...]) -> bool:
    covered = {r.lower() for r in token.repos}
    return all(r.lower() in covered for r in repos)


def tick_token(
    state: Path,
    repo: str,
    product: ProductConfig | None,
    app_id: int,
    key: Path,
    now: dt.datetime,
    signer: Signer,
    api: Api,
    write: bool,
) -> ProductToken:
    """S-093-4 to S-093-7: the tick's read token for the gate's repo, from state's
    `app-token-tick.json` while the same App minted it, it covers the very repos asked, and it
    has at least 10 minutes left, else minted (mint_tick) and, when write, cached there; a dry
    run passes write false. A product naming a repo of another owner raises OtherOwner; any
    failure raises a ReleaseError, and a refused token is never returned or cached"""
    base = tick_repos(repo, product)
    cache = state / TICK_CACHE
    cached = load_product_token(cache)
    usable = cached if cached is not None and cached.app_id == app_id and cached.expires - now >= REUSE_FOR else None
    probe: ProductToken | None = None
    if product is not None and product.home is not None:
        probe = usable if usable is not None and _covers(usable, base) else None
        if probe is None:
            probe = mint_tick(app_id, base, key, now, signer, api)
        repos = tick_repos(repo, product, home_repos(product.home, repo, probe.value, api))
    else:
        repos = base
    if usable is not None and usable.reusable(repos, app_id, now):
        return usable
    if probe is not None and probe is not usable and probe.reusable(repos, app_id, now):
        fresh = probe  # the home lists nothing more: the token that read its list is the one asked
    else:
        fresh = mint_tick(app_id, repos, key, now, signer, api)
    if write:
        save_product_token(cache, fresh)
    return fresh
