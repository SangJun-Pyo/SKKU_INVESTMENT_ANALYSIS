"""
service_ai.py — AI 투자위원회 서비스

Claude API를 통해 ETF 포트폴리오 분석을 제공합니다.
역할(CIO/CRO/Research/Writer)별로 다른 시스템 프롬프트를 사용하여
각 역할에 맞는 전문적인 답변을 유도합니다.

V2의 ClaudeAgent agentic loop 패턴을 계승하되,
Tool Use 없이 텍스트 대화에 집중합니다.
(ETF 과제에서 필요한 정보는 context로 주입되므로 Tool Use가 불필요합니다.)

싱글톤 히스토리 패턴을 사용하는 이유:
요청마다 새 인스턴스를 생성하면 이전 대화 컨텍스트가 사라지기 때문입니다.
역할별로 대화 히스토리를 분리하는 이유:
CRO가 리스크 점검 중인 상태가 CIO 대화에 섞이면 혼란이 발생합니다.
"""

from typing import Optional

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from prompts.portfolio_committee_prompt import get_system_prompt


# ── 지원 역할 목록 ────────────────────────────────────────────────────────
# 역할을 상수로 정의하는 이유:
# 프론트엔드에서 잘못된 역할 문자열을 보내도 폴백 처리가 명확합니다.
SUPPORTED_ROLES = [
    "CIO Assistant",
    "CRO Checker",
    "Research Summarizer",
    "Report Writer",
]

DEFAULT_ROLE = "CIO Assistant"


# ── 싱글톤 히스토리 ──────────────────────────────────────────────────────
# 역할별로 독립된 대화 히스토리를 유지합니다.
# 모듈 레벨에서 선언하는 이유: 서버 프로세스 내에서 상태를 유지하기 위해서입니다.
_histories: dict[str, list[dict]] = {
    role: [] for role in SUPPORTED_ROLES
}

# Anthropic 클라이언트 — lazy 초기화로 API 키 없이 서버 시작이 가능합니다.
_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    """
    Anthropic 클라이언트 lazy 초기화

    서버 시작 시 바로 초기화하지 않고 첫 chat() 호출 시 초기화합니다.
    이렇게 하는 이유: API 키가 없어도 서버가 일단 실행되게 하기 위해서입니다.
    """
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _normalize_role(role: str) -> str:
    """
    역할 이름을 정규화합니다.

    알 수 없는 역할은 DEFAULT_ROLE로 폴백합니다.
    대소문자 구분 없이 매칭을 시도합니다.
    """
    if role in SUPPORTED_ROLES:
        return role

    # 대소문자 무시 매칭 시도
    role_lower = role.lower()
    for supported in SUPPORTED_ROLES:
        if supported.lower() == role_lower:
            return supported

    # 부분 문자열 매칭 (예: "CIO" → "CIO Assistant")
    for supported in SUPPORTED_ROLES:
        if role_lower in supported.lower():
            return supported

    # 폴백: 기본 역할
    return DEFAULT_ROLE


