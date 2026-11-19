"""Spec 071: a component reads its product's direction, the home's docs/product.md and the
files under docs/product/ its moved sections link, as committed on the home's default branch.
It reads them through spec 065's read token (D-84): an installation token of the App over the
home repo alone, asking only reads, whose every request is a GET of the contents API on the
home. A token is minted only while the home's .github/shipmill.toml lists the component
(S-065-3), and is reused from, and saved to, the component's read-token cache. Whatever keeps
the home's direction from being read exits 2 naming the home and the fix (S-071-7)"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from shipmill.agents import ProductConfig, app_id_of
from shipmill.app import (
    APP_KEY,
    Api,
    NotInstalled,
    Signer,
    cached_read_token,
    contents,
    install_fix,
    mint_read,
    read_cache,
    require_key,
    save_product_token,
    session_key,
)
from shipmill.config import CONFIG_PATH
from shipmill.errors import ReleaseError
from shipmill.gate import state_dir
from shipmill.gitrepo import Git
from shipmill.product import Fetch, Inherited, read_home
from shipmill.product import home_refusal as _refused


@dataclass(frozen=True, slots=True)
class HomeReach:
    """What a component reaches its home with: GitHub's REST API, the JWT's signer, this
    process's environment (SHIPMILL_APP_KEY), and the user's home, under which the App's key
    lies by default"""

    api: Api
    signer: Signer
    environ: Mapping[str, str]
    home: Path


def inherited(root: Path, home: str, component: str | None, reach: HomeReach, now: dt.datetime) -> Inherited:
    """The product's direction for the component checked out at root, whose [product] home is
    home and whose GitHub repo is component (None when its origin can't be told)"""
    return read_home(home, _fetcher(root, home, component, reach, now))


def _fetcher(root: Path, home: str, component: str | None, reach: HomeReach, now: dt.datetime) -> Fetch:
    if component is None:
        raise _refused(
            home,
            "this checkout's origin isn't a GitHub repo, so the component reading can't be told (D-84)",
            "point origin at the component's GitHub repo",
        )
    app_id = app_id_of(root)
    if app_id is None:
        raise _refused(
            home,
            f"{CONFIG_PATH} sets no [agents] app_id, and the read token comes from that App (spec 065)",
            f"set [agents] app_id in {CONFIG_PATH}",
        )
    cache = state_dir(Git(root)) / read_cache(home.partition("/")[0])
    cached = cached_read_token(cache, (home,), app_id, now)
    if cached is not None:
        token = cached.value
    else:
        key = session_key(app_id, reach.environ, reach.home)
        try:
            require_key(key)
            minted = mint_read(app_id, (home,), key, now, reach.signer, reach.api)
        except NotInstalled as exc:
            raise _refused(home, f"the read token can't be minted: {exc}", f"run `{install_fix(home)}`") from None
        except ReleaseError as exc:
            first = str(exc).splitlines()[0]
            raise _refused(
                home,
                f"the read token can't be minted: {first}",
                f"put the App's key at {key} or name it in {APP_KEY}, and check the App's installation on {home}",
            ) from None
        token = minted.value
        _require_listed(home, component, token, reach.api)
        save_product_token(cache, minted)

    def fetch(file: str) -> str | None:
        try:
            return contents(home, file, token, reach.api)
        except ReleaseError as exc:
            raise _refused(home, f"{home}:{file} can't be read ({exc})", "retry once GitHub answers") from None

    return fetch


def _require_listed(home: str, component: str, token: str, api: Api) -> None:
    """S-065-3: the home's config on its default branch lists the component"""
    where = f"{home}:{CONFIG_PATH}"
    fix = f'add "{component}" to [product] repos in {home}\'s {CONFIG_PATH}'
    try:
        text = contents(home, str(CONFIG_PATH), token, api)
        found = None if text is None else ProductConfig.of_text(text, where)
    except ReleaseError as exc:
        raise _refused(home, f"{where} can't be read ({exc})", fix) from None
    if text is None:
        raise _refused(home, f"GitHub has no {where} on its default branch", fix)
    if found is None or not found.lists(component):
        raise _refused(home, f"its [product] repos doesn't list {component} (D-84)", fix)
