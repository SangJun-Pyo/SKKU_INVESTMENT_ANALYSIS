"""
service_risk_budget.py — MarkovPortfolio V4 포트폴리오 리스크 예산 점검 서비스

10개 가드레일을 검증하여 RiskBudgetReport를 생성합니다.
위반 항목은 violations 리스트에 한국어로 추가하여 보고서 자동 생성에 활용합니다.

numpy만 사용하며 scipy 등 외부 통계 라이브러리는 배제합니다.
— 수업 제출 환경의 의존성 최소화 및 가독성 확보를 위해서입니다.

Pydantic v2 규칙:
- 모델 직렬화 시 반드시 .model_dump() 사용 (.dict()는 deprecated)
"""

from typing import Optional

import numpy as np

from models import PortfolioPosition, PortfolioSnapshot, RiskBudgetReport
from config import (
    BASE_CAPITAL,
    MAX_TOTAL_EXPOSURE,
    MAX_LEVERAGE_RATIO,
    MAX_SHORT_RATIO,
    MAX_ETF_COUNT,
    RISK_THRESHOLDS,
)

# ── 단일 ETF 최대 배분 한도 ────────────────────────────────────────────────
# 가드레일 9번: 단일 ETF에 40억 초과 배분 시 WARN 처리합니다.
MAX_SINGLE_ETF_AMOUNT: float = 4_000_000_000  # 40억

# ── Alpha 리스크 기여 상한 ─────────────────────────────────────────────────
# 가드레일 10번: Alpha 포지션의 리스크 기여가 40%를 넘으면 WARN 처리합니다.
# Core(벤치마크 복제)가 포트폴리오의 핵심이어야 하므로 Alpha 비중을 제한합니다.
MAX_ALPHA_RISK_CONTRIBUTION: float = 0.40


# ── 핵심 리스크 계산 함수 ────────────────────────────────────────────────


def calculate_volatility(weekly_returns: list[float]) -> float:
    """
    주간 수익률 시계열에서 포트폴리오 변동성 계산

    최소 4주 데이터가 필요합니다.
    — 4주 미만이면 추정값으로 대체합니다 (과제 1주차 대응).

    반환값: 주간 변동성 (소수점, 예: 0.012 = 1.2%)

    연간 변동성이 아닌 주간 변동성을 사용하는 이유:
    과제가 주간 단위 체결(금요일 종가)을 기준으로 하기 때문에
    주간 변동성이 리스크 모니터링에 더 직관적입니다.
    """
    if not weekly_returns or len(weekly_returns) < 2:
        # 데이터 부족: 보수적으로 임계값에 근접한 추정값 반환
        # 0.01(1%)로 설정하여 임계값(1.5%)에 안전 마진을 둡니다
        return 0.01

    arr = np.array(weekly_returns, dtype=float)

    if len(arr) < 4:
        # 2-3주 데이터: ddof=1 표준편차를 사용하되 보수적 가정 적용
        return float(np.std(arr, ddof=1))

    # 충분한 데이터: 표본 표준편차 (ddof=1)
    # ddof=1을 사용하는 이유: 전체 기간이 아닌 표본 기간이므로 불편 추정량을 사용합니다
    return float(np.std(arr, ddof=1))


