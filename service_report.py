"""
service_report.py — 마크다운 리포트 자동 생성 서비스

Orders Report, Risk Rules, P&L Report 3가지를 마크다운으로 생성합니다.
과제 제출을 위한 한국어 보고서 형식에 맞춥니다.

보고서를 코드로 생성하는 이유:
- 매주 같은 형식을 반복 작성하는 수작업 제거
- 정량 데이터가 텍스트에 자동 반영되어 오기입 방지
- 리스크 위반 항목이 있으면 자동으로 경고 문구 삽입

모든 보고서 텍스트는 한국어로 작성합니다.
"""

from datetime import datetime
from typing import Optional

from models import WeeklyOrder, RiskBudgetReport, WeeklySignalScore, WeeklyPnL
from config import (
    CLASS_BENCHMARK,
    MAX_LEVERAGE_RATIO,
    MAX_ETF_COUNT,
    BASE_CAPITAL,
    MAX_TOTAL_EXPOSURE,
    MAX_BORROWING,
    WEEKLY_BORROW_COST,
    WEEKLY_CASH_INTEREST,
    RISK_THRESHOLDS,
)


# ── 내부 헬퍼 함수 ────────────────────────────────────────────────────────

def _fmt_krw(amount: float) -> str:
    """
    금액을 한국어 단위로 포맷합니다.
    억/만 단위를 사용하는 이유: 한국 금융에서 통용되는 단위이기 때문입니다.
    """
    abs_amount = abs(amount)
    sign = "-" if amount < 0 else ""

    if abs_amount >= 1_000_000_000:
        return f"{sign}{abs_amount / 1_000_000_000:.2f}억원"
    elif abs_amount >= 10_000:
        return f"{sign}{abs_amount / 10_000:.0f}만원"
    else:
        return f"{sign}{abs_amount:,.0f}원"


def _fmt_pct(value: float, decimals: int = 2) -> str:
    """수익률/비율을 백분율 문자열로 포맷합니다."""
    return f"{value * 100:.{decimals}f}%"


def _risk_status(passed: bool) -> str:
    """리스크 규칙 통과 여부를 이모지 없이 텍스트로 표시합니다."""
    return "통과" if passed else "위반"


# ── 리포트 생성 함수 ──────────────────────────────────────────────────────

