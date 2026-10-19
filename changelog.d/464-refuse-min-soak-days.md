### Removed

- `[lanes.stable] min_soak_days`, deprecated in 0.53.0: a policy that sets it, whatever its value, exits 2 with `[lanes.stable] min_soak_days was removed (spec 029); delete it, or run shipmill upgrade --apply stable-every-batch`, and `shipmill doctor` reports that as its policy failure. `shipmill upgrade --apply stable-every-batch` still reads and fixes such a config. `promote_from = "rc"` promotes the newest rc once a stable trigger is due, whatever its age, and its reason says how old the rc is, `promotes v1.5.0rc2, cut 1 day(s) ago`, instead of `soaked 1 day(s)` (#464)
