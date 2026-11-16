### Fixed

- A release workflow opted in to landing as the App now passes its `land` job `secrets: inherit`, so `land.yml` reads the `shipmill-land` environment's `SHIPMILL_LAND_KEY`: without it a called workflow saw the secret empty and no stable release landed. `shipmill init --caller --land-as-app --force` writes it; a caller written before needs the line added (#1180)
