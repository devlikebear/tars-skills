#!/usr/bin/env bash
# github-ops companion CLI. Thin wrapper over `gh` and `git worktree`.
# See SKILL.md for argument shapes and output schemas.

set -u
set -o pipefail

readonly REPO_RE='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
readonly BRANCH_RE='^[A-Za-z0-9_./-]+$'
readonly SLUG_RE='^[A-Za-z0-9_.-]+$'
readonly PINT_RE='^[1-9][0-9]*$'

usage() {
    cat <<'EOF' >&2
Usage:
  github_ops.sh issue-search   --repo OWNER/NAME [--query Q] [--state open|closed|all] [--limit N]
  github_ops.sh issue-create   --repo OWNER/NAME --title T --body B [--label L ...]
  github_ops.sh issue-comment  --repo OWNER/NAME --issue N --body B
  github_ops.sh pr-draft       --repo OWNER/NAME --head BR [--base main] --title T --body B
  github_ops.sh worktree-setup --repo-path DIR --branch BR [--base main] [--slug NAME]
  github_ops.sh worktree-cleanup --repo-path DIR --branch BR [--slug NAME]

Emits a single JSON object on stdout. On error: {"ok":false,"error":"..."} + non-zero exit.
EOF
}

# -------------------- json helpers --------------------
json_escape() {
    local s="$1"
    s=$(printf '%s' "$s" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
    s=$(printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037')
    s=$(printf '%s' "$s" | sed -e 's/\t/\\t/g')
    printf '%s' "$s"
}

# fail EXIT_CODE ERROR_MESSAGE
fail() {
    local code="$1"; shift
    printf '{"ok":false,"error":"%s"}\n' "$(json_escape "$*")"
    exit "$code"
}

# -------------------- validation --------------------
validate_repo()   { [[ "$1" =~ $REPO_RE ]]   || fail 2 "invalid repo: $1"; }
validate_branch() { [[ "$1" =~ $BRANCH_RE ]] || fail 2 "invalid branch: $1"; }
validate_slug()   { [[ "$1" =~ $SLUG_RE ]]   || fail 2 "invalid slug: $1"; }
validate_pint()   { [[ "$1" =~ $PINT_RE ]]   || fail 2 "$2 must be a positive integer: $1"; }

gh_bin()  { printf '%s' "${GITHUB_OPS_GH_BIN:-gh}"; }
git_bin() { printf '%s' "${GITHUB_OPS_GIT_BIN:-git}"; }

require_gh() {
    local bin; bin=$(gh_bin)
    command -v "$bin" >/dev/null 2>&1 || fail 3 "gh binary not found on PATH"
}
require_git() {
    local bin; bin=$(git_bin)
    command -v "$bin" >/dev/null 2>&1 || fail 3 "git binary not found on PATH"
}

# -------------------- workspace helpers --------------------
managed_root() {
    local base="${TARS_WORKSPACE:-$PWD/workspace}"
    printf '%s/managed-repos' "$base"
}

slug_default() {
    local repo_path="$1"
    basename "$repo_path"
}

# -------------------- subcommands --------------------

cmd_issue_search() {
    local repo="" query="" state="open" limit="20"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo)  repo="${2:-}";  shift 2 ;;
            --query) query="${2:-}"; shift 2 ;;
            --state) state="${2:-}"; shift 2 ;;
            --limit) limit="${2:-}"; shift 2 ;;
            *) fail 2 "unknown option: $1" ;;
        esac
    done
    [[ -n "$repo" ]] || fail 2 "--repo is required"
    validate_repo "$repo"
    case "$state" in open|closed|all) ;; *) fail 2 "invalid --state: $state" ;; esac
    validate_pint "$limit" "--limit"
    require_gh

    local -a args
    args=(issue list --repo "$repo" --state "$state" --limit "$limit"
          --json "number,title,state,labels,createdAt,body")
    [[ -n "$query" ]] && args+=(--search "$query")

    local raw rc
    raw=$("$(gh_bin)" "${args[@]}" 2>&1); rc=$?
    [[ $rc -eq 0 ]] || fail 3 "gh issue list failed: $raw"

    # Validate raw is a JSON array (jq will fail otherwise). If jq not present,
    # fall back to passing the raw through. Most TARS hosts have jq.
    if command -v jq >/dev/null 2>&1; then
        local items
        items=$(printf '%s' "$raw" | jq -c 'map({
            number,
            title,
            state,
            labels: [.labels[]?.name],
            created_at: .createdAt,
            body: (.body // "")
        })' 2>/dev/null) || fail 3 "gh output was not valid JSON"
        printf '{"ok":true,"repo":"%s","state":"%s","items":%s}\n' \
            "$(json_escape "$repo")" "$state" "$items"
    else
        printf '{"ok":true,"repo":"%s","state":"%s","items_raw":%s}\n' \
            "$(json_escape "$repo")" "$state" "$raw"
    fi
}

