# Test gate

A fix needs proof that fails on the old code and passes on the new. A new test is one kind of proof, and the most expensive one to keep: every test added per fix stays in the suite, runs on every push, and is read by every later agent. Add one only when nothing cheaper already catches the regression.

## Before writing a test

Answer each question from the code, in order. The first "yes" is the proof; stop there.

1. **Does an existing test fail on the old code?** Revert the fix locally (`git stash` the production change, keep any test edits) and run the tests that touch the changed symbol. When one goes red for the issue's reason, that test is the proof. Extend it (a new row in its table, one more assertion) only when the issue's repro shape is not already in it
2. **Does the repo's type checker catch it?** When the repo runs a type checker in CI (mypy, pyright, `tsc`) and the bug is a missing attribute or key, a wrong type, or `None` where a value is required, run the checker on the old code. When it reports the bug, the proof is the checker; if it did not report it because the type was too loose (`Any`, a `__getattr__`, an untyped dict), tighten the type as part of the fix instead of adding a test, and show the checker's error on the old code
3. **Does a parser at the boundary catch it?** When bad input caused the bug (a field missing from stored or fetched data, a renamed key, a value nobody listed) and the repo parses that input into a strict model, the fix belongs in the model, and the proof is the model rejecting the bad record with the repro data
4. **Otherwise, write a test.** It guards a behavior or business rule a regression would break: what the code computes, decides, writes or sends. It fails on the old code for the issue's reason and passes after, uses the issue's repro shape, extends an existing test file or parametrized table before adding a new function, asserts results rather than calls on the subject's collaborators, and needs no test-only production seam (a parameter, global or getter only the test uses)

Never add a test that only restates a data shape (a key exists, a field has a type) when the type checker or a boundary model already guarantees it; never replay one regression at every layer it crosses.

## In the PR

The Test plan names the proof and shows it failing on the old code: the existing test's name and its failure, the checker's error line, the model's rejection, or the new test and its failure. A repo rule such as "a fix comes with a test that fails without it" is met by any of these; if the repo's `REVIEW.md` says "test" literally, follow it and say in the PR that the gate would have chosen otherwise, so the maintainer can update the rule.