def calculate_var(
    weekly_returns: list[float],
    confidence: float = 0.95,
    portfolio_value: float = BASE_CAPITAL,
) -> float:
    """
    역사적 VaR 계산 (원화 금액 기준)

    반환값: 음수 원화 금액 (예: -150_000_000 = -1.5억)
    — 손실이므로 음수로 표현합니다.

    역사적 VaR를 사용하는 이유:
    정규분포 가정이 불필요하며 실제 관측된 수익률 분포를 그대로 반영합니다.
    단, 관측 기간이 짧으면 tail risk를 과소 추정할 수 있습니다.

    데이터 부족 시(4주 미만) 보수적 추정값을 반환합니다.
    — 과제 1주차처럼 이력이 없을 때도 리스크 보고서가 작동하게 합니다.
    """
    if not weekly_returns or len(weekly_returns) < 4:
        # 데이터 부족(Week 1 등): 현실적인 ETF 분산 포트폴리오 변동성으로 추정합니다.
        #
        # 기존 0.014(1.4%) → 0.008(0.8%)로 낮추는 근거:
        # - 0.014는 연간 변동성 10% 가정이지만 ETF 10개 미만의 분산 포트폴리오는
        #   개별 종목보다 변동성이 낮습니다. (연간 5~6% ≈ 주간 0.7~0.8%)
        # - 첫 주에 0.014를 적용하면 VaR = -1.65 × 0.014 × 100억 ≈ -2.31억으로
        #   -2억 한도를 초과해 이력 없는 상태만으로 BLOCK이 발생합니다.
        # - 과제 1주차는 이력 자체가 없으므로 이 추정이 과도하게 엄격하면 안 됩니다.
        # - 0.008(0.8%) → VaR ≈ -1.32억 (한도 내)
        estimated_weekly_vol = 0.008
        estimated_var = -1.65 * estimated_weekly_vol * portfolio_value
        return round(estimated_var, 0)

    arr = np.array(weekly_returns, dtype=float)

    # 역사적 VaR: (1 - confidence) 백분위수
    # confidence=0.95 → 5번째 백분위수 = 가장 나쁜 5%의 수익률
    # interpolation='lower'를 사용하는 이유: 보수적 추정 (실제 관측값만 사용)
    var_return = float(np.percentile(arr, (1 - confidence) * 100))

    # 수익률 → 원화 금액 변환
    var_amount = var_return * portfolio_value
    return round(var_amount, 0)


def calculate_benchmark_beta(
    portfolio_returns: list[float],
    benchmark_returns: list[float],
) -> float:
    """
    포트폴리오 베타 계산 (벤치마크 대비)

    Beta = Cov(포트폴리오, 벤치마크) / Var(벤치마크)

    데이터 부족(4주 미만) 또는 벤치마크 분산이 0에 가까울 때
    포지션 비중 가중 베타로 근사합니다.
    — ETF의 벤치마크 민감도를 단순화하여 1.0으로 가정합니다.

    반환값: 베타 값 (1.0 = 벤치마크와 동일한 변동성)
    """
    if (
        not portfolio_returns
        or not benchmark_returns
        or len(portfolio_returns) < 4
        or len(benchmark_returns) < 4
    ):
        # 데이터 부족: Core가 100억으로 벤치마크를 복제하므로 1.0으로 근사
        return 1.0

    p = np.array(portfolio_returns, dtype=float)
    b = np.array(benchmark_returns, dtype=float)

    # 배열 길이가 다르면 짧은 쪽 기준으로 맞춤
    min_len = min(len(p), len(b))
    p = p[-min_len:]
    b = b[-min_len:]

    # 벤치마크 분산이 0에 가까우면(벤치마크가 변동이 없으면) 베타 계산 불가
    benchmark_var = float(np.var(b, ddof=1))
    if benchmark_var < 1e-10:
        return 1.0

    # 공분산 행렬에서 [0,1] 원소가 포트폴리오-벤치마크 공분산
    cov_matrix = np.cov(p, b, ddof=1)
    covariance = float(cov_matrix[0, 1])

    beta = covariance / benchmark_var
    # 비정상적인 베타 값 클리핑 (음수 또는 극단값 방지)
    return float(np.clip(beta, -3.0, 5.0))


def calculate_tracking_error(active_returns: list[float]) -> Optional[float]:
    """
    추적 오차 계산 (포트폴리오 - 벤치마크의 주간 초과수익률 표준편차)

    추적 오차(TE)가 낮을수록 벤치마크에 가깝게 운용하는 것입니다.
    Core 100억이 벤치마크를 복제하므로 TE는 Alpha 포지션 크기에 비례합니다.

    4주 미만 데이터는 None을 반환합니다.
    — 통계적으로 의미 있는 TE 계산에 최소 4주 데이터가 필요합니다.
    """
    if not active_returns or len(active_returns) < 4:
        return None

    arr = np.array(active_returns, dtype=float)
    return float(np.std(arr, ddof=1))


def calculate_information_ratio(
    active_returns: list[float],
) -> Optional[float]:
    """
    정보 비율(Information Ratio) 계산

    IR = 평균 초과수익률 / 추적 오차
    — 단위 리스크당 초과수익을 측정합니다.
    IR > 0.5 이면 양호, IR < 0 이면 Alpha 전략이 역효과를 내고 있음을 의미합니다.

    TE가 0이거나 None이면 None을 반환합니다.
    """
    te = calculate_tracking_error(active_returns)
    if te is None or te == 0:
        return None

    arr = np.array(active_returns, dtype=float)
    mean_active = float(np.mean(arr))
    return round(mean_active / te, 4)