cmd_issue_create() {
    local repo="" title="" body=""
    local -a labels=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo)  repo="${2:-}";  shift 2 ;;
            --title) title="${2:-}"; shift 2 ;;
            --body)  body="${2:-}";  shift 2 ;;
            --label) labels+=("${2:-}"); shift 2 ;;
            *) fail 2 "unknown option: $1" ;;
        esac
    done
    [[ -n "$repo"  ]] || fail 2 "--repo is required"
    [[ -n "$title" ]] || fail 2 "--title is required"
    [[ -n "$body"  ]] || fail 2 "--body is required"
    validate_repo "$repo"
    require_gh

    local -a args=(issue create --repo "$repo" --title "$title" --body "$body")
    local l
    for l in "${labels[@]:-}"; do
        [[ -z "$l" ]] && continue
        args+=(--label "$l")
    done

    local raw rc
    raw=$("$(gh_bin)" "${args[@]}" 2>&1); rc=$?
    [[ $rc -eq 0 ]] || fail 3 "gh issue create failed: $raw"

    # gh prints the issue URL on stdout.
    local url number
    url=$(printf '%s' "$raw" | grep -Eo 'https://[^ ]+' | tail -n1)
    number=$(printf '%s' "$url" | grep -Eo '[0-9]+$')
    printf '{"ok":true,"repo":"%s","number":%s,"url":"%s"}\n' \
        "$(json_escape "$repo")" "${number:-0}" "$(json_escape "$url")"
}

cmd_issue_comment() {
    local repo="" issue="" body=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo)  repo="${2:-}";  shift 2 ;;
            --issue) issue="${2:-}"; shift 2 ;;
            --body)  body="${2:-}";  shift 2 ;;
            *) fail 2 "unknown option: $1" ;;
        esac
    done
    [[ -n "$repo"  ]] || fail 2 "--repo is required"
    [[ -n "$issue" ]] || fail 2 "--issue is required"
    [[ -n "$body"  ]] || fail 2 "--body is required"
    validate_repo "$repo"
    validate_pint "$issue" "--issue"
    require_gh

    local raw rc
    raw=$("$(gh_bin)" issue comment "$issue" --repo "$repo" --body "$body" 2>&1); rc=$?
    [[ $rc -eq 0 ]] || fail 3 "gh issue comment failed: $raw"

    local url
    url=$(printf '%s' "$raw" | grep -Eo 'https://[^ ]+' | tail -n1)
    printf '{"ok":true,"repo":"%s","issue":%s,"url":"%s"}\n' \
        "$(json_escape "$repo")" "$issue" "$(json_escape "$url")"
}

cmd_pr_draft() {
    local repo="" head="" base="main" title="" body=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo)  repo="${2:-}";  shift 2 ;;
            --head)  head="${2:-}";  shift 2 ;;
            --base)  base="${2:-}";  shift 2 ;;
            --title) title="${2:-}"; shift 2 ;;
            --body)  body="${2:-}";  shift 2 ;;
            *) fail 2 "unknown option: $1" ;;
        esac
    done
    [[ -n "$repo"  ]] || fail 2 "--repo is required"
    [[ -n "$head"  ]] || fail 2 "--head is required"
    [[ -n "$title" ]] || fail 2 "--title is required"
    [[ -n "$body"  ]] || fail 2 "--body is required"
    validate_repo "$repo"
    validate_branch "$head"
    validate_branch "$base"
    require_gh

    local raw rc
    raw=$("$(gh_bin)" pr create --repo "$repo" --head "$head" --base "$base" \
          --title "$title" --body "$body" --draft 2>&1); rc=$?
    [[ $rc -eq 0 ]] || fail 3 "gh pr create failed: $raw"

    local url number
    url=$(printf '%s' "$raw" | grep -Eo 'https://[^ ]+' | tail -n1)
    number=$(printf '%s' "$url" | grep -Eo '[0-9]+$')
    printf '{"ok":true,"repo":"%s","number":%s,"url":"%s"}\n' \
        "$(json_escape "$repo")" "${number:-0}" "$(json_escape "$url")"
}

