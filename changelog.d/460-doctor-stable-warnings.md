### Deprecated

- `[lanes.stable] min_soak_days`: still honoured for this minor release, with a `shipmill doctor` WARN naming spec 029 and `shipmill upgrade --apply stable-every-batch`; the next minor release refuses it. `shipmill doctor` also warns about a prepare or land job lacking `issues: write` for a config whose stable lane can hold a breaking change (`[bump] major`), in the one warning per job it already gives (#460)
