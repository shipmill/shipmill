### Added

- `fleet.py queue --order impact` lists what waits on the maintainer by how many open issues each item holds back, most first, then oldest first: one `chains.py impact` walk over every fleet repo gives each row its `holds`, printed on its line and in `--json` with the object's `order`; a walk that fails keeps the oldest-first order, prints `IMPACT_ERROR`, and exits 2. Without `--order` the queue is unchanged. github-ship-watch's Fleet section documents it, and github-issue-triage's Chains section documents `chains.py impact`, `stalled`, and `path` (spec 086) (#1533)
