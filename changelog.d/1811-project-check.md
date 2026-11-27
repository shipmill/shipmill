### Added

- `shipmill project check <head> --title "<what will be true>" --check-file <path>` files a project's check issue (`Check: <title>` with its `## Check`, and `## Cleanup` from `--cleanup-file`) and links it as the head's sub-issue; it refuses a head that has an open check issue already (spec 108, #1811)