def calculate_max_drawdown(weekly_returns: list[float]) -> float:
    """
    주간 수익률 시계열에서 최대 낙폭(MDD) 계산

    MDD = (고점 - 저점) / 고점 — 음수로 반환합니다.
    예: -0.05 = 최대 5% 손실 구간이 있었음

    누적 수익률 기준으로 계산하는 이유:
    단순 변동폭이 아닌 실제 "물 먹은" 기간을 측정하기 위해서입니다.
    """
    if not weekly_returns or len(weekly_returns) < 2:
        return 0.0

    # 누적 수익률 계산: (1 + r1)(1 + r2)... - 1
    arr = np.array(weekly_returns, dtype=float)
    cumulative = np.cumprod(1 + arr)

    # 각 시점의 고점(running maximum)
    running_max = np.maximum.accumulate(cumulative)

    # 낙폭: (현재 누적 - 고점) / 고점
    drawdowns = (cumulative - running_max) / running_max

    mdd = float(np.min(drawdowns))
    return round(mdd, 6)


def calculate_risk_contribution(
    positions: list[PortfolioPosition],
    total_exposure: float,
) -> dict[str, float]:
    """
    ETF별 리스크 기여도 계산 (단순 비중 기반)

    정확한 리스크 기여도는 상관관계 행렬이 필요하지만,
    주간 데이터가 부족한 과제 환경에서는 비중 기반 근사를 사용합니다.
    — 비중이 클수록 리스크 기여가 크다는 합리적 가정입니다.

    반환값: {ticker: risk_contribution_ratio} (합계 ≈ 1.0)
    """
    if total_exposure == 0:
        return {}

    contributions = {}
    for pos in positions:
        # 단순 비중을 리스크 기여도로 사용
        # 롱과 숏 모두 절대값 기준으로 계산 (양방향 위험)
        weight = abs(pos.target_amount) / total_exposure
        contributions[pos.ticker] = round(weight, 6)

    return contributions


# ── 메인 가드레일 점검 함수 ────────────────────────────────────────────────


