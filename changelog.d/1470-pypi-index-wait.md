### Fixed

- `move-major-tag.yml` no longer fails a release whose version PyPI's index lists a few minutes after the upload, with an error blaming `SHIPMILL_LAND_KEY`: before the App's token check it resolves the release's shipmill past uv's cache every 20 s for up to 10 minutes, and out of time fails naming PyPI's index, with nothing pushed; the token check's helper refreshes uv's cache too, and its error no longer names PyPI (#1470)
