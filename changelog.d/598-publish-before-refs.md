### Fixed

- A release publishes before it moves its references (D-50): a lane's new `after_publish` workflows start only once each `dispatch` run of the release succeeded and PyPI serves the version, and a publish that fails or never ends leaves them unstarted, naming the run. shipmill's own `@v0` and plugin marketplace `ref` now move in `move-major-tag.yml` after publish, no longer in the release commit; a lane without `after_publish` lands as before (#598)
