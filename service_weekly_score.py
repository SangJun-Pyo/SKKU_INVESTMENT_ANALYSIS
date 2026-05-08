"""
service_weekly_score.py — ETF 주간 신호 점수 계산 서비스

100점 만점 6개 항목으로 ETF 매매 우선순위를 정량화합니다.
단일 지표에 의존하지 않고 추세/눌림/변동성/모멘텀/낙폭/상관관계를
복합적으로 반영하는 이유:
각 지표는 서로 다른 시장 국면에서 우위가 다르기 때문에
여러 관점을 가중 평균하면 어느 한 지표가 극단적 신호를 낼 때의
오판 확률을 낮출 수 있습니다.

모든 계산은 yfinance OHLCV 데이터를 기반으로 합니다.
외부 데이터 제공자가 없어도 동작하는 것이 핵심 설계 목표입니다.
"""

import math
from typing import Optional

import numpy as np

from models import WeeklySignalScore, PortfolioPosition
from service_market import get_daily_prices


# ── 점수 항목별 가중치 ─────────────────────────────────────────────────────
# 합계는 반드시 1.0 (각 항목 만점의 합이 100점)
# 추세를 가장 높게 두는 이유: 추세는 모든 시간 프레임에서 가장 신뢰도 높은 신호입니다.
SCORE_WEIGHTS = {
    "trend":       0.25,   # 추세 점수: 25점 만점
    "pullback":    0.20,   # 눌림목 점수: 20점 만점
    "volatility":  0.20,   # 변동성 점수: 20점 만점
    "momentum":    0.15,   # 모멘텀 점수: 15점 만점
    "drawdown":    0.10,   # 낙폭 점수: 10점 만점
    "correlation": 0.10,   # 상관관계 점수: 10점 만점
}

# 최소 데이터 요건 — 이보다 적으면 "No Buy" 처리
MIN_DAILY_BARS = 20   # 최소 20일 일간 데이터 (20일 MA 계산 최소치)


# ── RSI 계산 헬퍼 ──────────────────────────────────────────────────────────

def _calc_rsi(closes: list[float], period: int = 14) -> float:
    """
    RSI(Relative Strength Index) 계산

    외부 라이브러리 없이 직접 구현하는 이유:
    ta-lib, pandas-ta 등의 라이브러리는 추가 설치가 필요하며,
    yfinance 환경에서 호환성 문제가 발생할 수 있습니다.
    Wilder's smoothing (지수이동평균 변형)을 사용합니다.

    데이터가 period+1 미만이면 50(중립)을 반환합니다.
    """
    if len(closes) < period + 1:
        # 데이터 부족 시 중립 RSI 반환
        return 50.0

    closes_arr = np.array(closes, dtype=float)
    deltas = np.diff(closes_arr)

    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # 초기 평균: 단순 평균으로 시작 (Wilder 방식)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # 이후 구간: Wilder's 지수평활법 (단순 EMA보다 과거 가중치를 낮춤)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        # 하락이 전혀 없는 경우: RSI 최대치
        return 100.0

    rs  = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


# ── 개별 점수 항목 계산 ────────────────────────────────────────────────────

