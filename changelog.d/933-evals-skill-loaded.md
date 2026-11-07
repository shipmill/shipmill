### Fixed

- Evals: the 12 cases whose prompt opens with a `/shipmill:<skill>` slash command no longer fail every run on a `skill-loaded` grader, since the slash command puts the skill's text in the prompt and the session never calls the Skill tool; the grader stays in the cases that reach their skill by its description (#933)
