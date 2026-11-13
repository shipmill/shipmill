### Added

- Goals: the twelve stage metrics (`issue_to_agent_comment_*`, `issue_to_pr_*`, `issue_to_pr_person_*`, `issue_to_pr_agent_*`, `pr_to_merge_*`, `merge_to_release_*`, each `_median` and `_p90`) join the goal-measure registry with `<n>h` or `<n>d` targets, and the weekly retro reads their status; a missed `issue_to_release_*` or `lead_time_*` goal gains `grew_most`, the stage that grew most from the week before, shown as `grew most:` on its Goals row (#1092)
