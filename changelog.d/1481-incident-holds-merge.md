### Fixed

- The merge gate holds a pull request as `BLOCKED`, naming the incident, while an open incident is on an environment's latest deploy; a revert or a hotfix still reads `READY`, and an incident from an earlier deploy holds nothing (#1481)
