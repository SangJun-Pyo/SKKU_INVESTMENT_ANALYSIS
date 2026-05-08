# MarkovPortfolio V4 — 과제용 아키텍처 상세 문서

> 이 문서는 기존 Markov Trade V3 아키텍처를 기반으로, 6-week PaperTrade 과제용 MarkovPortfolio V4를 구현하기 위한 개발 레퍼런스다.

---

## 1. 아키텍처 전환 개요

### V3 구조

```text
Chart / Signal / Trade Planner / AI / Journal / Analytics
```

### V4 구조

```text
ETF Universe / Weekly Score / Allocation / Risk Budget / Orders Report / Weekly P&L / AI Committee
```

### 핵심 변경점

| 영역 | V3 | V4 |
|---|---|---|
| 사용자 | 단기 트레이더 | 투자분석관리 수업 팀 / CIO |
| 자산 | 선물, 주식, 코인 | ETF 중심 |
| 의사결정 | LONG/SHORT 진입 | Buy / Reduce / Hold / Hedge |
| 시간 단위 | 5m, 1h, 1d | 주간 의사결정, 금요일 종가 |
| 리스크 | 개별 트레이드 R:R | 포트폴리오 변동성, VaR, 레버리지 |
| 성과 | R-multiple, 승률 | 벤치마크 대비 Active Return |
| 기록 | 매매일지 | Weekly Decision Log + Orders Report |

---

## 2. 백엔드 레이어 구조

기존 단방향 의존 구조는 유지한다.

```text
config.py
   ↓
models.py
   ↓
repository_*.py
   ↓
service_*.py
   ↓
schemas.py
   ↓
api_routes.py
   ↓
main.py
```

### V4 신규/확장 파일 제안

```text
backend
├── service_portfolio.py          ← 포트폴리오 배분, 익스포저, 레버리지 계산
├── service_risk_budget.py        ← 변동성, VaR, MDD, Beta, Risk Contribution 계산
├── service_weekly_score.py       ← ETF별 Weekly Signal Score 계산
├── service_benchmark.py          ← 수업 벤치마크 수익률 계산
├── service_report.py             ← Risk Rules / Orders / P&L 보고서 생성
├── repository_papertrade.py      ← 주간 포트폴리오 스냅샷, 주문, 의사결정 저장
└── prompts/
    ├── portfolio_committee_prompt.py
    └── report_writer_prompt.py
```

---

## 3. 데이터 모델

## 3-1. models.py 확장

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class ETFMeta(BaseModel):
    # 왜 필요한가: ETF별 역할과 환노출을 알아야 Core/Alpha/Risk 구분이 가능하다.
    ticker: str
    name: str
    asset_class: str
    role: Literal['Core', 'Alpha', 'Hedge', 'Tactical', 'Short']
    currency_exposure: Literal['KRW', 'USD', 'Hedged', 'Unhedged']
    enabled: bool = True

class WeeklySignalScore(BaseModel):
    # 왜 필요한가: 단타 신호 대신 주간 포트폴리오 편입 우선순위를 계산한다.
    ticker: str
    week: int
    trend_score: float
    pullback_score: float
    volatility_score: float
    momentum_score: float
    drawdown_score: float
    correlation_score: float
    total_score: float
    regime: Literal['Risk-On', 'Neutral', 'Risk-Off']
    action: Literal['Increase', 'Small Buy', 'Hold', 'Reduce', 'Exit', 'No Buy']
    reason: str

class PortfolioPosition(BaseModel):
    ticker: str
    name: str
    role: str
    target_amount: float
    target_weight: float
    quantity: Optional[float] = None
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.05
    signal_score: Optional[float] = None
    regime: Optional[str] = None

class PortfolioSnapshot(BaseModel):
    week: int
    date: str
    base_capital: float = 10_000_000_000
    borrowed_cash: float = 0
    cash: float = 0
    total_exposure: float = 0
    positions: list[PortfolioPosition] = Field(default_factory=list)

class RiskBudgetReport(BaseModel):
    week: int
    total_exposure: float
    leverage_ratio: float
    short_exposure_ratio: float
    etf_count: int
    expected_weekly_volatility: float
    var_95: float
    max_drawdown: float
    benchmark_beta: float
    tracking_error: Optional[float] = None
    information_ratio: Optional[float] = None
    violations: list[str] = Field(default_factory=list)

