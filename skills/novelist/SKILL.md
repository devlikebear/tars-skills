---
name: novelist
description: Long-running creative project guide that interviews the user, maintains BRIEF/STATE docs, and advances a story project in small steps.
user-invocable: true
---
# Novelist Skill

이 스킬은 장기 창작 프로젝트를 작은 단계로 이어가는 외부 스킬입니다.

## Core Contract
- 프로젝트가 아직 없으면 현재 세션의 `BRIEF.md`를 기준으로 사용자와 티키타카하며 요구사항을 구체화합니다.
- 이미 프로젝트가 있으면 `PROJECT.md`, `STATE.md`, `STORY_BIBLE.md`, `CHARACTERS.md`, `PLOT.md`를 읽고 현재 상태를 파악합니다.
- 한 번에 1-3개의 질문만 던집니다.
- 충분한 정보가 모이지 않았는데 임의로 프로젝트를 확정하지 않습니다.
- 사용자가 확인하기 전에는 brief를 `finalized`로 만들지 않습니다.

## Recommended Tools
- `read_file`
- `write_file`
- `project_brief_get`
- `project_brief_update`
- `project_brief_finalize`
- `project_state_get`
- `project_state_update`
- `project_get`
- `project_update`
- `project_activate`
- `memory_search`
- `sessions_history`

## Recommended Project Files
- `BRIEF.md`
- `PROJECT.md`
- `STATE.md`
- `STORY_BIBLE.md`
- `CHARACTERS.md`
- `PLOT.md`

## Wake Phases
- `plan`
- `draft`
- `review`
- `update_state`

## Interview Mode
- `project_brief_get`으로 현재 brief를 읽습니다.
- 정보가 부족하면 다음 우선순위로 질문합니다:
  1. 작품 목표와 완성 조건
  2. 장르와 분위기
  3. 분량, 연재 주기, 총 화수
  4. 핵심 플롯과 반드시 넣을 요소 / 피할 요소
- 새 결정사항은 `project_brief_update`로 바로 brief에 반영합니다.
- brief가 충분히 채워지면 요약을 보여주고 사용자 확인을 받은 뒤 `project_brief_finalize`를 사용합니다.
- brief만 있는 상태에서는 `cron_create`/`schedule_create`로 자율 집필 작업을 예약하지 않습니다.
- 사용자가 "이후에는 네가 알아서" 또는 "크론으로 계속 써"라고 말해도, 먼저 brief 요약을 보여주고 `project_brief_finalize`로 실제 프로젝트를 만든 뒤에만 예약합니다.
- 프로젝트가 아직 없다면 사용자가 요청한 자동 진행은 다음처럼 안내합니다:
  1. brief 요약
  2. finalize 확인
  3. `project_brief_finalize`
  4. 그 다음에 `project_id`를 포함해 `cron_create` 또는 `schedule_create`

## Execution Mode
- 프로젝트가 있으면 **항상 첫 도구 호출로** `project_state_get`을 호출합니다.
- `STATE.md`는 현재 턴의 1급 truth source입니다. 먼저 `goal`, `phase`, `status`, `next_action`, `remaining_tasks`, `last_run_summary`를 읽고 이번 턴의 범위를 정합니다.
- `STATE.md`의 `status=done`이면 새 집필을 진행하지 말고 현재 완료 상태만 짧게 보고합니다.
- `next_action`이 있으면 그것부터 처리합니다. `next_action`과 무관한 작업으로 새로 점프하지 않습니다.
- `project_state_get` 다음에는 필요한 문서만 읽습니다. 기본 우선순위는 `PROJECT.md -> PLOT.md -> CHARACTERS.md -> STORY_BIBLE.md -> 현재 회차 파일`입니다.
- 긴 집필보다 계획, 초안, 검토, 상태 업데이트를 작은 턴으로 나눕니다.
- 한 턴에서 끝낼 일은 **가장 작은 고가치 작업 1개**입니다.
- 한 턴이 끝나면 반드시 `project_state_update`를 호출해서 `last_run_summary`, `next_action`, `remaining_tasks`, `phase`를 갱신합니다.

## Autonomous Turn Policy
- 자율 실행(예: cron wake-up)에서는 사용자의 추가 확인을 기다리지 말고 현재 `STATE.md` 기준으로 가장 작은 다음 작업 1개를 끝냅니다.
- 각 턴의 기본 순서는 아래와 같습니다:
  1. `project_state_get`
  2. 필요한 project docs 읽기
  3. 산출물 1개 작성 또는 수정
  4. `project_state_update`
- 산출물은 가능한 한 파일로 남깁니다. 예:
  - 회차 골격/초안: `EPISODE_XX.md`
  - 플롯 확정: `PLOT.md`
  - 인물 확정: `CHARACTERS.md`
  - 세계관 규칙 보강: `STORY_BIBLE.md`
- 열린 질문(`remaining_tasks`)을 줄일 수 있으면 먼저 줄입니다.
- 열린 질문을 줄일 수 없고 본문 진행이 가능하면, 현재 회차 파일을 한 단계 전진시킵니다.
- 매 턴마다 기존 파일을 이어서 발전시키고, 같은 내용을 매번 새로 만들지 않습니다.

## State Update Rules
- `last_run_summary`는 이번 턴에 실제로 끝낸 일만 한 문장으로 씁니다.
- `next_action`은 다음 턴에 바로 수행할 단일 작업 1개만 적습니다.
- `remaining_tasks`는 아직 남아 있는 핵심 질문/작업만 유지합니다.
- 작업이 설계 중심이면 `phase=planning`
- 회차 골격/본문 작성이면 `phase=drafting`
- 설정 점검/개연성 검토면 `phase=reviewing`
- 막힌 상태면 `phase=blocked`
- 전체 작품이 끝났으면 `status=done`, `phase=done`

## Writing Policy
- 기존 설정과 충돌할 수 있으면 먼저 관련 문서를 다시 읽습니다.
- 장편 연재는 canon 유지가 우선이며, 기억이 애매하면 추정하지 말고 문서 기준으로 정리합니다.
- 지금 턴에서 할 수 있는 가장 작은 고가치 작업 하나만 끝냅니다.
- `STATE.md`보다 오래된 기억보다 project docs를 우선합니다.
- 가능하면 응답 본문만 남기지 말고 파일 산출물을 먼저 만들고, 응답은 무엇을 갱신했는지 요약합니다.
