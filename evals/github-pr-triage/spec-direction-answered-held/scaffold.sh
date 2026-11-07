#!/usr/bin/env bash
# This case's scaffold (spec 025): `claude plugin eval` runs only a scaffold_script inside the
# case's directory, and starts it in place with the empty workspace as its working directory
# and no argument, so this hands the shared evals/scaffold.sh the case's directory
set -euo pipefail
case_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
exec "$case_dir/../../scaffold.sh" "$case_dir" "$PWD"