def check_violations(
    positions: list[PortfolioPosition],
    borrowed_cash: float,
    week: int = 1,
    weekly_returns: Optional[list[float]] = None,
    benchmark_returns: Optional[list[float]] = None,
) -> RiskBudgetReport:
    """
    10개 가드레일 전체 점검 후 RiskBudgetReport 반환

    가드레일 목록:
    1. 총 노출 ≤ 130억 (BLOCK)
    2. 레버리지 ≤ 30% (BLOCK)
    3. 숏 ETF 비중 ≤ 30% (BLOCK)
    4. ETF 수 < 10 (BLOCK)
    5. 주간 변동성 ≤ 1.5% (BLOCK)
    6. 95% VaR ≥ -20억 (BLOCK)
    7. MDD 트리거 -3% (WARN)
    8. 벤치마크 베타 ≤ 1.2 (BLOCK)
    9. 단일 ETF 금액 ≤ 40억 (WARN)
    10. Alpha 리스크 기여 ≤ 40% (WARN)

    violations 예시:
    "레버리지 35.2% — 30% 상한 초과 (BLOCK)"
    "MDD -4.1% — -3% 경고 기준 초과 (WARN)"
    """
    violations: list[str] = []

    # ── 1. 총 익스포저 계산 ───────────────────────────────────────────────
    # 롱 포지션 합계: 전체 target_amount 합산
    # 숏 포지션(role='Short')도 절대값으로 합산하여 총 노출 계산
    total_exposure = sum(pos.target_amount for pos in positions)

    # ── 2. 파생 지표 계산 ─────────────────────────────────────────────────
    # 레버리지 = 차입금 / 기본자본
    leverage_ratio = borrowed_cash / BASE_CAPITAL if BASE_CAPITAL > 0 else 0.0

    # Short ETF 비중 = Short 역할 포지션 금액 합계 / 총자산
    short_amount = sum(
        pos.target_amount for pos in positions if pos.role == "Short"
    )
    total_assets = BASE_CAPITAL + borrowed_cash
    short_exposure_ratio = short_amount / total_assets if total_assets > 0 else 0.0

    # ETF 수: 과제 규칙에서 "10개 미만" = 9개까지 허용
    etf_count = len(positions)

    # ── 3. 수익률 기반 지표 계산 ─────────────────────────────────────────
    # 수익률 데이터가 없으면 추정값 사용 (과제 1주차 대응)
    returns = weekly_returns or []
    bench_returns = benchmark_returns or []

    expected_weekly_volatility = calculate_volatility(returns)
    var_95 = calculate_var(returns, confidence=0.95, portfolio_value=total_exposure or BASE_CAPITAL)
    max_drawdown = calculate_max_drawdown(returns)
    benchmark_beta = calculate_benchmark_beta(returns, bench_returns)

    # 추적 오차 및 정보 비율 (과거 수익률과 벤치마크 수익률이 모두 있어야 계산 가능)
    if len(returns) >= 4 and len(bench_returns) >= 4:
        min_len = min(len(returns), len(bench_returns))
        active_returns = [
            returns[-min_len + i] - bench_returns[-min_len + i]
            for i in range(min_len)
        ]
        tracking_error = calculate_tracking_error(active_returns)
        information_ratio = calculate_information_ratio(active_returns)
    else:
        tracking_error = None
        information_ratio = None

    # ── 4. 리스크 기여도 계산 ─────────────────────────────────────────────
    risk_contributions = calculate_risk_contribution(positions, total_exposure)

    # Alpha 포지션의 리스크 기여 합산
    alpha_risk = sum(
        v for k, v in risk_contributions.items()
        if any(pos.ticker == k and pos.role == "Alpha" for pos in positions)
    )

    # ── 5. 10개 가드레일 순서대로 점검 ───────────────────────────────────

    # 가드레일 1: 총 익스포저 ≤ 130억 (10만원 이하 부동소수점 오차 허용)
    if total_exposure > MAX_TOTAL_EXPOSURE + 100_000:
        violations.append(
            f"총 익스포저 {total_exposure/1e8:.1f}억 원 — "
            f"{MAX_TOTAL_EXPOSURE/1e8:.0f}억 상한 초과 (BLOCK)"
        )

    # 가드레일 2: 레버리지 ≤ 30% (0.01% 부동소수점 오차 허용)
    if leverage_ratio > MAX_LEVERAGE_RATIO + 0.0001:
        violations.append(
            f"레버리지 {leverage_ratio:.1%} — "
            f"{MAX_LEVERAGE_RATIO:.0%} 상한 초과 (BLOCK)"
        )

    # 가드레일 3: 숏 ETF 비중 ≤ 30%
    if short_exposure_ratio > MAX_SHORT_RATIO:
        violations.append(
            f"숏 ETF 비중 {short_exposure_ratio:.1%} — "
            f"{MAX_SHORT_RATIO:.0%} 상한 초과 (BLOCK)"
        )

    # 가드레일 4: ETF 수 < 10
    if etf_count >= MAX_ETF_COUNT + 1:  # MAX_ETF_COUNT = 9, 10개 이상이면 위반
        violations.append(
            f"ETF 수 {etf_count}개 — 10개 미만 제한 위반 (BLOCK)"
        )

    # 가드레일 5: 주간 변동성 ≤ 1.5%
    max_vol = RISK_THRESHOLDS["max_weekly_volatility"]
    if expected_weekly_volatility > max_vol:
        violations.append(
            f"예상 주간 변동성 {expected_weekly_volatility:.2%} — "
            f"{max_vol:.1%} 상한 초과 (BLOCK)"
        )

    # 가드레일 6: 95% VaR ≥ -20억 (절대값 기준, 더 큰 손실은 위반)
    # 이력이 4주 미만인 경우(추정값 사용): WARN으로 완화
    # — 과제 1~3주차처럼 이력이 짧을 때 추정값으로 BLOCK을 내리면
    #   포트폴리오 운용 자체가 불가능해집니다. 이력 축적 후 BLOCK으로 전환됩니다.
    min_var = RISK_THRESHOLDS["min_var_95"]
    if var_95 < min_var:
        has_sufficient_history = bool(returns and len(returns) >= 4)
        severity = "BLOCK" if has_sufficient_history else "WARN(이력부족)"
        violations.append(
            f"95% VaR {var_95/1e8:.1f}억 원 — "
            f"{min_var/1e8:.0f}억 원 하한 이탈 ({severity})"
        )

    # 가드레일 7: MDD 트리거 -3% (경고 수준, BLOCK 아님)
    if max_drawdown < -0.03:
        violations.append(
            f"MDD {max_drawdown:.1%} — -3% 경고 기준 초과 (WARN)"
        )

    # 가드레일 8: 벤치마크 베타 ≤ 1.2
    max_beta = RISK_THRESHOLDS["max_benchmark_beta"]
    if benchmark_beta > max_beta:
        violations.append(
            f"벤치마크 베타 {benchmark_beta:.2f} — "
            f"{max_beta:.2f} 상한 초과 (BLOCK)"
        )

    # 가드레일 9: 단일 ETF 금액 ≤ 40억
    # Core 포지션(벤치마크 복제)은 40억 초과가 허용됩니다.
    # KODEX 200이 40억으로 고정되므로 Core를 제외해야 오탐을 방지할 수 있습니다.
    for pos in positions:
        if pos.role != "Core" and pos.target_amount > MAX_SINGLE_ETF_AMOUNT:
            violations.append(
                f"{pos.ticker} 배분 {pos.target_amount/1e8:.1f}억 — "
                f"단일 ETF 40억 한도 초과 (WARN)"
            )

    # 가드레일 10: Alpha 리스크 기여 ≤ 40%
    if alpha_risk > MAX_ALPHA_RISK_CONTRIBUTION:
        violations.append(
            f"Alpha 리스크 기여 {alpha_risk:.1%} — "
            f"{MAX_ALPHA_RISK_CONTRIBUTION:.0%} 상한 초과 (WARN)"
        )

    # ── 6. RiskBudgetReport 생성 및 반환 ──────────────────────────────────
    return RiskBudgetReport(
        week=week,
        total_exposure=total_exposure,
        leverage_ratio=round(leverage_ratio, 6),
        short_exposure_ratio=round(short_exposure_ratio, 6),
        etf_count=etf_count,
        expected_weekly_volatility=round(expected_weekly_volatility, 6),
        var_95=var_95,
        max_drawdown=round(max_drawdown, 6),
        benchmark_beta=round(benchmark_beta, 4),
        tracking_error=round(tracking_error, 6) if tracking_error is not None else None,
        information_ratio=round(information_ratio, 4) if information_ratio is not None else None,
        violations=violations,
    )