def _calc_trend_score(closes: list[float]) -> tuple[float, str]:
    """
    추세 점수 계산 (0-25점)

    20일/60일 이동평균 대비 현재가 위치를 측정합니다.
    골든크로스(20MA > 60MA)는 추세 전환의 핵심 신호이므로 보너스를 부여합니다.
    이동평균 기울기(slope)가 양수이면 추가 점수를 줘서 횡보와 상승을 구분합니다.

    점수 구조:
    - 현재가 > 20MA + 20MA > 60MA: 25점
    - 현재가 > 20MA 또는 20MA > 60MA 중 하나: 15점
    - 현재가 < 20MA < 60MA (완전 하락 추세): 0점
    """
    reasons = []
    score = 0.0

    n = len(closes)
    if n < 20:
        return 0.0, "데이터 부족 (최소 20일 필요)"

    ma20 = float(np.mean(closes[-20:]))
    current = closes[-1]

    # 60일 MA: 데이터 있을 때만 계산, 없으면 20MA로 대체
    if n >= 60:
        ma60 = float(np.mean(closes[-60:]))
    else:
        ma60 = float(np.mean(closes))

    # 20일 MA 기울기: 최근 5일 MA 평균과 그 이전 5일 MA 평균 비교
    # 기울기를 5일 구간으로 보는 이유: 단기 노이즈를 줄이기 위해
    if n >= 25:
        ma20_now  = float(np.mean(closes[-20:]))
        ma20_prev = float(np.mean(closes[-25:-5]))
        slope_positive = ma20_now > ma20_prev
    else:
        slope_positive = current > ma20

    # 현재가와 이동평균 위치 평가
    above_ma20 = current > ma20
    above_ma60 = current > ma60
    golden_cross = ma20 > ma60  # 골든크로스 여부

    if above_ma20 and above_ma60 and golden_cross:
        score = 25.0
        reasons.append("완전 상승 추세: 현재가>20MA>60MA(골든크로스)")
    elif above_ma20 and golden_cross:
        score = 20.0
        reasons.append("상승 추세: 현재가>20MA, 골든크로스 유지")
    elif above_ma20 and above_ma60:
        score = 18.0
        reasons.append("상승 추세: 현재가가 두 이동평균 위")
    elif above_ma20:
        score = 12.0
        reasons.append("단기 상승: 현재가>20MA, 60MA 확인 필요")
    elif above_ma60 and not above_ma20:
        score = 8.0
        reasons.append("단기 조정 중: 20MA 아래이나 60MA 위")
    elif not above_ma20 and not above_ma60:
        if ma20 < ma60:
            # 데드크로스: 완전 하락 추세
            score = 0.0
            reasons.append("완전 하락 추세: 데드크로스, 현재가<20MA<60MA")
        else:
            score = 3.0
            reasons.append("하락 추세: 현재가<20MA")
    else:
        score = 5.0
        reasons.append("추세 혼재")

    # 기울기 양수 보너스: 추세가 살아있다는 추가 확신
    if slope_positive and score >= 12:
        score = min(25.0, score + 2.0)
        reasons.append("+기울기 양수")

    return round(score, 2), " | ".join(reasons)


