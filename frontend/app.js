/**
 * app.js — MarkovPortfolio V4 메인 앱 진입점
 *
 * 역할:
 * - DOMContentLoaded 후 모든 모듈 초기화
 * - 탭 네비게이션 처리
 * - Week 선택기 처리
 * - 전역 이벤트 바인딩
 *
 * 로드 순서 의존성 (index.html에서 보장):
 *   [1] CDN: TradingView Lightweight Charts @4.2.0
 *   [2] 전략: regime_classifier → pullback_entry → weekly_etf_score → strategy_engine
 *   [3] AppState (최우선)
 *   [4] 엔진: allocationEngine, riskBudget
 *   [5] UI: etfUniverse, weeklyScore, ordersReport, weeklyPnL, aiCommittee
 *   [6] app.js (마지막)
 *
 * V2에서 V4로의 변경점:
 *   - 탭 A(신호/차트), 탭 B(저널) → 5탭 포트폴리오 관리 UI
 *   - LONG/SHORT 단타 버튼 제거 (papertrade 모드)
 *   - AppState 중심 반응형 상태 관리 도입
 */

(function () {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     DOMContentLoaded: 모든 DOM 요소가 준비된 후 초기화 시작
  ══════════════════════════════════════════════════════════ */
  document.addEventListener('DOMContentLoaded', () => {
    console.log('[App] MarkovPortfolio V4 초기화 시작');

    /* 의존 모듈 존재 확인 */
    _checkDependencies();

    /* 탭 네비게이션 초기화 */
    _initTabNav();

    /* Week 선택기 초기화 */
    _initWeekSelector();

    /* 각 기능 모듈 초기화 */
    _initModules();

    console.log('[App] 초기화 완료');
  });

  /* ══════════════════════════════════════════════════════════
     의존성 체크
     필수 모듈이 로드되지 않았을 때 명확한 오류 메시지를 출력합니다.
  ══════════════════════════════════════════════════════════ */
  function _checkDependencies() {
    const required = ['AppState', 'ETFUniverseModule', 'WeeklyScoreModule',
      'AllocationEngine', 'RiskBudgetModule', 'OrdersReportModule',
      'WeeklyPnLModule', 'AICommitteeModule'];

    const missing = required.filter(name => !window[name]);
    if (missing.length > 0) {
      console.error('[App] 필수 모듈 미로드:', missing);
    }

    /* TradingView 버전 확인 (v4.2.0 고정 여부) */
    if (window.LightweightCharts) {
      console.log('[App] TradingView Lightweight Charts 로드됨');
    }
  }

  /* ══════════════════════════════════════════════════════════
     탭 네비게이션 초기화
     탭 버튼 클릭 시 해당 섹션만 표시하고 나머지를 숨깁니다.
  ══════════════════════════════════════════════════════════ */
  function _initTabNav() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.dataset.tab;

        /* 모든 탭 버튼 비활성화 */
        tabBtns.forEach(b => b.classList.remove('active'));
        /* 클릭한 버튼 활성화 */
        btn.classList.add('active');

        /* 모든 탭 컨텐츠 숨김 */
        tabContents.forEach(section => {
          section.classList.add('hidden');
        });

        /* 해당 탭 컨텐츠 표시 */
        const targetSection = document.getElementById(`tab-${targetTab}`);
        if (targetSection) {
          targetSection.classList.remove('hidden');
        }

        /* 탭 전환 시 컨텍스트 업데이트 (AI 위원회 탭) */
        if (targetTab === 'committee') {
          _refreshAIContext();
        }
      });
    });
  }

  /* ══════════════════════════════════════════════════════════
     Week 선택기 초기화
  ══════════════════════════════════════════════════════════ */
  function _initWeekSelector() {
    const weekSelect = document.getElementById('week-select');
    if (!weekSelect) return;

    /* localStorage에서 마지막으로 선택한 주차 복원 */
    const savedWeek = parseInt(localStorage.getItem('markov_last_week') || '1');
    const validWeek = Math.min(Math.max(savedWeek, 1), 6);
    weekSelect.value = String(validWeek);
    AppState.set('week', validWeek);

    weekSelect.addEventListener('change', () => {
      const week = parseInt(weekSelect.value);
      if (week < 1 || week > 6) return;

      /* 주차 변경 확인 */
      const currentWeek = AppState.get('week');
      if (week !== currentWeek) {
        const ok = confirm(
          `Week ${week}로 전환합니다.\n` +
          `현재 주차의 점수/주문 정보가 초기화됩니다.\n\n계속하시겠습니까?`
        );
        if (!ok) {
          weekSelect.value = String(currentWeek);
          return;
        }
      }

      /* signalScores, orders, riskBudget 초기화 (유니버스/포트폴리오는 유지)
         — resetWeek 내부에서 AppState.set('week', week)도 함께 처리됩니다 */
      AppState.resetWeek(week);
      localStorage.setItem('markov_last_week', String(week));
      console.log(`[App] Week ${week}로 변경 — 점수/주문/리스크 초기화`);
    });
  }

  /* ══════════════════════════════════════════════════════════
     모듈 초기화
     index.html 로드 순서대로 초기화합니다.
  ══════════════════════════════════════════════════════════ */
  function _initModules() {
    /* ETF 유니버스 관리 */
    if (window.ETFUniverseModule) {
      ETFUniverseModule.init();
    }

    /* 주간 신호 점수 */
    if (window.WeeklyScoreModule) {
      WeeklyScoreModule.init();
    }

    /* 포트폴리오 배분 엔진 */
    if (window.AllocationEngine) {
      AllocationEngine.init();
    }

    /* 리스크 가드레일 */
    if (window.RiskBudgetModule) {
      RiskBudgetModule.init();
    }

    /* 주문 & 리포트 */
    if (window.OrdersReportModule) {
      OrdersReportModule.init();
    }

    /* 주간 P&L 추적 */
    if (window.WeeklyPnLModule) {
      WeeklyPnLModule.init();
    }

    /* AI 투자위원회 */
    if (window.AICommitteeModule) {
      AICommitteeModule.init();
    }
  }

  /* ══════════════════════════════════════════════════════════
     AI 컨텍스트 요약 새로고침
     AI 탭 전환 시 최신 상태를 반영합니다.
  ══════════════════════════════════════════════════════════ */
  function _refreshAIContext() {
    const el = document.getElementById('context-summary');
    if (!el) return;

    const week      = AppState.get('week');
    const universe  = AppState.get('universe');
    const portfolio = AppState.get('portfolio');
    const risk      = AppState.get('riskBudget');
    const scores    = AppState.get('signalScores');

    const lines = [
      `Week ${week}`,
      `ETF ${universe.length}개`,
      `포지션 ${portfolio.positions.length}개`,
      `점수 ${Object.keys(scores).length}개 계산됨`,
      portfolio.totalExposure > 0
        ? `노출 ${AppState.formatAmount(portfolio.totalExposure)}`
        : '배분 미완료',
      risk
        ? `리스크 위반 ${risk.violations.length}건`
        : '리스크 미검증',
    ];

    el.textContent = lines.join('\n');
  }

})();
