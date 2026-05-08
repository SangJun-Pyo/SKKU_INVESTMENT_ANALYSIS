/**
 * allocationEngine.js — 포트폴리오 배분 UI 모듈
 *
 * 역할:
 * - "배분 제안" 버튼 → /papertrade/allocation/suggest API 호출
 * - Core 100억 (40/30/30) 자동 배분 표시
 * - Alpha 30억 점수 기반 배분 표시
 * - 총 익스포저 및 레버리지 비율 표시
 * - AppState.portfolio 업데이트
 *
 * 서버가 없을 때의 폴백(fallback):
 *   Core 배분을 클라이언트에서 직접 계산합니다.
 *   이렇게 하면 백엔드 없이도 UI 데모가 가능합니다.
 */
window.AllocationEngine = (() => {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════════════════ */
  function init() {
    const btn = document.getElementById('suggest-allocation-btn');
    if (btn) {
      btn.addEventListener('click', _handleSuggest);
    }

    /* 포트폴리오 변경 시 UI 자동 업데이트 */
    AppState.on('portfolio', _renderAllocation);

    /* 초기 렌더링: 상태가 있으면 바로 표시 */
    const portfolio = AppState.get('portfolio');
    if (portfolio.positions.length > 0) {
      _renderAllocation(portfolio);
    }
  }

  /* ══════════════════════════════════════════════════════════
     배분 제안 API 호출
  ══════════════════════════════════════════════════════════ */
  async function _handleSuggest() {
    const universe = AppState.get('universe');
    if (universe.length === 0) {
      alert('ETF 유니버스를 먼저 설정하세요.');
      return;
    }

    const btn = document.getElementById('suggest-allocation-btn');
    if (btn) btn.disabled = true;

    try {
      const week = AppState.get('week');
      const signalScores = AppState.get('signalScores');
      const scores = Object.values(signalScores);

      const res = await fetch('/papertrade/allocation/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          week,
          universe,
          scores,
          reserve_amount: 0,   // 예비금 0 → Core 100억 + Alpha 최대 30억 = 130억 풀 활용
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const snapshot = await res.json();
      /* AllocationSuggestResponse → AppState.portfolio 변환
         서버 응답 필드: { positions, total_exposure, leverage_ratio, cash_remaining, week, warnings }
         AppState.update 미존재 → AppState.set 사용 */
      const baseCapital = AppState.get('baseCapital');
      const totalExp    = snapshot.total_exposure || 0;
      const borrowed    = Math.max(0, totalExp - baseCapital);
      AppState.set('portfolio', {
        cash:          snapshot.cash_remaining ?? (baseCapital - totalExp),
        borrowedCash:  borrowed,
        totalExposure: totalExp,
        positions:     snapshot.positions || [],
      });

      console.log('[AllocationEngine] 배분 제안 완료:', snapshot);

    } catch (err) {
      console.warn('[AllocationEngine] 서버 오류, 클라이언트 폴백 실행:', err.message);
      /* 서버 없을 때 클라이언트에서 직접 Core 배분 계산 */
      _fallbackCoreAllocation(universe);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ══════════════════════════════════════════════════════════
     폴백: 클라이언트에서 직접 Core 배분 계산
     서버가 없거나 오류일 때도 기본 동작이 가능하게 합니다.
  ══════════════════════════════════════════════════════════ */
  function _fallbackCoreAllocation(universe) {
    const baseCapital = AppState.get('baseCapital');
    const benchmark   = AppState.get('benchmark');
    const scores      = AppState.get('signalScores');

    const coreETFs = universe.filter(e => e.role === 'Core');
    const alphaETFs = universe.filter(e =>
      (e.role === 'Alpha' || e.role === 'Tactical') &&
      scores[e.ticker] &&
      scores[e.ticker].total_score >= 65
    );

    const positions = [];
    let totalAlloc = 0;

    /* Core 배분: 벤치마크 비율 기반 */
    const coreMap = {
      /* KRW Core: 40% */
      KRW: baseCapital * benchmark.kospi200,
      /* Hedged Core: 30% */
      Hedged: baseCapital * benchmark.sp500Hedged,
      /* Unhedged Core: 30% */
      Unhedged: baseCapital * benchmark.sp500Unhedged,
    };

    coreETFs.forEach((etf, i) => {
      /* currency_exposure 기반으로 Core 금액 결정 */
      const coreAmounts = Object.values(coreMap);
      const amount = coreAmounts[i % coreAmounts.length] || baseCapital * 0.33;
      const weight  = amount / baseCapital;

      positions.push({
        ticker:         etf.ticker,
        name:           etf.name,
        role:           etf.role,
        target_amount:  amount,
        target_weight:  weight,
        signal_score:   scores[etf.ticker]?.total_score || null,
        regime:         scores[etf.ticker]?.regime || null,
      });
      totalAlloc += amount;
    });

    /* Alpha 배분: 최대 25억 (30억 - 5억 reserve), 점수 비례 분배 */
    const maxAlpha = 2_500_000_000;
    const alphaTotal = alphaETFs.reduce((s, e) => s + (scores[e.ticker]?.total_score || 0), 0);

    alphaETFs.forEach(etf => {
      const sc = scores[etf.ticker];
      if (!sc) return;
      /* 점수 비율로 Alpha 예산 분배 */
      const weight  = alphaTotal > 0 ? sc.total_score / alphaTotal : 1 / alphaETFs.length;
      const amount  = Math.round(maxAlpha * weight);
      const pWeight = amount / baseCapital;

      positions.push({
        ticker:         etf.ticker,
        name:           etf.name,
        role:           etf.role,
        target_amount:  amount,
        target_weight:  pWeight,
        signal_score:   sc.total_score,
        regime:         sc.regime,
      });
      totalAlloc += amount;
    });

    const borrowedFallback = Math.max(0, totalAlloc - baseCapital);
    AppState.set('portfolio', {
      cash:          Math.max(0, baseCapital - totalAlloc),
      borrowedCash:  borrowedFallback,
      totalExposure: totalAlloc,
      positions,
    });
  }

  /* ══════════════════════════════════════════════════════════
     배분 UI 렌더링
  ══════════════════════════════════════════════════════════ */
  function _renderAllocation(portfolio) {
    const positions  = portfolio.positions || [];
    const corePos    = positions.filter(p => p.role === 'Core');
    const alphaPos   = positions.filter(p => p.role !== 'Core');

    _renderPositionList('core-allocation-list', corePos);
    _renderPositionList('alpha-allocation-list', alphaPos);
    _updateSummary(portfolio);
  }

  /* 포지션 목록 렌더링 (제거 버튼 + 금액 인라인 편집 포함) */
  function _renderPositionList(containerId, positions) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (positions.length === 0) {
      container.innerHTML = '<div class="hint">배분 없음</div>';
      return;
    }

    container.innerHTML = positions.map(p => {
      const amount    = AppState.formatAmount(p.target_amount);
      const weight    = (p.target_weight * 100).toFixed(1) + '%';
      const scoreText = p.signal_score != null
        ? `<span style="color:var(--text-muted);font-size:0.75rem">${p.signal_score.toFixed(0)}점</span>`
        : '';

      return `
        <div class="allocation-item" data-ticker="${p.ticker}">
          <span class="alloc-ticker">${p.ticker}</span>
          <span style="color:var(--text-muted);font-size:0.8rem;flex:1">${p.name}</span>
          ${scoreText}
          <!-- 금액: 클릭 시 편집 모드 진입, data-amount에 원(원화) 단위 값을 보관 -->
          <span class="alloc-amount editable-amount"
                data-ticker="${p.ticker}"
                data-amount="${p.target_amount}"
                title="클릭하여 금액 수정 (억 단위)">
            ${amount}
          </span>
          <span class="alloc-weight" data-ticker="${p.ticker}">${weight}</span>
          <button class="alloc-remove-btn" data-ticker="${p.ticker}" title="${p.ticker} 제거">✕</button>
        </div>
      `;
    }).join('');

    /* 금액 클릭 → 인라인 편집 모드 진입
       왜 querySelectorAll 후 forEach: 동적 생성된 DOM에 이벤트를 개별 바인딩하기 위함 */
    container.querySelectorAll('.editable-amount').forEach(el => {
      el.addEventListener('click', _handleAmountEdit);
    });

    /* 제거 버튼 이벤트 바인딩 */
    container.querySelectorAll('.alloc-remove-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        const ticker = e.currentTarget.dataset.ticker;
        _removePosition(ticker);
      });
    });
  }

  /* ══════════════════════════════════════════════════════════
     금액 인라인 편집 핸들러
     왜 span → input 교체 방식인가:
     별도 모달 없이 셀 내부에서 바로 수정이 가능하므로 UX가 간결합니다.
  ══════════════════════════════════════════════════════════ */
  function _handleAmountEdit(e) {
    const span = e.currentTarget;
    const ticker = span.dataset.ticker;
    const currentAmount = parseFloat(span.dataset.amount);
    /* 억 단위로 환산: 사용자는 억 단위로 입력하는 것이 직관적 */
    const currentOk = Math.round(currentAmount / 100_000_000);

    /* span을 number input으로 교체 */
    const input = document.createElement('input');
    input.type    = 'number';
    input.value   = currentOk;
    input.min     = 0;
    input.max     = 130; /* 총 익스포저 상한 130억 */
    input.step    = 1;
    input.className = 'alloc-amount-input';
    input.title   = '억 단위 입력 후 Enter (Escape: 취소)';
    /* 인라인 스타일: 전역 CSS가 없어도 동작하도록 최소한 지정 */
    input.style.cssText = 'width:60px;background:#21262d;border:1px solid #388bfd;color:#c9d1d9;border-radius:4px;padding:0.2rem 0.4rem;font-size:0.82rem;text-align:right;';

    span.replaceWith(input);
    input.focus();
    input.select();

    /* Enter: 확정 / Escape: 취소(원래 span 복원) */
    const _commit = () => {
      const newOk = parseFloat(input.value);
      if (isNaN(newOk) || newOk < 0) {
        /* 잘못된 값이면 원래 span을 복원해 데이터 손실 방지 */
        input.replaceWith(span);
        return;
      }
      /* 억 단위 → 원 단위로 변환 후 AppState 업데이트 */
      const newAmount = Math.round(newOk * 100_000_000);
      _updatePositionAmount(ticker, newAmount);
    };

    input.addEventListener('keydown', ev => {
      if (ev.key === 'Enter')  { ev.preventDefault(); _commit(); }
      if (ev.key === 'Escape') { input.replaceWith(span); }
    });
    /* blur 시에도 확정: 다른 곳 클릭 시 자동 저장 */
    input.addEventListener('blur', _commit);
  }

  /* ══════════════════════════════════════════════════════════
     포지션 금액 업데이트
     왜 target_weight를 여기서 재계산하는가:
     개별 금액이 바뀌면 전체 대비 비중도 달라지므로
     AppState에 저장하기 전에 일괄 재계산해야 UI 정합성이 유지됩니다.
  ══════════════════════════════════════════════════════════ */
  function _updatePositionAmount(ticker, newAmount) {
    const portfolio   = AppState.get('portfolio');
    const baseCapital = AppState.get('baseCapital');

    /* 해당 ticker만 금액 교체, 나머지는 그대로 유지 */
    const newPositions = portfolio.positions.map(p => {
      if (p.ticker !== ticker) return p;
      return { ...p, target_amount: newAmount };
    });

    /* 전체 익스포저 합산 후 비중 재계산 */
    const totalExp = newPositions.reduce((s, p) => s + (p.target_amount || 0), 0);
    const reweighted = newPositions.map(p => ({
      ...p,
      target_weight: totalExp > 0 ? p.target_amount / totalExp : 0,
    }));

    /* 차입금: 총 익스포저가 자기자본을 초과한 부분 */
    const borrowed = Math.max(0, totalExp - baseCapital);

    AppState.set('portfolio', {
      ...portfolio,
      positions:     reweighted,
      totalExposure: totalExp,
      borrowedCash:  borrowed,
      cash:          Math.max(0, baseCapital - totalExp),
    });
  }

  /* 배분 목록에서 포지션 제거 */
  async function _removePosition(ticker) {
    const portfolio = AppState.get('portfolio');
    const newPositions = portfolio.positions.filter(p => p.ticker !== ticker);
    const newExposure  = newPositions.reduce((s, p) => s + (p.target_amount || 0), 0);
    const baseCapital  = AppState.get('baseCapital');
    const newBorrowed  = Math.max(0, newExposure - baseCapital);

    /* target_weight 재계산 */
    const totalW = newExposure > 0 ? newExposure : 1;
    const reweighted = newPositions.map(p => ({
      ...p,
      target_weight: p.target_amount / totalW,
    }));

    AppState.set('portfolio', {
      ...portfolio,
      positions:     reweighted,
      totalExposure: newExposure,
      borrowedCash:  newBorrowed,
      cash:          Math.max(0, baseCapital - newExposure),
    });

    /* 유니버스에서도 제거 (서버 DELETE 호출) */
    try {
      await fetch(`/papertrade/universe/${encodeURIComponent(ticker)}`, { method: 'DELETE' });
      /* 로컬 유니버스 업데이트 */
      const universe = AppState.get('universe');
      AppState.set('universe', universe.filter(e => e.ticker !== ticker));
    } catch (_) { /* 서버 없어도 로컬은 업데이트됨 */ }
  }

  /* 배분 요약 (총 노출 + 레버리지) */
  function _updateSummary(portfolio) {
    const exposureEl  = document.getElementById('total-exposure');
    const leverageEl  = document.getElementById('leverage-ratio');
    const baseCapital = AppState.get('baseCapital');

    if (exposureEl) {
      const formatted = AppState.formatAmount(portfolio.totalExposure);
      const overLimit = portfolio.totalExposure > 13_000_000_000;
      exposureEl.textContent = formatted;
      exposureEl.style.color = overLimit ? 'var(--danger)' : 'var(--success)';
    }

    if (leverageEl) {
      const ratio = portfolio.borrowedCash / baseCapital;
      const pct   = (ratio * 100).toFixed(1) + '%';
      leverageEl.textContent = pct;
      leverageEl.style.color = ratio > 0.30 ? 'var(--danger)'
        : ratio > 0.20 ? 'var(--warn)'
        : 'var(--success)';
    }
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return { init, suggest: _handleSuggest };
})();