def chat(
    message: str,
    role: str = DEFAULT_ROLE,
    context: Optional[dict] = None,
) -> str:
    """
    역할별 AI 대화

    V2 ClaudeAgent의 agentic loop 패턴을 단순화한 버전입니다.
    Tool Use를 제거한 이유:
    ETF 과제에서 필요한 포트폴리오 데이터는 context 딕셔너리로 주입하므로
    Claude가 외부 도구를 호출할 필요가 없습니다.

    context 주입 방식:
    - 메시지에 컨텍스트를 추가하지 않고 시스템 프롬프트에 포함합니다.
    - 이렇게 하는 이유: 매 턴마다 컨텍스트가 바뀌더라도 히스토리는 유지되어야 하기 때문입니다.
    - 단, 첫 메시지에서 컨텍스트를 사용자 메시지에 포함시켜 컨텍스트 인식을 강화합니다.

    반환: Claude의 텍스트 응답 (오류 시 오류 메시지 문자열)
    """
    # 역할 정규화 — 잘못된 역할 입력에도 안전하게 동작
    normalized_role = _normalize_role(role)

    # 해당 역할의 대화 히스토리 가져오기
    history = _histories[normalized_role]

    # 컨텍스트가 있고 히스토리가 비어있으면 첫 메시지에 컨텍스트 포함
    # 이후 메시지는 시스템 프롬프트의 컨텍스트만 참조
    user_content = message
    if context and not history:
        # 포트폴리오 상태를 요약해서 첫 메시지에 포함
        ctx_summary = _build_context_summary(context)
        if ctx_summary:
            user_content = f"{ctx_summary}\n\n{message}"

    history.append({"role": "user", "content": user_content})

    # 컨텍스트를 시스템 프롬프트에 주입 (매 턴마다 최신 컨텍스트 반영)
    # 히스토리 이후 컨텍스트가 변경되어도 시스템 프롬프트는 업데이트됩니다.
    system_prompt = get_system_prompt(role=normalized_role, context=context)

    try:
        client = _get_client()

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,    # 과제 보고서 수준의 응답 길이로 제한
            system=system_prompt,
            messages=history,
        )

        # 응답 텍스트 추출
        assistant_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                assistant_text = block.text
                break

        if not assistant_text:
            assistant_text = "응답을 생성했으나 텍스트가 없습니다."

        # 히스토리에 어시스턴트 응답 추가 (다음 대화에서 맥락 유지)
        history.append({"role": "assistant", "content": assistant_text})

        return assistant_text

    except anthropic.AuthenticationError:
        # API 키 오류 — 히스토리에는 추가하지 않음 (대화 흐름 보존)
        history.pop()  # 추가했던 user 메시지 제거
        return "API 인증 오류: .env 파일에 ANTHROPIC_API_KEY를 확인해주세요."

    except anthropic.RateLimitError:
        history.pop()
        return "API 요청 한도 초과: 잠시 후 다시 시도해주세요."

    except anthropic.APIConnectionError:
        history.pop()
        return "API 연결 오류: 네트워크 상태를 확인해주세요."

    except Exception as e:
        history.pop()
        return f"AI 응답 오류: {str(e)}"


def _build_context_summary(context: dict) -> str:
    """
    context 딕셔너리를 사용자가 전달한 메시지에 추가할 요약 텍스트로 변환합니다.

    시스템 프롬프트와 별개로 사용자 메시지에도 컨텍스트를 포함하는 이유:
    일부 Claude 버전에서 시스템 프롬프트보다 사용자 메시지의 정보를
    더 직접적으로 참조하기 때문에, 첫 메시지에는 두 곳 모두에 포함합니다.
    """
    if not context:
        return ""

    parts = ["[현재 주차 포트폴리오 요약]"]

    week = context.get("week")
    if week is not None:
        parts.append(f"과제 주차: {week}주차")

    portfolio = context.get("portfolio")
    if portfolio and isinstance(portfolio, list):
        total_pos = len(portfolio)
        parts.append(f"보유 포지션 수: {total_pos}개")

    risk_budget = context.get("risk_budget")
    if risk_budget and isinstance(risk_budget, dict):
        violations = risk_budget.get("violations", [])
        if violations:
            parts.append(f"리스크 위반 항목: {len(violations)}건")
        else:
            parts.append("리스크 가드레일: 전체 통과")

    scores = context.get("scores")
    if scores and isinstance(scores, list):
        buy_count = sum(
            1 for s in scores
            if isinstance(s, dict) and s.get("action") in ("Increase", "Small Buy")
        )
        if buy_count > 0:
            parts.append(f"매수 신호 ETF: {buy_count}개")

    return "\n".join(parts) if len(parts) > 1 else ""


def reset(role: str = "all") -> None:
    """
    역할별 대화 히스토리 초기화

    role="all"이면 모든 역할의 히스토리를 초기화합니다.
    특정 역할만 초기화하면 다른 역할의 대화 맥락은 유지됩니다.

    언제 사용하는가:
    - 새 과제 주차(week)가 시작될 때
    - 사용자가 "새 대화" 버튼을 클릭할 때
    - 테스트 목적으로 히스토리를 비울 때
    """
    global _histories

    if role == "all":
        # 전체 역할 초기화
        _histories = {r: [] for r in SUPPORTED_ROLES}
    elif role in _histories:
        # 특정 역할만 초기화
        _histories[role] = []
    else:
        # 알 수 없는 역할 — 정규화 후 초기화
        normalized = _normalize_role(role)
        _histories[normalized] = []


def get_history(role: str = DEFAULT_ROLE) -> list[dict]:
    """
    역할별 대화 히스토리 조회 (디버그/프론트엔드 표시용)

    역할을 정규화하여 알 수 없는 역할 입력에도 안전하게 동작합니다.
    """
    normalized = _normalize_role(role)
    return list(_histories.get(normalized, []))


def get_supported_roles() -> list[str]:
    """
    지원하는 역할 목록 반환 (프론트엔드 드롭다운용)
    """
    return list(SUPPORTED_ROLES)
