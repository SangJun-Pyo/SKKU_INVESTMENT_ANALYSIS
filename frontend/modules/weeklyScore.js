/**
 * weeklyScore.js — 주간 신호 점수 UI 모듈
 *
 * 역할:
 * - "점수 계산" 버튼 클릭 → /papertrade/score/run API 호출
 * - 6가지 점수 컬럼 + 총점 + 레짐 + 액션 배지 렌더링
 * - AppState.signalScores 업데이트
 *
 * 점수 체계 (서버 service_weekly_score.py 기준):
 *   trend_score:      0-25pt (20일/60일 이동평균 방향성)
 *   pullback_score:   0-20pt (고점 대비 조정폭 + RSI 냉각)
 *   volatility_score: 0-20pt (변동성이 한도 이내인지)
 *   momentum_score:   0-15pt (최근 4주 수익률, RSI)
 *   drawdown_score:   0-10pt (고점 대비 낙폭 역점수)
 *   correlation_score: 0-10pt (기존 포트폴리오와 상관관계 낮을수록 유리)
 */
window.WeeklyScoreModule = (() => {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════════════════ */
  function init() {
    const btn = document.getElementById('run-score-btn');
    if (btn) {
      btn.addEventListener('click', _handleRunScore);
    }

    /* signalScores 변경 시 테이블 자동 업데이트 */
    AppState.on('signalScores', _renderTable);

    /* ── 점수 근거 툴팁 이벤트 위임 ───────────────────────────────
       각 행(tr)에 직접 이벤트를 붙이면 테이블 재렌더링 때마다
       이벤트를 재등록해야 하므로, 부모 tbody에 위임(delegation)합니다.
       mouseover: 가장 가까운 data-reason을 가진 tr을 찾아 툴팁 표시
       mouseleave: tbody 전체에서 마우스가 벗어나면 툴팁 숨김 */
    const tbody = document.getElementById('score-tbody');

    if (tbody) {
      tbody.addEventListener('mouseover', e => {
        /* 이벤트 타겟에서 가장 가까운 data-reason 속성 행을 탐색 */
        const row = e.target.closest('tr[data-reason]');
        if (!row) return;

        const reason = row.dataset.reason;
        if (!reason) return;

        /* 툴팁 엘리먼트가 없으면 생성하여 카드에 추가
           sticky bottom 위치로 스크롤 위치에 상관없이 카드 하단 고정 */
        let tooltipEl = document.getElementById('score-reason-tooltip');
        if (!tooltipEl) {
          tooltipEl = document.createElement('div');
          tooltipEl.id        = 'score-reason-tooltip';
          tooltipEl.className = 'score-tooltip hidden';
          /* 점수 카드 전체 컨테이너에 추가: 테이블 래퍼가 아닌 카드 수준 */
          document.getElementById('weekly-score-card')?.appendChild(tooltipEl);
        }

        /* reason 포맷: "[추세] xxx / [눌림목] yyy / ..."
           ' / '를 기준으로 분리하여 항목별로 줄바꿈 적용 */
        tooltipEl.innerHTML = reason
          .split(' / ')
          .filter(Boolean)
          .map(part => `<div class="tooltip-line">${part}</div>`)
          .join('');

        tooltipEl.classList.remove('hidden');
      });

      /* tbody 마우스 이탈 시 툴팁 숨김 */
      tbody.addEventListener('mouseleave', () => {
        document.getElementById('score-reason-tooltip')?.classList.add('hidden');
      });
    }
  }

  /* ══════════════════════════════════════════════════════════
     점수 계산 API 호출
  ══════════════════════════════════════════════════════════ */
  async function _handleRunScore() {
    const universe = AppState.get('universe');
    if (universe.length === 0) {
      alert('ETF 유니버스를 먼저 설정하세요.');
      return;
    }

    const loading = document.getElementById('score-loading');
    const btn = document.getElementById('run-score-btn');

    /* 로딩 상태 표시 */
    if (loading) loading.classList.remove('hidden');
    if (btn) btn.disabled = true;

    try {
      const week = AppState.get('week');
      const res = await fetch('/papertrade/score/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          week,
          tickers: universe.filter(e => e.enabled).map(e => e.ticker),
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      /* 서버 응답: { scores: [...], week: N } */
      const scoreList = Array.isArray(data) ? data : (data.scores || []);
      const scoresMap = {};
      scoreList.forEach(s => { scoresMap[s.ticker] = s; });

      /* 점수 계산 후 현재가 병렬 조회 */
      const priceMap = {};
      await Promise.allSettled(
        Object.keys(scoresMap).map(async ticker => {
          try {
            const pr = await fetch(`/price/${encodeURIComponent(ticker)}`);
            if (pr.ok) {
              const pd = await pr.json();
              priceMap[ticker] = pd.price;
            }
          } catch (_) { /* 가격 조회 실패는 무시 */ }
        })
      );
      AppState.set('prices', { ...AppState.get('prices'), ...priceMap });

      AppState.set('signalScores', scoresMap);
      console.log(`[WeeklyScore] ${Object.keys(scoresMap).length}개 ETF 점수 계산 완료`);

      /* 점수 계산 완료 후 배분 자동 재계산
         AllocationEngine이 로드되어 있으면 배분 제안 API를 자동 호출합니다.
         사용자가 수동으로 "배분 제안" 버튼을 누를 필요 없이 최신 점수 반영 */
      if (window.AllocationEngine && typeof window.AllocationEngine.suggest === 'function') {
        console.log('[WeeklyScore] 배분 자동 재계산 시작...');
        window.AllocationEngine.suggest();
      } else {
        /* 버튼 클릭으로 대체: AllocationEngine 공개 API 없으면 버튼 트리거 */
        const allocBtn = document.getElementById('suggest-allocation-btn');
        if (allocBtn && !allocBtn.disabled) {
          allocBtn.click();
        }
      }

    } catch (err) {
      console.error('[WeeklyScore] 점수 계산 오류:', err);
      alert(`점수 계산 오류: ${err.message}`);
    } finally {
      if (loading) loading.classList.add('hidden');
      if (btn) btn.disabled = false;
    }
  }

  /* ══════════════════════════════════════════════════════════
     점수 테이블 렌더링
     AppState.signalScores 변경 시 자동 호출됩니다.
  ══════════════════════════════════════════════════════════ */
  function _renderTable(scoresMap) {
    const tbody = document.getElementById('score-tbody');
    if (!tbody) return;

    const universe = AppState.get('universe');
    const prices   = AppState.get('prices') || {};

    if (universe.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" class="empty-state">ETF 유니버스를 먼저 설정하세요.</td></tr>';
      return;
    }

    /* 유니버스 순서대로 렌더링 */
    const rows = universe.map(etf => {
      const sc    = scoresMap[etf.ticker];
      const price = prices[etf.ticker];
      const priceStr = price
        ? (price >= 10000
            ? price.toLocaleString('ko-KR') + '원'
            : price.toLocaleString('en-US', { maximumFractionDigits: 2 }) + '$')
        : '-';

      if (!sc) {
        /* 아직 점수 계산 전인 ETF: 플레이스홀더 표시 */
        return `
          <tr>
            <td style="text-align:left">
              <strong style="color:var(--accent)">${etf.ticker}</strong>
              <span class="role-badge ${etf.role}" style="margin-left:4px">${etf.role}</span>
            </td>
            <td style="color:var(--text-muted);font-size:0.8rem">${priceStr}</td>
            <td colspan="9" style="color:var(--text-muted);font-size:0.8rem">점수 계산 전</td>
          </tr>
        `;
      }

      /* 총점에 따른 행 강조 색상 결정 */
      const rowClass = sc.total_score >= 80 ? 'score-row-high'
        : sc.total_score >= 65 ? 'score-row-good'
        : sc.total_score >= 35 ? ''
        : 'score-row-low';

      /* data-reason: 점수 근거 문자열을 HTML 속성으로 삽입
         마우스 오버 시 툴팁 패널에 렌더링하기 위해 저장합니다.
         쌍따옴표는 &quot;로 이스케이프하여 HTML 속성 파싱 오류를 방지합니다. */
      const reasonAttr = (sc.reason || '').replace(/"/g, '&quot;');

      return `
        <tr class="${rowClass} score-row-hover" data-reason="${reasonAttr}">
          <td style="text-align:left">
            <strong style="color:var(--accent)">${etf.ticker}</strong>
            <span class="role-badge ${etf.role}" style="margin-left:4px">${etf.role}</span>
            <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px">${etf.name}</div>
          </td>
          <td style="font-family:monospace;font-size:0.8rem;color:var(--text-secondary)">${priceStr}</td>
          <td>${_scoreCell(sc.trend_score, 25)}</td>
          <td>${_scoreCell(sc.pullback_score, 20)}</td>
          <td>${_scoreCell(sc.volatility_score, 20)}</td>
          <td>${_scoreCell(sc.momentum_score, 15)}</td>
          <td>${_scoreCell(sc.drawdown_score, 10)}</td>
          <td>${_scoreCell(sc.correlation_score, 10)}</td>
          <td>
            <strong style="font-size:1rem;color:${_totalColor(sc.total_score)}">
              ${sc.total_score.toFixed(0)}
            </strong>
          </td>
          <td>${_regimeBadge(sc.regime)}</td>
          <td>${_actionBadge(sc.action)}</td>
        </tr>
      `;
    }).join('');

    tbody.innerHTML = rows || '<tr><td colspan="10" class="empty-state">데이터 없음</td></tr>';
  }

  /* ══════════════════════════════════════════════════════════
     점수 셀: 실제 점수 / 만점 표시 + 색상 코딩
  ══════════════════════════════════════════════════════════ */
  function _scoreCell(score, maxScore) {
    const ratio = score / maxScore;
    const color = ratio >= 0.75 ? 'var(--success)'
      : ratio >= 0.50 ? 'var(--accent)'
      : ratio >= 0.25 ? 'var(--warn)'
      : 'var(--danger)';
    return `<span style="color:${color};font-weight:500">${score.toFixed(0)}</span>`;
  }

  /* 총점 색상 */
  function _totalColor(total) {
    if (total >= 80) return 'var(--success)';
    if (total >= 65) return 'var(--accent)';
    if (total >= 50) return 'var(--text)';
    if (total >= 35) return 'var(--warn)';
    return 'var(--danger)';
  }

  /* 레짐 배지 HTML */
  function _regimeBadge(regime) {
    const cls = (regime || 'Neutral').replace(' ', '-');
    return `<span class="regime-badge ${cls}">${regime || '-'}</span>`;
  }

  /* 액션 배지 HTML */
  function _actionBadge(action) {
    /* 'Small Buy'에서 공백을 하이픈으로 변환해야 CSS 클래스 매칭이 됩니다 */
    const cls = (action || 'Hold').replace(' ', '-');
    return `<span class="action-badge ${cls}">${action || '-'}</span>`;
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return { init };
})();
