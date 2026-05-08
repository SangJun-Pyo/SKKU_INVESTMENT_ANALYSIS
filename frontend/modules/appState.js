/**
 * appState.js — 앱 전역 상태 관리 모듈
 *
 * 클로저 기반 싱글톤 패턴으로 구현합니다.
 * 이유: 여러 모듈이 동일한 상태를 공유해야 하며,
 *       import/export 없는 바닐라 JS 환경에서 window 오염을 최소화하기 위함.
 *
 * 이벤트 버스 역할도 겸합니다:
 *   - on(key, fn): 상태 변경 구독
 *   - set(key, val): 상태 변경 + 구독자 알림
 * 이렇게 하면 각 UI 모듈이 폴링 없이 상태 변화에 반응할 수 있습니다.
 */
window.AppState = (() => {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     초기 상태 정의
     과제 도메인 규칙 (100억 기본자본, 30억 최대 차입 등)을
     여기에 집중 정의하여 모든 모듈이 동일한 기준을 사용하게 합니다.
  ══════════════════════════════════════════════════════════ */
  const _state = {
    /* 앱 모드: papertrade 고정 (단타 모드는 숨김 처리) */
    mode: 'papertrade',

    /* 현재 작업 주차 (1~6) */
    week: 1,

    /* 현재 AI 역할 */
    role: 'CIO Assistant',

    /* ── 과제 자본 구조 ───────────────────────────────── */
    baseCapital:      10_000_000_000,   // 기본 자본: 100억 KRW
    maxBorrowingRatio:  0.30,           // 최대 레버리지 비율: 30%
    maxBorrowing:    3_000_000_000,     // 최대 차입 한도: 30억 KRW
    maxTotalExposure: 13_000_000_000,   // 총 익스포저 상한: 130억 KRW
    maxAlphaExposure:  3_000_000_000,   // Alpha 배분 상한: 30억 KRW

    /* ── 비용 구조 ────────────────────────────────────── */
    // 주간 기준으로 적용됩니다 (연 환산 ÷ 52)
    weeklyBorrowingCost:  0.0007,       // 차입 이자: 주간 0.07%
    weeklyCashInterest:   0.00035,      // 현금 이자: 주간 0.035%

    /* ── 벤치마크 배분 비중 ───────────────────────────── */
    // 수업 기준 벤치마크: KOSPI200 40% + S&P500(H) 30% + S&P500(U) 30%
    benchmark: {
      kospi200:      0.40,
      sp500Hedged:   0.30,
      sp500Unhedged: 0.30,
    },

    /* 벤치마크 ETF 티커 (yfinance 형식) */
    benchmarkTickers: {
      kospi200:      '069500.KS',   // KODEX 200
      sp500Hedged:   '219480.KS',   // KODEX S&P500(H)
      sp500Unhedged: '379800.KS',   // KODEX S&P500(U)
    },

    /* Core 기본 배분액 (벤치마크 비율 × 100억) */
    coreAllocation: {
      kospi200Core:      4_000_000_000,  // 40억
      sp500HedgedCore:   3_000_000_000,  // 30억
      sp500UnhedgedCore: 3_000_000_000,  // 30억
    },

    /* ── ETF 유니버스 ─────────────────────────────────── */
    // ETFMeta 배열: { ticker, name, role, currency_exposure, enabled }
    // 최대 9개 (10개 미만 규칙)
    universe: [],

    /* ── 시장 데이터 캐시 ─────────────────────────────── */
    // 불필요한 API 중복 호출을 방지하기 위해 메모리에 캐시
    prices: {},   // { ticker: latestPrice }
    ohlcv:  {},   // { ticker: OHLCV[] }

    /* ── 신호 점수 ────────────────────────────────────── */
    // WeeklySignalScore 배열: { ticker, total_score, action, regime, ... }
    signalScores: {},   // { ticker: WeeklySignalScore }

    /* ── 포트폴리오 상태 ──────────────────────────────── */
    portfolio: {
      cash:          10_000_000_000,   // 미배분 현금 (초기 = 기본 자본)
      borrowedCash:  0,                // 현재 차입금
      totalExposure: 0,                // 총 투자 금액 (롱 + 숏 절댓값)
      positions:     [],               // PortfolioPosition 배열
    },

    /* ── 리스크 예산 ──────────────────────────────────── */
    // RiskBudgetReport: { total_exposure, leverage_ratio, violations, ... }
    riskBudget: null,

    /* ── 주문 내역 ────────────────────────────────────── */
    // WeeklyOrder 배열: { ticker, action, amount, risk_check, reason, ... }
    orders: [],

    /* ── 주간 P&L 이력 ────────────────────────────────── */
    // WeeklyPnL 배열: { week, portfolio_return, benchmark_return, ... }
    weeklyPnL: [],
  };

  /* ══════════════════════════════════════════════════════════
     이벤트 리스너 맵
     key → callback[] 형태로 구독자를 관리합니다.
  ══════════════════════════════════════════════════════════ */
  const _listeners = {};

  /* ══════════════════════════════════════════════════════════
     상태 읽기
     key가 없으면 전체 상태의 얕은 복사본을 반환합니다.
     얕은 복사: 직접 수정을 방지하되, 중첩 객체는 참조로 공유합니다.
  ══════════════════════════════════════════════════════════ */
  function get(key) {
    if (key === undefined || key === null) {
      return Object.assign({}, _state);
    }
    return _state[key];
  }

  /* ══════════════════════════════════════════════════════════
     상태 쓰기
     값을 변경한 후 해당 key의 구독자들에게 알립니다.
     reactive 시스템처럼 동작하게 하는 핵심입니다.
  ══════════════════════════════════════════════════════════ */
  function set(key, value) {
    _state[key] = value;
    // 해당 키 구독자들에게 새 값과 전체 상태를 함께 전달
    if (_listeners[key]) {
      _listeners[key].forEach(fn => {
        try {
          fn(value, _state);
        } catch (err) {
          console.error(`[AppState] 리스너 오류 (key=${key}):`, err);
        }
      });
    }
  }

  /* ══════════════════════════════════════════════════════════
     상태 부분 업데이트 (중첩 객체용)
     예: AppState.update('portfolio', { cash: 5_000_000_000 })
  ══════════════════════════════════════════════════════════ */
  function update(key, partialValue) {
    if (typeof _state[key] === 'object' && _state[key] !== null && !Array.isArray(_state[key])) {
      _state[key] = Object.assign({}, _state[key], partialValue);
    } else {
      _state[key] = partialValue;
    }
    if (_listeners[key]) {
      _listeners[key].forEach(fn => {
        try {
          fn(_state[key], _state);
        } catch (err) {
          console.error(`[AppState] update 리스너 오류 (key=${key}):`, err);
        }
      });
    }
  }

  /* ══════════════════════════════════════════════════════════
     상태 변경 구독
     동일 키에 여러 모듈이 구독할 수 있습니다.
  ══════════════════════════════════════════════════════════ */
  function on(key, fn) {
    if (!_listeners[key]) {
      _listeners[key] = [];
    }
    _listeners[key].push(fn);
  }

  /* ══════════════════════════════════════════════════════════
     구독 해제
     컴포넌트 소멸 시 메모리 누수를 방지하기 위해 사용합니다.
  ══════════════════════════════════════════════════════════ */
  function off(key, fn) {
    if (!_listeners[key]) return;
    _listeners[key] = _listeners[key].filter(f => f !== fn);
  }

  /* ══════════════════════════════════════════════════════════
     주차 초기화
     새 주차 시작 시 주문/점수를 리셋하되, 유니버스는 유지합니다.
     이유: ETF 유니버스는 주차 간 지속되어야 하기 때문입니다.
  ══════════════════════════════════════════════════════════ */
  function resetWeek(week) {
    _state.week = week;
    _state.signalScores = {};
    _state.orders = [];
    _state.riskBudget = null;
    // 포트폴리오는 이전 주차 결과를 유지 (주차 간 연속성 필요)
    // P&L 이력도 유지
    if (_listeners['week']) {
      _listeners['week'].forEach(fn => fn(week, _state));
    }
    console.log(`[AppState] Week ${week} 초기화 완료`);
  }

  /* ══════════════════════════════════════════════════════════
     AI 컨텍스트 빌더
     AI Committee 채팅 시 현재 상태 요약을 시스템 프롬프트에 첨부합니다.
     이렇게 하면 AI가 현재 포트폴리오 상황을 인식한 채 답변할 수 있습니다.
  ══════════════════════════════════════════════════════════ */
  function buildAIContext() {
    const s = _state;
    const portfolioSummary = s.portfolio.positions.length > 0
      ? s.portfolio.positions
          .map(p => `  - ${p.ticker}(${p.role}): ${formatAmount(p.target_amount)}, 비중 ${(p.target_weight * 100).toFixed(1)}%`)
          .join('\n')
      : '  (포트폴리오 미구성)';

    const scoresSummary = Object.keys(s.signalScores).length > 0
      ? Object.entries(s.signalScores)
          .map(([t, sc]) => `  - ${t}: ${sc.total_score}점 (${sc.action}, ${sc.regime})`)
          .join('\n')
      : '  (점수 계산 전)';

    const riskSummary = s.riskBudget
      ? `총노출 ${formatAmount(s.riskBudget.total_exposure)}, ` +
        `레버리지 ${(s.riskBudget.leverage_ratio * 100).toFixed(1)}%, ` +
        `위반 ${s.riskBudget.violations.length}건`
      : '(리스크 검증 전)';

    return `
[MarkovPortfolio V4 컨텍스트]
- 모드: 과제용 Paper Trading
- 현재 주차: Week ${s.week}
- 기본 자본: ${formatAmount(s.baseCapital)}
- 벤치마크: KOSPI200 ${s.benchmark.kospi200*100}% + S&P500(H) ${s.benchmark.sp500Hedged*100}% + S&P500(U) ${s.benchmark.sp500Unhedged*100}%
- 체결 기준: 금요일 종가

[ETF 유니버스] (${s.universe.length}개)
${s.universe.map(e => `  - ${e.ticker}(${e.role}): ${e.name}`).join('\n') || '  (미설정)'}

[포트폴리오 포지션]
${portfolioSummary}

[주간 신호 점수]
${scoresSummary}

[리스크 현황]
${riskSummary}

[주의사항]
- 단타 매매(LONG/SHORT)가 아닌 포트폴리오 관점에서 답변하세요.
- 모든 배분은 금요일 종가 기준입니다.
- ETF 개수는 항상 10개 미만이어야 합니다.
`.trim();
  }

  /* ══════════════════════════════════════════════════════════
     헬퍼: 금액 포맷 (억 원 단위)
     100,000,000 → "10.0억"
  ══════════════════════════════════════════════════════════ */
  function formatAmount(amount) {
    if (amount === null || amount === undefined || isNaN(amount)) return '-';
    return (amount / 100_000_000).toFixed(1) + '억';
  }

  /* ══════════════════════════════════════════════════════════
     헬퍼: 수익률 포맷 (퍼센트 + 부호)
     0.015 → "+1.50%", -0.005 → "-0.50%"
  ══════════════════════════════════════════════════════════ */
  function formatReturn(rate) {
    if (rate === null || rate === undefined || isNaN(rate)) return '-';
    const pct = (rate * 100).toFixed(2) + '%';
    return rate >= 0 ? '+' + pct : pct;
  }

  /* ══════════════════════════════════════════════════════════
     헬퍼: 숫자 포맷 (천 단위 구분자)
     1234567 → "1,234,567"
  ══════════════════════════════════════════════════════════ */
  function formatNumber(num) {
    if (num === null || num === undefined || isNaN(num)) return '-';
    return Math.round(num).toLocaleString('ko-KR');
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return {
    get,
    set,
    update,
    on,
    off,
    resetWeek,
    buildAIContext,
    formatAmount,
    formatReturn,
    formatNumber,
  };
})();
