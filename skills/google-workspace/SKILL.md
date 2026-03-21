---
name: google-workspace
description: Google Workspace 개인비서 스킬. gogcli(gog)를 사용하여 캘린더, 이메일, 드라이브, 태스크를 관리한다.
user-invocable: true
recommended_tools:
  - bash
---
# Google Workspace 개인비서 스킬

gogcli(`gog`) CLI를 사용하여 Google Calendar, Gmail, Drive, Tasks를 조회·관리하는 개인비서 스킬.

## 사전 조건
- `gog` CLI 설치 및 인증 완료 (`gog auth add devlikebear@gmail.com`)
- 계정: devlikebear@gmail.com

## 핵심 원칙
- 모든 `gog` 명령에 `--json` 플래그를 붙여 구조화된 출력을 받는다.
- 사용자에게 보여줄 때는 한국어로 요약한다.
- 파괴적 작업(삭제, 발송)은 반드시 사용자 확인 후 실행한다.
- 개인정보가 포함된 내용은 요약만 보여주고 전문은 요청 시에만 표시한다.

---

## 캘린더 (Google Calendar)

### 오늘 일정 조회
```bash
gog calendar events --from today --to today --json
```

### 특정 기간 일정 조회
```bash
gog calendar events --from "2026-03-21" --to "2026-03-25" --json
```

### 일정 검색
```bash
gog calendar search "회의" --json
```

### 일정 생성
```bash
gog calendar create primary --summary "팀 미팅" --start "2026-03-22T14:00:00" --end "2026-03-22T15:00:00" --json
```

### 일정 수정
```bash
gog calendar update primary <eventId> --summary "변경된 제목" --json
```

### 일정 삭제 (확인 필요)
```bash
gog calendar delete primary <eventId>
```

### 빈 시간 확인
```bash
gog calendar freebusy devlikebear@gmail.com --from "2026-03-22T09:00:00" --to "2026-03-22T18:00:00" --json
```

---

## 이메일 (Gmail)

### 미읽은 메일 조회
```bash
gog gmail search "is:unread" --max 10 --json
```

### 받은편지함 최신 메일
```bash
gog gmail search "in:inbox" --max 10 --json
```

### 특정 발신자 메일 검색
```bash
gog gmail search "from:someone@example.com" --max 10 --json
```

### 메일 본문 읽기
```bash
gog gmail get <messageId> --json
```

### 메일 발송 (확인 필요)
```bash
gog gmail send --to "recipient@example.com" --subject "제목" --body "본문" --json
```

### 라벨 목록
```bash
gog gmail labels list --json
```

---

## 드라이브 (Google Drive)

### 루트 폴더 파일 목록
```bash
gog drive ls --max 20 --json
```

### 특정 폴더 내 파일
```bash
gog drive ls --parent <folderId> --json
```

### 파일 검색
```bash
gog drive search "보고서" --json
```

### 파일 다운로드
```bash
gog drive download <fileId>
```

### 파일 업로드
```bash
gog drive upload /path/to/file --parent <folderId> --json
```

---

## 태스크 (Google Tasks)

### 태스크 리스트 목록
```bash
gog tasks lists list --json
```

### 태스크 조회
```bash
gog tasks list <tasklistId> --json
```

### 태스크 추가
```bash
gog tasks add <tasklistId> --title "할 일" --json
```

### 태스크 완료
```bash
gog tasks done <tasklistId> <taskId>
```

---

## 통합 브리핑

사용자가 "오늘 브리핑" 또는 "모닝 브리핑"을 요청하면 아래를 순서대로 실행하고 한국어로 요약한다:

1. **오늘 일정**: `gog calendar events --from today --to today --json`
2. **미읽은 메일**: `gog gmail search "is:unread" --max 10 --json`
3. **오늘 마감 태스크**: `gog tasks list <tasklistId> --json` (due today 필터)

### 브리핑 출력 형식
```
## 오늘의 브리핑 (YYYY-MM-DD)

### 일정
- HH:MM ~ HH:MM  일정 제목
- (없으면 "오늘 일정이 없습니다")

### 미읽은 메일 (N건)
- 발신자 — 제목 (시간)
- ...

### 할 일
- [ ] 태스크 제목 (마감일)
- ...
```