def generate_risk_rules(week: int = 1) -> str:
    """
    리스크 규칙 마크다운 생성 (첫 금요일 제출용)

    과제의 리스크 관리 규칙 8개를 문서화합니다.
    규칙을 코드로 관리하는 이유: config.py 상수와 일치하는 수치를 보장하기 위해서입니다.
    손절/부분청산/레버리지 축소/방어 전환 규칙은 과제 요건에 따라 설정되어 있습니다.
    """
    borrow_cost_pct = _fmt_pct(WEEKLY_BORROW_COST)
    cash_int_pct    = _fmt_pct(WEEKLY_CASH_INTEREST)
    max_lev_pct     = _fmt_pct(MAX_LEVERAGE_RATIO)
    max_etf         = MAX_ETF_COUNT
    max_borrow_krw  = _fmt_krw(MAX_BORROWING)
    base_krw        = _fmt_krw(BASE_CAPITAL)
    max_exp_krw     = _fmt_krw(MAX_TOTAL_EXPOSURE)

    lines = [
        f"# MarkovPortfolio V4 — 리스크 규칙 (Week {week})",
        "",
        f"> 제출일: {datetime.now().strftime('%Y-%m-%d')}  ",
        f"> 기본 자본: {base_krw} | 최대 익스포저: {max_exp_krw} | 최대 차입: {max_borrow_krw}",
        "",
        "---",
        "",
        "## 포트폴리오 구조 규칙",
        "",
        "| 항목 | 기준값 | 비고 |",
        "|---|---|---|",
        f"| 기본 자본 | {base_krw} | 변경 불가 |",
        f"| 최대 차입(레버리지) | {max_borrow_krw} ({max_lev_pct}) | 초과 시 차단 |",
        f"| 총 익스포저 상한 | {max_exp_krw} | 롱+숏 합산 |",
        f"| ETF 최대 보유 수 | {max_etf}개 | 초과 시 신규 매수 차단 |",
        f"| 체결 기준 | 금요일 종가 | 모든 주문은 금요일 종가 기준 |",
        f"| 차입 이자 | 주간 {borrow_cost_pct} | 매주 P/L에서 차감 |",
        f"| 현금 이자 | 주간 {cash_int_pct} | 미배분 현금에 적용 |",
        "",
        "---",
        "",
        "## 벤치마크",
        "",
        "| 구성 | 비중 | ETF |",
        "|---|---|---|",
        f"| KOSPI200 | {_fmt_pct(CLASS_BENCHMARK['kospi200'])} | KODEX 200 (069500.KS) |",
        f"| S&P500 헷지 | {_fmt_pct(CLASS_BENCHMARK['sp500Hedged'])} | KODEX S&P500선물(H) (219480.KS) |",
        f"| S&P500 비헷지 | {_fmt_pct(CLASS_BENCHMARK['sp500Unhedged'])} | KODEX S&P500 TR (379800.KS) |",
        "",
        "---",
        "",
        "## 개별 포지션 리스크 규칙",
        "",
        "### 규칙 1 — 손절 (Hard Stop)",
        "",
        "- **조건**: 개별 ETF 진입가 대비 **-5% 하락** 시",
        "- **실행**: 해당 ETF 전량 청산 (금요일 종가 기준)",
        "- **목적**: 단일 ETF가 포트폴리오 전체에 미치는 최대 손실을 제한합니다.",
        "",
        "### 규칙 2 — 부분 청산 (Soft Stop)",
        "",
        "- **조건**: 개별 ETF 진입가 대비 **-3% 하락** 시",
        "- **실행**: 해당 ETF 보유 수량의 50% 매도",
        "- **목적**: 추세가 살아있을 가능성을 열어두면서 손실을 제한합니다.",
        "",
        "### 규칙 3 — Alpha 포지션 청산 (Signal Exit)",
        "",
        "- **조건**: 해당 Alpha ETF의 주간 신호 점수가 **50점 미만** 으로 하락 시",
        "- **실행**: Alpha 포지션 전량 청산",
        "- **목적**: 점수 기반 시스템에서 약한 신호는 포지션을 유지할 근거가 없습니다.",
        "",
        "### 규칙 4 — 익절 (Take Profit)",
        "",
        "- **조건**: 개별 ETF 진입가 대비 **+5% 상승** 시",
        "- **실행**: 해당 ETF 보유의 30~50% 실현",
        "- **목적**: 수익 일부를 확정하고 추가 상승에도 참여합니다.",
        "",
        "---",
        "",
        "## 포트폴리오 수준 리스크 규칙",
        "",
        "### 규칙 5 — 레버리지 축소 (Weekly Loss Trigger)",
        "",
        "- **조건**: 해당 주 포트폴리오 손실이 **-1.5%** 초과 시",
        "- **실행**: 차입금을 현재의 50%로 축소, 초과 포지션 매도",
        "- **목적**: 연속 손실 시 레버리지로 인한 급격한 자본 훼손을 방지합니다.",
        "",
        "### 규칙 6 — 방어 전환 (Drawdown Defense)",
        "",
        "- **조건**: 누적 손실이 **-3%** 초과 시",
        "- **실행**: Alpha 포지션 전량 청산 → Core 100% 비중으로 전환",
        "- **목적**: 심각한 손실 구간에서는 벤치마크 복제로 하방을 막습니다.",
        "",
        "### 규칙 7 — 신규 주문 한도 (Turnover Limit)",
        "",
        "- **조건**: 매주 적용",
        "- **실행**: 신규 매수/매도 총액은 직전 주 거래대금의 **25% 이내**",
        "- **목적**: 과도한 회전율(거래비용)을 억제하고 장기 전략을 유지합니다.",
        "",
        "### 규칙 8 — 차입 한도 (Borrowing Cap)",
        "",
        "- **조건**: 항상 적용",
        f"- **실행**: 차입금은 최대 {max_borrow_krw} (총 자산의 {max_lev_pct}) 이내",
        "- **목적**: 레버리지 한도를 명시적으로 제한합니다.",
        "",
        "---",
        "",
        "## 가드레일 요약 (Guard Rails)",
        "",
        "| # | 항목 | 기준 | 위반 시 조치 |",
        "|---|---|---|---|",
        f"| 1 | 총 익스포저 | {max_exp_krw} 이하 | BLOCK — 주문 거부 |",
        f"| 2 | 레버리지 비율 | {max_lev_pct} 이하 | BLOCK |",
        f"| 3 | Short/ETF 비율 | {_fmt_pct(MAX_LEVERAGE_RATIO)} 이하 | BLOCK |",
        f"| 4 | ETF 개수 | {max_etf}개 이하 | BLOCK |",
        f"| 5 | 주간 변동성 | {_fmt_pct(RISK_THRESHOLDS['max_weekly_volatility'])} 이하 | WARN |",
        f"| 6 | 95% VaR | {_fmt_krw(RISK_THRESHOLDS['min_var_95'])} 이상 | WARN |",
        f"| 7 | 벤치마크 베타 | {RISK_THRESHOLDS['max_benchmark_beta']:.2f} 이하 | WARN |",
        f"| 8 | 개별 ETF 손절 | -5% | 자동 청산 트리거 |",
        f"| 9 | 부분 청산 | -3% | 50% 청산 트리거 |",
        f"| 10 | 신호 점수 | 50점 미만 | Alpha 청산 |",
        "",
        "---",
        "",
        f"*본 리스크 규칙은 MarkovPortfolio V4 시스템에 하드코딩되어 있으며,",
        f"위반 시 자동으로 BLOCK 또는 WARN 처리됩니다.*",
    ]

    return "\n".join(lines)


