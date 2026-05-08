/**
 * weeklyPnL.js — 주간 P&L 추적 UI 모듈
 *
 * 역할:
 * - 금요일 종가 입력 → P&L 계산
 * - 벤치마크 대비 Active Return 표시
 * - 레버리지 비용(주간 0.07%) + 현금 이자(주간 0.035%) 반영
 * - ETF별 기여도(Contribution) 계산 및 표시
 * - AppState.weeklyPnL 업데이트
 * - 누적 수익률 차트 (TradingView Lightweight Charts v4.2.0) 렌더링
 *
 * 계산 공식:
 *   portfolio_return  = Σ (position_weight × etf_return)
 *   benchmark_return  = 0.40 × kospi200_r + 0.30 × sp500h_r + 0.30 × sp500u_r
 *   active_return     = portfolio_return - benchmark_return
 *   leverage_cost     = borrowed_cash / base_capital × 0.0007
 *   cash_interest     = (cash / base_capital) × 0.00035
 *   net_return        = portfolio_return - leverage_cost + cash_interest
 *
 * 벤치마크 수익률 우선순위:
 *   1순위: 화면 상단의 벤치마크 전용 입력 필드 (bm-price-*)
 *   2순위: 유니버스 ETF 종가 입력 (price-*)
 *   — 이렇게 분리한 이유: 벤치마크 3종이 포트폴리오 유니버스에 없어도
 *     벤치마크 수익률은 항상 계산되어야 하기 때문
 */
