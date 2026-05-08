# /develop — 기능 구현 커맨드

구현할 기능: $ARGUMENTS

---

## 실행 절차

아래 순서를 반드시 따르세요.

### 1단계: 규칙 & 컨텍스트 로드

다음 파일들을 **항상** 먼저 읽으세요:

- `skills/code.rules.md` — 코딩 규칙 (한국어 주석 등)
- `agents/chart_planner_agent_dev.md` — 에이전트 설계 문서
- 구현 대상과 관련된 기존 파일 (`agent.py`, `tools.py`, `dashboard.py`)

### 2단계: Plan 서브에이전트로 구현 계획 수립

**Plan 에이전트**를 실행해서 다음을 설계하세요:
- 어느 파일에 무엇을 추가/수정할지
- 새 Tool이 필요하다면 `tools.py`의 `TOOLS` 리스트와 핸들러에 추가하는 방식
- `code.rules.md` 규칙을 어떻게 적용할지

### 3단계: 구현

Plan 에이전트의 결과를 바탕으로 직접 코드를 작성하세요.

**반드시 지켜야 할 규칙 (`skills/code.rules.md`):**
- 모든 코드에 **한국어 주석**을 달아 비전공자도 이해할 수 있게 작성
- 주석은 "무엇을 하는가"가 아닌 "왜 이렇게 하는가"를 설명

**구현 원칙:**
- 기존 파일 구조(`agent.py` / `tools.py` / `dashboard.py`)를 유지
- 새 Tool 추가 시 → `tools.py`의 `TOOLS` 리스트 + `TOOL_HANDLERS` 딕셔너리 + 핸들러 함수 모두 업데이트
- Streamlit UI 변경 시 → `dashboard.py`만 수정
- 에이전트 로직 변경 시 → `agent.py`만 수정

### 4단계: 검증 & 요약

구현 후 다음을 확인하고 사용자에게 보고하세요:
- 변경된 파일 목록
- 추가된 기능 설명 (비전공자도 이해할 수 있게)
- 실행 방법 또는 테스트 방법