def generate_orders_report(
    week: int,
    date: str,
    orders: list[WeeklyOrder],
    risk_report: RiskBudgetReport,
    scores: list[WeeklySignalScore],
    market_summary: str = "",
) -> str:
    """
    Orders Report 마크다운 생성 (5섹션)

    금요일 종가 기준의 주문 내역 보고서를 생성합니다.
    각 섹션이 독립적인 이유: 교수가 특정 섹션만 확인하는 경우에도 내용이 명확해야 합니다.

    시장 배경이 없으면 점수 데이터에서 자동으로 레짐을 추출합니다.
    리스크 위반이 있으면 위반 경고 문구를 자동 삽입합니다.
    """
    lines = []

    # ── 헤더 ──
    lines += [
        f"# MarkovPortfolio V4 — Week {week} Orders Report",
        f"> 기준일: {date} (금요일 종가 체결)",
        "",
        "---",
        "",
    ]

    # ── 섹션 1: 시장 배경 ──
    lines += ["## 1. 시장 배경", ""]

    if market_summary:
        lines += [market_summary, ""]
    elif scores:
        # 점수 데이터에서 레짐 분포 자동 요약
        risk_on  = sum(1 for s in scores if s.regime == "Risk-On")
        neutral  = sum(1 for s in scores if s.regime == "Neutral")
        risk_off = sum(1 for s in scores if s.regime == "Risk-Off")
        dominant = max(
            [("Risk-On", risk_on), ("Neutral", neutral), ("Risk-Off", risk_off)],
            key=lambda x: x[1]
        )[0]

        lines += [
            f"유니버스 {len(scores)}개 ETF 신호 점수 분석 결과:",
            f"- Risk-On: {risk_on}개 | Neutral: {neutral}개 | Risk-Off: {risk_off}개",
            f"- 지배적 레짐: **{dominant}**",
            "",
        ]
    else:
        lines += ["시장 배경 데이터 없음.", ""]

    # ── 섹션 2: 전략 방향 ──
    lines += ["## 2. 전략 방향", ""]

    if scores:
        # 상위 5개 ETF 점수 요약
        top5 = sorted(scores, key=lambda s: s.total_score, reverse=True)[:5]
        lines += ["**ETF 신호 점수 상위 종목:**", ""]
        lines += ["| 종목 | 총점 | 추세 | 눌림목 | 변동성 | 레짐 | 액션 |"]
        lines += ["|---|---|---|---|---|---|---|"]
        for s in top5:
            lines += [
                f"| {s.ticker} | {s.total_score:.0f}점 | "
                f"{s.trend_score:.0f} | {s.pullback_score:.0f} | "
                f"{s.volatility_score:.0f} | {s.regime} | {s.action} |"
            ]
        lines += [""]

        # Increase/Small Buy 종목 강조
        buy_scores = [s for s in scores if s.action in ("Increase", "Small Buy")]
        if buy_scores:
            lines += ["**이번 주 매수 신호 ETF:**", ""]
            for s in buy_scores:
                lines += [f"- {s.ticker}: {s.total_score:.0f}점 ({s.action}) — {s.reason[:80]}..."]
            lines += [""]

    else:
        lines += ["신호 점수 데이터 없음.", ""]

    # ── 섹션 3: 리스크 체크 ──
    lines += ["## 3. 리스크 체크 (가드레일 10개)", ""]

    # 각 가드레일 통과 여부 확인
    max_exp = MAX_TOTAL_EXPOSURE
    violations_set = set(risk_report.violations)

    exp_ok   = risk_report.total_exposure <= max_exp
    lev_ok   = risk_report.leverage_ratio <= MAX_LEVERAGE_RATIO
    short_ok = risk_report.short_exposure_ratio <= MAX_LEVERAGE_RATIO
    etf_ok   = risk_report.etf_count <= MAX_ETF_COUNT
    vol_ok   = risk_report.expected_weekly_volatility <= RISK_THRESHOLDS["max_weekly_volatility"]
    var_ok   = risk_report.var_95 >= RISK_THRESHOLDS["min_var_95"]
    beta_ok  = risk_report.benchmark_beta <= RISK_THRESHOLDS["max_benchmark_beta"]

    lines += ["| # | 가드레일 | 현재값 | 기준 | 결과 |"]
    lines += ["|---|---|---|---|---|"]
    lines += [
        f"| 1 | 총 익스포저 | {_fmt_krw(risk_report.total_exposure)} | "
        f"{_fmt_krw(max_exp)} 이하 | {_risk_status(exp_ok)} |",

        f"| 2 | 레버리지 비율 | {_fmt_pct(risk_report.leverage_ratio)} | "
        f"{_fmt_pct(MAX_LEVERAGE_RATIO)} 이하 | {_risk_status(lev_ok)} |",

        f"| 3 | Short 비율 | {_fmt_pct(risk_report.short_exposure_ratio)} | "
        f"{_fmt_pct(MAX_LEVERAGE_RATIO)} 이하 | {_risk_status(short_ok)} |",

        f"| 4 | ETF 개수 | {risk_report.etf_count}개 | "
        f"{MAX_ETF_COUNT}개 이하 | {_risk_status(etf_ok)} |",

        f"| 5 | 주간 변동성 | {_fmt_pct(risk_report.expected_weekly_volatility)} | "
        f"{_fmt_pct(RISK_THRESHOLDS['max_weekly_volatility'])} 이하 | {_risk_status(vol_ok)} |",

        f"| 6 | 95% VaR | {_fmt_krw(risk_report.var_95)} | "
        f"{_fmt_krw(RISK_THRESHOLDS['min_var_95'])} 이상 | {_risk_status(var_ok)} |",

        f"| 7 | 벤치마크 베타 | {risk_report.benchmark_beta:.3f} | "
        f"{RISK_THRESHOLDS['max_benchmark_beta']:.2f} 이하 | {_risk_status(beta_ok)} |",
    ]

    # 나머지 3개 가드레일 (손절/부분청산/신호점수는 별도 룰)
    lines += [
        "| 8 | 손절 트리거(-5%) | 자동 모니터링 | 진입가 대비 -5% | 규칙 설정 완료 |",
        "| 9 | 부분청산(-3%) | 자동 모니터링 | 진입가 대비 -3% | 규칙 설정 완료 |",
        "| 10 | 신호점수(Alpha) | 자동 계산 | 50점 미만 시 청산 | 규칙 설정 완료 |",
    ]
    lines += [""]

    if risk_report.violations:
        lines += ["**[경고] 가드레일 위반 항목:**", ""]
        for v in risk_report.violations:
            lines += [f"- {v}"]
        lines += [""]
    else:
        lines += ["모든 가드레일을 통과했습니다.", ""]

    # ── 섹션 4: 주문 내역 ──
    lines += ["## 4. 주문 내역 (금요일 종가 체결)", ""]

    if orders:
        lines += ["| 종목 | 액션 | 금액 | 목표비중 | 리스크 | 근거 |"]
        lines += ["|---|---|---|---|---|---|"]
        for o in orders:
            lines += [
                f"| {o.ticker} | {o.action} | {_fmt_krw(o.amount)} | "
                f"{_fmt_pct(o.target_weight)} | {o.risk_check} | {o.reason[:50]}... |"
            ]
        lines += [""]

        # BLOCK 주문 경고
        blocked = [o for o in orders if o.risk_check == "BLOCK"]
        if blocked:
            lines += ["**[차단] 리스크 위반으로 다음 주문은 실행되지 않습니다:**", ""]
            for o in blocked:
                lines += [f"- {o.ticker} {o.action}: {o.reason}"]
            lines += [""]
    else:
        lines += ["이번 주 주문 없음 (Hold 유지).", ""]

    # ── 섹션 5: 결론 ──
    lines += ["## 5. 결론", ""]

    total_buy   = sum(o.amount for o in orders if o.action in ("BUY", "Small Buy", "Increase"))
    total_sell  = sum(o.amount for o in orders if o.action in ("SELL", "REDUCE", "COVER"))
    net_trade   = total_buy - total_sell

    lines += [
        f"- 이번 주 총 매수 금액: {_fmt_krw(total_buy)}",
        f"- 이번 주 총 매도 금액: {_fmt_krw(total_sell)}",
        f"- 순 거래 금액(순매수): {_fmt_krw(net_trade)}",
        "",
        "**다음 주 모니터링 포인트:**",
        "",
        "- 금요일 종가 확인 후 P/L 입력",
        "- 개별 ETF 손절/익절 트리거 모니터링",
        "- 벤치마크 대비 초과수익(Active Return) 추적",
        "- 레짐 변화 시 Core/Alpha 비중 재검토",
        "",
        "---",
        "",
        f"*본 보고서는 MarkovPortfolio V4 자동 생성 보고서입니다. ({datetime.now().strftime('%Y-%m-%d %H:%M')})*",
    ]

    return "\n".join(lines)


