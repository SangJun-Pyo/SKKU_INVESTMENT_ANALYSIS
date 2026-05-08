"""
models.py — MarkovPortfolio V4 내부 도메인 모델

HTTP/API와 무관한 순수 비즈니스 데이터 구조를 정의합니다.
Pydantic v2 BaseModel을 사용하여 타입 안전성을 확보합니다.

레이어 규칙:
- schemas.py(API 경계)를 import하면 안 됩니다 (레이어 경계 위반)
- HTTP 요청/응답 로직을 포함하면 안 됩니다

V4 모델 목록:
1. ETFMeta           — ETF 유니버스 정보
2. WeeklySignalScore — 주간 신호 점수
3. PortfolioPosition — 개별 포트폴리오 포지션
4. PortfolioSnapshot — 특정 주의 전체 포트폴리오 스냅샷
5. RiskBudgetReport  — 리스크 예산 점검 결과
6. WeeklyOrder       — 금요일 체결 기준 주간 주문
7. WeeklyPnL         — 주간 손익 기록
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class ETFMeta(BaseModel):
    """
    ETF 유니버스 메타데이터

    투자 가능한 ETF 목록을 관리합니다.
    role로 포트폴리오 내 역할을 구분하여 Core/Alpha 배분 로직에 활용합니다.
    currency_exposure로 환 헷지 여부를 추적해 환율 리스크를 파악합니다.
    """
    ticker: str               # 종목 코드 (예: 069500.KS, SPY)
    name: str                 # 종목명 (예: KODEX 200, SPDR S&P 500 ETF)
    asset_class: str          # 자산 구분 (예: "Korea ETF", "US ETF", "Inverse ETF")
    role: Literal[
        'Core',       # 벤치마크 복제용 핵심 포지션 (항상 보유)
        'Alpha',      # 초과수익 추구 포지션 (점수 기반 배분)
        'Hedge',      # 하락 헷지 (VIX, 채권 등)
        'Tactical',   # 전술적 기회 포지션 (단기 테마)
        'Short',      # 인버스/공매도 포지션
    ]
    currency_exposure: Literal[
        'KRW',        # 원화 자산 (국내 ETF)
        'USD',        # 달러 자산 (환 노출)
        'Hedged',     # 달러 자산이지만 환 헷지 적용
        'Unhedged',   # 달러 자산 환 노출 (명시적)
    ]
    enabled: bool = True      # False면 점수 계산 및 배분에서 제외


class WeeklySignalScore(BaseModel):
    """
    ETF별 주간 신호 점수

    총 100점 만점으로 구성됩니다.
    각 항목은 서로 다른 시장 관점을 반영하여 단일 지표에 과의존하지 않도록 합니다.
    Action은 총점 기반으로 결정되어 일관된 매매 규칙을 유지합니다.
    """
    ticker: str
    week: int                  # 과제 주차 (1주차부터 시작)

    # 점수 항목 — 각 항목의 만점 합계가 100점이 되어야 합니다
    trend_score: float         # 추세 점수: 0-25점 (20일/60일 이동평균 방향성)
    pullback_score: float      # 눌림목 점수: 0-20점 (고점 대비 조정폭 + RSI 냉각)
    volatility_score: float    # 변동성 점수: 0-20점 (변동성이 한도 이내인지)
    momentum_score: float      # 모멘텀 점수: 0-15점 (최근 4주 수익률, RSI)
    drawdown_score: float      # 낙폭 점수: 0-10점 (고점 대비 현재 낙폭 역점수)
    correlation_score: float   # 상관관계 점수: 0-10점 (기존 포트폴리오와 낮을수록 유리)
    total_score: float         # 합산 점수: 0-100점

    # 시장 레짐 판단
    regime: Literal[
        'Risk-On',   # 상승 추세 + 변동성 정상 + 모멘텀 양호
        'Neutral',   # 방향성 혼재 또는 점수 중간
        'Risk-Off',  # 하락 추세 + 변동성 확대 + 낙폭 확대
    ]

    # 행동 지침 — total_score 구간으로 자동 결정됩니다
    action: Literal[
        'Increase',  # 80점 이상: 비중 확대
        'Small Buy', # 65-79점: 소량 매수
        'Hold',      # 50-64점: 보유 유지
        'Reduce',    # 35-49점: 비중 축소
        'Exit',      # 35점 미만: 전량 청산
        'No Buy',    # 데이터 부족 또는 유니버스 미등록
    ]

    reason: str                # 점수 산정 근거 (보고서 자동 생성용)


class PortfolioPosition(BaseModel):
    """
    개별 포트폴리오 포지션

    목표 금액과 실제 보유 수량을 함께 관리합니다.
    금요일 종가를 기준으로 수량을 계산하기 때문에
    entry_price와 current_price가 분리되어 있습니다.
    """
    ticker: str
    name: str
    role: str                  # ETFMeta.role과 동일

    # 배분 목표 — 포트폴리오 구성 단계에서 설정됩니다
    target_amount: float       # KRW 목표 금액 (예: 4_000_000_000)
    target_weight: float       # 포트폴리오 내 목표 비중 0.0-1.0

    # 실제 체결 — 금요일 종가 확인 후 입력됩니다
    quantity: Optional[float] = None        # 보유 수량 (주/계약)
    entry_price: Optional[float] = None    # 평균 진입 단가
    current_price: Optional[float] = None  # 현재가 (평가용)

    # 리스크 관리 기준 — 기본값은 5% 손절/익절
    stop_loss_pct: float = 0.05    # 손절 비율 (5% 하락 시 청산)
    take_profit_pct: float = 0.05  # 익절 비율 (5% 상승 시 일부 실현)

    # 신호 참조 — WeeklySignalScore에서 복사됩니다
    signal_score: Optional[float] = None   # 해당 주 점수
    regime: Optional[str] = None           # 해당 주 레짐


class PortfolioSnapshot(BaseModel):
    """
    특정 주의 전체 포트폴리오 상태 스냅샷

    매주 금요일 종가 체결 후 저장합니다.
    week를 기본 키로 사용해 주차별 조회가 가능합니다.
    borrowed_cash가 0이 아니면 이자 비용이 발생합니다.
    """
    week: int                          # 과제 주차
    date: str                          # 스냅샷 날짜 (ISO 8601)

    # 자본 구조
    base_capital: float = 10_000_000_000   # 기본 자본: 100억
    borrowed_cash: float = 0.0             # 차입금 (최대 30억)
    cash: float = 10_000_000_000           # 미배분 현금

    # 익스포저
    total_exposure: float = 0.0            # 총 투자금액 (롱 + 숏 절대값)

    # 포지션 목록
    positions: list[PortfolioPosition] = []


class RiskBudgetReport(BaseModel):
    """
    포트폴리오 리스크 예산 점검 결과

    교수 평가용 리스크 규칙 준수 여부를 정량적으로 보고합니다.
    violations 리스트가 비어있으면 모든 규칙을 준수한 것입니다.
    위반 항목이 있으면 Orders Report 생성 시 경고 문구가 자동 삽입됩니다.
    """
    week: int

    # 핵심 리스크 지표
    total_exposure: float         # 총 익스포저 (원)
    leverage_ratio: float         # 차입금 / 기본자본 (0.30 이하여야 함)
    short_exposure_ratio: float   # 숏 포지션 / 총자산 (0.30 이하여야 함)
    etf_count: int                # 보유 ETF 수 (10 미만이어야 함)

    # 수익률/변동성 지표
    expected_weekly_volatility: float   # 예상 주간 변동성 (0.015 이하여야 함)
    var_95: float                       # 95% 신뢰구간 VaR (원, 음수) — 최소 -2억 이내
    max_drawdown: float                 # 최대 낙폭 (소수점)

    # 벤치마크 대비 지표
    benchmark_beta: float               # 벤치마크 베타 (1.20 이하여야 함)
    tracking_error: Optional[float] = None      # 추적 오차
    information_ratio: Optional[float] = None   # 정보 비율 (Active Return / TE)

    # 위반 항목 목록 — 빈 리스트면 전체 통과
    violations: list[str] = []


class WeeklyOrder(BaseModel):
    """
    주간 주문 내역 (금요일 종가 체결 기준)

    주문 생성 시 risk_check가 BLOCK이면 실제 체결 불가 처리합니다.
    order_type을 'Friday Close'로 고정하여 체결 기준을 명확히 합니다.
    """
    week: int
    date: str                          # 주문 날짜 (금요일)
    ticker: str

    action: Literal[
        'BUY',    # 신규 매수 또는 비중 확대
        'SELL',   # 전량 매도
        'HOLD',   # 보유 유지 (주문 불필요, 기록용)
        'REDUCE', # 일부 매도 (비중 축소)
        'SHORT',  # 인버스 ETF 신규 매수 (공매도 효과)
        'COVER',  # 인버스 ETF 청산
    ]

    order_type: str = 'Friday Close'   # 체결 기준: 항상 금요일 종가
    amount: float                      # 주문 금액 (KRW)
    target_weight: float               # 주문 후 목표 비중 0.0-1.0
    reason: str                        # 주문 근거 (보고서 자동 생성용)

    risk_check: Literal[
        'OK',    # 리스크 규칙 모두 통과
        'WARN',  # 경고: 체결 가능하지만 주의 필요
        'BLOCK', # 차단: 리스크 규칙 위반으로 체결 불가
    ] = 'OK'


class WeeklyPnL(BaseModel):
    """
    주간 손익 기록

    벤치마크 대비 초과수익(Active Return)을 핵심 지표로 관리합니다.
    leverage_cost와 cash_interest는 실제 비용이므로 net_return에서 차감합니다.
    contribution_by_etf로 어떤 ETF가 수익/손실에 기여했는지 분석할 수 있습니다.
    """
    week: int
    date: str                   # 해당 주 금요일 날짜

    # 수익률 (소수점 형태, 예: 0.015 = 1.5%)
    portfolio_return: float     # 포트폴리오 총 수익률
    benchmark_return: float     # 벤치마크 수익률 (40/30/30 가중평균)
    active_return: float        # 초과수익 = portfolio_return - benchmark_return

    # 비용 — 주간 기준으로 반영합니다
    leverage_cost: float        # 차입 이자 비용 (기본 0.00070)
    cash_interest: float        # 현금 이자 수익 (기본 0.00035)

    # 비용 차감 후 순수익률
    net_return: float           # portfolio_return - leverage_cost + cash_interest
    cumulative_return: float    # 1주차부터 현재까지 누적 수익률

    # ETF별 기여도 — {ticker: contribution} 형태 (소수점)
    contribution_by_etf: dict[str, float] = {}