cmd_worktree_setup() {
    local repo_path="" branch="" base="main" slug=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo-path) repo_path="${2:-}"; shift 2 ;;
            --branch)    branch="${2:-}";    shift 2 ;;
            --base)      base="${2:-}";      shift 2 ;;
            --slug)      slug="${2:-}";      shift 2 ;;
            *) fail 2 "unknown option: $1" ;;
        esac
    done
    [[ -n "$repo_path" ]] || fail 2 "--repo-path is required"
    [[ -n "$branch"    ]] || fail 2 "--branch is required"
    [[ -d "$repo_path/.git" || -f "$repo_path/.git" ]] || fail 2 "not a git repo: $repo_path"
    validate_branch "$branch"
    validate_branch "$base"
    [[ -z "$slug" ]] && slug=$(slug_default "$repo_path")
    validate_slug "$slug"
    require_git

    local wt_path="$(managed_root)/$slug/$branch"
    mkdir -p "$(dirname "$wt_path")" || fail 3 "mkdir failed: $(dirname "$wt_path")"

    local raw rc
    raw=$("$(git_bin)" -C "$repo_path" worktree add "$wt_path" -b "$branch" "$base" 2>&1); rc=$?
    [[ $rc -eq 0 ]] || fail 3 "git worktree add failed: $raw"

    printf '{"ok":true,"repo_path":"%s","branch":"%s","base":"%s","worktree_path":"%s"}\n' \
        "$(json_escape "$repo_path")" "$(json_escape "$branch")" \
        "$(json_escape "$base")" "$(json_escape "$wt_path")"
}

cmd_worktree_cleanup() {
    local repo_path="" branch="" slug=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo-path) repo_path="${2:-}"; shift 2 ;;
            --branch)    branch="${2:-}";    shift 2 ;;
            --slug)      slug="${2:-}";      shift 2 ;;
            *) fail 2 "unknown option: $1" ;;
        esac
    done
    [[ -n "$repo_path" ]] || fail 2 "--repo-path is required"
    [[ -n "$branch"    ]] || fail 2 "--branch is required"
    validate_branch "$branch"
    [[ -z "$slug" ]] && slug=$(slug_default "$repo_path")
    validate_slug "$slug"
    require_git

    local wt_path="$(managed_root)/$slug/$branch"
    local removed="false"
    if [[ -d "$wt_path" ]]; then
        local raw rc
        raw=$("$(git_bin)" -C "$repo_path" worktree remove "$wt_path" --force 2>&1); rc=$?
        if [[ $rc -ne 0 ]]; then
            # Fall back to rm if git refuses, e.g. for a dangling worktree entry.
            rm -rf "$wt_path" 2>/dev/null || fail 3 "worktree remove failed: $raw"
        fi
        removed="true"
    fi
    "$(git_bin)" -C "$repo_path" worktree prune >/dev/null 2>&1 || true

    printf '{"ok":true,"repo_path":"%s","branch":"%s","worktree_path":"%s","removed":%s}\n' \
        "$(json_escape "$repo_path")" "$(json_escape "$branch")" \
        "$(json_escape "$wt_path")" "$removed"
}

main() {
    if [[ $# -lt 1 ]]; then usage; exit 2; fi
    local sub="$1"; shift
    case "$sub" in
        issue-search)     cmd_issue_search "$@" ;;
        issue-create)     cmd_issue_create "$@" ;;
        issue-comment)    cmd_issue_comment "$@" ;;
        pr-draft)         cmd_pr_draft "$@" ;;
        worktree-setup)   cmd_worktree_setup "$@" ;;
        worktree-cleanup) cmd_worktree_cleanup "$@" ;;
        -h|--help)        usage; exit 0 ;;
        *) fail 2 "unknown subcommand: $sub" ;;
    esac
}

main "$@"
