"""
service_benchmark.py — 벤치마크 수익률 계산 서비스

수업 과제 기준 벤치마크: KOSPI200 40% + S&P500(H) 30% + S&P500(U) 30%
주간 수익률을 기반으로 추적 오차, 정보 비율 등을 계산합니다.

벤치마크를 별도 서비스로 분리하는 이유:
- 벤치마크 계산 로직이 변경되어도 service_portfolio.py 등 다른 서비스에 영향 없음
- 과제 기준이 변경될 때 이 파일만 수정하면 됩니다
"""

import math
from typing import Optional

import numpy as np

from config import CLASS_BENCHMARK, WEEKLY_BORROW_COST, WEEKLY_CASH_INTEREST
from models import WeeklyPnL


# ── 벤치마크 ETF 종목 코드 ────────────────────────────────────────────────
# 수업 과제에서 지정한 벤치마크 복제 ETF들입니다.
# KRX 상장 ETF를 사용하는 이유: 원화 기준으로 비교가 직접적이기 때문입니다.
BENCHMARK_TICKERS = {
    "kospi200":      "069500.KS",   # KODEX 200 — 코스피200 추종
    "sp500Hedged":   "219480.KS",   # KODEX S&P500선물(H) — 환헷지
    "sp500Unhedged": "379800.KS",   # KODEX S&P500 TR — 환노출
}


def get_benchmark_return(
    friday_prices: dict[str, float],
    prev_prices: dict[str, float],
) -> float:
    """
    주간 벤치마크 수익률 계산

    각 구성 ETF의 주간 수익률을 CLASS_BENCHMARK 비중으로 가중 평균합니다.
    가중 평균을 사용하는 이유: 벤치마크는 각 구성 자산의 비중에 따라 수익률이 결정되기 때문입니다.

    friday_prices: {ticker: close_price} — 이번 주 금요일 종가
    prev_prices:   {ticker: close_price} — 지난 주 금요일 종가

    가격이 없는 구성 요소는 수익률 0으로 처리합니다.
    전체 가중치 합이 1이 아닐 경우를 대비해 available_weight로 정규화합니다.
    """
    weighted_return = 0.0
    available_weight = 0.0

    for key, weight in CLASS_BENCHMARK.items():
        ticker = BENCHMARK_TICKERS.get(key)
        if ticker is None:
            continue

        current = friday_prices.get(ticker) or friday_prices.get(key)
        prev    = prev_prices.get(ticker)   or prev_prices.get(key)

        if current is None or prev is None or prev <= 0:
            # 가격 데이터 없으면 해당 구성 요소 제외
            continue

        component_return = (current - prev) / prev
        weighted_return += weight * component_return
        available_weight += weight

    if available_weight <= 0:
        # 모든 가격 데이터가 없는 경우 — 0 반환
        return 0.0

    # 사용 가능한 가중치로 정규화 (일부 데이터 누락 시 보정)
    if available_weight < 1.0:
        weighted_return = weighted_return / available_weight

    return round(weighted_return, 6)


def calculate_class_benchmark_return(
    kospi200_return: float,
    sp500_hedged_return: float,
    sp500_unhedged_return: float,
) -> float:
    """
    수업 과제 기준 벤치마크 수익률 직접 계산

    개별 구성 수익률이 이미 알려진 경우 사용합니다.
    벤치마크 비중: KOSPI200 40% + S&P500(H) 30% + S&P500(U) 30%

    반환: 가중 수익률 (예: 0.012 = 1.2%)
    """
    return (
        CLASS_BENCHMARK["kospi200"]      * kospi200_return +
        CLASS_BENCHMARK["sp500Hedged"]   * sp500_hedged_return +
        CLASS_BENCHMARK["sp500Unhedged"] * sp500_unhedged_return
    )


def calculate_tracking_error(
    portfolio_returns: list[float],
    benchmark_returns: list[float],
) -> float:
    """
    추적 오차(Tracking Error) 계산

    포트폴리오와 벤치마크 간 초과수익(Active Return)의 표준편차를 연환산합니다.
    sqrt(52)로 연환산하는 이유: 주간 데이터를 연간으로 스케일업하기 위해서입니다.

    데이터가 2주 미만이면 계산 불가 → 0.0 반환
    """
    if len(portfolio_returns) < 2 or len(benchmark_returns) < 2:
        return 0.0

    min_len = min(len(portfolio_returns), len(benchmark_returns))
    p = np.array(portfolio_returns[-min_len:], dtype=float)
    b = np.array(benchmark_returns[-min_len:], dtype=float)

    active_returns = p - b

    # ddof=1: 표본 표준편차 (불편 추정량)
    te_weekly = float(np.std(active_returns, ddof=1))

    # 주간 → 연환산 (52주 기준)
    te_annual = te_weekly * math.sqrt(52)
    return round(te_annual, 6)


