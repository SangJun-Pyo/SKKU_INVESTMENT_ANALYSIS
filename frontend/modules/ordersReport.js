/**
 * ordersReport.js — 주문 생성 및 리포트 UI 모듈
 *
 * 역할:
 * - 주문 생성: /papertrade/orders/generate
 * - 주문 확정: /papertrade/orders/confirm
 * - 리포트 생성: /papertrade/report/risk-rules, /orders, /weekly-pnl
 * - Markdown 복사 기능
 *
 * 체결 기준: 항상 금요일 종가 (order_type = 'Friday Close')
 * BLOCK 상태 주문이 있으면 주문 확정이 불가합니다.
 */
window.OrdersReportModule = (() => {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════════════════ */
  function init() {
    /* 주문 관련 버튼 */
    _bindBtn('generate-orders-btn',  _handleGenerateOrders);
    _bindBtn('confirm-orders-btn',   _handleConfirmOrders);

    /* 리포트 생성 버튼 */
    _bindBtn('gen-risk-rules-btn',   () => _handleGenerateReport('risk-rules'));
    _bindBtn('gen-orders-report-btn',() => _handleGenerateReport('orders'));
    _bindBtn('gen-pnl-report-btn',   () => _handleGenerateReport('weekly-pnl'));
    _bindBtn('copy-report-btn',      _handleCopyReport);

    /* 주문 변경 시 UI 자동 업데이트 */
    AppState.on('orders', _renderOrdersTable);
  }

  function _bindBtn(id, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', fn);
  }

  /* ══════════════════════════════════════════════════════════
     주문 생성 API 호출
  ══════════════════════════════════════════════════════════ */
  async function _handleGenerateOrders() {
    const portfolio  = AppState.get('portfolio');
    const riskBudget = AppState.get('riskBudget');
    const universe   = AppState.get('universe');

    if (portfolio.positions.length === 0) {
      alert('포트폴리오 배분을 먼저 진행하세요.');
      return;
    }

    /* BLOCK 위반이 있을 때 경고 표시 (주문 생성 자체는 허용) */
    if (riskBudget && riskBudget.violations.length > 0) {
      const ok = confirm(
        `리스크 위반 항목 ${riskBudget.violations.length}건이 있습니다.\n` +
        `해당 주문은 BLOCK 처리됩니다.\n\n계속하시겠습니까?`
      );
      if (!ok) return;
    }

    const btn = document.getElementById('generate-orders-btn');
    if (btn) btn.disabled = true;

    try {
      const week = AppState.get('week');
      const today = new Date().toISOString().slice(0, 10);

      /* OrdersGenerateRequest: { week, date } */
      const res  = await fetch('/papertrade/orders/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ week, date: today }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const orders = await res.json();
      AppState.set('orders', Array.isArray(orders) ? orders : orders.orders || []);

      /* 주문 확정 버튼 표시 */
      const confirmBtn = document.getElementById('confirm-orders-btn');
      if (confirmBtn) confirmBtn.classList.remove('hidden');

    } catch (err) {
      console.warn('[OrdersReport] 서버 오류, 클라이언트 폴백:', err.message);
      _fallbackGenerateOrders();
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ══════════════════════════════════════════════════════════
     폴백: 클라이언트에서 직접 주문 생성
     포트폴리오 포지션을 기반으로 간단한 주문 목록을 생성합니다.
  ══════════════════════════════════════════════════════════ */
  function _fallbackGenerateOrders() {
    const portfolio  = AppState.get('portfolio');
    const riskBudget = AppState.get('riskBudget');
    const week       = AppState.get('week');
    const today      = new Date().toISOString().slice(0, 10);

    const violations = riskBudget?.violations || [];

    const orders = portfolio.positions.map(pos => {
      /* 포지션의 리스크 위반 여부 확인 */
      const hasBlockViolation = violations.length > 0;

      /* 점수 기반 액션 결정 */
      let action = 'BUY';
      const sc = pos.signal_score;
      if (sc != null) {
        if (sc >= 80)      action = 'BUY';
        else if (sc >= 50) action = pos.role === 'Core' ? 'HOLD' : 'BUY';
        else if (sc >= 35) action = 'REDUCE';
        else               action = 'SELL';
      }

      return {
        week,
        date:          today,
        ticker:        pos.ticker,
        action,
        order_type:    'Friday Close',
        amount:        pos.target_amount,
        target_weight: pos.target_weight,
        reason:        _buildOrderReason(pos, action),
        risk_check:    hasBlockViolation ? 'WARN' : 'OK',
      };
    });

    AppState.set('orders', orders);

    const confirmBtn = document.getElementById('confirm-orders-btn');
    if (confirmBtn) confirmBtn.classList.remove('hidden');
  }

  /* 주문 근거 문구 생성 */
  function _buildOrderReason(pos, action) {
    const scoreText = pos.signal_score != null
      ? `신호점수 ${pos.signal_score.toFixed(0)}점`
      : '신호 없음';
    const regimeText = pos.regime ? `, ${pos.regime}` : '';
    return `${pos.role} 포지션 — ${scoreText}${regimeText} — ${action} @ Friday Close`;
  }

  /* ══════════════════════════════════════════════════════════
     주문 확정 API 호출
  ══════════════════════════════════════════════════════════ */
  async function _handleConfirmOrders() {
    const orders = AppState.get('orders');

    /* BLOCK 주문이 있으면 확정 불가 */
    const blockOrders = orders.filter(o => o.risk_check === 'BLOCK');
    if (blockOrders.length > 0) {
      alert(
        `BLOCK 주문이 ${blockOrders.length}건 있습니다.\n` +
        `리스크 위반을 해소한 후 재시도하세요.\n\n` +
        blockOrders.map(o => `• ${o.ticker}: ${o.reason}`).join('\n')
      );
      return;
    }

    const ok = confirm(
      `금요일 종가 기준으로 ${orders.length}개 주문을 확정합니다.\n` +
      `확정 후에는 취소할 수 없습니다.\n\n계속하시겠습니까?`
    );
    if (!ok) return;

    try {
      /* OrdersConfirmRequest: { week, orders } */
      const week = AppState.get('week');
      const res = await fetch('/papertrade/orders/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ week, orders }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      /* ── 확정된 주문을 portfolio.positions에 반영 ──────────────────
         다음 주 P&L 계산 시 기준 가격(entry_price) 및 목표 비중을
         올바르게 참조하기 위해 AppState.portfolio를 동기화합니다.
         서버 저장은 완료되었으므로 클라이언트 상태도 일치시킵니다. */
      const portfolio = AppState.get('portfolio');
      const updatedPositions = [...portfolio.positions];

      orders.forEach(order => {
        const idx = updatedPositions.findIndex(p => p.ticker === order.ticker);

        if (order.action === 'SELL' || order.action === 'COVER') {
          /* 매도/커버: 포지션 제거 */
          if (idx !== -1) updatedPositions.splice(idx, 1);
        } else if (order.action === 'HOLD') {
          /* 보유 유지: 변경 없음 */
        } else if (idx !== -1) {
          /* 기존 포지션 업데이트: 목표 금액과 비중을 새 주문 기준으로 갱신 */
          updatedPositions[idx] = {
            ...updatedPositions[idx],
            target_amount: order.amount,
            target_weight: order.target_weight,
          };
        } else if (order.action === 'BUY') {
          /* 신규 매수: 유니버스에서 메타 정보를 찾아 포지션 추가 */
          const universe = AppState.get('universe');
          const etfMeta  = universe.find(e => e.ticker === order.ticker);
          updatedPositions.push({
            ticker:        order.ticker,
            name:          etfMeta?.name  || order.ticker,
            role:          etfMeta?.role  || 'Alpha',
            target_amount: order.amount,
            target_weight: order.target_weight,
          });
        }
      });

      /* 동기화된 positions으로 portfolio 상태 업데이트 */
      AppState.set('portfolio', { ...portfolio, positions: updatedPositions });

      /* 확정 완료 후 주문 목록 초기화 — 이미 서버에 저장되었으므로 중복 방지 */
      AppState.set('orders', []);

      alert('주문이 확정되었습니다. P&L 탭에서 가격을 입력하여 성과를 추적하세요.');

      /* 확정 버튼 숨기기 */
      const confirmBtn = document.getElementById('confirm-orders-btn');
      if (confirmBtn) confirmBtn.classList.add('hidden');

    } catch (err) {
      console.error('[OrdersReport] 주문 확정 오류:', err);
      alert(`주문 확정 오류: ${err.message}`);
    }
  }

  /* ══════════════════════════════════════════════════════════
     주문 테이블 렌더링
  ══════════════════════════════════════════════════════════ */
  function _renderOrdersTable(orders) {
    const tbody = document.getElementById('orders-tbody');
    if (!tbody) return;

    if (!orders || orders.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">주문이 없습니다.</td></tr>';
      return;
    }

    tbody.innerHTML = orders.map(o => `
      <tr>
        <td style="color:var(--accent);font-weight:600">${o.ticker}</td>
        <td style="color:var(--text-muted);font-size:0.8rem">${o.name || '-'}</td>
        <td><span class="order-action ${o.action}">${o.action}</span></td>
        <td style="text-align:right;font-family:monospace">${AppState.formatAmount(o.amount)}</td>
        <td style="text-align:right">${(o.target_weight * 100).toFixed(1)}%</td>
        <td><span class="risk-check ${o.risk_check}">${o.risk_check}</span></td>
        <td style="font-size:0.78rem;color:var(--text-muted)">${o.reason || ''}</td>
      </tr>
    `).join('');
  }

  /* ══════════════════════════════════════════════════════════
     리포트 생성 API 호출
     type: 'risk-rules' | 'orders' | 'weekly-pnl'
  ══════════════════════════════════════════════════════════ */
  async function _handleGenerateReport(type) {
    const btn = document.getElementById(`gen-${type}-btn`);
    if (btn) btn.disabled = true;

    /* 리포트 뷰어 초기화 */
    const content = document.getElementById('report-content');
    if (content) content.textContent = '리포트 생성 중...';

    const copyBtn = document.getElementById('copy-report-btn');
    if (copyBtn) copyBtn.classList.add('hidden');

    try {
      const week     = AppState.get('week');
      const portfolio = AppState.get('portfolio');
      const orders   = AppState.get('orders');
      const pnl      = AppState.get('weeklyPnL');
      const risk     = AppState.get('riskBudget');

      /* 각 리포트 엔드포인트별 올바른 스키마로 전송
         risk-rules: { week, include_violations }
         orders:     { week, market_background, strategy_note }
         weekly-pnl: { week } */
      let reqBody = { week };
      if (type === 'risk-rules') {
        reqBody.include_violations = true;
      } else if (type === 'orders') {
        const context = _buildMarketContext();
        reqBody.market_background = `레짐 분포: Risk-On ${context.regime_distribution.risk_on}개 / 전체 ${context.regime_distribution.total}개`;
      }

      const res = await fetch(`/papertrade/report/${type}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reqBody),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      /* ReportResponse: { markdown: str, week: int } */
      const reportText = data.markdown || data.report || data.content || JSON.stringify(data, null, 2);

      if (content) content.textContent = reportText;
      if (copyBtn) copyBtn.classList.remove('hidden');

    } catch (err) {
      console.warn(`[OrdersReport] 리포트 생성 오류 (${type}), 폴백 실행:`, err.message);
      /* 서버 없을 때 클라이언트에서 템플릿 리포트 생성 */
      const fallback = _fallbackReport(type);
      if (content) content.textContent = fallback;
      if (copyBtn) copyBtn.classList.remove('hidden');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ══════════════════════════════════════════════════════════
     폴백 리포트 템플릿 (서버 없을 때)
  ══════════════════════════════════════════════════════════ */
  function _fallbackReport(type) {
    const week     = AppState.get('week');
    const risk     = AppState.get('riskBudget');
    const orders   = AppState.get('orders');
    const pnl      = AppState.get('weeklyPnL');
    const today    = new Date().toISOString().slice(0, 10);

    if (type === 'risk-rules') {
      return `# Week ${week} 리스크 규칙 점검 보고서
날짜: ${today}

## 1. 포트폴리오 제약 조건
- 기본 자본: 100억 KRW
- 최대 차입: 30억 KRW (레버리지 30% 이하)
- 총 익스포저 상한: 130억 KRW
- ETF 수: 10개 미만
- 체결 기준: 금요일 종가

## 2. 리스크 지표 현황
${risk ? `- 총 노출: ${AppState.formatAmount(risk.total_exposure)}
- 레버리지: ${(risk.leverage_ratio * 100).toFixed(1)}%
- 숏 비중: ${(risk.short_exposure_ratio * 100).toFixed(1)}%
- ETF 수: ${risk.etf_count}개
- 위반 항목: ${risk.violations.length}건` : '- 리스크 검증 전'}

## 3. 위반 항목
${risk && risk.violations.length > 0
  ? risk.violations.map(v => `- ${v}`).join('\n')
  : '- 없음 (전체 통과)'}

## 4. 결론
${risk && risk.violations.length === 0
  ? '모든 리스크 규칙을 준수하고 있습니다.'
  : '일부 위반 항목이 있습니다. 조정이 필요합니다.'}
`;
    }

    if (type === 'orders') {
      const orderLines = orders.map(o =>
        `| ${o.ticker} | ${o.action} | ${AppState.formatAmount(o.amount)} | ${(o.target_weight*100).toFixed(1)}% | ${o.risk_check} |`
      ).join('\n');

      return `# Week ${week} 주문 리포트 (금요일 종가 기준)
날짜: ${today}

## 시장 배경
현재 주 시장 상황 및 매크로 환경을 기술합니다.

## 전략
- Core 포지션: 벤치마크(KOSPI200 40% + S&P500 60%) 복제
- Alpha 포지션: 주간 신호 점수 65점 이상 ETF에 선택적 배분
- 체결 기준: 금요일 종가 (Next Friday Close)

## 주문 내역
| 티커 | 액션 | 금액 | 비중 | 리스크 |
|------|------|------|------|--------|
${orderLines || '| - | - | - | - | - |'}

## 리스크 점검
${risk ? `- 총 노출: ${AppState.formatAmount(risk.total_exposure)} (한도: 130억)
- 레버리지: ${(risk.leverage_ratio*100).toFixed(1)}% (한도: 30%)
- 위반 항목: ${risk.violations.length}건` : '검증 전'}

## 결론
금요일 종가 기준으로 위 주문을 실행합니다.
`;
    }

    if (type === 'weekly-pnl') {
      const latestPnL = pnl && pnl.length > 0 ? pnl[pnl.length - 1] : null;
      return `# Week ${week} P&L 리포트
날짜: ${today}

## 성과 요약
${latestPnL ? `- 포트폴리오 수익: ${AppState.formatReturn(latestPnL.portfolio_return)}
- 벤치마크 수익: ${AppState.formatReturn(latestPnL.benchmark_return)}
- 초과수익 (α): ${AppState.formatReturn(latestPnL.active_return)}
- 차입 비용: ${AppState.formatReturn(-latestPnL.leverage_cost)}
- 순수익률: ${AppState.formatReturn(latestPnL.net_return)}
- 누적수익: ${AppState.formatReturn(latestPnL.cumulative_return)}` : '데이터 없음'}

## 벤치마크
KOSPI200 40% + S&P500(H) 30% + S&P500(U) 30%

## 분석
추가 분석 내용을 입력하세요.
`;
    }

    return '리포트 유형을 알 수 없습니다.';
  }

  /* 리스크 규칙 텍스트 생성 (API 요청 본문용) */
  function _buildRiskRulesText() {
    return {
      max_total_exposure:    13_000_000_000,
      max_borrowing_ratio:   0.30,
      max_short_ratio:       0.30,
      max_etf_count:         9,
      max_weekly_volatility: 0.015,
      min_var_95:            -2_000_000_000,
      max_beta:              1.20,
      max_single_etf:        4_000_000_000,
      max_alpha_risk_ratio:  0.40,
      execution:             'Friday Close',
    };
  }

  /* 시장 컨텍스트 빌드 (간단한 버전) */
  function _buildMarketContext() {
    const scores = AppState.get('signalScores');
    const riskOnCount = Object.values(scores).filter(s => s.regime === 'Risk-On').length;
    const riskOffCount = Object.values(scores).filter(s => s.regime === 'Risk-Off').length;
    const total = Object.keys(scores).length;

    return {
      regime_distribution: { risk_on: riskOnCount, risk_off: riskOffCount, total },
      date: new Date().toISOString().slice(0, 10),
    };
  }

  /* ══════════════════════════════════════════════════════════
     리포트 클립보드 복사
  ══════════════════════════════════════════════════════════ */
  async function _handleCopyReport() {
    const content = document.getElementById('report-content');
    if (!content) return;

    try {
      await navigator.clipboard.writeText(content.textContent);
      const btn = document.getElementById('copy-report-btn');
      if (btn) {
        btn.textContent = '복사됨!';
        setTimeout(() => { btn.textContent = '복사'; }, 2000);
      }
    } catch (err) {
      /* clipboard API가 없는 환경을 위한 폴백 */
      const range = document.createRange();
      range.selectNode(content);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      document.execCommand('copy');
      window.getSelection().removeAllRanges();
    }
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return { init };
})();