window.WeeklyPnLModule = (() => {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════════════════ */
  function init() {
    const btn = document.getElementById('update-pnl-btn');
    if (btn) {
      btn.addEventListener('click', _handleUpdatePnL);
    }

    /* P&L 이력 변경 시 테이블과 차트를 동시에 업데이트
       — 두 렌더링을 하나의 리스너로 묶는 이유:
         데이터가 바뀔 때마다 테이블과 차트가 항상 동기화되어야 하기 때문 */
    AppState.on('weeklyPnL', (history) => {
      _renderPnLTable(history);
      _renderPnLChart(history);
    });

    /* 서버에서 기존 P&L 이력 로드 */
    _loadFromServer();
  }

  /* ══════════════════════════════════════════════════════════
     서버에서 P&L 이력 로드
  ══════════════════════════════════════════════════════════ */
  async function _loadFromServer() {
    try {
      const res = await fetch('/papertrade/pnl');
      if (!res.ok) return;
      const data = await res.json();
      /* 서버 응답: { pnl_list: [...], count: N } */
      const list = data.pnl_list || (Array.isArray(data) ? data : []);
      if (list.length > 0) {
        AppState.set('weeklyPnL', list);
      }
    } catch (err) {
      console.warn('[WeeklyPnL] 서버 로드 실패 (로컬 상태로 운영):', err.message);
    }
  }

  /* ══════════════════════════════════════════════════════════
     P&L 업데이트 처리
     입력된 종가를 기반으로 수익률을 계산합니다.

     벤치마크 가격 처리 전략:
     - allPrices = 포트폴리오 ETF 가격 + 벤치마크 전용 입력값
     - 벤치마크 전용 입력이 있으면 포트폴리오 입력보다 우선 적용
     - allPrices를 캐시에 저장해서 다음 주 기준가로 활용
  ══════════════════════════════════════════════════════════ */
  async function _handleUpdatePnL() {
    const portfolio   = AppState.get('portfolio');
    const universe    = AppState.get('universe');
    const week        = AppState.get('week');
    const baseCapital = AppState.get('baseCapital');

    if (portfolio.positions.length === 0) {
      alert('포트폴리오 배분을 먼저 진행하세요.');
      return;
    }

    /* 포트폴리오 ETF 종가 입력값 수집 */
    const prices = {};
    universe.forEach(etf => {
      const input = document.getElementById(`price-${etf.ticker}`);
      if (input && input.value) {
        const price = parseFloat(input.value);
        if (!isNaN(price) && price > 0) {
          prices[etf.ticker] = price;
        }
      }
    });

    if (Object.keys(prices).length === 0) {
      alert('최소 1개 ETF의 금요일 종가를 입력하세요.');
      return;
    }

    /* 벤치마크 전용 입력값을 allPrices에 병합
       — 유니버스에 없는 벤치마크 ETF도 수익률 계산에 포함하기 위해
         별도 입력 필드(bm-price-*)를 먼저 읽고 prices에 덮어쓰지 않고 추가 */
    const bmt      = AppState.get('benchmarkTickers');
    const allPrices = { ...prices };
    [bmt.kospi200, bmt.sp500Hedged, bmt.sp500Unhedged].forEach(ticker => {
      const bmInput = document.getElementById(`bm-price-${ticker}`);
      if (bmInput && bmInput.value) {
        const val = parseFloat(bmInput.value);
        if (!isNaN(val) && val > 0) {
          /* 벤치마크 전용 입력이 있으면 덮어쓰기
             이유: 유니버스에 동일 티커가 있더라도 벤치마크 입력을 명시적으로
             입력한 경우 그 값이 더 정확할 가능성이 높기 때문 */
          allPrices[ticker] = val;
        }
      }
    });

    /* 이전 주의 가격 정보 (직전 주 캐시 또는 기존 P&L에서 추출)
       — allPrices 기반 캐시를 사용하므로 벤치마크 가격도 포함 */
    const prevPrices = _getPreviousPrices(week);

    /* ETF별 수익률 계산 (포트폴리오 포지션 기준) */
    const returns = {};
    portfolio.positions.forEach(pos => {
      const currPrice = allPrices[pos.ticker];
      const prevPrice = prevPrices[pos.ticker];
      if (currPrice && prevPrice && prevPrice > 0) {
        returns[pos.ticker] = (currPrice - prevPrice) / prevPrice;
      }
    });

    /* 포트폴리오 수익률 계산 (가중평균) */
    let portfolioReturn = 0;
    const contribution = {};
    portfolio.positions.forEach(pos => {
      const ret = returns[pos.ticker] ?? 0;
      const weight = pos.target_weight;
      const contrib = weight * ret;
      contribution[pos.ticker] = contrib;
      portfolioReturn += contrib;
    });

    /* 벤치마크 수익률 계산
       — allPrices와 prevPrices를 모두 활용하여
         벤치마크 전용 입력 가격도 수익률에 반영 */
    const bm = AppState.get('benchmark');
    const bmR = {
      kospi200: (allPrices[bmt.kospi200] && prevPrices[bmt.kospi200])
        ? (allPrices[bmt.kospi200] - prevPrices[bmt.kospi200]) / prevPrices[bmt.kospi200]
        : 0,
      sp500Hedged: (allPrices[bmt.sp500Hedged] && prevPrices[bmt.sp500Hedged])
        ? (allPrices[bmt.sp500Hedged] - prevPrices[bmt.sp500Hedged]) / prevPrices[bmt.sp500Hedged]
        : 0,
      sp500Unhedged: (allPrices[bmt.sp500Unhedged] && prevPrices[bmt.sp500Unhedged])
        ? (allPrices[bmt.sp500Unhedged] - prevPrices[bmt.sp500Unhedged]) / prevPrices[bmt.sp500Unhedged]
        : 0,
    };
    const benchmarkReturn = bm.kospi200    * bmR.kospi200
      + bm.sp500Hedged   * bmR.sp500Hedged
      + bm.sp500Unhedged * bmR.sp500Unhedged;

    /* 비용 계산 */
    const leverageCost = (portfolio.borrowedCash / baseCapital) * AppState.get('weeklyBorrowingCost');
    const cashInterest = (portfolio.cash / baseCapital) * AppState.get('weeklyCashInterest');

    /* 순수익률 */
    const activeReturn = portfolioReturn - benchmarkReturn;
    const netReturn    = portfolioReturn - leverageCost + cashInterest;

    /* 누적 수익률 계산 (이전 주 누적 + 현재 주 순수익)
       — 복리 방식: (1 + 전주누적) × (1 + 현주순수익) - 1 */
    const pnlHistory    = AppState.get('weeklyPnL');
    const prevCumReturn = pnlHistory.length > 0
      ? pnlHistory[pnlHistory.length - 1].cumulative_return
      : 0;
    const cumulativeReturn = (1 + prevCumReturn) * (1 + netReturn) - 1;

    /* WeeklyPnL 객체 생성 */
    const pnlEntry = {
      week,
      date:               new Date().toISOString().slice(0, 10),
      portfolio_return:   portfolioReturn,
      benchmark_return:   benchmarkReturn,
      active_return:      activeReturn,
      leverage_cost:      leverageCost,
      cash_interest:      cashInterest,
      net_return:         netReturn,
      cumulative_return:  cumulativeReturn,
      contribution_by_etf: contribution,
    };

    /* 서버에 저장 시도 (allPrices 전송: 벤치마크 가격 포함)
       — prices 대신 allPrices를 쓰는 이유: 벤치마크 가격도 서버 캐시에 남겨
         다음 주 기준가 조회 시 활용할 수 있도록 하기 위함 */
    await _saveToServer(pnlEntry, allPrices);

    /* AppState 업데이트 (기존 같은 week 항목 교체) */
    const newHistory = pnlHistory.filter(p => p.week !== week);
    newHistory.push(pnlEntry);
    newHistory.sort((a, b) => a.week - b.week);
    AppState.set('weeklyPnL', newHistory);

    /* allPrices를 다음 주를 위해 캐시
       — prices 대신 allPrices: 벤치마크 가격도 다음 주 기준가로 사용 */
    _savePriceCache(week, allPrices);

    console.log(
      `[WeeklyPnL] Week ${week} P&L 업데이트: ` +
      `포트폴리오 ${AppState.formatReturn(portfolioReturn)}, ` +
      `벤치마크 ${AppState.formatReturn(benchmarkReturn)}, ` +
      `α ${AppState.formatReturn(activeReturn)}`
    );
  }

  /* ══════════════════════════════════════════════════════════
     이전 주 가격 조회
     직전 주의 종가를 기준 가격으로 사용합니다.
     — localStorage에 저장된 이유: 새로고침해도 이전 주 가격이 유지되어야
       수익률 계산이 가능하기 때문
  ══════════════════════════════════════════════════════════ */
  function _getPreviousPrices(currentWeek) {
    try {
      const cached = localStorage.getItem(`markov_prices_week_${currentWeek - 1}`);
      if (cached) return JSON.parse(cached);
    } catch (e) { /* localStorage 접근 불가 시 무시 */ }
    return {};
  }

  /* 현재 주 가격을 localStorage에 저장
     — allPrices를 저장하는 이유: 벤치마크 가격도 다음 주 기준가로 사용하기 위함 */
  function _savePriceCache(week, prices) {
    try {
      localStorage.setItem(`markov_prices_week_${week}`, JSON.stringify(prices));
    } catch (e) { /* 저장 실패 시 무시 */ }
  }

  /* ══════════════════════════════════════════════════════════
     서버에 P&L 저장
  ══════════════════════════════════════════════════════════ */
  async function _saveToServer(pnlEntry, allPrices) {
    /* 서버 PnLUpdateRequest: { week, date, friday_prices, benchmark_prices }
       frontend가 이미 계산한 결과를 활용하고 allPrices도 함께 전송 */
    const bmt = AppState.get('benchmarkTickers');
    const benchmarkPrices = {};
    [bmt.kospi200, bmt.sp500Hedged, bmt.sp500Unhedged].forEach(t => {
      if (allPrices[t]) benchmarkPrices[t] = allPrices[t];
    });

    try {
      await fetch('/papertrade/pnl/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          week:             pnlEntry.week,
          date:             pnlEntry.date,
          friday_prices:    allPrices,
          benchmark_prices: benchmarkPrices,
        }),
      });
    } catch (err) {
      console.warn('[WeeklyPnL] 서버 저장 실패 (로컬 상태 유지):', err.message);
    }
  }

  /* ══════════════════════════════════════════════════════════
     P&L 테이블 렌더링
  ══════════════════════════════════════════════════════════ */
  function _renderPnLTable(history) {
    const tbody = document.getElementById('pnl-tbody');
    if (!tbody) return;

    if (!history || history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">P&L 데이터가 없습니다.</td></tr>';
      return;
    }

    tbody.innerHTML = history.map(pnl => {
      const portR = AppState.formatReturn(pnl.portfolio_return);
      const bmR   = AppState.formatReturn(pnl.benchmark_return);
      const alphR = AppState.formatReturn(pnl.active_return);
      const levC  = AppState.formatReturn(-pnl.leverage_cost);
      const netR  = AppState.formatReturn(pnl.net_return);
      const cumR  = AppState.formatReturn(pnl.cumulative_return);

      const portClass = pnl.portfolio_return  >= 0 ? 'pnl-positive' : 'pnl-negative';
      const alphClass = pnl.active_return     >= 0 ? 'pnl-positive' : 'pnl-negative';
      const netClass  = pnl.net_return        >= 0 ? 'pnl-positive' : 'pnl-negative';
      const cumClass  = pnl.cumulative_return >= 0 ? 'pnl-positive' : 'pnl-negative';

      return `
        <tr>
          <td>Week ${pnl.week}<div style="font-size:0.72rem;color:var(--text-muted)">${pnl.date}</div></td>
          <td class="${portClass}">${portR}</td>
          <td>${bmR}</td>
          <td class="${alphClass}"><strong>${alphR}</strong></td>
          <td style="color:var(--danger)">${levC}</td>
          <td class="${netClass}">${netR}</td>
          <td class="${cumClass}"><strong>${cumR}</strong></td>
        </tr>
      `;
    }).join('');
  }

  /* ══════════════════════════════════════════════════════════
     누적 수익률 차트 렌더링
     TradingView Lightweight Charts v4.2.0을 사용합니다.

     왜 라인 차트인가:
     - 주간 누적 수익률은 시계열 추세 비교가 핵심
     - 캔들스틱보다 라인이 두 시리즈(포트폴리오 vs 벤치마크)를 비교하기 쉬움

     왜 window._pnlChart로 인스턴스를 보관하는가:
     - P&L 업데이트 때마다 기존 차트를 제거하고 새로 생성해야
       데이터 누적 오류가 없기 때문
  ══════════════════════════════════════════════════════════ */
  function _renderPnLChart(pnlHistory) {
    const container = document.getElementById('pnl-chart-container');
    if (!container) return;

    /* 데이터가 없으면 차트를 제거하고 안내 문구 표시 */
    if (!pnlHistory || pnlHistory.length === 0) {
      if (window._pnlChart) {
        window._pnlChart.remove();
        window._pnlChart = null;
      }
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#8b949e;font-size:0.83rem;">P&L 데이터 없음</div>';
      return;
    }

    /* 기존 차트 인스턴스 제거
       — 같은 컨테이너에 새 차트를 생성하기 전에 반드시 제거해야
         DOM에 중첩 canvas가 쌓이는 문제를 방지할 수 있음 */
    if (window._pnlChart) {
      window._pnlChart.remove();
      window._pnlChart = null;
    }
    /* innerHTML도 초기화하여 안내 문구 div가 남지 않도록 */
    container.innerHTML = '';

    /* TradingView Lightweight Charts v4.2.0 차트 생성
       — 앱 배경색(#0d1117)과 일치시켜 카드 내에서 자연스럽게 보이도록 */
    const chart = LightweightCharts.createChart(container, {
      width:  container.clientWidth,
      height: 250,
      layout: {
        background: { color: '#0d1117' },
        textColor:  '#8b949e',
      },
      grid: {
        vertLines: { color: '#21262d' },
        horzLines: { color: '#21262d' },
      },
      timeScale: {
        borderColor: '#30363d',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: '#30363d',
      },
    });
    window._pnlChart = chart;

    /* 포트폴리오 누적 수익률 라인 (파란색: 주 색상) */
    const portfolioLine = chart.addLineSeries({
      color:     '#388bfd',
      lineWidth: 2,
      title:     '포트폴리오',
    });

    /* 벤치마크 누적 수익률 라인 (회색 점선: 비교 기준)
       — lineStyle 1 = Dotted, 점선으로 구분하는 이유:
         포트폴리오 라인과 겹칠 때도 시각적으로 구분되어야 하기 때문 */
    const benchmarkLine = chart.addLineSeries({
      color:     '#8b949e',
      lineWidth: 2,
      lineStyle: 1,
      title:     '벤치마크',
    });

    /* 데이터 변환: week별 누적 수익률 → 차트 데이터 포인트
       - time: Unix timestamp (초 단위) — LightweightCharts 요구 형식
       - value: % 단위 변환 (0.05 → 5.00)
       - 벤치마크 누적은 별도로 복리 계산 (pnl에 저장된 benchmark_return 활용) */
    const portfolioData = [];
    const benchmarkData = [];
    let benchmarkCumReturn = 0; /* 벤치마크 누적은 저장되지 않아 여기서 직접 계산 */

    pnlHistory.forEach(p => {
      /* date 필드가 있으면 사용, 없으면 week 번호로 임의 날짜 생성
         — 실제 날짜가 있으면 타임스케일에 정확한 날짜가 표시됨 */
      const dateStr = p.date
        ? p.date
        : `2025-01-${String(Math.min(p.week * 7, 28)).padStart(2, '0')}`;
      const time = Math.floor(new Date(dateStr).getTime() / 1000);

      /* 벤치마크 누적 수익률 복리 계산
         — benchmark_return은 해당 주 수익률이므로 누적 복리로 합산 */
      benchmarkCumReturn = (1 + benchmarkCumReturn) * (1 + (p.benchmark_return || 0)) - 1;

      portfolioData.push({
        time,
        value: parseFloat((p.cumulative_return * 100).toFixed(2)),
      });
      benchmarkData.push({
        time,
        value: parseFloat((benchmarkCumReturn * 100).toFixed(2)),
      });
    });

    /* 차트 데이터 설정 및 전체 범위 fit
       — fitContent()를 호출하는 이유: 주 수가 적을 때도 차트가 꽉 차 보이도록 */
    if (portfolioData.length > 0) {
      portfolioLine.setData(portfolioData);
      benchmarkLine.setData(benchmarkData);
      chart.timeScale().fitContent();
    }

    /* 윈도우 리사이즈 대응
       — 차트 width를 컨테이너 기준으로 재설정하는 이유:
         LightweightCharts는 width를 픽셀 단위로 고정 설정하기 때문에
         창 크기가 바뀌면 수동으로 다시 계산해야 함 */
    window.removeEventListener('resize', _onPnLChartResize);
    window.addEventListener('resize', _onPnLChartResize);
  }

  /* 리사이즈 핸들러를 분리한 이유:
     인라인 화살표 함수를 addEventListener에 넘기면 removeEventListener로
     제거할 수 없어 매번 핸들러가 중복 등록되기 때문 */
  function _onPnLChartResize() {
    const container = document.getElementById('pnl-chart-container');
    if (window._pnlChart && container) {
      window._pnlChart.applyOptions({ width: container.clientWidth });
    }
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return { init };
})();