def calculate_information_ratio(
    active_returns: list[float],
    tracking_error: float,
) -> float:
    """
    정보 비율(Information Ratio) 계산

    IR = 연환산 평균 초과수익 / 추적 오차
    IR이 높을수록 리스크 대비 초과수익을 잘 창출하는 포트폴리오입니다.

    TE가 0이면 IR은 정의되지 않으므로 0.0을 반환합니다.
    """
    if tracking_error <= 0 or not active_returns:
        return 0.0

    # 평균 주간 초과수익 → 연환산
    mean_active_weekly = float(np.mean(active_returns))
    mean_active_annual = mean_active_weekly * 52

    ir = mean_active_annual / tracking_error
    return round(ir, 4)


def apply_costs(
    portfolio_return: float,
    borrowed_cash: float,
    total_capital: float,
    cash_held: float,
) -> tuple[float, float, float]:
    """
    비용 적용 후 순수익률 계산

    비용을 별도로 계산하는 이유:
    교수 평가 시 비용 명세를 보여줘야 하며,
    레버리지 비용과 현금 이자를 따로 구분하면 투명한 리포팅이 가능합니다.

    leverage_cost: 차입금 × 주간 차입 이자율 / 총 자본
    cash_interest: 보유 현금 × 주간 현금 이자율 / 총 자본 (수익)
    net_return: 포트폴리오 수익 - 차입 비용 + 현금 이자

    반환: (leverage_cost, cash_interest, net_return)
    """
    if total_capital <= 0:
        return 0.0, 0.0, portfolio_return

    # 차입 이자 비용: 차입금이 클수록 비용 증가
    leverage_cost = (borrowed_cash / total_capital) * WEEKLY_BORROW_COST

    # 현금 이자 수익: 미배분 현금에서 이자 수익 발생
    cash_interest = (cash_held / total_capital) * WEEKLY_CASH_INTEREST

    # 순수익률 = 포트폴리오 수익 - 차입 비용 + 현금 이자
    net_return = portfolio_return - leverage_cost + cash_interest

    return (
        round(leverage_cost, 6),
        round(cash_interest, 6),
        round(net_return, 6),
    )


def build_weekly_pnl(
    week: int,
    date: str,
    portfolio_return: float,
    benchmark_return: float,
    borrowed_cash: float,
    total_capital: float,
    cash_held: float,
    contribution_by_etf: dict,
    prev_pnl_list: list,
) -> WeeklyPnL:
    """
    WeeklyPnL 객체 생성

    누적 수익률은 이전 주 목록을 활용하여 복리로 계산합니다.
    복리 계산식: cumulative = (1 + r1) * (1 + r2) * ... - 1
    단순 합산이 아닌 복리를 사용하는 이유: 실제 투자 성과를 정확하게 반영하기 위해서입니다.
    """
    leverage_cost, cash_interest, net_return = apply_costs(
        portfolio_return=portfolio_return,
        borrowed_cash=borrowed_cash,
        total_capital=total_capital,
        cash_held=cash_held,
    )

    active_return = round(portfolio_return - benchmark_return, 6)

    # 누적 수익률: 이전 주 net_return들을 복리로 계산
    cumulative = 1.0
    for prev in prev_pnl_list:
        # WeeklyPnL 객체이거나 딕셔너리일 수 있으므로 방어적으로 접근
        if hasattr(prev, "net_return"):
            r = prev.net_return
        elif isinstance(prev, dict):
            r = prev.get("net_return", 0.0)
        else:
            r = 0.0
        cumulative *= (1 + r)

    # 이번 주 net_return까지 포함
    cumulative *= (1 + net_return)
    cumulative_return = round(cumulative - 1.0, 6)

    return WeeklyPnL(
        week=week,
        date=date,
        portfolio_return=round(portfolio_return, 6),
        benchmark_return=round(benchmark_return, 6),
        active_return=active_return,
        leverage_cost=leverage_cost,
        cash_interest=cash_interest,
        net_return=round(net_return, 6),
        cumulative_return=cumulative_return,
        contribution_by_etf=contribution_by_etf,
    )


def get_cumulative_benchmark_return(pnl_list: list) -> float:
    """
    누적 벤치마크 수익률 계산 (복리 기준)

    여러 주의 WeeklyPnL에서 벤치마크 수익률을 누적합니다.
    포트폴리오 누적 수익률과 함께 비교하기 위해 동일한 복리 방식을 사용합니다.
    """
    if not pnl_list:
        return 0.0

    cumulative = 1.0
    for pnl in pnl_list:
        if hasattr(pnl, "benchmark_return"):
            r = pnl.benchmark_return
        elif isinstance(pnl, dict):
            r = pnl.get("benchmark_return", 0.0)
        else:
            r = 0.0
        cumulative *= (1 + r)

    return round(cumulative - 1.0, 6)
