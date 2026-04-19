#!/usr/bin/env bash
# log-watcher companion CLI.
# Collects recent log lines from docker containers or local files and emits a
# uniform JSON envelope on stdout.

set -u
set -o pipefail

readonly DEFAULT_TAIL=200
readonly DOCKER_TAIL_MAX=2000
readonly FILE_TAIL_MAX=5000

usage() {
    cat <<'EOF' >&2
Usage:
  log_watcher.sh docker --container NAME [--since DURATION] [--tail N]
  log_watcher.sh file   --path PATH      [--tail N] [--grep REGEX]

Emits a single JSON object on stdout:
  {source, target, lines:[{ts,level,msg,raw}], truncated, line_count, error?}

Non-zero exit + single-line stderr on invalid args / missing deps / unreachable target.
EOF
}

# json_escape STRING
# Minimal JSON string escaper for shell values. Handles backslash, double quote,
# control characters. Produces NO surrounding quotes.
json_escape() {
    local s="$1"
    # shellcheck disable=SC2001
    s=$(printf '%s' "$s" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
    # Strip or escape remaining control characters (tab -> \t, newline handled by caller).
    s=$(printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037')
    s=$(printf '%s' "$s" | sed -e 's/\t/\\t/g')
    printf '%s' "$s"
}

# emit_envelope SOURCE TARGET TRUNCATED LINE_COUNT LINES_JSON_ARRAY [ERROR]
emit_envelope() {
    local source="$1" target="$2" truncated="$3" line_count="$4" lines="$5" err="${6:-}"
    local err_field=""
    if [[ -n "$err" ]]; then
        err_field=",\"error\":\"$(json_escape "$err")\""
    fi
    printf '{"source":"%s","target":"%s","truncated":%s,"line_count":%s,"lines":%s%s}\n' \
        "$source" "$(json_escape "$target")" "$truncated" "$line_count" "$lines" "$err_field"
}

# classify_and_pack RAW_LINE
# Try to parse the line as JSON with ts/level/msg. On success extract fields.
# On failure return raw only. Emits a JSON object for a single line.
classify_and_pack() {
    local raw="$1"
    local ts="" level="" msg=""

    # Cheap heuristic: if line starts with `{` and ends with `}`, attempt field
    # extraction with awk. This avoids a jq runtime dep on minimal images.
    if [[ "$raw" == \{*\} ]]; then
        # ts: accept `ts`, `time`, `timestamp`, `@timestamp` (first match wins)
        for key in ts time timestamp "@timestamp"; do
            ts=$(printf '%s' "$raw" | sed -n 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
            [[ -n "$ts" ]] && break
        done
        level=$(printf '%s' "$raw" | sed -n 's/.*"level"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
        msg=$(printf '%s' "$raw" | sed -n 's/.*"msg"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
    fi

    printf '{"ts":"%s","level":"%s","msg":"%s","raw":"%s"}' \
        "$(json_escape "$ts")" \
        "$(json_escape "$level")" \
        "$(json_escape "$msg")" \
        "$(json_escape "$raw")"
}

# read_stream_to_lines_json
# Reads lines from stdin and writes a JSON array of line objects to stdout.
read_stream_to_lines_json() {
    local first=1
    printf '['
    while IFS= read -r raw || [[ -n "$raw" ]]; do
        [[ $first -eq 1 ]] || printf ','
        first=0
        classify_and_pack "$raw"
    done
    printf ']'
}

# validate_tail N MAX
validate_tail() {
    local n="$1" max="$2"
    if ! [[ "$n" =~ ^[0-9]+$ ]] || (( n < 1 )) || (( n > max )); then
        echo "log-watcher: --tail must be an integer between 1 and $max" >&2
        return 1
    fi
}

# cmd_docker
cmd_docker() {
    local container="" since="1h" tail="$DEFAULT_TAIL"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --container) container="${2:-}"; shift 2 ;;
            --since)     since="${2:-}";     shift 2 ;;
            --tail)      tail="${2:-}";      shift 2 ;;
            *) echo "log-watcher: unknown option: $1" >&2; return 2 ;;
        esac
    done

    if [[ -z "$container" ]]; then
        echo "log-watcher: --container is required" >&2
        return 2
    fi
    if ! [[ "$container" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        echo "log-watcher: invalid container name: $container" >&2
        return 2
    fi
    if ! [[ "$since" =~ ^[0-9]+[smhd]?$ ]]; then
        echo "log-watcher: invalid --since: $since" >&2
        return 2
    fi
    validate_tail "$tail" "$DOCKER_TAIL_MAX" || return 2

    local docker_bin
    docker_bin="${DOCKER_WATCHER_DOCKER_BIN:-docker}"
    if ! command -v "$docker_bin" >/dev/null 2>&1; then
        emit_envelope "docker" "$container" "false" "0" "[]" "docker binary not found on PATH"
        return 3
    fi

    local raw_out
    if ! raw_out=$("$docker_bin" logs --tail "$tail" --since "$since" "$container" 2>&1); then
        emit_envelope "docker" "$container" "false" "0" "[]" "docker logs failed: $raw_out"
        return 3
    fi

    local line_count truncated lines_json
    line_count=$(printf '%s' "$raw_out" | grep -c '^' || true)
    truncated="false"
    if (( line_count >= tail )); then truncated="true"; fi

    lines_json=$(printf '%s\n' "$raw_out" | read_stream_to_lines_json)
    emit_envelope "docker" "$container" "$truncated" "$line_count" "$lines_json"
}

# cmd_file
cmd_file() {
    local path="" tail="$DEFAULT_TAIL" grep_pat=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --path) path="${2:-}";     shift 2 ;;
            --tail) tail="${2:-}";     shift 2 ;;
            --grep) grep_pat="${2:-}"; shift 2 ;;
            *) echo "log-watcher: unknown option: $1" >&2; return 2 ;;
        esac
    done

    if [[ -z "$path" ]]; then
        echo "log-watcher: --path is required" >&2
        return 2
    fi
    validate_tail "$tail" "$FILE_TAIL_MAX" || return 2

    if [[ ! -e "$path" ]]; then
        emit_envelope "file" "$path" "false" "0" "[]" "file not found: $path"
        return 3
    fi
    if [[ ! -r "$path" ]]; then
        emit_envelope "file" "$path" "false" "0" "[]" "file not readable: $path"
        return 3
    fi

    local raw_out
    if [[ -n "$grep_pat" ]]; then
        raw_out=$(grep -E -- "$grep_pat" "$path" 2>/dev/null | tail -n "$tail" || true)
    else
        raw_out=$(tail -n "$tail" "$path" 2>/dev/null || true)
    fi

    local line_count truncated lines_json
    line_count=$(printf '%s' "$raw_out" | grep -c '^' || true)
    truncated="false"
    if (( line_count >= tail )); then truncated="true"; fi

    lines_json=$(printf '%s\n' "$raw_out" | read_stream_to_lines_json)
    emit_envelope "file" "$path" "$truncated" "$line_count" "$lines_json"
}

main() {
    if [[ $# -lt 1 ]]; then
        usage
        return 2
    fi
    local sub="$1"; shift
    case "$sub" in
        docker) cmd_docker "$@" ;;
        file)   cmd_file   "$@" ;;
        -h|--help) usage; return 0 ;;
        *) echo "log-watcher: unknown subcommand: $sub" >&2; usage; return 2 ;;
    esac
}

main "$@"
