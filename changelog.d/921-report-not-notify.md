### Deprecated

- `[notices]` in `.github/shipmill.toml`: a config that sets it still loads, nothing reads it, and `shipmill doctor` warns naming D-69 and spec 021 until it is deleted (#921)

### Removed

- shipmill posts no notice on a fixed issue (D-69): `shipped.py` drops `--post`, `--install`, and the deployment notice, and reports which closed issues a release or a deployment fixed, with `--json` printing one object per issue (`number`, `tag`, `stage`, `source`); the watch reports no UNANNOUNCED or REQUESTER_CONFIRMED, the gate walks seven tiers without the notices tier, a stable promotion's plan reason counts no confirmed requesters, and metrics' issue to release runs from the issue to the stable release that shipped the pull request closing it; comments already posted stay (#921)