def _calc_pullback_score(closes: list[float], highs: list[float]) -> tuple[float, str]:
    """
    눌림목 점수 계산 (0-20점)

    고점 대비 적절한 조정이 일어난 자리가 최적의 매수 기회입니다.
    - 너무 조금 빠진 구간(0~2%): 아직 충분히 식지 않음 → 낮은 점수
    - 적절히 빠진 구간(-2%~-5%): 눌림목 최적 구간 → 최고 점수
    - 많이 빠진 구간(-5%~-10%): 주의 필요하지만 관심 가능 → 중간 점수
    - 과도한 하락(-10%+): 지지선 붕괴 가능성 → 낮은 점수

    RSI 40-60: 과매수/과매도 아닌 냉각 구간 확인 → 보너스
    """
    reasons = []
    score = 0.0

    if not closes or not highs:
        return 0.0, "데이터 없음"

    # 최근 60일(약 3개월) 내 고점 기준
    lookback = min(60, len(highs))
    recent_high = float(np.max(highs[-lookback:]))
    current = closes[-1]

    if recent_high <= 0:
        return 0.0, "고점 데이터 오류"

    # 고점 대비 조정폭 (음수: 하락, 양수: 고점 돌파)
    pullback_pct = (current - recent_high) / recent_high

    if -0.02 <= pullback_pct <= 0.01:
        # 고점 근처 (0~2% 아래): 조정이 부족해 눌림목 진입 타이밍 아님
        score = 8.0
        reasons.append(f"고점 근처 ({pullback_pct*100:.1f}%), 추가 조정 기다림")
    elif -0.05 < pullback_pct < -0.02:
        # 이상적인 눌림목 구간 (-2%~-5%)
        score = 20.0
        reasons.append(f"눌림목 최적 구간 ({pullback_pct*100:.1f}%)")
    elif -0.10 < pullback_pct <= -0.05:
        # 적당한 조정 (-5%~-10%): 관심 가능하나 추세 확인 필요
        score = 12.0
        reasons.append(f"조정 진행 중 ({pullback_pct*100:.1f}%)")
    elif pullback_pct <= -0.10:
        # 과도한 하락 (-10%+): 지지 붕괴 가능성
        score = 4.0
        reasons.append(f"과도한 하락 ({pullback_pct*100:.1f}%), 리스크 높음")
    else:
        # 고점 돌파 (모멘텀 강하지만 눌림목 진입 타이밍 아님)
        score = 6.0
        reasons.append(f"고점 돌파 (+{pullback_pct*100:.1f}%), 눌림목 대기")

    # RSI 냉각 보너스: RSI 40-60 구간은 과매도/과매수 없는 건강한 눌림목
    rsi = _calc_rsi(closes)
    if 40 <= rsi <= 60:
        score = min(20.0, score + 2.0)
        reasons.append(f"+RSI 냉각({rsi:.0f})")
    elif rsi < 35:
        # 과매도: 단기 반등 가능하나 하락 추세 신호일 수 있음
        score = max(0.0, score - 2.0)
        reasons.append(f"-과매도({rsi:.0f})")
    elif rsi > 70:
        # 과매수: 추가 상승 여력 제한
        score = max(0.0, score - 2.0)
        reasons.append(f"-과매수({rsi:.0f})")

    return round(score, 2), " | ".join(reasons)


def _calc_volatility_score(closes: list[float]) -> tuple[float, str]:
    """
    변동성 점수 계산 (0-20점)

    볼린저 밴드 폭(BB Width)으로 변동성 수준을 측정합니다.
    밴드 폭이 너무 좁으면(침체) 방향성이 없고,
    너무 넓으면(과도한 변동성) 포트폴리오 리스크가 커집니다.

    BB Z-score: 현재가가 볼린저 밴드의 어느 위치인지 (-2 ~ +2)
    하단에 가까울수록(Z-score가 낮을수록) 매수 기회일 수 있습니다.
    """
    reasons = []
    score = 0.0

    if len(closes) < 20:
        return 10.0, "데이터 부족, 중립 점수 적용"

    closes_arr = np.array(closes[-20:], dtype=float)
    ma20 = float(np.mean(closes_arr))
    std20 = float(np.std(closes_arr, ddof=1))

    if ma20 <= 0 or std20 == 0:
        return 10.0, "이동평균 또는 표준편차 계산 오류"

    # 볼린저 밴드 폭: (2*std / MA) — 변동성의 상대적 크기
    bb_width = (2 * std20) / ma20

    # BB Z-score: 현재가의 밴드 내 위치
    current = closes[-1]
    bb_zscore = (current - ma20) / std20

    # 변동성 수준 평가 (BB 폭 기준)
    if 0.03 <= bb_width <= 0.10:
        # 적정 변동성: 방향성 있으면서 리스크 관리 가능
        score = 18.0
        reasons.append(f"적정 변동성(BB폭 {bb_width*100:.1f}%)")
    elif 0.10 < bb_width <= 0.15:
        # 다소 높은 변동성: 주의하되 진입 가능
        score = 14.0
        reasons.append(f"중간 변동성(BB폭 {bb_width*100:.1f}%)")
    elif bb_width > 0.15:
        # 과도한 변동성: 포지션 사이즈 축소 필요
        score = 5.0
        reasons.append(f"과도한 변동성(BB폭 {bb_width*100:.1f}%) - 주의")
    elif bb_width < 0.03:
        # 변동성 침체: 방향성 돌파 임박 가능성 (양방향 리스크)
        score = 8.0
        reasons.append(f"변동성 침체(BB폭 {bb_width*100:.1f}%) - 돌파 대기")
    else:
        score = 10.0
        reasons.append(f"변동성 보통(BB폭 {bb_width*100:.1f}%)")

    # BB Z-score 보너스: 밴드 하단 근처는 매수 기회
    # Z-score -2.0~-0.5: 밴드 하단 근처 → 반등 기대 → 매수 유리
    if -2.0 <= bb_zscore <= -0.5:
        score = min(20.0, score + 2.0)
        reasons.append(f"+밴드 하단 근처(Z={bb_zscore:.2f})")
    elif bb_zscore > 1.5:
        # 밴드 상단 초과: 과매수 신호
        score = max(0.0, score - 2.0)
        reasons.append(f"-밴드 상단 초과(Z={bb_zscore:.2f})")

    return round(score, 2), " | ".join(reasons)


