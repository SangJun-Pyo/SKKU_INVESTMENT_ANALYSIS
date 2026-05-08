/**
 * strategy_engine.js — 전략 엔진 통합 모듈
 *
 * 역할:
 * - 개별 전략 모듈(regime_classifier, pullback_entry, weekly_etf_score)을 조합
 * - 클라이언트 사이드에서 서버 없이 점수 계산을 수행하는 폴백 제공
 * - V2의 engine.js 역할을 계승하되, 단타 전략 대신 ETF 주간 점수에 집중
 *
 * V2 마이그레이션 노트:
 *   V2의 bb_rsi, dip_buyer, trend_follow 전략은 MarkovTrade 단타 기능입니다.
 *   V4에서는 mode='papertrade' 에서 이 전략들을 직접 호출하지 않습니다.
 *   기존 전략 파일이 서버에 있어도 V4 UI에서는 접근하지 않습니다.
 */
window.StrategyEngine = (() => {
  'use strict';

  /**
   * ETF 유니버스 전체 점수 계산 (클라이언트 사이드)
   * 서버 API(/papertrade/score/run)가 실패할 때 폴백으로 사용합니다.
   *
   * @param {ETFMeta[]} universe  - ETF 메타 배열
   * @param {Object}    ohlcvMap  - { ticker: OHLCV[] }
   * @param {number}    week      - 현재 주차
   * @param {Array}     positions - 기존 포트폴리오 포지션 (상관관계용)
   * @returns {WeeklySignalScore[]}
   */
  function runWeeklyScoring(universe, ohlcvMap, week, positions = []) {
    if (!window.WeeklyETFScoreStrategy) {
      console.error('[StrategyEngine] WeeklyETFScoreStrategy 미로드');
      return [];
    }

    return universe
      .filter(etf => etf.enabled !== false)
      .map(etf => {
        const ohlcv = ohlcvMap[etf.ticker] || [];
        return window.WeeklyETFScoreStrategy.calculate(etf.ticker, ohlcv, week, positions);
      });
  }

  /**
   * 레짐 분류 (단일 ETF)
   * RegimeClassifier 래퍼입니다.
   */
  function classifyRegime(closes) {
    if (!window.RegimeClassifier) return 'Neutral';
    const ma20 = _sma(closes.slice(-20));
    const ma60 = closes.length >= 60 ? _sma(closes.slice(-60)) : ma20;
    const rsi  = window.RegimeClassifier.calculateRSI(closes);

    /* 단순화된 레짐 분류 (전체 점수 없이) */
    const trendUp  = ma20 > ma60 && closes[closes.length - 1] > ma20;
    const rsiGood  = rsi > 50;

    if (trendUp && rsiGood) return 'Risk-On';
    if (!trendUp && !rsiGood) return 'Risk-Off';
    return 'Neutral';
  }

  /* 단순 이동평균 */
  function _sma(arr) {
    if (!arr || arr.length === 0) return 0;
    return arr.reduce((s, v) => s + v, 0) / arr.length;
  }

  return { runWeeklyScoring, classifyRegime };
})();
