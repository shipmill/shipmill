### Added

- The registry metrics `decided_credited` and `decided_written_as_decider` (unit `ratio`, target `<n>%`): a measure in `docs/product.md` can hold on the share of the decided work GitHub credits to every decider, or written as the decider with the agent as co-author; `shipmill product check` refuses an `h`, `d`, or `/week` target for them, the weekly retro reads them from metrics.py's Decided work credited and Decided work written as the decider, and shipmill-setup offers them (#1835)
