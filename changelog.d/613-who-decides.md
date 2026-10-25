### Added

- github-issue-triage's `needs-decision.md` opens with "Who decides": in a repo whose config has `[agents]`, a session asks `shipmill decide classify` first, then places what code doesn't see in a zone, takes the strictest level among a decision's zones (`unknown` when none fits), and follows it: `act` goes on, `notify` posts a `<!-- shipmill:decided zone=<id> until=<time> -->` comment and the `decided` label and goes on, `ask` asks with the zone on the question's second line, and `never` prepares the change and leaves the step to the maintainer, even after a yes in chat; it also says how a veto is taken up. The design gate, the spec gate, the triage comments, and the resolve, PR triage, and product intake skills point to it, `docs/flow.md` gains a "Who decides" section with the zone table, and four eval cases cover act, notify, ask, and never (spec 030, S-030-21, S-030-22) (#613)

### Changed

- In a repo whose config has `[agents]`, a won't fix, duplicate, postpone, or close verdict, a reading of a spec, and an additive contract change carry a decided comment and the `decided` label at their default `notify` level, where they went on before with only the triage comment (#613)
