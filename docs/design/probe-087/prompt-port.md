This is spec 087's local-port probe (shipmill/shipmill#1588). Run each step below exactly once, in
order, with the tool named. Never retry a refused step through another program, another tool or
another path, and never ask to run a command outside the sandbox. After the last step, print one
line per step: `STEP <n>: ALLOWED` or `STEP <n>: REFUSED`, then the tool result's text verbatim
(its first 300 characters). Print nothing else after those lines.

1. Bash: `curl -sS -m 5 http://127.0.0.1:{port}/ok.txt`
2. Bash: `curl -sS -m 5 http://127.0.0.1:{other}/ok.txt`
3. Bash: `curl -sS -m 5 http://localhost:{port}/ok.txt`
4. Bash: `curl -sS -m 5 'http://[::1]:{port}/ok.txt'`
5. Bash: `curl -sS -m 5 http://127.0.0.2:{port}/ok.txt`
6. Bash: `uv run --no-project python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:{port}/ok.txt', timeout=5).read())"`
7. Bash: `uv run --no-project python -c "import socket; socket.create_connection(('127.0.0.1', {port}), 5); print('connected')"`
8. Bash: `uv run --no-project python -c "import socket; socket.create_connection(('127.0.0.1', {other}), 5); print('connected')"`
9. Bash: `uv run --no-project python -c "import os; print({{k: v for k, v in os.environ.items() if k.lower() == 'no_proxy'}})"`
10. Bash: `curl -sS -m 5 --noproxy '' http://127.0.0.1:{port}/ok.txt`
11. Bash: `curl -sS -m 5 --noproxy '' http://127.0.0.1:{other}/ok.txt`
12. Bash: `curl -sS -m 5 --noproxy '' http://localhost:{port}/ok.txt`
