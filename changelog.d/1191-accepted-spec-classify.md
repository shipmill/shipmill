### Added

- `shipmill decide classify --pr N` reports `accepted-spec` in place of `scope` for a spec whose status line becomes `approved` when every `Spec for #N` issue of the pull request's body is open and either an accepted opportunity (`opportunity` and `planned`) or filed by an OWNER, MEMBER, or COLLABORATOR with no agent marker in its body; the reason names the issues, and anything else, an issue that can't be read included, stays `scope` (#1191)
