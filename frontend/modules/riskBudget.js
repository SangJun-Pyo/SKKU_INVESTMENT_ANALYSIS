/**
 * riskBudget.js — 리스크 가드레일 UI 모듈
 *
 * 역할:
 * - "리스크 검증" 버튼 → /papertrade/risk/check API 호출
 * - 10개 가드레일 상태 표시 (OK/WARN/BLOCK)
 * - 위반 항목 상세 표시
 * - AppState.riskBudget 업데이트
 *
 * 가드레일 기준:
 *   총 노출    ≤ 130억
 *   레버리지   ≤ 30%
 *   숏 비중    ≤ 30%
 *   ETF 수     < 10
 *   주간변동성  ≤ 1.5%
 *   95% VaR   ≥ -20억 (절댓값 20억 이하)
 *   MDD       < -3% 시 디레버리징 트리거
 *   베타       0.9 ~ 1.2
 *   단일 ETF   ≤ 40억
 *   알파 리스크 ≤ 40%
 */
window.RiskBudgetModule = (() => {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════════════════ */
  function init() {
    const btn = document.getElementById('check-risk-btn');
    if (btn) {
      btn.addEventListener('click', _handleCheckRisk);
    }

    /* riskBudget 변경 시 가드레일 UI 자동 업데이트 */
    AppState.on('riskBudget', _renderGuardrails);

    /* 포트폴리오 변경 시 클라이언트 사이드 빠른 검증 실행 */
    AppState.on('portfolio', _quickClientCheck);
  }

  /* ══════════════════════════════════════════════════════════
     리스크 검증 API 호출
  ══════════════════════════════════════════════════════════ */
  async function _handleCheckRisk() {
    const portfolio = AppState.get('portfolio');
    if (portfolio.positions.length === 0) {
      alert('포트폴리오 배분을 먼저 진행하세요.');
      return;
    }

    const btn = document.getElementById('check-risk-btn');
    if (btn) btn.disabled = true;

    try {
      const week     = AppState.get('week');
      const universe = AppState.get('universe');

      const res = await fetch('/papertrade/risk/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        /* 서버 RiskCheckRequest: { week, positions } */
        body: JSON.stringify({
          week,
          positions: portfolio.positions || [],
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      /* 서버 응답: { report: RiskBudgetReport, passed, block_count, warn_count }
         _renderGuardrails는 RiskBudgetReport 필드에 직접 접근하므로 내부 report 추출 */
      const riskReport = data.report || data;
      /* 서버에 없는 클라이언트 전용 필드 보완 */
      const positions = AppState.get('portfolio').positions || [];
      riskReport.max_single_etf    = positions.length
        ? Math.max(...positions.map(p => p.target_amount || 0)) : 0;
      const alphaExp = positions
        .filter(p => p.role === 'Alpha' || p.role === 'Tactical')
        .reduce((s, p) => s + (p.target_amount || 0), 0);
      riskReport.alpha_risk_ratio = riskReport.total_exposure > 0
        ? alphaExp / riskReport.total_exposure : 0;
      riskReport.passed      = data.passed;
      riskReport.block_count = data.block_count;
      riskReport.warn_count  = data.warn_count;
      AppState.set('riskBudget', riskReport);
      console.log('[RiskBudget] 리스크 검증 완료:', riskReport);

    } catch (err) {
      console.warn('[RiskBudget] 서버 오류, 클라이언트 폴백:', err.message);
      /* 서버 없을 때 클라이언트에서 기본 지표 계산 */
      _fallbackClientCheck();
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ══════════════════════════════════════════════════════════
     클라이언트 빠른 검증 (서버 호출 없이 즉시 계산)
     포트폴리오 변경 시 자동으로 실행되어 실시간 피드백을 제공합니다.
  ══════════════════════════════════════════════════════════ */
  function _quickClientCheck(portfolio) {
    const baseCapital    = AppState.get('baseCapital');
    const maxTotal       = AppState.get('maxTotalExposure');
    const universe       = AppState.get('universe');
    const positions      = portfolio.positions || [];

    /* 기본 지표 계산 */
    const totalExposure  = portfolio.totalExposure || 0;
    const leverageRatio  = portfolio.borrowedCash / baseCapital;
    const etfCount       = positions.length;
    const shortExposure  = positions
      .filter(p => p.role === 'Short')
      .reduce((s, p) => s + p.target_amount, 0);
    const shortRatio     = totalExposure > 0 ? shortExposure / totalExposure : 0;
    const maxSingleETF   = positions.reduce((m, p) => Math.max(m, p.target_amount), 0);
    const alphaExposure  = positions
      .filter(p => p.role === 'Alpha' || p.role === 'Tactical')
      .reduce((s, p) => s + p.target_amount, 0);
    const alphaRisk      = totalExposure > 0 ? alphaExposure / totalExposure : 0;

    /* 간소화된 RiskBudgetReport 구조 생성 */
    const quickReport = {
      week:                      AppState.get('week'),
      total_exposure:            totalExposure,
      leverage_ratio:            leverageRatio,
      short_exposure_ratio:      shortRatio,
      etf_count:                 etfCount,
      expected_weekly_volatility: null,   // 서버에서만 계산 가능
      var_95:                    null,
      max_drawdown:              null,
      benchmark_beta:            null,
      max_single_etf:            maxSingleETF,
      alpha_risk_ratio:          alphaRisk,
      violations:                [],
    };

    /* 위반 항목 수집 */
    if (totalExposure > maxTotal) {
      quickReport.violations.push(`총 익스포저 ${AppState.formatAmount(totalExposure)} > 한도 130억`);
    }
    if (leverageRatio > 0.30) {
      quickReport.violations.push(`레버리지 ${(leverageRatio*100).toFixed(1)}% > 한도 30%`);
    }
    if (shortRatio > 0.30) {
      quickReport.violations.push(`숏 비중 ${(shortRatio*100).toFixed(1)}% > 한도 30%`);
    }
    if (etfCount >= 10) {
      quickReport.violations.push(`ETF 수 ${etfCount}개 ≥ 한도 10개`);
    }
    if (maxSingleETF > 4_000_000_000) {
      quickReport.violations.push(`단일 ETF ${AppState.formatAmount(maxSingleETF)} > 한도 40억`);
    }
    if (alphaRisk > 0.40) {
      quickReport.violations.push(`알파 리스크 비율 ${(alphaRisk*100).toFixed(1)}% > 한도 40%`);
    }

    AppState.set('riskBudget', quickReport);
  }

  /* ══════════════════════════════════════════════════════════
     폴백: 서버 없을 때 클라이언트 전체 검증
  ══════════════════════════════════════════════════════════ */
  function _fallbackClientCheck() {
    const portfolio = AppState.get('portfolio');
    _quickClientCheck(portfolio);
  }

  /* ══════════════════════════════════════════════════════════
     가드레일 UI 렌더링
     riskBudget 변경 시 자동 호출됩니다.
  ══════════════════════════════════════════════════════════ */
  function _renderGuardrails(report) {
    if (!report) return;

    const baseCapital = AppState.get('baseCapital');

    /* 각 가드레일 아이템 업데이트 */
    _updateGuardrail(
      'gr-total-exposure',
      AppState.formatAmount(report.total_exposure),
      report.total_exposure <= 13_000_000_000 ? 'OK' : 'BLOCK'
    );

    _updateGuardrail(
      'gr-leverage',
      `${(report.leverage_ratio * 100).toFixed(1)}%`,
      report.leverage_ratio <= 0.30 ? 'OK' : 'BLOCK'
    );

    _updateGuardrail(
      'gr-short',
      `${(report.short_exposure_ratio * 100).toFixed(1)}%`,
      report.short_exposure_ratio <= 0.30 ? 'OK' : 'BLOCK'
    );

    _updateGuardrail(
      'gr-etf-count',
      `${report.etf_count}개`,
      report.etf_count < 10 ? 'OK' : 'BLOCK'
    );

    /* 서버에서만 계산되는 지표: null이면 미검증 표시 */
    _updateGuardrail(
      'gr-volatility',
      report.expected_weekly_volatility != null
        ? `${(report.expected_weekly_volatility * 100).toFixed(2)}%`
        : '미검증',
      report.expected_weekly_volatility == null ? 'WARN'
        : report.expected_weekly_volatility <= 0.015 ? 'OK' : 'BLOCK'
    );

    _updateGuardrail(
      'gr-var',
      report.var_95 != null
        ? AppState.formatAmount(report.var_95)
        : '미검증',
      report.var_95 == null ? 'WARN'
        : report.var_95 >= -2_000_000_000 ? 'OK' : 'BLOCK'
    );

    _updateGuardrail(
      'gr-mdd',
      report.max_drawdown != null
        ? `${(report.max_drawdown * 100).toFixed(2)}%`
        : '미검증',
      report.max_drawdown == null ? 'WARN'
        : report.max_drawdown > -0.03 ? 'OK' : 'WARN'
    );

    _updateGuardrail(
      'gr-beta',
      report.benchmark_beta != null
        ? report.benchmark_beta.toFixed(2)
        : '미검증',
      report.benchmark_beta == null ? 'WARN'
        : (report.benchmark_beta >= 0.9 && report.benchmark_beta <= 1.2) ? 'OK' : 'WARN'
    );

    _updateGuardrail(
      'gr-single-etf',
      report.max_single_etf != null
        ? AppState.formatAmount(report.max_single_etf)
        : '미검증',
      report.max_single_etf == null ? 'WARN'
        : report.max_single_etf <= 4_000_000_000 ? 'OK' : 'BLOCK'
    );

    _updateGuardrail(
      'gr-alpha-risk',
      report.alpha_risk_ratio != null
        ? `${(report.alpha_risk_ratio * 100).toFixed(1)}%`
        : '미검증',
      report.alpha_risk_ratio == null ? 'WARN'
        : report.alpha_risk_ratio <= 0.40 ? 'OK' : 'BLOCK'
    );

    /* 위반 항목 표시 */
    _renderViolations(report.violations || []);
  }

  /* ══════════════════════════════════════════════════════════
     개별 가드레일 아이템 상태 업데이트
     status: 'OK' | 'WARN' | 'BLOCK'
  ══════════════════════════════════════════════════════════ */
  function _updateGuardrail(elementId, value, status) {
    const el = document.getElementById(elementId);
    if (!el) return;

    /* 기존 상태 클래스 제거 후 새로 적용 */
    el.classList.remove('ok', 'warn', 'block');

    const statusLower = status.toLowerCase();
    el.classList.add(statusLower);

    const valueEl  = el.querySelector('.guardrail-value');
    const statusEl = el.querySelector('.guardrail-status');

    if (valueEl)  valueEl.textContent  = value;
    if (statusEl) statusEl.textContent = status;
  }

  /* ══════════════════════════════════════════════════════════
     위반 항목 표시
  ══════════════════════════════════════════════════════════ */
  function _renderViolations(violations) {
    const container = document.getElementById('risk-violations');
    if (!container) return;

    if (violations.length === 0) {
      container.classList.add('hidden');
      return;
    }

    container.classList.remove('hidden');
    container.innerHTML = `
      <strong style="display:block;margin-bottom:0.4rem">위반 항목 (${violations.length}건)</strong>
      ${violations.map(v => `<div style="margin:0.2rem 0">• ${v}</div>`).join('')}
    `;
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return { init };
})();
