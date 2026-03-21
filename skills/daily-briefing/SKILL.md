---
name: daily-briefing
description: "Daily briefing skill that aggregates calendar, email, and task summaries using a helper script."
user-invocable: true
recommended_tools:
  - bash
---
# Daily Briefing

이 스킬은 부속 스크립트 `briefing.sh`를 실행하여 오늘의 브리핑을 수집하고 요약한다.

## 사용법

1. 같은 디렉토리에 있는 `briefing.sh` 스크립트를 `read_file`로 확인한다.
2. `bash`로 스크립트를 실행한다.
3. 출력 결과를 한국어로 요약한다.

## 스크립트 위치

이 스킬의 디렉토리에 다음 파일이 함께 설치된다:
- `briefing.sh` — 브리핑 데이터를 수집하는 셸 스크립트
- `templates/summary.txt` — 출력 템플릿

## 실행

```bash
bash <skill_dir>/briefing.sh
```

결과를 `templates/summary.txt` 형식에 맞춰 정리한다.
