/**
 * etfUniverse.js — ETF 유니버스 관리 UI 모듈
 *
 * 역할:
 * - 후보 ETF 클릭으로 한 번에 추가
 * - ETF 추가/삭제 인터페이스 (수동 입력도 유지)
 * - Core/Alpha/Hedge/Tactical/Short 역할 태그 관리
 * - ETF 10개 미만 규칙 검증
 */
window.ETFUniverseModule = (() => {
  'use strict';

  // 유니버스는 무제한 후보 풀 — 배분 시 서버가 상위 9개 자동 선택
  // MAX_ETF_COUNT는 UI 배지 표시용으로만 사용
  const MAX_ETF_COUNT = 9;
  const UNIVERSE_IS_UNLIMITED = true;

  /* ── 후보 ETF 목록 ─────────────────────────────────────────────────────
     클릭 한 번으로 추가할 수 있는 과제용 ETF 유니버스입니다.
     reason은 툴팁으로 표시됩니다. */
  const CANDIDATE_ETFS = [
    /* ── Core 벤치마크 ── */
    { ticker: '069500.KS', name: 'KODEX 200',                      role: 'Core',     currency_exposure: 'KRW',      asset_class: 'Korea ETF',   label: 'KOSPI200',    reason: 'KOSPI200 벤치마크 40%를 복제하기 위한 필수 Core ETF.' },
    { ticker: '449180.KS', name: 'KODEX 미국S&P500(H)',              role: 'Core',     currency_exposure: 'Hedged',   asset_class: 'Korea ETF',   label: 'S&P500(H)',   reason: 'S&P500 환헤지 벤치마크 30%를 복제. 거래량 충분(674K주/일).' },
    { ticker: '379800.KS', name: 'KODEX 미국S&P500TR',              role: 'Core',     currency_exposure: 'Unhedged', asset_class: 'Korea ETF',   label: 'S&P500(U)',   reason: 'S&P500 환노출 벤치마크 30%를 복제하기 위한 Core ETF.' },

    /* ── Growth / Tech Alpha ── */
    { ticker: '426030.KS', name: 'TIME 미국나스닥100액티브',         role: 'Alpha',    currency_exposure: 'Unhedged', asset_class: 'Korea ETF',   label: '나스닥액티브', reason: '나스닥100 기반 글로벌 테크 액티브 ETF. 성장주 모멘텀이 강할 때 S&P500 대비 초과수익 후보.' },
    { ticker: '456600.KS', name: 'TIME 글로벌AI인공지능액티브',      role: 'Alpha',    currency_exposure: 'Unhedged', asset_class: 'Korea ETF',   label: 'AI액티브',    reason: 'AI/반도체/데이터 인프라 테마에 집중하는 액티브 ETF. 단기 AI 모멘텀 활용 후보.' },
    { ticker: '381180.KS', name: 'TIGER 미국필라델피아반도체나스닥', role: 'Alpha',    currency_exposure: 'Unhedged', asset_class: 'Korea ETF',   label: '미국반도체',   reason: '미국 반도체 사이클 노출. AI 인프라 수요가 강할 때 알파 후보.' },
    { ticker: '390390.KS', name: 'KODEX 미국반도체MV',               role: 'Alpha',    currency_exposure: 'Unhedged', asset_class: 'Korea ETF',   label: '반도체MV',    reason: '반도체 종목 분산도가 넓어 381180 대비 변동성 완충. 반도체 섹터 균형 노출.' },
    { ticker: '305080.KS', name: 'TIGER 미국나스닥100',              role: 'Alpha',    currency_exposure: 'Unhedged', asset_class: 'Korea ETF',   label: '나스닥100',   reason: '미국 대형 기술주 모멘텀 노출. QQQ 대체 국내 상장 ETF.' },

    /* ── Korea Alpha ── */
    { ticker: '091160.KS', name: 'KODEX 반도체',                    role: 'Alpha',    currency_exposure: 'KRW',      asset_class: 'Korea ETF',   label: 'KR반도체',    reason: '한국 반도체 업종 노출. KOSPI200 대비 국내 주식 알파 후보.' },
    { ticker: '396500.KS', name: 'TIGER Fn반도체TOP10',              role: 'Alpha',    currency_exposure: 'KRW',      asset_class: 'Korea ETF',   label: '반도체TOP10', reason: '국내 대표 반도체 종목 압축 노출. 삼성전자/SK하이닉스 중심 알파 후보.' },
    { ticker: '229200.KS', name: 'KODEX 코스닥150',                  role: 'Alpha',    currency_exposure: 'KRW',      asset_class: 'Korea ETF',   label: '코스닥150',   reason: '국내 성장주/고베타 노출. 반등장에서는 초과수익 가능하나 변동성 관리 필요.' },

    /* ── Hedge ── */
    { ticker: '273130.KS', name: 'KODEX 종합채권(AA-이상)액티브',   role: 'Hedge',    currency_exposure: 'KRW',      asset_class: 'Korea ETF',   label: '종합채권',    reason: '주식 변동성 확대 시 방어 자산. 포트폴리오 변동성 완화 목적.' },
    { ticker: '148070.KS', name: 'KOSEF 국고채10년',                 role: 'Hedge',    currency_exposure: 'KRW',      asset_class: 'Korea ETF',   label: '국고채10년',  reason: '금리 하락 국면에서 수익 가능. 주식 알파 포지션의 변동성 완충 역할.' },
    { ticker: 'GLD',       name: 'SPDR Gold Shares',                  role: 'Hedge',    currency_exposure: 'USD',      asset_class: 'Global ETF',  label: '금(GLD)',      reason: '위험회피와 달러 약세 국면의 방어 자산. 주식과 다른 방향의 헤지 후보.' },

    /* ── Currency / Tactical ── */
    { ticker: '261240.KS', name: 'KODEX 미국달러선물',               role: 'Tactical', currency_exposure: 'KRW',      asset_class: 'Korea ETF',   label: '달러선물',    reason: '원/달러 상승 시 수혜. S&P500 환노출 비중과 함께 환율 전략에 활용.' },
    { ticker: '195930.KS', name: 'TIGER 유로스탁스50(합성 H)',       role: 'Tactical', currency_exposure: 'Hedged',   asset_class: 'Korea ETF',   label: '유로스탁스',  reason: '미국 중심 포트폴리오의 지역 분산 후보. 유럽 경기 회복 국면에서 활용.' },

    /* ── Short / Inverse ── */
    { ticker: '114800.KS', name: 'KODEX 인버스',                     role: 'Short',    currency_exposure: 'KRW',      asset_class: 'Inverse ETF', label: '코스피인버스', reason: 'KOSPI 하락 방어용. Core KOSPI200 포지션의 단기 헤지 수단.' },
    { ticker: '252670.KS', name: 'KODEX 200선물인버스2X',            role: 'Short',    currency_exposure: 'KRW',      asset_class: 'Inverse ETF', label: '인버스2X',    reason: '강한 하락장 헤지 수단. 레버리지 인버스이므로 제한적으로만 사용.' },
  ];

  /* ── 카테고리별 그룹 ────────────────────────────────────────────────── */
  const CANDIDATE_GROUPS = [
    {
      label: '📌 Core 벤치마크',
      tickers: ['069500.KS', '449180.KS', '379800.KS'],
    },
    {
      label: '🚀 Growth / Tech Alpha',
      tickers: ['426030.KS', '456600.KS', '381180.KS', '390390.KS', '305080.KS'],
    },
    {
      label: '🇰🇷 Korea Alpha',
      tickers: ['091160.KS', '396500.KS', '229200.KS'],
    },
    {
      label: '🛡️ Hedge',
      tickers: ['273130.KS', '148070.KS', 'GLD'],
    },
    {
      label: '💱 Currency / Tactical',
      tickers: ['261240.KS', '195930.KS'],
    },
    {
      label: '📉 Short / Inverse',
      tickers: ['114800.KS', '252670.KS'],
    },
  ];

  /* ticker → candidate 조회용 맵 */
  const _candidateMap = Object.fromEntries(CANDIDATE_ETFS.map(c => [c.ticker, c]));

  /* ══════════════════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════════════════ */
  function init() {
    /* 후보 목록 렌더링 (DOM 준비 직후 1회) */
    _renderCandidates([]);

    /* 추가 버튼 */
    const addBtn = document.getElementById('etf-add-btn');
    if (addBtn) addBtn.addEventListener('click', _handleAdd);

    /* 엔터키로 추가 */
    const tickerInput = document.getElementById('etf-ticker-input');
    if (tickerInput) tickerInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') _handleAdd();
    });

    /* AppState 변경 시 UI 자동 업데이트 */
    AppState.on('universe', _render);

    /* 서버에서 기존 유니버스 복원 */
    _loadFromServer();
  }

  /* ══════════════════════════════════════════════════════════
     서버에서 유니버스 로드
  ══════════════════════════════════════════════════════════ */
  async function _loadFromServer() {
    try {
      const res = await fetch('/papertrade/universe');
      if (!res.ok) return;
      const data = await res.json();
      /* 서버 응답: { universe: [...], count: N } */
      const list = data.universe || data;
      if (Array.isArray(list) && list.length > 0) {
        AppState.set('universe', list);
        console.log(`[ETFUniverse] 서버에서 ${list.length}개 ETF 로드 완료`);
      }
    } catch (err) {
      console.warn('[ETFUniverse] 서버 로드 실패 (로컬 상태로 운영):', err.message);
    }
  }

  /* ══════════════════════════════════════════════════════════
     전체 추가 — 모든 후보 ETF를 한 번에 추가
  ══════════════════════════════════════════════════════════ */
  async function _handleAddAll() {
    const addAllBtn = document.getElementById('add-all-candidates-btn');
    if (addAllBtn) { addAllBtn.disabled = true; addAllBtn.textContent = '추가 중...'; }

    const universe = AppState.get('universe');
    const addedTickers = new Set(universe.map(e => e.ticker));
    const toAdd = CANDIDATE_ETFS.filter(c => !addedTickers.has(c.ticker));

    let successCount = 0;
    for (const candidate of toAdd) {
      const newETF = {
        ticker:            candidate.ticker,
        name:              candidate.name,
        asset_class:       candidate.asset_class,
        role:              candidate.role,
        currency_exposure: candidate.currency_exposure,
        enabled:           true,
      };
      const ok = await _postToServer(newETF);
      if (ok) {
        successCount++;
        /* AppState 즉시 업데이트 (렌더링 실시간 반영) */
        const current = AppState.get('universe');
        AppState.set('universe', [...current, newETF]);
      }
    }

    if (addAllBtn) { addAllBtn.disabled = false; addAllBtn.textContent = '전체 추가'; }
    console.log(`[ETFUniverse] 전체 추가 완료: ${successCount}/${toAdd.length}개`);
  }

  /* ══════════════════════════════════════════════════════════
     전체 삭제 — 유니버스 초기화
  ══════════════════════════════════════════════════════════ */
  async function _handleClearAll() {
    const universe = AppState.get('universe');
    if (universe.length === 0) return;

    const ok = confirm(`유니버스의 ETF ${universe.length}개를 전부 삭제합니다.\n계속하시겠습니까?`);
    if (!ok) return;

    for (const etf of [...universe]) {
      try {
        await fetch(`/papertrade/universe/${encodeURIComponent(etf.ticker)}`, { method: 'DELETE' });
      } catch (_) {}
    }
    AppState.set('universe', []);
  }

  /* ══════════════════════════════════════════════════════════
     후보 클릭으로 빠른 추가
  ══════════════════════════════════════════════════════════ */
  async function _handleCandidateClick(ticker) {
    const candidate = _candidateMap[ticker];
    if (!candidate) return;

    const universe = AppState.get('universe');

    /* 이미 추가된 경우 */
    if (universe.some(e => e.ticker === ticker)) return;

    /* 유니버스는 무제한 — 개수 제한 없음 */

    const newETF = {
      ticker: candidate.ticker,
      name:   candidate.name,
      asset_class: candidate.asset_class,
      role:   candidate.role,
      currency_exposure: candidate.currency_exposure,
      enabled: true,
    };

    /* 서버 저장 */
    const ok = await _postToServer(newETF);
    if (!ok) {
      alert(`${ticker} 추가 실패. 서버 응답을 확인하세요.`);
      return;
    }

    /* AppState 업데이트 */
    AppState.set('universe', [...universe, newETF]);
  }

  /* ══════════════════════════════════════════════════════════
     수동 입력으로 추가
  ══════════════════════════════════════════════════════════ */
  async function _handleAdd() {
    const tickerInput = document.getElementById('etf-ticker-input');
    const nameInput   = document.getElementById('etf-name-input');
    const roleSelect  = document.getElementById('etf-role-select');
    const currSelect  = document.getElementById('etf-currency-select');

    const ticker = tickerInput.value.trim().toUpperCase();
    const name   = nameInput.value.trim();
    const role   = roleSelect.value;
    const currency_exposure = currSelect.value;

    if (!ticker) { alert('티커를 입력하세요.'); tickerInput.focus(); return; }
    if (!name)   { alert('ETF 이름을 입력하세요.'); nameInput.focus(); return; }

    const universe = AppState.get('universe');

    if (universe.some(e => e.ticker === ticker)) {
      alert(`${ticker}는 이미 유니버스에 있습니다.`); return;
    }
    /* 유니버스는 무제한 후보 풀 — 개수 제한 없음 */

    const newETF = {
      ticker,
      name,
      asset_class: ticker.endsWith('.KS') ? 'Korea ETF' : 'Global ETF',
      role,
      currency_exposure,
      enabled: true,
    };

    const ok = await _postToServer(newETF);
    if (!ok) { alert(`${ticker} 추가 실패. 허용 티커 목록을 확인하세요.`); return; }

    AppState.set('universe', [...universe, newETF]);
    tickerInput.value = '';
    nameInput.value   = '';
    tickerInput.focus();
  }

  /* ══════════════════════════════════════════════════════════
     ETF 삭제
  ══════════════════════════════════════════════════════════ */
  async function _handleRemove(ticker) {
    const universe = AppState.get('universe');
    const target = universe.find(e => e.ticker === ticker);

    if (target && target.role === 'Core') {
      const ok = confirm(
        `"${ticker}"는 Core ETF입니다.\n` +
        `Core ETF를 삭제하면 벤치마크 복제 구조가 깨질 수 있습니다.\n\n삭제하시겠습니까?`
      );
      if (!ok) return;
    }

    try {
      await fetch(`/papertrade/universe/${encodeURIComponent(ticker)}`, { method: 'DELETE' });
    } catch (err) {
      console.warn('[ETFUniverse] 서버 삭제 실패:', err.message);
    }

    AppState.set('universe', universe.filter(e => e.ticker !== ticker));
  }

  /* ══════════════════════════════════════════════════════════
     서버 API 단건 POST
  ══════════════════════════════════════════════════════════ */
  async function _postToServer(etf) {
    try {
      const res = await fetch('/papertrade/universe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(etf),
      });
      return res.ok;
    } catch (err) {
      console.warn('[ETFUniverse] 서버 저장 실패:', err.message);
      return false;
    }
  }

  /* ══════════════════════════════════════════════════════════
     UI 렌더링 (AppState 변경 시 호출)
  ══════════════════════════════════════════════════════════ */
  function _render(universe) {
    _renderList(universe);
    _updateCountBadge(universe.length);
    _renderCandidates(universe);
    _renderPriceInputs(universe);
  }

  /* ── 추가된 ETF 목록 ── */
  function _renderList(universe) {
    const container = document.getElementById('etf-list');
    if (!container) return;

    if (universe.length === 0) {
      container.innerHTML = '<div class="empty-state" style="color:#8b949e;font-size:0.85rem;padding:0.5rem 0;">아래 후보 목록에서 클릭하거나 직접 입력하세요.</div>';
      return;
    }

    container.innerHTML = universe.map(etf => `
      <div class="etf-item" data-ticker="${etf.ticker}">
        <span class="ticker">${etf.ticker}</span>
        <span class="name">${etf.name}</span>
        <span class="role-badge ${etf.role}">${etf.role}</span>
        <span class="role-badge" style="background:rgba(139,148,158,0.1);color:#8b949e;border:1px solid #30363d;font-size:0.65rem;">${etf.currency_exposure}</span>
        <button class="remove-btn" data-ticker="${etf.ticker}" title="${etf.ticker} 삭제">✕</button>
      </div>
    `).join('');

    container.querySelectorAll('.remove-btn').forEach(btn => {
      btn.addEventListener('click', e => _handleRemove(e.currentTarget.dataset.ticker));
    });
  }

  /* ── 개수 배지 ── */
  function _updateCountBadge(count) {
    const badge = document.getElementById('etf-count-badge');
    if (!badge) return;
    // 유니버스는 무제한 — 배분 시 상위 9개 자동 선택
    badge.textContent = `${count}종목`;
    badge.className = 'count-badge';
  }

  /* ── 후보 ETF 목록 (카테고리별 칩) ── */
  function _renderCandidates(universe) {
    let container = document.getElementById('etf-candidates');

    /* 컨테이너가 없으면 동적으로 생성 (etf-list 아래에 삽입) */
    if (!container) {
      const card = document.getElementById('etf-universe-card');
      if (!card) return;
      container = document.createElement('div');
      container.id = 'etf-candidates';
      container.style.cssText = 'margin-top:1rem;border-top:1px solid #30363d;padding-top:0.75rem;';
      card.appendChild(container);
    }

    const addedTickers = new Set((universe || []).map(e => e.ticker));
    const isFull = false; // 유니버스는 무제한

    const groupsHtml = CANDIDATE_GROUPS.map(group => {
      const chipsHtml = group.tickers.map(ticker => {
        const c = _candidateMap[ticker];
        if (!c) return '';
        const isAdded = addedTickers.has(ticker);
        const isCore  = c.role === 'Core';
        const disabled = isAdded || isFull;

        return `
          <button
            class="candidate-chip ${isAdded ? 'added' : ''} ${disabled && !isAdded ? 'disabled' : ''}"
            data-ticker="${ticker}"
            title="${c.reason || c.name} (${c.currency_exposure})"
            ${disabled ? 'disabled' : ''}
          >
            <span class="chip-ticker">${ticker}</span>
            <span class="chip-label">${c.label}</span>
            ${isAdded ? '<span class="chip-check">✓</span>' : ''}
            ${isCore && !isAdded ? '<span class="chip-core">Core</span>' : ''}
          </button>
        `;
      }).join('');

      return `
        <div class="candidate-group">
          <div class="candidate-group-label">${group.label}</div>
          <div class="candidate-chips">${chipsHtml}</div>
        </div>
      `;
    }).join('');

    container.innerHTML = `
      <div class="candidate-header" style="font-size:0.8rem;color:#8b949e;margin-bottom:0.5rem;display:flex;align-items:center;gap:0.75rem;">
        <span>후보 ETF — 클릭하여 추가</span>
        <button id="add-all-candidates-btn" style="
          background:#1f6feb;border:none;color:#fff;
          font-size:0.72rem;padding:0.2rem 0.6rem;
          border-radius:4px;cursor:pointer;white-space:nowrap;
        ">전체 추가</button>
        <button id="clear-universe-btn" style="
          background:none;border:1px solid #f8514960;color:#f85149;
          font-size:0.72rem;padding:0.2rem 0.6rem;
          border-radius:4px;cursor:pointer;white-space:nowrap;
        ">전체 삭제</button>
      </div>
      ${groupsHtml}
    `;

    /* 칩 클릭 이벤트 */
    container.querySelectorAll('.candidate-chip:not([disabled])').forEach(btn => {
      btn.addEventListener('click', () => _handleCandidateClick(btn.dataset.ticker));
    });

    /* 전체 추가 버튼 */
    const addAllBtn = document.getElementById('add-all-candidates-btn');
    if (addAllBtn) {
      addAllBtn.onclick = _handleAddAll;
    }

    /* 전체 삭제 버튼 */
    const clearBtn = document.getElementById('clear-universe-btn');
    if (clearBtn) {
      clearBtn.onclick = _handleClearAll;
    }
  }

  /* ── P&L 탭 가격 입력 필드 동기화 ── */
  function _renderPriceInputs(universe) {
    const container = document.getElementById('price-input-list');
    if (!container) return;

    if (universe.length === 0) {
      container.innerHTML = '<div class="hint">ETF 유니버스를 먼저 설정하세요.</div>';
      return;
    }

    container.innerHTML = universe.map(etf => `
      <div class="price-input-item">
        <label for="price-${etf.ticker}">${etf.ticker} — ${etf.name}</label>
        <input
          type="number"
          id="price-${etf.ticker}"
          data-ticker="${etf.ticker}"
          placeholder="금요일 종가"
          step="any"
          min="0"
        />
      </div>
    `).join('');
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return { init };
})();