def _calc_momentum_score(closes: list[float]) -> tuple[float, str]:
    """
    모멘텀 점수 계산 (0-15점)

    RSI와 4주 수익률로 모멘텀 강도를 측정합니다.
    RSI 50-65 구간을 최선으로 보는 이유:
    RSI가 너무 낮으면 하락 추세, 너무 높으면 과매수 → 되돌림 리스크
    50-65는 상승 추세를 유지하면서 아직 과열되지 않은 "스위트 스팟"입니다.

    4주 수익률이 양수이면 추세 지속 가능성이 있습니다.
    """
    reasons = []
    score = 0.0

    if len(closes) < 5:
        return 7.5, "데이터 부족, 중립 점수 적용"

    # RSI(14) 계산 — 모멘텀 강도의 핵심 지표
    rsi = _calc_rsi(closes, period=14)

    # RSI 구간별 점수
    if 50 <= rsi <= 65:
        # 최적 구간: 상승 모멘텀이 있으나 과열 아님
        score = 15.0
        reasons.append(f"RSI 최적 구간({rsi:.0f})")
    elif 40 <= rsi < 50:
        # 중립~약세 모멘텀: 전환 가능성 관찰
        score = 9.0
        reasons.append(f"RSI 중립 구간({rsi:.0f})")
    elif 65 < rsi <= 70:
        # 강한 모멘텀이지만 과매수 임박
        score = 10.0
        reasons.append(f"RSI 강세 구간({rsi:.0f}) - 과매수 주의")
    elif rsi > 70:
        # 과매수: 단기 되돌림 가능성 높음
        score = 4.0
        reasons.append(f"RSI 과매수({rsi:.0f}) - 진입 자제")
    elif 30 <= rsi < 40:
        # 약세 모멘텀: 기술적 반등 가능하나 주의
        score = 6.0
        reasons.append(f"RSI 약세({rsi:.0f}) - 반등 가능성 주시")
    else:
        # 과매도: 반등 기대하나 추세 전환 확인 필요
        score = 2.0
        reasons.append(f"RSI 과매도({rsi:.0f}) - 추세 전환 대기")

    # 4주(20 거래일) 수익률: 중기 모멘텀 확인
    # 4주 데이터가 없으면 있는 만큼으로 계산
    #
    # 보정 폭을 넓히는 이유:
    # 상승장에서 ETF 간 모멘텀 강도 차이가 미세하게 나타나 75점 수렴 현상이 발생합니다.
    # 절대 수익률 구간을 세분화하여 (+4~+8%, +8%+, -4~-8%, -8%-) 변별력을 높입니다.
    lookback = min(20, len(closes) - 1)
    if lookback >= 4:
        four_week_return = (closes[-1] - closes[-lookback]) / closes[-lookback]
        if four_week_return > 0.08:
            # +8% 이상: 강한 모멘텀 — 다른 ETF와 확실히 구분되는 추진력
            score = min(15.0, score + 4.0)
            reasons.append(f"+4주 강한 모멘텀({four_week_return*100:.1f}%)")
        elif four_week_return > 0.04:
            # +4~8%: 양호한 모멘텀
            score = min(15.0, score + 3.0)
            reasons.append(f"+4주 수익률 양호({four_week_return*100:.1f}%)")
        elif four_week_return > 0.02:
            # +2~4%: 완만한 상승
            score = min(15.0, score + 2.0)
            reasons.append(f"+4주 수익률 완만({four_week_return*100:.1f}%)")
        elif four_week_return > 0:
            # 소폭 양수: 방향성은 있으나 모멘텀 미약
            score = min(15.0, score + 1.0)
            reasons.append(f"+4주 수익률 소폭 양수({four_week_return*100:.1f}%)")
        elif four_week_return < -0.08:
            # -8% 이하: 급락 — 모멘텀 완전 역전
            score = max(0.0, score - 4.0)
            reasons.append(f"-4주 급락({four_week_return*100:.1f}%)")
        elif four_week_return < -0.04:
            # -4~-8%: 의미 있는 하락
            score = max(0.0, score - 2.0)
            reasons.append(f"-4주 수익률 부진({four_week_return*100:.1f}%)")
        elif four_week_return < -0.02:
            # -2~-4%: 소폭 음수
            score = max(0.0, score - 1.0)
            reasons.append(f"-4주 수익률 소폭 음수({four_week_return*100:.1f}%)")

    return round(score, 2), " | ".join(reasons)


