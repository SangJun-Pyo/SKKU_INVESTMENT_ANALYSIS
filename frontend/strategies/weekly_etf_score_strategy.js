/**
 * weekly_etf_score_strategy.js — 주간 ETF 점수 계산 전략 (클라이언트 사이드)
 *
 * 역할:
 * - OHLCV 데이터에서 6개 점수를 계산합니다.
 * - 서버 /papertrade/score/run 호출 전 클라이언트 미리보기에 사용 가능합니다.
 * - 서버의 service_weekly_score.py와 동일한 로직을 유지해야 합니다.
 *
 * 의존성:
 * - RegimeClassifier (regime_classifier.js)
 * - PullbackEntryStrategy (pullback_entry_strategy.js)
 *
 * 점수 체계:
 *   trend_score:       0-25점 (20일/60일 이동평균 방향성)
 *   pullback_score:    0-20점 (눌림목 진입 조건)
 *   volatility_score:  0-20점 (변동성이 한도 이내인지)
 *   momentum_score:    0-15점 (최근 4주 수익률, RSI)
 *   drawdown_score:    0-10점 (고점 대비 낙폭 역점수)
 *   correlation_score: 0-10점 (기존 포트폴리오와 상관관계 낮을수록 유리)
 */
window.WeeklyETFScoreStrategy = (() => {
  'use strict';

  /**
   * 단일 ETF 점수 계산
   * @param {string} ticker  - ETF 티커
   * @param {Array}  ohlcv   - OHLCV 배열 [{time, open, high, low, close, volume}]
   * @param {number} week    - 현재 주차
   * @param {Array}  existingPositions - 기존 포트폴리오 포지션 (상관관계 계산용)
   * @returns {WeeklySignalScore} 점수 객체
   */
  function calculate(ticker, ohlcv, week, existingPositions = []) {
    /* 데이터 부족 시 기본값 반환 */
    if (!ohlcv || ohlcv.length < 20) {
      return _defaultScore(ticker, week, 'No Buy', '데이터 부족 (최소 20개 캔들 필요)');
    }

    const closes  = ohlcv.map(c => c.close);
    const highs   = ohlcv.map(c => c.high);
    const volumes = ohlcv.map(c => c.volume || 0);

    /* 1. 추세 점수 */
    const trendScore = _calcTrendScore(closes);

    /* 2. 눌림목 점수 */
    const pullbackScore = window.PullbackEntryStrategy
      ? window.PullbackEntryStrategy.score(closes, highs)
      : _calcPullbackFallback(closes, highs);

    /* 3. 변동성 점수 */
    const volatilityScore = _calcVolatilityScore(closes);

    /* 4. 모멘텀 점수 */
    const momentumScore = _calcMomentumScore(closes);

    /* 5. 낙폭 점수 */
    const drawdownScore = _calcDrawdownScore(closes, highs);

    /* 6. 상관관계 점수 */
    const correlationScore = _calcCorrelationScore(closes, existingPositions);

    /* 합산 */
    const totalScore = trendScore + pullbackScore + volatilityScore
      + momentumScore + drawdownScore + correlationScore;

    /* 레짐 분류 */
    const regime = window.RegimeClassifier
      ? window.RegimeClassifier.classify(trendScore, volatilityScore, momentumScore, drawdownScore)
      : _fallbackRegime(totalScore);

    /* 액션 결정 */
    const action = _determineAction(totalScore);

    /* 근거 문구 생성 */
    const reason = _buildReason(ticker, trendScore, pullbackScore, volatilityScore,
      momentumScore, drawdownScore, correlationScore, totalScore, regime);

    return {
      ticker,
      week,
      trend_score:       trendScore,
      pullback_score:    pullbackScore,
      volatility_score:  volatilityScore,
      momentum_score:    momentumScore,
      drawdown_score:    drawdownScore,
      correlation_score: correlationScore,
      total_score:       parseFloat(totalScore.toFixed(1)),
      regime,
      action,
      reason,
    };
  }

  /* ══════════════════════════════════════════════════════════
     1. 추세 점수 (0-25점)
     20일 이동평균이 60일 이동평균 위에 있고, 현재가가 MA20 위이면 만점
  ══════════════════════════════════════════════════════════ */
  function _calcTrendScore(closes) {
    if (closes.length < 60) return 12;  // 데이터 부족: 중간값

    const current = closes[closes.length - 1];
    const ma20    = _sma(closes.slice(-20));
    const ma60    = _sma(closes.slice(-60));
    const prevMa20 = closes.length >= 21 ? _sma(closes.slice(-21, -1)) : ma20;

    let score = 0;

    /* MA20 vs MA60 정렬 */
    if (ma20 > ma60) score += 10;

    /* 현재가 vs MA20 */
    if (current > ma20) score += 8;

    /* MA20 기울기 (상승 중인지) */
    if (ma20 > prevMa20) score += 7;

    return Math.min(25, score);
  }

  /* ══════════════════════════════════════════════════════════
     2. 변동성 점수 (0-20점)
     변동성이 낮을수록 높은 점수
  ══════════════════════════════════════════════════════════ */
  function _calcVolatilityScore(closes) {
    if (closes.length < 20) return 10;

    /* 일간 수익률 표준편차로 주간 변동성 추정 */
    const returns = [];
    for (let i = 1; i < Math.min(closes.length, 60); i++) {
      returns.push((closes[i] - closes[i-1]) / closes[i-1]);
    }

    const mean   = returns.reduce((s, r) => s + r, 0) / returns.length;
    const stdDev = Math.sqrt(returns.reduce((s, r) => s + (r - mean) ** 2, 0) / returns.length);

    /* 주간 변동성 환산 (√5 ≈ 2.236) */
    const weeklyVol = stdDev * Math.sqrt(5);

    /* 변동성 기준: 주간 1.5% (0.015) */
    if (weeklyVol <= 0.008)  return 20;   // 매우 낮음
    if (weeklyVol <= 0.012)  return 16;   // 낮음
    if (weeklyVol <= 0.015)  return 12;   // 정상
    if (weeklyVol <= 0.020)  return 8;    // 약간 높음
    if (weeklyVol <= 0.025)  return 4;    // 높음
    return 0;                              // 매우 높음 (> 2.5%)
  }

  /* ══════════════════════════════════════════════════════════
     3. 모멘텀 점수 (0-15점)
     최근 4주(20일) 수익률 + RSI 기반
  ══════════════════════════════════════════════════════════ */
  function _calcMomentumScore(closes) {
    if (closes.length < 20) return 7;

    /* 4주 수익률 */
    const prev4w  = closes[closes.length - 20];
    const current = closes[closes.length - 1];
    const ret4w   = (current - prev4w) / prev4w;

    /* RSI */
    const rsi = window.RegimeClassifier
      ? window.RegimeClassifier.calculateRSI(closes)
      : 50;

    let score = 0;

    /* 수익률 점수 */
    if (ret4w >= 0.04)  score += 8;        // 4% 이상 상승
    else if (ret4w >= 0.02) score += 6;    // 2-4% 상승
    else if (ret4w >= 0)    score += 4;    // 보합~소폭 상승
    else if (ret4w >= -0.02) score += 2;   // 소폭 하락
    // ret4w < -0.02: 0점

    /* RSI 점수 */
    if (rsi >= 55 && rsi <= 70) score += 7;       // 강세 구간
    else if (rsi >= 45 && rsi < 55) score += 5;   // 보합 구간
    else if (rsi >= 70) score += 3;                // 과매수 (부담)
    else if (rsi >= 35 && rsi < 45) score += 3;   // 약세 구간
    // rsi < 35: 0점

    return Math.min(15, score);
  }

  /* ══════════════════════════════════════════════════════════
     4. 낙폭 점수 (0-10점)
     고점 대비 낙폭이 작을수록 높은 점수 (역점수)
  ══════════════════════════════════════════════════════════ */
  function _calcDrawdownScore(closes, highs) {
    if (closes.length < 10) return 5;

    const recentData = (highs || closes).slice(-60);
    const peak       = Math.max(...recentData);
    const current    = closes[closes.length - 1];
    const drawdown   = peak > 0 ? (current - peak) / peak : 0;  // 음수 또는 0
    const ddPct      = Math.abs(drawdown) * 100;

    if (ddPct < 3)  return 10;  // 고점 근처 (강세)
    if (ddPct < 7)  return 8;   // 소폭 조정
    if (ddPct < 15) return 5;   // 중간 조정
    if (ddPct < 25) return 2;   // 깊은 조정
    return 0;                    // 25% 이상 하락 (추세 붕괴 가능성)
  }

  /* ══════════════════════════════════════════════════════════
     5. 상관관계 점수 (0-10점)
     기존 포트폴리오와 상관관계가 낮을수록 분산 효과 높음 → 높은 점수
  ══════════════════════════════════════════════════════════ */
  function _calcCorrelationScore(closes, existingPositions) {
    /* 기존 포지션이 없으면 기본 점수 부여 */
    if (!existingPositions || existingPositions.length === 0) return 7;

    /* 클라이언트에서 실제 상관관계 계산은 복잡하므로 단순화 */
    /* 서버에서 정확한 계산이 이루어지며, 클라이언트는 추정값 사용 */
    return 7;
  }

  /* ══════════════════════════════════════════════════════════
     6. 액션 결정 (총점 기반)
  ══════════════════════════════════════════════════════════ */
  function _determineAction(total) {
    if (total >= 80) return 'Increase';
    if (total >= 65) return 'Small Buy';
    if (total >= 50) return 'Hold';
    if (total >= 35) return 'Reduce';
    return 'Exit';
  }

  /* ══════════════════════════════════════════════════════════
     7. 폴백 눌림목 계산 (PullbackEntryStrategy 미로드 시)
  ══════════════════════════════════════════════════════════ */
  function _calcPullbackFallback(closes, highs) {
    if (closes.length < 20) return 10;
    const recent = (highs || closes).slice(-20);
    const peak   = Math.max(...recent);
    const curr   = closes[closes.length - 1];
    const dd     = Math.abs((curr - peak) / peak) * 100;
    if (dd >= 3 && dd < 7)  return 14;
    if (dd >= 7 && dd < 15) return 10;
    if (dd < 3)             return 8;
    return 4;
  }

  /* 레짐 폴백 (RegimeClassifier 미로드 시) */
  function _fallbackRegime(total) {
    if (total >= 65) return 'Risk-On';
    if (total >= 35) return 'Neutral';
    return 'Risk-Off';
  }

  /* 단순 이동평균 */
  function _sma(arr) {
    if (!arr || arr.length === 0) return 0;
    return arr.reduce((s, v) => s + v, 0) / arr.length;
  }

  /* 데이터 부족 시 기본값 점수 객체 */
  function _defaultScore(ticker, week, action, reason) {
    return {
      ticker, week,
      trend_score: 0, pullback_score: 0, volatility_score: 0,
      momentum_score: 0, drawdown_score: 0, correlation_score: 0,
      total_score: 0, regime: 'Neutral', action, reason,
    };
  }

  /* 점수 산정 근거 문구 생성 */
  function _buildReason(ticker, trend, pullback, vol, momentum, drawdown, corr, total, regime) {
    const parts = [];
    if (trend >= 20)    parts.push('강한 상승 추세');
    else if (trend >= 12) parts.push('약한 상승 추세');
    else                parts.push('하락 추세');

    if (pullback >= 14) parts.push('눌림목 진입 적기');
    if (vol < 8)        parts.push('변동성 과대');
    if (momentum >= 12) parts.push('모멘텀 강함');
    if (drawdown <= 2)  parts.push('고점 대비 낙폭 과대');

    return `${parts.join(', ')} — 총점 ${total.toFixed(0)}pt (${regime})`;
  }

  return { calculate };
})();
