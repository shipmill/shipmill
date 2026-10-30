### Fixed

- The `shipmill status` tests run git without the host's config, so S-008-3's origin check passes under the gate, whose agents rewrite SSH remotes to https (#833)