def _calc_drawdown_score(closes: list[float]) -> tuple[float, str]:
    """
    낙폭 점수 계산 (0-10점)

    현재 고점 대비 낙폭(Max Drawdown from recent high)을 측정합니다.
    낙폭이 작을수록 포트폴리오가 건강하다는 의미이므로 역점수(낮은 낙폭 → 높은 점수)입니다.

    이 점수가 독립적으로 존재하는 이유:
    pullback_score는 '매수 타이밍'을 보지만
    drawdown_score는 '현재 포지션 건강도'를 봅니다.
    """
    reasons = []

    if not closes:
        return 0.0, "데이터 없음"

    # 전체 기간 내 최고가 대비 현재가 낙폭
    all_time_high = float(np.max(closes))
    current = closes[-1]

    if all_time_high <= 0:
        return 0.0, "최고가 데이터 오류"

    drawdown = (current - all_time_high) / all_time_high  # 음수

    if drawdown >= -0.05:
        # 낙폭 5% 이내: 건강한 상태
        score = 10.0
        reasons.append(f"낙폭 경미({drawdown*100:.1f}%) - 건강한 포지션")
    elif drawdown >= -0.10:
        # 낙폭 5~10%: 조정 구간
        score = 7.0
        reasons.append(f"낙폭 보통({drawdown*100:.1f}%) - 조정 구간")
    elif drawdown >= -0.20:
        # 낙폭 10~20%: 의미있는 하락
        score = 4.0
        reasons.append(f"낙폭 심화({drawdown*100:.1f}%) - 모니터링 필요")
    else:
        # 낙폭 20%+: 심각한 하락 (손절 고려)
        score = 0.0
        reasons.append(f"낙폭 과도({drawdown*100:.1f}%) - 손절 검토 필요")

    return round(score, 2), " | ".join(reasons)


