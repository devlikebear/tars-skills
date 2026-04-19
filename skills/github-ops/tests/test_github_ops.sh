#!/usr/bin/env bash
# Plain-bash test runner for github_ops.sh.
# Uses fake gh/git binaries on PATH (overridden via GITHUB_OPS_GH_BIN / GITHUB_OPS_GIT_BIN).

set -u
set -o pipefail

readonly TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly SKILL_DIR="$(cd "$TEST_DIR/.." && pwd)"
readonly CLI="$SKILL_DIR/github_ops.sh"

if ! command -v jq >/dev/null 2>&1; then echo "tests require jq"; exit 2; fi

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

# Fake gh behaviours. Use a per-test tmpdir.
make_fake_gh() {
    local tmpdir="$1" mode="$2"
    local bin="$tmpdir/gh"
    case "$mode" in
        issue-list-ok)
            cat >"$bin" <<'EOF'
#!/usr/bin/env bash
# Pretend to be `gh issue list … --json …`
cat <<JSON
[
  {"number":1,"title":"First","state":"OPEN","labels":[{"name":"bug"}],"createdAt":"2026-04-19T10:00:00Z","body":"seen once"},
  {"number":2,"title":"Second","state":"OPEN","labels":[],"createdAt":"2026-04-19T11:00:00Z","body":""}
]
JSON
EOF
            ;;
        issue-create-ok)
            cat >"$bin" <<'EOF'
#!/usr/bin/env bash
echo "https://github.com/devlikebear/tars-examples-foo/issues/42"
EOF
            ;;
        issue-comment-ok)
            cat >"$bin" <<'EOF'
#!/usr/bin/env bash
echo "https://github.com/devlikebear/tars-examples-foo/issues/42#issuecomment-1"
EOF
            ;;
        pr-draft-ok)
            cat >"$bin" <<'EOF'
#!/usr/bin/env bash
echo "https://github.com/devlikebear/tars-examples-foo/pull/7"
EOF
            ;;
        fail)
            cat >"$bin" <<'EOF'
#!/usr/bin/env bash
echo "auth expired" >&2
exit 1
EOF
            ;;
    esac
    chmod +x "$bin"
    export GITHUB_OPS_GH_BIN="$bin"
}

# Real git is fine for worktree tests. We set up a bare fixture repo.
setup_fixture_repo() {
    local tmpdir="$1"
    local repo="$tmpdir/repo"
    git init -q -b main "$repo"
    (cd "$repo" && git -c user.email=test@example.com -c user.name=test commit -q --allow-empty -m "init")
    printf '%s' "$repo"
}

section() { printf "\n== %s ==\n" "$1"; }

# -------------------- issue-search --------------------
test_issue_search_ok() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    make_fake_gh "$tmpdir" "issue-list-ok"
    local out
    out=$("$CLI" issue-search --repo devlikebear/tars-examples-foo --query "boom" --limit 5) || return 1
    assert_json_eq '.ok' 'true' "$out" || return 1
    assert_json_eq '.repo' 'devlikebear/tars-examples-foo' "$out" || return 1
    assert_json_eq '.state' 'open' "$out" || return 1
    assert_json_eq '.items | length' '2' "$out" || return 1
    assert_json_eq '.items[0].number' '1' "$out" || return 1
    assert_json_eq '.items[0].labels[0]' 'bug' "$out" || return 1
}

test_issue_search_rejects_bad_repo() {
    set +e
    "$CLI" issue-search --repo "bad repo" >/dev/null 2>&1
    local rc=$?; set -e
    [[ $rc -eq 2 ]]
}

test_issue_search_rejects_bad_state() {
    set +e
    "$CLI" issue-search --repo a/b --state weird >/dev/null 2>&1
    local rc=$?; set -e
    [[ $rc -eq 2 ]]
}

test_issue_search_missing_gh() {
    export GITHUB_OPS_GH_BIN="/nonexistent/gh"
    local out rc
    set +e; out=$("$CLI" issue-search --repo a/b); rc=$?; set -e
    [[ $rc -ne 0 ]] || return 1
    assert_json_eq '.ok' 'false' "$out" || return 1
    local err; err=$(printf '%s' "$out" | jq -r '.error')
    [[ "$err" == *"gh binary not found"* ]] || return 1
    unset GITHUB_OPS_GH_BIN
}

test_issue_search_gh_failure() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    make_fake_gh "$tmpdir" "fail"
    local out rc
    set +e; out=$("$CLI" issue-search --repo a/b); rc=$?; set -e
    [[ $rc -ne 0 ]] || return 1
    assert_json_eq '.ok' 'false' "$out" || return 1
    local err; err=$(printf '%s' "$out" | jq -r '.error')
    [[ "$err" == *"auth expired"* ]] || return 1
}

