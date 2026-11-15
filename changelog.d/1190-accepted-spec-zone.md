### Added

- The decision policy gains the zone `accepted-spec`, right after `scope`: approving the spec of work the maintainer already accepted, default `ask` and floor `notify`, so `[decisions] accepted-spec = "notify"` is accepted while `"act"` exits 2 naming the floor, and `[decisions.paths.accepted-spec]` exits 2 as the zone takes no paths; `shipmill decide levels` lists it and `retro.py gather --decisions` counts its questions and decided comments in its own row; the default stays `ask`, so no repository changes behaviour on upgrade (spec 067) (#1190)