def _calc_correlation_score(
    ticker: str,
    ticker_closes: list[float],
    all_ohlcv: dict,
) -> tuple[float, str]:
    """
    상관관계 점수 계산 (0-10점)

    [변경] 기존 포트폴리오 기준 → 유니버스 내 다른 ETF들과의 평균 상관관계 기준
    이유: 확정된 포트폴리오가 주가지수 ETF들이면 모든 신규 ETF가 0.70 이상 상관관계를
    가져 전부 1점으로 수렴하는 문제가 있었음.
    유니버스 내 상대 비교를 사용하면 채권·금 등 헤지 ETF와 주식 ETF 간
    자연스러운 점수 차이가 발생함.

    비교 대상이 없으면 7점(중립) 부여.
    """
    reasons = []

    ticker_arr = np.array(ticker_closes, dtype=float)
    if len(ticker_arr) < 10:
        return 5.0, "데이터 부족 - 중립 점수"

    # 유니버스 내 다른 ETF들과의 상관관계 계산
    if not all_ohlcv or len(all_ohlcv) <= 1:
        return 7.0, "비교 대상 ETF 없음 - 기본 점수"

    correlations = []
    for other_ticker, other_data in all_ohlcv.items():
        # 자기 자신은 제외
        if other_ticker == ticker or not other_data:
            continue

        other_closes = [d["close"] for d in other_data]
        other_arr = np.array(other_closes, dtype=float)

        min_len = min(len(ticker_arr), len(other_arr))
        if min_len < 10:
            continue

        try:
            corr = float(np.corrcoef(ticker_arr[-min_len:], other_arr[-min_len:])[0, 1])
            if not math.isnan(corr):
                correlations.append(abs(corr))
        except Exception:
            continue

    if not correlations:
        return 7.0, "상관관계 계산 불가 - 기본 점수"

    avg_corr = float(np.mean(correlations))

    # 상관관계 수준별 점수
    # 채권·금 같은 헤지 자산은 주식과 낮은 상관관계 → 높은 점수
    # 주식 ETF끼리는 필연적으로 높은 상관관계이므로 최솟값 5점 보장
    # (Core ETF가 상관관계로 인해 지나치게 낮은 점수를 받지 않도록)
    if avg_corr < 0.30:
        score = 10.0
        reasons.append(f"낮은 상관관계({avg_corr:.2f}) - 우수한 분산 효과")
    elif avg_corr < 0.50:
        score = 8.0
        reasons.append(f"중간 상관관계({avg_corr:.2f}) - 양호한 분산 효과")
    elif avg_corr < 0.65:
        score = 7.0
        reasons.append(f"보통 상관관계({avg_corr:.2f}) - 적당한 분산 효과")
    elif avg_corr < 0.80:
        score = 6.0
        reasons.append(f"높은 상관관계({avg_corr:.2f}) - 분산 효과 제한")
    else:
        score = 5.0
        reasons.append(f"매우 높은 상관관계({avg_corr:.2f}) - 주식 ETF 특성상 기본점수")

    return round(score, 2), " | ".join(reasons)


# ── 레짐 분류 및 액션 결정 ──────────────────────────────────────────────────

def classify_regime(total_score: float, trend_score: float, volatility_score: float) -> str:
    """
    시장 레짐 분류

    레짐을 별도로 분류하는 이유:
    총점이 같아도 추세 구조가 다를 수 있습니다.
    예: 총점 60점이라도 추세는 강하지만 변동성이 높은 경우(Risk-On 주의)와
        추세는 약하지만 변동성이 낮은 경우(Neutral)는 다른 대응이 필요합니다.

    Risk-On:  총점 65+ AND 추세 15+ AND 변동성 12+ → 공격적 배분 가능
    Risk-Off: 총점 <40 OR 추세 <8 OR 변동성 <6   → 방어 전환
    Neutral:  나머지 → 현상 유지
    """
    is_risk_on = (
        total_score >= 65 and
        trend_score >= 15 and
        volatility_score >= 12
    )
    is_risk_off = (
        total_score < 40 or
        trend_score < 8 or
        volatility_score < 6
    )

    if is_risk_on:
        return "Risk-On"
    elif is_risk_off:
        return "Risk-Off"
    else:
        return "Neutral"


def get_action(total_score: float) -> str:
    """
    총점 → 매매 액션 결정

    구간을 명확하게 정해 두는 이유:
    판단 기준이 명시적일수록 리스크 규칙 위반 시 설명이 용이합니다.
    """
    if total_score >= 80:
        return "Increase"
    elif total_score >= 65:
        return "Small Buy"
    elif total_score >= 50:
        return "Hold"
    elif total_score >= 35:
        return "Reduce"
    else:
        return "Exit"


