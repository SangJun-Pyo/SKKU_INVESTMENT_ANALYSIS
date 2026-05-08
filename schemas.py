"""
schemas.py — MarkovPortfolio V4 API 경계 입출력 스키마

HTTP 요청/응답 데이터 구조를 정의합니다.
도메인 판단 로직은 포함하지 않고 데이터 검증만 담당합니다.

규칙:
- Pydantic v2: model_dump() 사용, .dict() 절대 금지
- models.py의 도메인 모델을 재정의하지 않고 가져다 씁니다
- API 경계에서만 사용하며 service_*.py 내부에서는 직접 사용하지 않습니다

스키마 구조:
- ETF Universe (유니버스 관리)
- Weekly Score (주간 점수 계산)
- Allocation (포트폴리오 배분)
- Risk Check (리스크 점검)
- Orders (주문 생성/확인)
- PnL (손익 기록)
- Report (보고서 생성)
- Chat (AI Committee 채팅)
"""

from pydantic import BaseModel
from typing import Optional

# 도메인 모델을 직접 재사용합니다.
# API 응답에서 도메인 모델을 그대로 내보내면
# 프론트엔드가 일관된 데이터 구조를 받을 수 있습니다.
from models import (
    ETFMeta,
    WeeklySignalScore,
    PortfolioPosition,
    RiskBudgetReport,
    WeeklyOrder,
    WeeklyPnL,
)


# ── ETF Universe (유니버스 관리) ─────────────────────────────────────────

class ETFAddRequest(BaseModel):
    """
    ETF 유니버스에 종목 추가 요청

    enabled는 기본 True로 설정하여 추가 즉시 점수 계산 대상이 됩니다.
    ETF 10개 미만 제약은 API 라우터에서 검증합니다.
    """
    ticker: str
    name: str
    asset_class: str          # "Korea ETF", "US ETF", "Inverse ETF" 등
    role: str                 # Core, Alpha, Hedge, Tactical, Short
    currency_exposure: str    # KRW, USD, Hedged, Unhedged
    enabled: bool = True


class ETFUniverseResponse(BaseModel):
    """ETF 유니버스 조회 응답"""
    universe: list[ETFMeta]
    count: int                # 활성화된 ETF 수 (enabled=True인 것만)


# ── Weekly Score (주간 점수 계산) ────────────────────────────────────────

class ScoreRunRequest(BaseModel):
    """
    주간 신호 점수 계산 요청

    week를 명시하는 이유: 같은 종목도 주차마다 다른 점수를 가지며
    이전 주차의 점수를 재계산할 때도 week를 지정해야 합니다.
    tickers를 비워두면 전체 유니버스를 대상으로 계산합니다.
    """
    week: int
    tickers: list[str] = []   # 빈 리스트면 전체 유니버스 계산


class ScoreResponse(BaseModel):
    """주간 신호 점수 계산 결과"""
    scores: list[WeeklySignalScore]
    week: int


# ── Allocation (포트폴리오 배분) ─────────────────────────────────────────

class AllocationSuggestRequest(BaseModel):
    """
    포트폴리오 배분 제안 요청

    use_alpha=False이면 Core 100억만 구성하고 Alpha 배분을 건너뜁니다.
    reserve_amount는 Pullback Reserve로 현금으로 유보할 금액입니다.
    """
    week: int
    use_alpha: bool = True
    reserve_amount: float = 0   # 예비금 0 → Core 100억 + Alpha 최대 30억 = 130억 풀 활용


class AllocationSuggestResponse(BaseModel):
    """포트폴리오 배분 제안 결과"""
    positions: list[PortfolioPosition]
    total_exposure: float        # 총 익스포저 (원)
    leverage_ratio: float        # 차입 비율 (0.0-0.30)
    cash_remaining: float        # 미배분 현금 (원)
    week: int
    warnings: list[str] = []     # 변동성 초과 등 주의 사항


# ── Risk Check (리스크 점검) ─────────────────────────────────────────────

class RiskCheckRequest(BaseModel):
    """
    리스크 규칙 위반 여부 점검 요청

    포트폴리오 배분 확정 전에 항상 실행해야 합니다.
    BLOCK 위반이 있으면 Orders 생성이 차단됩니다.
    """
    week: int
    positions: list[PortfolioPosition]


