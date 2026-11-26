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
over those two; the home's list widens the token only while it lists the component (D-84)."""

import datetime as dt
from pathlib import Path

from shipmill.agents import ProductConfig
from shipmill.app import (
    REUSE_FOR,
    TICK_CACHE,
    Api,
    OtherOwner,
    ProductToken,
    Signer,
    contents,
    load_product_token,
    mint_tick,
    save_product_token,
)
from shipmill.config import CONFIG_PATH


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