# ── 메인 점수 계산 함수 ────────────────────────────────────────────────────

def score_etf(
    ticker: str,
    week: int,
    portfolio: Optional[list[PortfolioPosition]] = None,
    all_ohlcv: Optional[dict] = None,
) -> WeeklySignalScore:
    """
    단일 ETF 점수 계산

    데이터 흐름:
    1. yfinance에서 일간 3개월 데이터 조회 (이동평균, BB, RSI용)
    2. 6개 항목 각각 계산
    3. 합산 후 레짐/액션 결정
    4. WeeklySignalScore 객체 반환

    데이터 부족(일간 20봉 미만)이면 No Buy를 반환합니다.
    서버 오류가 발생해도 No Buy로 안전하게 처리합니다.
    """
    try:
        # 일간 데이터: 이동평균, 볼린저밴드, 눌림목, 낙폭 계산에 사용
        daily_data = get_daily_prices(ticker, days=60)

        if len(daily_data) < MIN_DAILY_BARS:
            # 데이터 부족: 점수 계산 불가
            return WeeklySignalScore(
                ticker=ticker,
                week=week,
                trend_score=0.0,
                pullback_score=0.0,
                volatility_score=0.0,
                momentum_score=0.0,
                drawdown_score=0.0,
                correlation_score=0.0,
                total_score=0.0,
                regime="Risk-Off",
                action="No Buy",
                reason=f"데이터 부족: {len(daily_data)}봉 (최소 {MIN_DAILY_BARS}봉 필요)",
            )

        # OHLCV에서 Close, High 시리즈 추출
        closes = [d["close"] for d in daily_data]
        highs  = [d["high"]  for d in daily_data]

        # ── 6개 항목 계산 ──
        trend_s,   trend_reason   = _calc_trend_score(closes)
        pullback_s, pullback_reason = _calc_pullback_score(closes, highs)
        vol_s,     vol_reason     = _calc_volatility_score(closes)
        mom_s,     mom_reason     = _calc_momentum_score(closes)
        dd_s,      dd_reason      = _calc_drawdown_score(closes)
        corr_s,    corr_reason    = _calc_correlation_score(
            ticker, closes, all_ohlcv or {}
        )

        # 합산 점수 (각 항목 만점의 합 = 100점)
        total = round(
            trend_s + pullback_s + vol_s + mom_s + dd_s + corr_s, 2
        )

        regime = classify_regime(total, trend_s, vol_s)
        action = get_action(total)

        # 보고서용 근거 문자열 (각 항목을 줄바꿈으로 연결)
        reason_parts = [
            f"[추세] {trend_reason}",
            f"[눌림목] {pullback_reason}",
            f"[변동성] {vol_reason}",
            f"[모멘텀] {mom_reason}",
            f"[낙폭] {dd_reason}",
            f"[상관관계] {corr_reason}",
        ]
        reason = " / ".join(reason_parts)

        return WeeklySignalScore(
            ticker=ticker,
            week=week,
            trend_score=trend_s,
            pullback_score=pullback_s,
            volatility_score=vol_s,
            momentum_score=mom_s,
            drawdown_score=dd_s,
            correlation_score=corr_s,
            total_score=total,
            regime=regime,
            action=action,
            reason=reason,
        )

    except Exception as e:
        # 예외 상황에서도 서버가 멈추지 않도록 No Buy 반환
        print(f"[service_weekly_score] {ticker} 점수 계산 오류: {e}")
        return WeeklySignalScore(
            ticker=ticker,
            week=week,
            trend_score=0.0,
            pullback_score=0.0,
            volatility_score=0.0,
            momentum_score=0.0,
            drawdown_score=0.0,
            correlation_score=0.0,
            total_score=0.0,
            regime="Risk-Off",
            action="No Buy",
            reason=f"점수 계산 오류: {str(e)}",
        )


