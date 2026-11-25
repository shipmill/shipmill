#!/usr/bin/env bash
# Spec 087's probe (S-087-1): one real `claude -p` started as a sandboxed headless launch would
# start it, with a canary in ~/.ssh in place of a real key. Run from the gate's checkout (or a
# linked worktree of it) on a host where the gate already wrote its App helpers.
#
#   probe.sh <out dir>           the spec's settings, with no project settings file
#   probe.sh <out dir> widen     the same, plus a .claude/settings.local.json in the checkout
#                                that adds example.com to allowedDomains
#   probe.sh <out dir> port      #1588: allowedDomains names one local port, 127.0.0.1:18765, in
#                                place of the bare localhost, and prompt-port.md's checks run
#   probe.sh <out dir> binding   #1588: no local entry in allowedDomains and
#                                sandbox.network.allowLocalBinding on, with prompt-port.md
#
# The port modes serve the same file on 127.0.0.1:18765 (the named port), 127.0.0.1:18766 (another
# local port) and [::1]:18765 (the named port on another loopback address).
#
# Writes <out dir>/settings.json, prompt.txt, session.jsonl and result.txt. The canary, the local
# web server and the widening file are removed on exit, whatever happens.
set -euo pipefail

out=$(mkdir -p "${1:?usage: probe.sh <out dir> [widen]}" && cd "$1" && pwd)
mode=${2:-plain}
here=$(cd "$(dirname "$0")" && pwd)
checkout=$(git rev-parse --show-toplevel)
common=$(git rev-parse --path-format=absolute --git-common-dir)
app_id=$(sed -n 's/^app_id *= *\([0-9]*\).*/\1/p' "$checkout/.github/shipmill.toml")
key="$HOME/.config/shipmill/app-$app_id.pem"
slug=shipmill-romamo
bot_id=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]]['bot_id'])" "$common/shipmill/bot-ids.json" "$app_id")
login="$slug[bot]"
email="$bot_id+$slug[bot]@users.noreply.github.com"
port=18765
other=18766
stamp=$(date +%s)
canary="$HOME/.ssh/shipmill-probe-canary-$stamp"
outside="$HOME/shipmill-probe-outside-$stamp"
widen_file="$checkout/.claude/settings.local.json"
servers=""

cleanup() {
    rm -f "$canary" "$outside" "$common/hooks/shipmill-probe-$stamp"
    [ "$mode" = widen ] && rm -f "$widen_file" && rmdir "$checkout/.claude" 2>/dev/null || true
    for pid in $servers; do kill "$pid" 2>/dev/null || true; done
    [ ! -e "$canary" ] && echo "canary removed: $canary"
}
trap cleanup EXIT

mkdir -p "$HOME/.ssh" "$out/www"
python3 -c "import secrets;print(secrets.token_hex(16))" > "$canary"
chmod 600 "$canary"
echo ok > "$out/www/ok.txt"
serve() {
    python3 -m http.server "$1" --bind "$2" --directory "$out/www" >/dev/null 2>&1 &
    servers+=" $!"
}
serve "$port" 127.0.0.1
case "$mode" in
    plain|widen) prompt="$here/prompt.md" ;;
    port|binding) prompt="$here/prompt-port.md"; serve "$other" 127.0.0.1; serve "$port" ::1 ;;
    *) echo "unknown mode $mode" >&2; exit 2 ;;
esac

if [ "$mode" = widen ]; then
    [ -e "$widen_file" ] && { echo "refusing to overwrite $widen_file" >&2; exit 2; }
    mkdir -p "$checkout/.claude"
    echo '{"sandbox": {"network": {"allowedDomains": ["example.com"]}}}' > "$widen_file"
fi

python3 "$here/settings.py" "$checkout" "$key" "$login" "$email" romamo "$mode" "$port" > "$out/settings.json"
python3 - "$prompt" "$out/prompt.txt" <<EOF
import sys
text = open(sys.argv[1]).read().format(
    canary="$canary", ssh_dir="$HOME/.ssh", port=$port, other=$other, branch="probe/s-087-1-$stamp",
    outside="$outside", checkout="$checkout", hooks="$common/hooks/shipmill-probe-$stamp",
)
open(sys.argv[2], "w").write(text)
EOF

# S-005-3's command line with S-087's settings; Bash(cat|curl|ssh *) join the allowlist so the
# probe's commands reach the sandbox instead of the allowlist's denial (#1524)
# Edit and Write scoped to the write scope and the session's memory, as spec 087 amends HEADLESS_TOOLS
scope=$(python3 -c "import json,sys;print(' '.join(json.load(open(sys.argv[1]))['sandbox']['filesystem']['allowWrite']))" "$out/settings.json")
memory="$HOME/.claude/projects/$(python3 -c "import sys;print(''.join(c if c.isalnum() or c=='-' else '-' for c in sys.argv[1]))" "$checkout")/memory"
tools="Read Glob Grep Skill Agent SendMessage ListAgents TodoWrite"
for path in $scope "$memory"; do tools+=" Edit(/$path/**) Write(/$path/**)"; done
tools+=" Bash(gh *) Bash(git *) Bash(uv *) Bash(uvx *) Bash(cat *) Bash(curl *) Bash(ssh *)"
claude --version > "$out/version.txt"
(
    cd "$checkout"
    claude -p --permission-prompts none --output-format stream-json --verbose \
        --allowedTools "$tools" --disallowedTools AskUserQuestion \
        --session-id "$(python3 -c 'import uuid;print(uuid.uuid4())')" \
        --settings "$(cat "$out/settings.json")" -n "s-087-1-probe-$mode" \
        -- "$(cat "$out/prompt.txt")" < /dev/null > "$out/session.jsonl" 2>&1
) || echo "claude exited $?" >> "$out/session.jsonl"
python3 -c "
import json,sys
for line in open(sys.argv[1]):
    try: m = json.loads(line)
    except ValueError: continue
    if m.get('type') == 'result': print(m.get('result', ''))
" "$out/session.jsonl" > "$out/result.txt"
cat "$out/result.txt"
