### Fixed

- The merge gate counts each check once, by its newest run: a pull request closed and reopened lists two runs of a check on one head, and an older failure no longer fails it after a newer pass, while a newer run still in flight keeps it pending; the `checks=`, `green=`, `pending=` and `failed=` counts now count the deduplicated checks (#962)
