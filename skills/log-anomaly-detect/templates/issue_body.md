## 발생 시각

- UTC: {{first_seen_utc}} (마지막: {{last_seen_utc}})
- KST: {{first_seen_kst}} (마지막: {{last_seen_kst}})
- 창(window): `{{since}}` / 이번 수집에서 관측 횟수: **{{occurrences}}**

## 감지 패턴

- 서명(signature): `{{signature}}`
- 레벨: `{{level}}`
- 심각도: `severity:{{severity}}`
- 추정 컴포넌트: `{{component}}`
- LLM 신뢰도: `{{confidence}}` (high/medium/low)

## 로그 발췌

아래는 해당 anomaly 전후 라인 발췌. 전체 원본은 `log-watcher docker --tail`로 재수집 가능.

```
{{log_excerpt}}
```

### 대표 stack top frames

```
{{stack_top_frames}}
```

## 재발 여부

- `memory_search` 매치: {{memory_match_summary}}
- `[auto]` 라벨 기존 이슈 매치: {{github_match_summary}}
- 판단: **신규**

## 재현 방법 (추정)

{{reproduce_guess}}

## 진단/수정에 필요한 추가 정보

- [ ] 발생 빈도 추이 (메트릭 필요 시 별도 task)
- [ ] 관련 최근 배포 / 설정 변경
- [ ] 유사 anomaly 이슈와의 관계

---

*이 이슈는 `log-anomaly-detect` skill이 자동 등록했습니다. 실제 버그가 아닐 수 있으니 확인 후 `not-a-bug` 라벨로 닫아주세요.*
