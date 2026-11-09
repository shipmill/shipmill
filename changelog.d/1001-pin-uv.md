### Changed

- The reusable workflows pin uv to one exact version, 0.13.7, in every `astral-sh/setup-uv` step instead of installing the newest uv on each run, so a broken uv release no longer stops every connected repo's release at once; a test keeps every step on the same version, and `@v0` and the `tool` input keep floating on purpose (D-80) (#1001)
