### Fixed

- A release can publish before it moves its references (D-50): a lane's new `after_publish` workflows start only once each `dispatch` run of the release succeeded and PyPI serves the version, and a publish that fails or never ends leaves them unstarted, naming the run; a lane without `after_publish` lands as before. `move-major-tag.yml` also moves the plugin marketplace `ref`, for the newest stable release only. shipmill's own config turns `after_publish` on in a follow-up, once a release with it is on PyPI and the plugin installs have it (#598)
