### Fixed

- `move-major-tag.yml` with `land-environment` set proves the App's token with a dry-run push to the default branch before the major tag moves, so a bad `SHIPMILL_LAND_KEY` or an App that can't push fails with nothing pushed instead of leaving the major tag on the new release and the marketplace on the old one; a missing `.github/shipmill.toml` fails with an error naming the fix, not a traceback, the App's credential helper quotes the key's path so one with a space works, and a release that isn't the newest stable one no longer reads the key at all (#1188)
