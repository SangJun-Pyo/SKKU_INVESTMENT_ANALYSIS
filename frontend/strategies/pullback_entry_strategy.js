/**
 * pullback_entry_strategy.js — 눌림목(Pullback) 진입 전략 모듈
 *
 * 역할:
 * - 상승 추세 내 눌림목 구간을 감지하여 pullback_score를 계산합니다.
 * - weekly_etf_score_strategy.js에서 호출합니다.
 *
 * 눌림목 정의:
 *   - 최근 고점 대비 3~15% 조정: 좋은 진입 기회
 *   - RSI 50 이하로 냉각: 과매수 해소 확인
 *   - 추세는 여전히 상승(MA20 > MA60)
 *
 * 점수 체계 (0-20점):
 *   조정폭 3-7%:   +10점 (이상적인 눌림목)
 *   조정폭 7-15%:  +6점  (더 깊은 눌림목)
 *   RSI 40-50:    +6점  (냉각 완료)
 *   RSI 30-40:    +4점  (과매도 영역 진입)
 *   추세 유지:     +4점  (MA20 > MA60)
 */
window.PullbackEntryStrategy = (() => {
  'use strict';

  /**
   * 눌림목 점수 계산
   * @param {number[]} closes  - 종가 배열 (최신이 뒤에)
   * @param {number[]} highs   - 고가 배열
   * @param {number}   lookback - 고점 탐색 기간 (기본 20)
   * @returns {number} pullback_score (0-20점)
   */
  function score(closes, highs, lookback = 20) {
    if (!closes || closes.length < lookback) return 10; // 데이터 부족 시 중간값

    const current  = closes[closes.length - 1];
    const recentHighs = (highs || closes).slice(-lookback);
    const peak     = Math.max(...recentHighs);
    const drawdown = peak > 0 ? (current - peak) / peak : 0;  // 음수

    const rsi = window.RegimeClassifier
      ? window.RegimeClassifier.calculateRSI(closes)
      : 50;

    /* 단기/장기 이동평균 */
    const ma20 = _sma(closes.slice(-20));
    const ma60 = closes.length >= 60 ? _sma(closes.slice(-60)) : ma20;

    let totalScore = 0;

    /* [1] 조정폭 점수 (최대 10점) */
    const ddPct = Math.abs(drawdown) * 100;
    if (ddPct >= 3 && ddPct < 7) {
      totalScore += 10;  // 이상적인 눌림목: 3-7% 조정
    } else if (ddPct >= 7 && ddPct < 15) {
      totalScore += 6;   // 더 깊은 조정: 7-15%
    } else if (ddPct < 3) {
      totalScore += 5;   // 조정 부족: 아직 진입 부담
    } else {
      totalScore += 2;   // 과도한 조정(>15%): 추세 붕괴 위험
    }

    /* [2] RSI 냉각 점수 (최대 6점) */
    if (rsi >= 40 && rsi <= 55) {
      totalScore += 6;   // 이상적인 냉각 구간
    } else if (rsi >= 30 && rsi < 40) {
      totalScore += 4;   // 과매도 진입: 반등 가능하나 추가 하락도 있음
    } else if (rsi > 55 && rsi <= 70) {
      totalScore += 2;   // 아직 뜨거움: 눌림목 미완성
    } else if (rsi > 70) {
      totalScore += 0;   // 과매수: 진입 불리
    } else {
      totalScore += 3;   // RSI < 30: 극단적 과매도 (반등 가능성)
    }

    /* [3] 추세 유지 점수 (최대 4점) */
    if (ma20 > ma60) {
      totalScore += 4;   // 상승 추세 유지: 눌림목 신뢰도 높음
    } else if (Math.abs(ma20 - ma60) / ma60 < 0.01) {
      totalScore += 2;   // 횡보: 중립
    }
    // ma20 < ma60: 0점 (하락 추세 내 눌림목은 위험)

    return Math.min(20, Math.max(0, totalScore));
  }

  /* 단순 이동평균 헬퍼 */
  function _sma(arr) {
    if (!arr || arr.length === 0) return 0;
    return arr.reduce((s, v) => s + v, 0) / arr.length;
  }

  return { score };
})();
