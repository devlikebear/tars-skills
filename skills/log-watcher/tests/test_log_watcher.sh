#!/usr/bin/env bash
# Plain-bash test runner for log_watcher.sh. No bats dependency.
# Requires jq for JSON shape assertions.

set -u
set -o pipefail

readonly TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly SKILL_DIR="$(cd "$TEST_DIR/.." && pwd)"
readonly CLI="$SKILL_DIR/log_watcher.sh"

if ! command -v jq >/dev/null 2>&1; then
    echo "tests require jq"; exit 2
fi

PASS=0
FAIL=0
FAILED_TESTS=()

expect() {
    local name="$1"; shift
    if "$@"; then
        PASS=$((PASS+1))
        printf "  ok  %s\n" "$name"
    else
        FAIL=$((FAIL+1))
        FAILED_TESTS+=("$name")
        printf "  FAIL %s\n" "$name"
    fi
}

assert_json_eq() {
    local filter="$1" expected="$2" out="$3"
    local actual
    actual=$(printf '%s' "$out" | jq -r "$filter")
    [[ "$actual" == "$expected" ]] || {
        printf '    filter=%s expected=%q actual=%q\n' "$filter" "$expected" "$actual" >&2
        return 1
    }
}

# ------------------------------------------------------------
# docker subcommand — with a fake docker binary on PATH
# ------------------------------------------------------------
section() { printf "\n== %s ==\n" "$1"; }

setup_fake_docker() {
    local tmpdir="$1" mode="$2"
    local fake="$tmpdir/docker"
    case "$mode" in
        ok)
            cat >"$fake" <<'EOF'
#!/usr/bin/env bash
# Fake docker — emit three JSON-ish log lines and succeed
cat <<LOG
{"ts":"2026-04-19T10:00:00Z","level":"INFO","msg":"startup"}
{"ts":"2026-04-19T10:00:01Z","level":"ERROR","msg":"boom"}
plain text line without json
LOG
EOF
            ;;
        missing_container)
            cat >"$fake" <<'EOF'
#!/usr/bin/env bash
echo "Error: No such container: missing" >&2
exit 1
EOF
            ;;
    esac
    chmod +x "$fake"
    export DOCKER_WATCHER_DOCKER_BIN="$fake"
}

test_docker_ok() {
    local tmpdir; tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" RETURN
    setup_fake_docker "$tmpdir" "ok"
    local out
    out=$("$CLI" docker --container demo --tail 10 2>/dev/null) || return 1
    assert_json_eq '.source'     'docker' "$out" || return 1
    assert_json_eq '.target'     'demo'   "$out" || return 1
    assert_json_eq '.line_count' '3'      "$out" || return 1
    assert_json_eq '.lines[0].level' 'INFO'  "$out" || return 1
    assert_json_eq '.lines[1].level' 'ERROR' "$out" || return 1
    assert_json_eq '.lines[2].level' ''      "$out" || return 1
    assert_json_eq '.lines[2].raw'   'plain text line without json' "$out" || return 1
}

test_docker_missing_container() {
    local tmpdir; tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" RETURN
    setup_fake_docker "$tmpdir" "missing_container"
    local out rc
    set +e
    out=$("$CLI" docker --container missing --tail 10 2>/dev/null)
    rc=$?
    set -e
    [[ $rc -ne 0 ]] || return 1
    assert_json_eq '.line_count' '0' "$out" || return 1
    assert_json_eq '.lines | length' '0' "$out" || return 1
    # error field populated
    local err
    err=$(printf '%s' "$out" | jq -r '.error')
    [[ -n "$err" && "$err" != "null" ]] || return 1
}

test_docker_missing_binary() {
    # Point at a non-existent binary
    export DOCKER_WATCHER_DOCKER_BIN="/nonexistent/docker"
    local out rc
    set +e
    out=$("$CLI" docker --container x --tail 5 2>/dev/null)
    rc=$?
    set -e
    [[ $rc -ne 0 ]] || return 1
    assert_json_eq '.source'     'docker' "$out" || return 1
    local err
    err=$(printf '%s' "$out" | jq -r '.error')
    [[ "$err" == *"docker binary not found"* ]] || return 1
    unset DOCKER_WATCHER_DOCKER_BIN
}