def generate_weekly_pnl_report(
    week: int,
    pnl: WeeklyPnL,
    all_pnl: list[WeeklyPnL],
) -> str:
    """
    주간 P&L 리포트 마크다운 생성

    포트폴리오 vs 벤치마크 비교, ETF별 기여도, 누적 성과, 비용 분석을 포함합니다.
    교수 평가 시 '비용을 정확히 반영했는가'를 확인하므로 비용 섹션을 별도로 분리합니다.
    """
    lines = []

    date_str = pnl.date

    # ── 헤더 ──
    lines += [
        f"# MarkovPortfolio V4 — Week {week} P&L Report",
        f"> 기준일: {date_str}",
        "",
        "---",
        "",
    ]

    # ── 섹션 1: 성과 요약 ──
    lines += ["## 성과 요약", ""]

    # Active Return 방향 판단
    active = pnl.active_return
    active_label = "초과" if active >= 0 else "미달"

    lines += [
        "| 항목 | 이번 주 | 비고 |",
        "|---|---|---|",
        f"| 포트폴리오 수익률 | {_fmt_pct(pnl.portfolio_return)} | 비용 차감 전 |",
        f"| 벤치마크 수익률 | {_fmt_pct(pnl.benchmark_return)} | 40/30/30 가중평균 |",
        f"| 초과수익(Active Return) | {_fmt_pct(active)} | 벤치마크 {active_label} |",
        f"| 차입 비용 | -{_fmt_pct(pnl.leverage_cost)} | 주간 0.07% 적용 |",
        f"| 현금 이자 | +{_fmt_pct(pnl.cash_interest)} | 주간 0.035% 적용 |",
        f"| **순수익률(Net Return)** | **{_fmt_pct(pnl.net_return)}** | 비용 차감 후 |",
        f"| 누적 수익률 | {_fmt_pct(pnl.cumulative_return)} | 1주차부터 복리 |",
        "",
    ]

    # ── 섹션 2: ETF별 기여도 ──
    lines += ["## ETF별 기여도", ""]

    if pnl.contribution_by_etf:
        # 기여도 내림차순 정렬
        sorted_contrib = sorted(
            pnl.contribution_by_etf.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        lines += ["| ETF | 기여도 | 평가 |"]
        lines += ["|---|---|---|"]
        for ticker, contrib in sorted_contrib:
            eval_str = "기여" if contrib >= 0 else "손실"
            lines += [f"| {ticker} | {_fmt_pct(contrib)} | {eval_str} |"]
        lines += [""]
    else:
        lines += ["ETF별 기여도 데이터 없음.", ""]

    # ── 섹션 3: 누적 성과 (주별 비교) ──
    lines += ["## 누적 성과 (주별)", ""]

    if all_pnl:
        lines += ["| 주차 | 날짜 | 포트폴리오 | 벤치마크 | Active | 누적 |"]
        lines += ["|---|---|---|---|---|---|"]

        # 누적 벤치마크 수익률도 동시에 계산
        cumulative_bm = 1.0
        for p in all_pnl:
            cumulative_bm *= (1 + p.benchmark_return)
            cum_bm_ret = cumulative_bm - 1.0

            lines += [
                f"| {p.week}주 | {p.date} | {_fmt_pct(p.net_return)} | "
                f"{_fmt_pct(p.benchmark_return)} | {_fmt_pct(p.active_return)} | "
                f"{_fmt_pct(p.cumulative_return)} |"
            ]
        lines += [""]
    else:
        lines += ["누적 성과 데이터 없음.", ""]

    # ── 섹션 4: 비용 분석 ──
    lines += ["## 비용 분석", ""]

    lines += [
        "| 비용 항목 | 비율 | 금액 환산(100억 기준) | 비고 |",
        "|---|---|---|---|",
        f"| 차입 이자 | {_fmt_pct(pnl.leverage_cost)} | {_fmt_krw(pnl.leverage_cost * 10_000_000_000)} | 차입금 × 0.07% |",
        f"| 현금 이자 수익 | +{_fmt_pct(pnl.cash_interest)} | +{_fmt_krw(pnl.cash_interest * 10_000_000_000)} | 현금 × 0.035% |",
        f"| 순 비용 부담 | {_fmt_pct(pnl.leverage_cost - pnl.cash_interest)} | {_fmt_krw((pnl.leverage_cost - pnl.cash_interest) * 10_000_000_000)} | 차입비 - 현금이자 |",
        "",
        "> 차입을 활용할수록 비용이 증가하므로, Alpha 수익이 차입 비용을 상회해야 합니다.",
        "",
    ]

    # ── 섹션 5: 다음 주 계획 ──
    lines += ["## 다음 주 계획", ""]

    lines += [
        "- [ ] 금요일 종가 확인 및 P/L 입력",
        "- [ ] 주간 신호 점수 재계산",
        "- [ ] 손절/익절 트리거 확인",
        "- [ ] 리스크 가드레일 점검",
        "- [ ] 벤치마크 대비 Active Return 추적",
        "",
        "---",
        "",
        f"*본 보고서는 MarkovPortfolio V4 자동 생성 보고서입니다. ({datetime.now().strftime('%Y-%m-%d %H:%M')})*",
    ]

    return "\n".join(lines)
