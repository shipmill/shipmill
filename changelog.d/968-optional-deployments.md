### Added

- The gate's App asks for Deployments: read as an optional permission, so the report reads the environments' deployments; a new App asks for it at creation, and an existing installation accepts it once on the App's installation page (after it is added to the App's permissions). Until then sessions still start, the token never asks for it, and `shipmill doctor` and the gate's GitHub preflight warn naming what to accept (D-77) (#968)
