"""[[environments.<name>.probes]] (spec 084): the requests operate compares between the new
release and the previous one"""

import tomllib

import pytest

from shipmill.environments import Pointer, Probe
from shipmill.errors import ReleaseError
from shipmill.policy import Policy

from .conftest import POLICY

STAGING = '\n[environments.staging]\nlane = "rc"\nworkflow = "deploy.yml"\n'
ITEMS = '\n[[environments.staging.probes]]\nname = "items"\npath = "/api/items?limit=100"\n'
TABLE = r"policy \[environments\] \[staging\]"


def load(text: str) -> Policy:
    return Policy.parse(tomllib.loads(POLICY + STAGING + text), "policy")


def probe(**keys: object) -> str:
    lines = "".join(f"{key} = {value!r}\n".replace("'", '"') for key, value in keys.items())
    return f"\n[[environments.staging.probes]]\n{lines}"


def test_s084_1_probes_load_with_their_name_path_and_ignore_pointers() -> None:
    text = ITEMS + 'ignore = ["/generated_at", "/items/*/updated_at", "/a~1b/c~0d"]\n'
    text += probe(name="home", path="/")
    [items, home] = load(text).environments["staging"].probes
    assert (items.name, items.path) == ("items", "/api/items?limit=100")
    assert [p.text for p in items.ignore] == ["/generated_at", "/items/*/updated_at", "/a~1b/c~0d"]
    assert items.ignore[2].segments == ("a/b", "c~d")  # RFC 6901: ~1 is '/', ~0 is '~'
    assert home == Probe("home", "/", ())


def test_s084_1_an_environment_without_probes_has_none() -> None:
    assert load("").environments["staging"].probes == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (ITEMS + 'method = "POST"\n', rf"{TABLE} \[\[probes\]\]\[0\]: unknown keys \['method'\]"),
        (ITEMS + probe(name="items", path="/other"), rf"{TABLE} \[\[probes\]\]\[1\]: name 'items' names another"),
        (probe(name="items", path="api/items"), rf"{TABLE} \[\[probes\]\]\[0\]: path starts with '/'"),
        (probe(name="items", path="/api items"), rf"{TABLE} \[\[probes\]\]\[0\]: path .* holds no whitespace"),
        (probe(name="items", path="/", ignore=["items"]), rf"{TABLE} \[\[probes\]\]\[0\]: ignore holds 'items'"),
        (probe(name="items", path="/", ignore=["/a~2"]), r"ignore holds '/a~2': '~' in a JSON pointer is"),
        (probe(name="items", path="/", ignore="/a"), r"ignore must be a list of strings"),
        (probe(path="/"), rf"{TABLE} \[\[probes\]\]\[0\]: name is required"),
        (probe(name="items"), rf"{TABLE} \[\[probes\]\]\[0\]: path is required"),
        (probe(name="a b", path="/"), r"name is letters, digits"),
        ('probes = "items"\n', r"probes must be an array of tables"),
    ],
)
def test_s084_1_a_malformed_probe_names_its_table_and_key(text: str, message: str) -> None:
    with pytest.raises(ReleaseError, match=message):
        load(text)


def test_s084_1_a_21st_probe_is_refused() -> None:
    twenty = "".join(probe(name=f"p{i}", path=f"/{i}") for i in range(20))
    assert len(load(twenty).environments["staging"].probes) == 20
    with pytest.raises(ReleaseError, match=rf"{TABLE}: probes holds 21 tables; at most 20"):
        load(twenty + probe(name="p20", path="/20"))


def test_a_pointer_star_matches_any_one_segment() -> None:
    star = Pointer.parse("/items/*/updated_at")
    assert star.matches(("items", "3", "updated_at"))
    assert not star.matches(("items", "updated_at"))
    assert not star.matches(("items", "3", "updated_at", "x"))
    assert Pointer.parse("/").segments == ("",)  # the key "", as RFC 6901 reads it