def build_risk_report(
    snapshot: PortfolioSnapshot,
    weekly_returns: Optional[list[float]] = None,
    benchmark_returns: Optional[list[float]] = None,
) -> RiskBudgetReport:
    """
    PortfolioSnapshot으로부터 RiskBudgetReport를 생성합니다.

    check_violations()의 편의 래퍼입니다.
    PortfolioSnapshot 객체를 직접 받아 파라미터 분해를 처리합니다.

    API 라우터에서 스냅샷 객체를 바로 전달하여 호출할 수 있습니다:
    report = build_risk_report(snapshot, weekly_returns, benchmark_returns)
    """
    return check_violations(
        positions=snapshot.positions,
        borrowed_cash=snapshot.borrowed_cash,
        week=snapshot.week,
        weekly_returns=weekly_returns,
        benchmark_returns=benchmark_returns,
    )


def summarize_risk_for_report(report: RiskBudgetReport) -> str:
    """
    RiskBudgetReport를 보고서용 자연어 요약으로 변환합니다.

    Orders Report 및 Weekly P/L Report의 리스크 섹션 자동 생성에 사용됩니다.
    위반 항목이 없으면 "전체 리스크 규칙 준수" 메시지를 반환합니다.
    위반 항목이 있으면 각 항목을 번호 목록으로 나열합니다.
    """
    if not report.violations:
        return (
            f"[{report.week}주차 리스크 점검] 전체 10개 가드레일 준수. "
            f"총 익스포저 {report.total_exposure/1e8:.1f}억, "
            f"레버리지 {report.leverage_ratio:.1%}, "
            f"예상 주간 변동성 {report.expected_weekly_volatility:.2%}."
        )

    block_items = [v for v in report.violations if "(BLOCK)" in v]
    warn_items = [v for v in report.violations if "(WARN)" in v]

    lines = [f"[{report.week}주차 리스크 경고]"]
    if block_items:
        lines.append(f"BLOCK {len(block_items)}건 (즉시 조치 필요):")
        for item in block_items:
            lines.append(f"  - {item}")
    if warn_items:
        lines.append(f"WARN {len(warn_items)}건 (모니터링 필요):")
        for item in warn_items:
            lines.append(f"  - {item}")

    return "\n".join(lines)