test_docker_rejects_bad_container_name() {
    set +e
    "$CLI" docker --container 'bad; rm -rf /' --tail 5 >/dev/null 2>&1
    local rc=$?
    set -e
    [[ $rc -eq 2 ]]
}

test_docker_rejects_bad_tail() {
    set +e
    "$CLI" docker --container ok --tail 99999 >/dev/null 2>&1
    local rc=$?
    set -e
    [[ $rc -eq 2 ]]
}

# ------------------------------------------------------------
# file subcommand
# ------------------------------------------------------------

test_file_ok() {
    local tmpdir; tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" RETURN
    local logf="$tmpdir/app.log"
    cat >"$logf" <<'EOF'
{"ts":"2026-04-19T10:00:00Z","level":"INFO","msg":"startup"}
{"ts":"2026-04-19T10:00:02Z","level":"ERROR","msg":"boom"}
plain
EOF
    local out
    out=$("$CLI" file --path "$logf" --tail 10 2>/dev/null) || return 1
    assert_json_eq '.source'     'file' "$out" || return 1
    assert_json_eq '.line_count' '3'    "$out" || return 1
    assert_json_eq '.lines[1].level' 'ERROR' "$out" || return 1
}

test_file_grep() {
    local tmpdir; tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" RETURN
    local logf="$tmpdir/app.log"
    cat >"$logf" <<'EOF'
INFO: boring
ERROR: interesting 1
DEBUG: boring
ERROR: interesting 2
EOF
    local out
    out=$("$CLI" file --path "$logf" --grep '^ERROR' --tail 10 2>/dev/null) || return 1
    assert_json_eq '.line_count' '2' "$out" || return 1
    assert_json_eq '.lines[0].raw' 'ERROR: interesting 1' "$out" || return 1
    assert_json_eq '.lines[1].raw' 'ERROR: interesting 2' "$out" || return 1
}

test_file_missing() {
    local out rc
    set +e
    out=$("$CLI" file --path /tmp/definitely-not-here-$$.log --tail 5 2>/dev/null)
    rc=$?
    set -e
    [[ $rc -ne 0 ]] || return 1
    assert_json_eq '.source' 'file' "$out" || return 1
    local err
    err=$(printf '%s' "$out" | jq -r '.error')
    [[ "$err" == *"file not found"* ]] || return 1
}

test_file_truncated_flag() {
    local tmpdir; tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" RETURN
    local logf="$tmpdir/app.log"
    for i in $(seq 1 10); do echo "line $i"; done >"$logf"
    local out
    out=$("$CLI" file --path "$logf" --tail 5 2>/dev/null) || return 1
    assert_json_eq '.truncated'  'true' "$out" || return 1
    assert_json_eq '.line_count' '5'    "$out" || return 1
}

# ------------------------------------------------------------
# argument handling
# ------------------------------------------------------------

test_usage_on_no_args() {
    set +e
    "$CLI" >/dev/null 2>&1
    local rc=$?
    set -e
    [[ $rc -eq 2 ]]
}

test_unknown_subcommand() {
    set +e
    "$CLI" ostriches --container x >/dev/null 2>&1
    local rc=$?
    set -e
    [[ $rc -eq 2 ]]
}

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------

section "docker"
expect "docker: happy path"                test_docker_ok
expect "docker: missing container"         test_docker_missing_container
expect "docker: missing docker binary"     test_docker_missing_binary
expect "docker: rejects bad container"     test_docker_rejects_bad_container_name
expect "docker: rejects --tail out of range" test_docker_rejects_bad_tail

section "file"
expect "file: happy path"                  test_file_ok
expect "file: grep filter"                 test_file_grep
expect "file: missing file"                test_file_missing
expect "file: truncated flag"              test_file_truncated_flag

section "args"
expect "usage on no args"                  test_usage_on_no_args
expect "unknown subcommand"                test_unknown_subcommand

printf "\n"
if (( FAIL > 0 )); then
    printf "FAIL %d / %d\n" "$FAIL" "$((PASS+FAIL))"
    for t in "${FAILED_TESTS[@]}"; do printf "  - %s\n" "$t"; done
    exit 1
fi
printf "OK %d / %d\n" "$PASS" "$PASS"