# -------------------- issue-create --------------------
test_issue_create_ok() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    make_fake_gh "$tmpdir" "issue-create-ok"
    local out
    out=$("$CLI" issue-create --repo devlikebear/tars-examples-foo --title "boom" --body "panic in handler" --label bug --label auto) || return 1
    assert_json_eq '.ok' 'true' "$out" || return 1
    assert_json_eq '.number' '42' "$out" || return 1
    assert_json_eq '.url' 'https://github.com/devlikebear/tars-examples-foo/issues/42' "$out" || return 1
}

test_issue_create_missing_title() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    make_fake_gh "$tmpdir" "issue-create-ok"
    set +e; "$CLI" issue-create --repo a/b --body foo >/dev/null 2>&1; local rc=$?; set -e
    [[ $rc -eq 2 ]]
}

# -------------------- issue-comment --------------------
test_issue_comment_ok() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    make_fake_gh "$tmpdir" "issue-comment-ok"
    local out
    out=$("$CLI" issue-comment --repo devlikebear/tars-examples-foo --issue 42 --body "ping") || return 1
    assert_json_eq '.ok' 'true' "$out" || return 1
    assert_json_eq '.issue' '42' "$out" || return 1
}

test_issue_comment_rejects_non_numeric_issue() {
    set +e; "$CLI" issue-comment --repo a/b --issue abc --body x >/dev/null 2>&1; local rc=$?; set -e
    [[ $rc -eq 2 ]]
}

# -------------------- pr-draft --------------------
test_pr_draft_ok() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    make_fake_gh "$tmpdir" "pr-draft-ok"
    local out
    out=$("$CLI" pr-draft --repo devlikebear/tars-examples-foo --head feat/x --title t --body b) || return 1
    assert_json_eq '.ok' 'true' "$out" || return 1
    assert_json_eq '.number' '7' "$out" || return 1
}

# -------------------- worktree --------------------
test_worktree_roundtrip() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    local repo; repo=$(setup_fixture_repo "$tmpdir")
    export TARS_WORKSPACE="$tmpdir/ws"
    local out_setup
    out_setup=$("$CLI" worktree-setup --repo-path "$repo" --branch feat/phase-a-test --slug foo) || return 1
    assert_json_eq '.ok' 'true' "$out_setup" || return 1
    assert_json_eq '.branch' 'feat/phase-a-test' "$out_setup" || return 1
    local wt
    wt=$(printf '%s' "$out_setup" | jq -r '.worktree_path')
    [[ -d "$wt" ]] || return 1
    # Cleanup
    local out_clean
    out_clean=$("$CLI" worktree-cleanup --repo-path "$repo" --branch feat/phase-a-test --slug foo) || return 1
    assert_json_eq '.ok' 'true' "$out_clean" || return 1
    assert_json_eq '.removed' 'true' "$out_clean" || return 1
    [[ ! -d "$wt" ]] || return 1
    unset TARS_WORKSPACE
}

test_worktree_rejects_bad_branch() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    local repo; repo=$(setup_fixture_repo "$tmpdir")
    set +e
    "$CLI" worktree-setup --repo-path "$repo" --branch 'bad; rm -rf /' >/dev/null 2>&1
    local rc=$?; set -e
    [[ $rc -eq 2 ]]
}

test_worktree_rejects_non_git_path() {
    local tmpdir; tmpdir=$(mktemp -d); trap "rm -rf '$tmpdir'" RETURN
    set +e
    "$CLI" worktree-setup --repo-path "$tmpdir" --branch feat/x >/dev/null 2>&1
    local rc=$?; set -e
    [[ $rc -eq 2 ]]
}

# -------------------- args --------------------
test_unknown_subcommand() {
    set +e; "$CLI" melons >/dev/null 2>&1; local rc=$?; set -e
    [[ $rc -eq 2 ]]
}

section "issue-search"
expect "issue-search: happy path"         test_issue_search_ok
expect "issue-search: rejects bad repo"   test_issue_search_rejects_bad_repo
expect "issue-search: rejects bad state"  test_issue_search_rejects_bad_state
expect "issue-search: missing gh"         test_issue_search_missing_gh
expect "issue-search: gh auth failure"    test_issue_search_gh_failure

section "issue-create"
expect "issue-create: happy path"         test_issue_create_ok
expect "issue-create: missing title"      test_issue_create_missing_title

section "issue-comment"
expect "issue-comment: happy path"        test_issue_comment_ok
expect "issue-comment: rejects bad num"   test_issue_comment_rejects_non_numeric_issue

section "pr-draft"
expect "pr-draft: happy path"             test_pr_draft_ok

section "worktree"
expect "worktree: setup+cleanup round-trip" test_worktree_roundtrip
expect "worktree: rejects bad branch"     test_worktree_rejects_bad_branch
expect "worktree: rejects non-git path"   test_worktree_rejects_non_git_path

section "args"
expect "unknown subcommand"               test_unknown_subcommand

printf "\n"
if (( FAIL > 0 )); then
    printf "FAIL %d / %d\n" "$FAIL" "$((PASS+FAIL))"
    for t in "${FAILED_TESTS[@]}"; do printf "  - %s\n" "$t"; done
    exit 1
fi
printf "OK %d / %d\n" "$PASS" "$PASS"