def score_all(
    tickers: list[str],
    week: int,
    portfolio: Optional[list[PortfolioPosition]] = None,
) -> list[WeeklySignalScore]:
    """
    유니버스 전체 ETF 점수 계산

    순차 처리하는 이유:
    yfinance는 동시 다중 요청 시 rate limit 오류가 발생하기 쉽습니다.
    ETF 수가 최대 9개(규칙상)이므로 순차 처리해도 성능에 큰 영향이 없습니다.

    상관관계 계산을 위해 모든 ETF의 OHLCV를 먼저 수집합니다.
    이렇게 하면 ticker별 score_etf 호출 시 이미 캐시된 데이터를 재활용합니다.
    """
    if not tickers:
        return []

    # 상관관계 계산을 위해 전체 OHLCV 사전 수집
    all_ohlcv: dict = {}
    for ticker in tickers:
        data = get_daily_prices(ticker, days=60)
        if data:
            all_ohlcv[ticker] = data

    results = []
    for ticker in tickers:
        score = score_etf(
            ticker=ticker,
            week=week,
            portfolio=portfolio,
            all_ohlcv=all_ohlcv,
        )
        results.append(score)

    # ── 상대강도 보정 (유니버스 내 ETF 간 비교) ───────────────────────────────
    # 3개월 수익률을 기준으로 ETF 간 상대 순위를 계산해
    # 같은 상승장에서도 더 강한 ETF가 높은 점수를 받도록 보정합니다.
    #
    # 이 단계가 필요한 이유:
    # 상승장에서 개별 점수 계산만으로는 모든 ETF가 비슷한 구간(75점 전후)에 수렴합니다.
    # 상대강도 보정을 통해 "같은 상승장에서 누가 더 강한가"를 정량화합니다.
    # 보정 범위: -5점 ~ +5점 (기존 총점을 과도하게 왜곡하지 않기 위해)

    returns_3m = {}
    for ticker in tickers:
        ohlcv = all_ohlcv.get(ticker, [])
        # 약 3개월(60거래일) 데이터가 있을 때만 계산합니다.
        if len(ohlcv) >= 60:
            start = ohlcv[-60]["close"]
            end   = ohlcv[-1]["close"]
            if start > 0:
                returns_3m[ticker] = (end - start) / start

    # ETF가 2개 이상일 때만 상대강도를 의미 있게 계산할 수 있습니다.
    if len(returns_3m) >= 2:
        min_r = min(returns_3m.values())
        max_r = max(returns_3m.values())
        r_range = max_r - min_r

        # 최소 0.1% 이상 수익률 차이가 있을 때만 보정합니다.
        # 차이가 없는 경우(동일한 ETF군 등) 불필요한 부동소수점 오차 방지
        if r_range > 0.001:
            for i, sc in enumerate(results):
                if sc.ticker in returns_3m:
                    # 0(최저) ~ 10(최고)점 선형 매핑 후 중간값(5점) 기준으로 ±5 보정
                    rs = (returns_3m[sc.ticker] - min_r) / r_range * 10
                    adjustment = round(rs - 5.0, 2)

                    old_total = sc.total_score
                    new_total = round(max(0.0, min(100.0, old_total + adjustment)), 2)

                    # Pydantic v2: model_copy(update=...) 로 불변 객체를 복사·수정합니다.
                    # 직접 필드 대입을 피하는 이유: Pydantic v2에서 모델은 기본적으로 불변입니다.
                    updated = sc.model_copy(update={
                        "total_score": new_total,
                        "action": get_action(new_total),
                        "regime": classify_regime(new_total, sc.trend_score, sc.volatility_score),
                        "reason": sc.reason + (
                            f" / [상대강도 보정 {adjustment:+.1f}pt, "
                            f"3M수익률 {returns_3m[sc.ticker]*100:.1f}%]"
                        ),
                    })
                    results[i] = updated

    # 총점 내림차순 정렬 (높은 점수 ETF가 먼저)
    results.sort(key=lambda s: s.total_score, reverse=True)
    return results