class WeeklyOrder(BaseModel):
    week: int
    date: str
    ticker: str
    name: str
    action: Literal['BUY', 'SELL', 'HOLD', 'REDUCE', 'SHORT', 'COVER']
    order_type: Literal['Friday Close'] = 'Friday Close'
    amount: float
    target_weight: float
    reason: str
    risk_check: Literal['OK', 'WARN', 'BLOCK']

class WeeklyPnL(BaseModel):
    week: int
    portfolio_return: float
    benchmark_return: float
    active_return: float
    leverage_cost: float
    cash_interest: float
    contribution_by_etf: dict[str, float]
```

---

## 4. API 설계

## 4-1. 기존 API 유지

기존 `/price`, `/price/{ticker}/ohlcv`, `/chat`, `/journal`, `/simulate`는 유지한다.  
단, V4에서는 `/journal`을 직접 사용하기보다 과제용 `/papertrade/*` API를 별도로 추가하는 것을 권장한다.

## 4-2. 신규 API

```text
GET  /papertrade/universe
POST /papertrade/universe
GET  /papertrade/score?week=1
POST /papertrade/score/run
POST /papertrade/allocation/suggest
POST /papertrade/risk/check
POST /papertrade/orders/generate
POST /papertrade/orders/confirm
GET  /papertrade/pnl?week=1
POST /papertrade/pnl/update
POST /papertrade/report/risk-rules
POST /papertrade/report/orders
POST /papertrade/report/weekly-pnl
```

### API 역할

| API | 역할 |
|---|---|
| `/papertrade/universe` | 과제용 ETF 후보군 관리 |
| `/papertrade/score/run` | ETF별 Weekly Signal Score 계산 |
| `/papertrade/allocation/suggest` | Core 100억 + Alpha 30억 배분 제안 |
| `/papertrade/risk/check` | 레버리지, VaR, ETF 개수, 변동성 한도 검증 |
| `/papertrade/orders/generate` | 금요일 종가 기준 주문안 생성 |
| `/papertrade/orders/confirm` | 팀 동의 후 주문 확정 및 스냅샷 저장 |
| `/papertrade/pnl/update` | 월요일 P/L 업데이트 |
| `/papertrade/report/*` | 제출용 보고서 텍스트 생성 |

---

## 5. 프론트엔드 모듈 구조

## 5-1. 신규 파일 구조

```text
frontend/
├── index.html
├── style.css
├── app.js
├── modules/
│   ├── appState.js                 ← V4 AppState 중앙 관리
│   ├── chart.js                    ← 기존 유지
│   ├── etfUniverse.js              ← ETF 후보군 관리
│   ├── weeklyScore.js              ← ETF별 점수 테이블
│   ├── allocationEngine.js         ← 목표 비중/금액 계산
│   ├── riskBudget.js               ← 리스크 대시보드
│   ├── ordersReport.js             ← 주문 보고서 UI
│   ├── weeklyPnL.js                 ← P/L 및 벤치마크 성과
│   ├── aiCommittee.js              ← AI 컨텍스트 생성 및 채팅
│   ├── journal.js                  ← 기존 기능 일부 재사용
│   └── analytics.js                ← 벤치마크 성과 중심으로 확장
└── strategies/
    ├── weekly_etf_score_strategy.js ← 신규 핵심 전략
    ├── pullback_entry_strategy.js   ← 눌림목 판단
    ├── regime_classifier.js         ← Risk-On/Neutral/Risk-Off
    └── strategy_engine.js
```

## 5-2. 스크립트 로드 순서

```html
<!-- 1. CDN -->
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>

<!-- 2. 전략 -->
<script src="/static/strategies/regime_classifier.js?v=20260504"></script>
<script src="/static/strategies/pullback_entry_strategy.js?v=20260504"></script>
<script src="/static/strategies/weekly_etf_score_strategy.js?v=20260504"></script>
<script src="/static/strategies/strategy_engine.js?v=20260504"></script>

<!-- 3. 엔진/상태 -->
<script src="/static/modules/appState.js?v=20260504"></script>
<script src="/static/modules/allocationEngine.js?v=20260504"></script>
<script src="/static/modules/riskBudget.js?v=20260504"></script>

<!-- 4. UI 모듈 -->
<script src="/static/modules/chart.js?v=20260504"></script>
<script src="/static/modules/etfUniverse.js?v=20260504"></script>
<script src="/static/modules/weeklyScore.js?v=20260504"></script>
<script src="/static/modules/ordersReport.js?v=20260504"></script>
<script src="/static/modules/weeklyPnL.js?v=20260504"></script>
<script src="/static/modules/aiCommittee.js?v=20260504"></script>
<script src="/static/modules/analytics.js?v=20260504"></script>

<!-- 5. 진입점 -->
<script src="/static/app.js?v=20260504"></script>
```

---

## 6. AppState 설계

```javascript
window.AppState = (() => {
  const state = {
    mode: 'papertrade',
    week: 1,
    role: 'CIO',
    baseCapital: 10000000000,
    maxBorrowingRatio: 0.30,
    weeklyBorrowingCost: 0.0007,
    weeklyCashInterest: 0.00035,
    benchmark: {
      kospi200: 0.40,
      sp500Hedged: 0.30,
      sp500Unhedged: 0.30,
    },
    universe: [],
    prices: {},
    ohlcv: {},
    signalScores: {},
    portfolio: {
      cash: 0,
      borrowedCash: 0,
      totalExposure: 0,
      positions: [],
    },
    riskBudget: null,
    orders: [],
    weeklyPnL: [],
  };

  const listeners = {};

  function set(key, value) {
    // 왜 필요한가: 여러 모듈이 같은 포트폴리오 상태를 공유해야 보고서와 리스크 수치가 일관된다.
    state[key] = value;
    (listeners[key] || []).forEach(fn => fn(value, state));
  }

  function get(key) {
    return key ? state[key] : state;
  }

  function on(key, fn) {
    listeners[key] = listeners[key] || [];
    listeners[key].push(fn);
  }

  return { get, set, on };
})();
```

---

## 7. 핵심 모듈 공개 API

## 7-1. ETFUniverseModule

```javascript
ETFUniverseModule.init()
ETFUniverseModule.addETF(etfMeta)
ETFUniverseModule.removeETF(ticker)
ETFUniverseModule.validateUniverse()
ETFUniverseModule.render()
```

검증 규칙:
- 활성 ETF 수 < 10
- Core ETF 3개 이상 포함 권장
- 단일 종목/코인/단타 선물은 PaperTrade Mode에서 비활성화

## 7-2. WeeklyScoreModule

```javascript
WeeklyScoreModule.runAll()
WeeklyScoreModule.scoreETF(ticker, ohlcv, portfolio)
WeeklyScoreModule.renderScoreTable(scores)
WeeklyScoreModule.getAction(score)
```

점수 계산:
```javascript
const totalScore =
  trendScore * 0.25 +
  pullbackScore * 0.20 +
  volatilityScore * 0.20 +
  momentumScore * 0.15 +
  drawdownScore * 0.10 +
  correlationScore * 0.10;
```

## 7-3. AllocationEngine

```javascript
AllocationEngine.buildBenchmarkCore()
AllocationEngine.allocateAlpha(scores, riskBudget)
AllocationEngine.suggestPortfolio({ coreAmount, alphaAmount, reserveAmount })
AllocationEngine.validateExposure(portfolio)
```

기본 배분:
```javascript
const DEFAULT_CORE = {
  kospi200: 4000000000,
  sp500Hedged: 3000000000,
  sp500Unhedged: 3000000000,
};

const MAX_EXPOSURE = 13000000000;
```

## 7-4. RiskBudgetModule

```javascript
RiskBudgetModule.calculateVolatility(returns)
RiskBudgetModule.calculateVaR(returns, confidence = 0.95)
RiskBudgetModule.calculateBenchmarkBeta(portfolioReturns, benchmarkReturns)
RiskBudgetModule.calculateRiskContribution(positions, covarianceMatrix)
RiskBudgetModule.checkViolations(portfolio, riskMetrics)
RiskBudgetModule.render(report)
```

위반 조건:
```javascript
if (portfolio.totalExposure > 13000000000) violations.push('총 익스포저 130억 초과');
if (portfolio.borrowedCash / 10000000000 > 0.30) violations.push('차입 한도 30% 초과');
if (portfolio.positions.length >= 10) violations.push('ETF 개수 10개 이상');
if (risk.expectedWeeklyVolatility > 0.015) violations.push('주간 변동성 목표 초과');
if (risk.var95 < -200000000) violations.push('95% VaR 한도 초과');
```

## 7-5. OrdersReportModule

```javascript
OrdersReportModule.generateDraft()
OrdersReportModule.renderOrdersTable(orders)
OrdersReportModule.renderNarrative(reportText)
OrdersReportModule.exportMarkdown()
OrdersReportModule.confirmOrders()
```

## 7-6. WeeklyPnLModule

```javascript
WeeklyPnLModule.calculatePortfolioReturn(previousSnapshot, currentPrices)
WeeklyPnLModule.calculateBenchmarkReturn(benchmarkComponents)
WeeklyPnLModule.calculateActiveReturn(portfolioReturn, benchmarkReturn)
WeeklyPnLModule.applyBorrowingCost(borrowedCash)
WeeklyPnLModule.applyCashInterest(cash)
WeeklyPnLModule.renderPnLTable()
```

---

## 8. AI Committee 설계

## 8-1. 시스템 프롬프트 방향

```text
You are the AI Investment Committee assistant for a 6-week PaperTrade project.
The user is the CIO.
You must not recommend high-volatility speculative trades.
Your job is to help the team explain weekly ETF allocation decisions,
check risk-rule violations, and write concise reports for class submission.
All trades are assumed to be executed only at Friday closing prices.
```

## 8-2. AI 컨텍스트 생성

```javascript
AICommittee.buildContext = function () {
  const state = AppState.get();
  return {
    project: '6-week PaperTrade',
    role: state.role,
    week: state.week,
    benchmark: state.benchmark,
    portfolio: state.portfolio,
    riskBudget: state.riskBudget,
    scores: state.signalScores,
    orders: state.orders,
    constraints: {
      maxExposure: 13000000000,
      maxBorrowingRatio: 0.30,
      etfCountLimit: 9,
      execution: 'Friday Close Only',
    },
  };
};
```

---

## 9. 저장소 구조

## 9-1. repository_papertrade.py

```python
class PaperTradeRepository:
    def get_universe(self) -> list[ETFMeta]: ...
    def save_universe(self, universe: list[ETFMeta]) -> None: ...
    def get_snapshots(self) -> list[PortfolioSnapshot]: ...
    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None: ...
    def get_orders(self, week: int | None = None) -> list[WeeklyOrder]: ...
    def save_orders(self, orders: list[WeeklyOrder]) -> None: ...
    def get_pnl(self) -> list[WeeklyPnL]: ...
    def save_pnl(self, pnl: WeeklyPnL) -> None: ...
```

### 파일 저장 예시

```text
data/
├── trading_journal.json         ← 기존 단타 일지
├── papertrade_universe.json     ← ETF 후보군
├── papertrade_snapshots.json    ← 주간 포트폴리오 스냅샷
├── papertrade_orders.json       ← 금요일 주문 기록
└── papertrade_pnl.json          ← 월요일 P/L 기록
```

---

## 10. 구현 우선순위

### Phase 1 — 과제용 UI 골격
- 앱 이름을 `MarkovPortfolio V4`로 변경
- 메뉴를 `Weekly Allocation / Risk Budget / Orders Report / Weekly P&L / AI Committee`로 변경
- 기존 LONG/SHORT 버튼 숨김 또는 PaperTrade Mode에서 비활성화

### Phase 2 — ETF Universe + Weekly Score
- ETF Universe Manager 구현
- 10개 미만 제한 검증
- Weekly Signal Score 계산 및 테이블 표시

### Phase 3 — Allocation + Risk Budget
- Core 100억 자동 구성
- Alpha 30억 점수 기반 배분
- Exposure / Leverage / VaR / Volatility 검증

### Phase 4 — Reports
- Risk Management Rules 생성
- Orders Report 생성
- Weekly P/L Report 생성

### Phase 5 — AI Committee
- AI 프롬프트 전환
- 포트폴리오 컨텍스트 자동 주입
- 보고서 문장 초안 생성

---

## 11. 호환성 주의사항

- TradingView Lightweight Charts `@4.2.0` 고정
- Pydantic v2 `.model_dump()` 사용
- yfinance MultiIndex 컬럼 처리 유지
- 기존 `/journal` API는 깨지지 않게 유지
- 새 과제용 데이터는 `/papertrade/*`로 분리
- 기존 MarkovTrade 단타 모드는 삭제하지 말고 `mode`로 분기
- 모든 신규 코드 주석은 한국어로 작성
