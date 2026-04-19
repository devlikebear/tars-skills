---
name: log-anomaly-detect
description: "Scan a container's recent logs, identify anomalies, deduplicate against prior signatures and existing GitHub issues, and file new issues or comment on recurrences."
version: 0.1.0
user-invocable: true
recommended_tools:
  - bash
  - memory_search
  - memory_save
tags:
  - observability
  - anomaly
  - github
  - dogfooding
---

# log-anomaly-detect

TARS 도그푸딩의 감시→이슈 흐름을 담당하는 절차 skill. Phase A에서 설치된
`log-watcher` + `github-ops` CLI를 조합해 로그를 수집·분류하고, `memory_*`
도구로 중복 여부를 판단한 뒤 GitHub 이슈를 등록한다.

## 입력 (호출자 또는 자연어에서 추출)

- `container` — 감시 대상 Docker 컨테이너 이름 (필수)
- `repo` — 이슈를 등록할 `owner/name` (필수)
- `since` — log-watcher에 넘길 시간 창, 기본 `30m`
- `tail` — 라인 상한, 기본 `500`, 최대 `2000`
- `max_new_issues` — 한 실행에서 새로 등록할 이슈 상한, 기본 `5`

입력이 빠지면 합리적 기본값으로 진행하지 말고 호출자에게 되묻는다.

## 절차

### 1. 로그 수집

```bash
bash <skill_dir>/../log-watcher/log_watcher.sh docker \
  --container <container> --since <since> --tail <tail>
```

결과는 `{source, target, lines[{ts, level, msg, raw}], truncated,
line_count}` 엔벨로프. 실패 시 `error` 필드가 채워진다. 빈 응답(라인 0건)은
"이상 없음"으로 간주하고 즉시 종료.

### 2. anomaly 분류

받은 `lines` 배열을 LLM이 직접 분석한다. 다음 규칙을 적용:

- **trigger 대상**: `level == "ERROR"` 이거나 `msg`가 `panic`, `fatal`,
  `stack`, `database is locked`, `deadline`, `refused`, `timeout`을 포함
- **무시(노이즈)**: `level == "INFO"`의 `request` 로그, 헬스체크 응답,
  기동/종료 메시지
- **그룹화**: 같은 `msg` + 같은 error prefix(첫 80자)를 한 anomaly로 묶고
  첫 발생 시각, 마지막 발생 시각, 횟수, 대표 stack top frame 3줄을 기록
- **signature**: `<msg> :: <error_prefix_80>` 형태의 짧은 키. dedup에 사용
- **component 추정**: stack trace에서 `package/file.go:line` 첫 프레임을 뽑아
  소괄호 형태(`<short_file>:<line>`)로 요약. 미상이면 `unknown`
- **severity**:
  - `critical` — panic/fatal/stack/deadlock
  - `warn` — timeout/refused/locked/connection
  - `info` — 그 외 ERROR (판단 어려우면 warn)
- **confidence**: 자신의 판단에 대해 `high`/`medium`/`low` self-report

### 3. dedup 검사 (anomaly 각각에 대해)

**3-a. memory_search**로 과거 signature 조회:

```
memory_search(query="dogfooding <repo> <signature>", limit=5)
```

기존 매치가 있고 `issue_url`을 포함하면 재발로 분류. 없으면 다음 단계.

**3-b. github-ops로 기존 이슈 조회**:

```bash
bash <skill_dir>/../github-ops/github_ops.sh issue-search \
  --repo <repo> --state all --query "[auto] <short-component> <keyword>"
```

쿼리는 `[auto] <component>: <anomaly 앞단어 몇 개>` 수준으로. 제목 완전일치가
아니라 **키워드 포함 검색**이다. 반환 `items[]`에서 `title`이 `[auto]`로 시작
하고 `component`가 일치하는 건을 재발로 간주.

**3-c. memory와 GitHub 중 하나라도 매치되면 재발**로 분류. 모호하면 **보수적으로
재발로 판단** (중복 이슈 회피가 우선).

### 4. 이슈 등록 / 코멘트

**4-a. 신규 (memory·GitHub 모두 미매치)**:

`templates/issue_body.md`를 채워 본문 작성 후:

```bash
bash <skill_dir>/../github-ops/github_ops.sh issue-create \
  --repo <repo> \
  --title "[auto] <component>: <one-line-summary>" \
  --body "<rendered body>" \
  --label auto-detected \
  --label "severity:<level>" \
  --label "component:<component>"
```

생성 직후 반환된 `url`을 꺼내 다음을 실행:

```
memory_save(
  summary="anomaly signature=<signature> issue=<url>",
  category="error_resolved",
  tags=["dogfooding","<repo>","auto-detected","<component>"],
  importance=5
)
```

**4-b. 재발 (매치 있음)**:

기존 이슈 번호에 코멘트:

```bash
bash <skill_dir>/../github-ops/github_ops.sh issue-comment \
  --repo <repo> --number <N> --body "<재발 템플릿>"
```

재발 본문은 최소 다음 포함: 재발 시각(UTC+KST), 이번 창에서 관측 횟수, 대표
로그 발췌(전후 5줄). memory도 갱신한다 (`importance`는 기존보다 1 증가).

### 5. 안전장치

- **신규 이슈 cap**: `max_new_issues`를 초과할 때 남은 신규는 **한 건으로 묶어서**
  "다중 신규 anomaly" 이슈 1건으로 축약 등록. 절대로 상한을 넘어 개별 등록하지 않는다
- **gh/docker 실패**: CLI의 `ok:false` 응답을 받으면 해당 anomaly 처리 중단,
  이후 anomaly는 진행
- **명시적 중단 키워드**: 응답 본문에 `rate limit`, `401`, `403`이 포함되면
  즉시 전체 중단하고 요약에 `"aborted": true`를 담아 반환
- **빈 결과**: anomaly 0건이면 이슈/코멘트/memory 접근을 전혀 하지 않는다

### 6. 요약 응답

마지막에 JSON 형태로 다음 구조를 출력:

```json
{
  "container": "<name>",
  "repo": "<owner/name>",
  "window": "<since>",
  "new_issues": [{"url":"...","title":"...","component":"...","severity":"..."}],
  "recurrences": [{"url":"...","count":N}],
  "ignored_noise_count": N,
  "aborted": false
}
```

## 이슈 템플릿

본문은 같은 디렉토리 `templates/issue_body.md`를 사용한다. 템플릿의
`{{변수}}` 자리는 LLM이 직접 치환.

## LLM tier 권장

분류·요약 중심이라 `standard` 티어면 충분. 실제 운영에서 비용 문제 있으면
`light`로 낮춰도 되나 stack trace 해석 품질이 떨어질 수 있음.

## 수동 테스트 (Phase B 검증)

Phase A에서 시드된 `tars-examples-foo`를 대상으로:

1. `curl -X POST localhost:8080/bug/panic` — nil deref 유발
2. 이 skill 호출 — `container=tars-examples-foo`, `repo=devlikebear/tars-examples-foo`
3. GitHub에서 `[auto]` 라벨 이슈 확인
4. 같은 엔드포인트 재호출 → 같은 skill 재실행 → 신규 이슈 X, 기존 이슈 코멘트만
5. `/bug/bad` 트리거 → 새 component → 신규 별도 이슈
