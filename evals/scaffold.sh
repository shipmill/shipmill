#!/usr/bin/env bash
# Materialise an eval case's workspace (spec 025): this repository at the case's `commit`,
# with the case's fixture/ at .eval/ for the offline gh stub (evals/bin/gh).
#
#   evals/scaffold.sh [CASE_DIR [WORKSPACE]]
#
# Calling convention (assumed, not confirmed against `claude plugin eval --scaffold`): the
# runner starts the script with the workspace as its working directory. The case's directory
# is the first argument, else $EVAL_CASE_DIR; the workspace is the second argument, else the
# working directory. The workspace must be empty or missing, as `git clone` needs.
#
# Steps: a shared clone of the checkout this script sits in, a detached checkout of the
# case's `commit` from evals/cases.toml (the entry whose `path` is the case's directory
# relative to evals/), fixture/repo/ committed over it when the case has one, then
# fixture/ copied to .eval/ with an empty .eval/gh.jsonl, and
# .eval/case naming the case's directory for EVAL_GH_RECORD=1. .eval/ is excluded from git
# in the workspace, so a session's `git add -A` never commits it.
set -euo pipefail

die() {
  echo "scaffold: $*" >&2
  exit 1
}

evals_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
case_arg=${1:-${EVAL_CASE_DIR:-}}
[ -n "$case_arg" ] || die "name the case's directory: scaffold.sh CASE_DIR [WORKSPACE], or set EVAL_CASE_DIR"
[ -d "$case_arg" ] || die "no case directory $case_arg"
case_dir=$(cd "$case_arg" && pwd -P)
workspace=${2:-$PWD}

case "$case_dir/" in
  "$evals_dir"/*) rel=${case_dir#"$evals_dir"/} ;;
  *) die "$case_dir is not under $evals_dir" ;;
esac
[ -d "$case_dir/fixture" ] || die "$rel has no fixture/"
manifest="$evals_dir/cases.toml"
[ -f "$manifest" ] || die "no manifest $manifest"

# The `commit` of the [[case]] whose `path` is $rel; values are one-line basic strings
commit=$(awk -v want="$rel" '
  function value(line) { sub(/^[^=]*=[ \t]*"/, "", line); sub(/".*$/, "", line); return line }
  /^[ \t]*\[\[case\]\]/ { if (path == want && sha != "") exit; path = ""; sha = ""; next }
  /^[ \t]*path[ \t]*=/ { path = value($0) }
  /^[ \t]*commit[ \t]*=/ { sha = value($0) }
  END { if (path == want && sha != "") print sha }
' "$manifest")
[ -n "$commit" ] || die "$manifest has no [[case]] with path \"$rel\" and a commit"

source_repo=$(git -C "$evals_dir" rev-parse --show-toplevel)
git clone --quiet --shared --no-checkout "$source_repo" "$workspace"
git -C "$workspace" checkout --quiet --detach "$commit"

# A case may change files of the repository at its commit: fixture/repo/ (a config with
# [autonomy] levels no commit here holds, spec 040) is copied over the checkout and
# committed on top, so the session's git sees a clean tree in that state
if [ -d "$case_dir/fixture/repo" ]; then
  cp -R "$case_dir/fixture/repo/." "$workspace/"
  git -C "$workspace" add -A
  git -C "$workspace" -c user.name=shipmill-evals -c user.email=evals@shipmill.invalid -c commit.gpgsign=false \
    commit --quiet -m "eval: the case's repository state"
fi

mkdir "$workspace/.eval"
cp -R "$case_dir/fixture/." "$workspace/.eval/"
: >"$workspace/.eval/gh.jsonl"
printf '%s\n' "$case_dir" >"$workspace/.eval/case"
git_dir=$(git -C "$workspace" rev-parse --absolute-git-dir)
mkdir -p "$git_dir/info"
printf '.eval/\n' >>"$git_dir/info/exclude"