class RiskCheckResponse(BaseModel):
    """리스크 점검 결과"""
    report: RiskBudgetReport
    passed: bool                 # violations 리스트가 비어있으면 True
    block_count: int             # BLOCK 수준 위반 수
    warn_count: int              # WARN 수준 위반 수


# ── Orders (주문 생성/확인) ──────────────────────────────────────────────

class OrdersGenerateRequest(BaseModel):
    """
    금요일 주문표 생성 요청

    현재 포트폴리오와 배분 제안을 비교하여 필요한 주문을 자동 생성합니다.
    date는 해당 금요일의 날짜 (ISO 8601)입니다.
    """
    week: int
    date: str                    # 금요일 날짜 (예: "2025-03-07")


class OrdersConfirmRequest(BaseModel):
    """
    주문 확정 요청

    리스크 점검 결과를 포함한 주문 목록을 최종 확정합니다.
    BLOCK 상태의 주문이 포함된 경우 서버에서 거부합니다.
    """
    week: int
    orders: list[WeeklyOrder]


class OrdersResponse(BaseModel):
    """주문 목록 응답"""
    orders: list[WeeklyOrder]
    week: int
    total_buy_amount: float      # 매수 주문 합계 (원)
    total_sell_amount: float     # 매도 주문 합계 (원)


# ── PnL (손익 기록) ──────────────────────────────────────────────────────

class PnLUpdateRequest(BaseModel):
    """
    주간 손익 업데이트 요청

    friday_prices: 금요일 종가 기준 ETF별 가격 (KRW 환산)
    benchmark_prices: 벤치마크 ETF 종가 (kospi200, sp500Hedged, sp500Unhedged)

    금요일 종가를 별도로 받는 이유:
    yfinance의 실시간 데이터가 지연될 수 있어 사용자가 직접 확인한 값을 입력합니다.
    """
    week: int
    date: str                                    # 해당 주 금요일
    friday_prices: dict[str, float]              # {ticker: 종가 KRW}
    benchmark_prices: dict[str, float]           # {벤치마크 키: 종가}


class PnLResponse(BaseModel):
    """주간 손익 계산 결과"""
    pnl: WeeklyPnL
    benchmark_detail: dict[str, float] = {}      # 벤치마크별 수익률 세부 내역


# ── Report (보고서 생성) ─────────────────────────────────────────────────

class ReportRiskRulesRequest(BaseModel):
    """
    리스크 규칙 보고서 생성 요청

    교수 제출용 리스크 규칙 준수 보고서를 Markdown으로 생성합니다.
    """
    week: int
    include_violations: bool = True   # 위반 항목을 보고서에 포함할지 여부


class ReportOrdersRequest(BaseModel):
    """
    주문 보고서 생성 요청

    이번 주 매매 배경, 전략, 리스크 점검, 주문 내역을 포함한
    CIO 관점의 보고서를 생성합니다.
    """
    week: int
    market_background: Optional[str] = None   # 시장 배경 (없으면 AI가 생성)
    strategy_note: Optional[str] = None       # 전략 설명 (없으면 AI가 생성)


class ReportWeeklyPnLRequest(BaseModel):
    """
    주간 손익 보고서 생성 요청

    벤치마크 대비 성과, 기여도 분석을 포함한 주간 보고서를 생성합니다.
    """
    week: int


class ReportResponse(BaseModel):
    """보고서 생성 결과"""
    markdown: str                # Markdown 형식의 보고서 본문
    week: int


# ── Chat (AI Committee 채팅) ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    """
    AI Investment Committee 채팅 요청

    role로 AI의 관점을 지정합니다.
    context에는 현재 포트폴리오 상태, 점수, 리스크 지표 등을 담아
    AI가 과제 맥락을 이해하고 답변하도록 합니다.

    단타 트레이딩 관련 질문은 context에 mode='papertrade'를 포함하면
    시스템 프롬프트에서 포트폴리오 관점 답변으로 유도합니다.
    """
    message: str
    role: str = "CIO"            # CIO, CRO, Research, Report Writer
    context: Optional[dict] = None   # AppState에서 구성한 과제용 컨텍스트


class ChatResponse(BaseModel):
    """AI 채팅 응답"""
    response: str                # AI가 생성한 텍스트 (Markdown 지원)
    role: str                    # 실제 사용된 역할
