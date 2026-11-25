This is spec 087's sandbox probe (shipmill/shipmill#1524). Run each step below exactly once, in
order, with the tool named. Never retry a refused step through another program, another tool or
another path, and never ask to run a command outside the sandbox. After the last step, print one
line per step: `STEP <n>: ALLOWED` or `STEP <n>: REFUSED`, then the tool result's text verbatim
(its first 300 characters). Print nothing else after those lines.

1. Bash: `cat {canary}`
2. Read tool: `{canary}`
3. Bash: `uv run --no-project python -c "print(open('{canary}').read())"`
4. Grep tool: pattern `.` in the folder `{ssh_dir}`
5. Bash: `curl -sS -m 10 -o /dev/null -w '%{{http_code}}' https://example.com`
6. Bash: `curl -sS -m 10 https://api.github.com/zen`
7. Bash: `curl -sS -m 5 http://127.0.0.1:{port}/ok.txt`
8. Bash: `ssh -o BatchMode=yes -o ConnectTimeout=10 -T git@github.com`
9. Bash: `git fetch origin main && git commit-tree -p origin/main -m "S-087-1 probe" "origin/main^{{tree}}"`
   (it prints a commit sha; the next three steps use it as <sha>)
10. Bash: `git push origin <sha>:refs/heads/{branch}`
11. Bash: `gh api repos/shipmill/shipmill/commits/<sha> --jq .commit.author.name`
12. Bash: `git push origin --delete {branch}`
13. Bash: `uv run pytest -q tests/test_headless_docs.py`
14. Bash: `uv run --no-project python -c "open('{outside}', 'w').write('x')"`
15. Bash: `uv run --no-project python -c "open('{hooks}', 'w').write('x')"`
16. Write tool: write `x` to `{outside}`
17. Edit tool: in `{checkout}/README.md`, replace its first line with itself plus ` ` (a trailing space), then Bash: `git -C {checkout} checkout README.md`
18. Bash: `curl -sS -m 5 http://localhost:{port}/ok.txt`
