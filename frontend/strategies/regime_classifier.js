/**
 * regime_classifier.js — 시장 레짐 분류 전략 모듈
 *
 * 역할:
 * - OHLCV 데이터를 기반으로 Risk-On / Neutral / Risk-Off 레짐 판별
 * - weekly_etf_score_strategy.js에서 호출하여 regime 필드를 채웁니다.
 *
 * 레짐 기준:
 *   Risk-On:  상승 추세(MA20 > MA60) + 변동성 정상 + 모멘텀 양호(RSI > 50)
 *   Neutral:  방향성 혼재 또는 점수 중간
 *   Risk-Off: 하락 추세(MA20 < MA60) + 변동성 확대 + 낙폭 확대
 */
window.RegimeClassifier = (() => {
  'use strict';

  /**
   * 레짐 분류
   * @param {number} trendScore      - 추세 점수 (0-25)
   * @param {number} volatilityScore - 변동성 점수 (0-20)
   * @param {number} momentumScore   - 모멘텀 점수 (0-15)
   * @param {number} drawdownScore   - 낙폭 점수 (0-10)
   * @returns {'Risk-On' | 'Neutral' | 'Risk-Off'}
   */
  function classify(trendScore, volatilityScore, momentumScore, drawdownScore) {
    /* 핵심 지표 4개 가중합으로 레짐 결정 */
    const maxScore = 25 + 20 + 15 + 10;   // 70점 만점
    const score    = trendScore + volatilityScore + momentumScore + drawdownScore;
    const ratio    = score / maxScore;

    if (ratio >= 0.65) return 'Risk-On';
    if (ratio >= 0.35) return 'Neutral';
    return 'Risk-Off';
  }

  /**
   * 이동평균 기반 추세 방향 계산
   * @param {number[]} closes - 종가 배열 (최신 순서가 뒤에)
   * @param {number} shortPeriod  - 단기 이동평균 기간 (기본 20일)
   * @param {number} longPeriod   - 장기 이동평균 기간 (기본 60일)
   * @returns {'up' | 'down' | 'flat'}
   */
  function trendDirection(closes, shortPeriod = 20, longPeriod = 60) {
    if (!closes || closes.length < longPeriod) return 'flat';

    const recent = closes.slice(-longPeriod);
    const ma20 = _sma(recent.slice(-shortPeriod));
    const ma60 = _sma(recent);
    const current = recent[recent.length - 1];

    if (current > ma20 && ma20 > ma60) return 'up';
    if (current < ma20 && ma20 < ma60) return 'down';
    return 'flat';
  }

  /**
   * RSI 계산 (Wilder 스무딩 방식)
   * @param {number[]} closes - 종가 배열
   * @param {number} period   - RSI 기간 (기본 14)
   * @returns {number} RSI 값 (0~100)
   */
  function calculateRSI(closes, period = 14) {
    if (!closes || closes.length < period + 1) return 50;

    const changes = [];
    for (let i = 1; i < closes.length; i++) {
      changes.push(closes[i] - closes[i - 1]);
    }

    const recentChanges = changes.slice(-period * 2);

    let avgGain = 0;
    let avgLoss = 0;
    for (let i = 0; i < period; i++) {
      const c = recentChanges[i];
      if (c > 0) avgGain += c;
      else avgLoss += Math.abs(c);
    }
    avgGain /= period;
    avgLoss /= period;

    /* Wilder 스무딩: 이후 데이터 반영 */
    for (let i = period; i < recentChanges.length; i++) {
      const c = recentChanges[i];
      avgGain = (avgGain * (period - 1) + Math.max(c, 0)) / period;
      avgLoss = (avgLoss * (period - 1) + Math.max(-c, 0)) / period;
    }

    if (avgLoss === 0) return 100;
    const rs = avgGain / avgLoss;
    return 100 - (100 / (1 + rs));
  }

  /* 단순 이동평균 */
  function _sma(arr) {
    if (!arr || arr.length === 0) return 0;
    return arr.reduce((s, v) => s + v, 0) / arr.length;
  }

  return { classify, trendDirection, calculateRSI };
})();
