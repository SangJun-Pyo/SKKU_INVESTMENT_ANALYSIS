# MarkovPortfolio V4 — 6-week PaperTrade 과제용 전체 기획서

> **이 문서를 읽는 AI 에이전트에게**: 기존 `Markov Trade V3`는 선물/주식/코인 트레이더를 위한 개인용 단기 트레이딩 분석 도구였다.  
> 이 V4 문서는 이를 투자분석관리 수업의 **6-week PaperTrade 전용 ETF 포트폴리오 운용 시스템**으로 피벗하기 위한 기준 문서다.  
> 기존 V3의 핵심 개선 방향인 `Unified State Flow`, `AI Context 자동 주입`, `Trade Planner 자동 연결`은 유지하되, LONG/SHORT 단타 중심 구조를 **Weekly ETF Allocation + Risk Management Dashboard**로 전환한다.

---

## 0. 피벗 요약

### 기존 Markov Trade V3

**목적**: 선물/주식/코인 트레이더가 단기 진입 여부, 손절가, 목표가, 포지션 크기를 판단하는 개인용 트레이딩 툴

```text
종목 선택 → 차트 로드 → 3-TF 분석 → LONG/SHORT 신호 → Trade Planner → AI 어시스턴트 → 매매 일지
```

### 과제용 MarkovPortfolio V4

**목적**: 6주 PaperTrade 프로젝트에서 CIO가 매주 금요일 종가 기준으로 ETF 포트폴리오를 운용하고, 변동성·레버리지·손절 규칙을 정량적으로 관리하는 의사결정 지원 툴

```text
ETF Universe 선택
  → 주간 데이터 로드
  → ETF별 Weekly Signal Score 계산
  → Portfolio Risk Budget 점검
  → 금요일 종가 기준 주문 생성
  → Risk/Orders Report 자동 작성
  → Weekly P/L 및 벤치마크 대비 성과 기록
```

---

## 1. 앱 개요

**MarkovPortfolio V4** — 투자분석관리 수업의 6-week PaperTrade를 위한 주간 ETF 포트폴리오 운용·리스크 관리 도구.

### 핵심 컨셉

> **Core 100억은 수업 벤치마크를 복제하고,  
> 허용 레버리지 30억은 정량 점수 기반 Tactical Alpha에 배분한다.**

### 기본 운용 구조

| 구분 | 금액 | 역할 |
|---|---:|---|
| KOSPI200 Core | 40억 | 과제 벤치마크 40% 복제 |
| S&P500 Hedged Core | 30억 | 과제 벤치마크 30% 복제 |
| S&P500 Unhedged Core | 30억 | 과제 벤치마크 30% 복제 + 달러 노출 |
| Growth/Tech Alpha | 10~20억 | Nasdaq/AI/반도체 등 초과수익 |
| Currency/Sector Tactical | 5~10억 | 달러/금/방산/에너지 등 방어·전술 |
| Pullback Reserve | 0~5억 | 눌림목 추가 진입 대기 |
| **총 익스포저** | **최대 130억** | Cash borrowing 최대 30% 활용 |

### 수업 제약조건 반영

| 제약 | V4 반영 방식 |
|---|---|
| 매매는 금요일 종가 기준 | `Friday Close Order Mode` 고정 |
| ETF 개수 10개 미만 | Universe 선택 시 최대 9개 제한 |
| 현금 이자 주간 0.035% | Cash Interest 계산 모듈 |
| 차입 이자 주간 0.07% | Leverage Cost 계산 모듈 |
| Cash Borrowing 최대 30% | Exposure Guardrail: 130억 상한 |
| ETF Borrowing 최대 30% | Short ETF Exposure Guardrail 별도 관리 |
| 변동성 크면 감점 가능 | Volatility Target / VaR / MDD Trigger 추가 |
| Futures/Options 가능하나 단순화 | V4 1차 구현은 ETF 중심, 파생은 후순위 |

---

## 2. V4 핵심 사용 흐름

### 2-1. CIO Weekly Workflow

```text
월요일
  → 지난주 P/L 확인
  → 벤치마크 대비 성과 확인
  → 리스크 룰 위반 여부 점검

화~목요일
  → ETF별 추세/변동성/눌림목 점수 업데이트
  → Research 의견 반영
  → CRO와 리스크 한도 협의

금요일 3pm 전
  → Risk Management Rules 확인
  → Orders Report 생성
  → 팀 동의 후 주문 확정

금요일 종가
  → Paper Trade 체결가 입력 또는 자동 반영
  → 포트폴리오 스냅샷 저장
```

### 2-2. 화면 흐름

```text
Dashboard
  → ETF Universe
  → Weekly Allocation
  → Risk Budget
  → Orders Report
  → Weekly P/L
  → AI Investment Committee
  → Journal / History
```

---

## 3. V4 주요 기능

## 3-1. ETF Universe Manager

### 목적
과제에서 투자할 ETF 후보군을 10개 미만으로 관리한다.

### 기본 카테고리

| 카테고리 | 예시 역할 |
|---|---|
| Core Korea | KOSPI200 ETF |
| Core US Hedged | S&P500 환헤지 ETF |
| Core US Unhedged | S&P500 환노출 ETF |
| Growth / Tech | Nasdaq100, AI, 반도체 ETF |
| Korea Alpha | KOSDAQ150, 국내 반도체, 밸류업 ETF |
| Currency | USD ETF, 달러선물 ETF |
| Defensive | Gold, Bond, Short-term bond ETF |
| Sector Tactical | 방산, 에너지, 금융, 원자재 ETF |
| Short / Inverse | KOSPI200 inverse 등 제한적 활용 |

### 기능 요구사항
- ETF 후보는 최대 9개까지만 활성화 가능
- 각 ETF에 `Core / Alpha / Hedge / Tactical / Short` 태그 부여
- 각 ETF에 `Hedged / Unhedged / KRW / USD exposure` 메타데이터 부여
- 단일 종목 주식, 개별 주식 선물, 개별 주식 옵션은 Universe에서 제외

---

## 3-2. Weekly Signal Score

### 목적
기존 LONG/SHORT 단타 신호를 ETF별 주간 편입 점수로 전환한다.

### 점수 구조

| 항목 | 배점 | 설명 |
|---|---:|---|
| Trend Score | 25 | 20일/60일 이동평균, 추세 유지 여부 |
| Pullback Score | 20 | 상승 추세 내 눌림목 여부 |
| Volatility Score | 20 | 최근 변동성이 목표 범위 이내인지 |
| Momentum Score | 15 | RSI, 4주 수익률, 상대강도 |
| Drawdown Risk Score | 10 | 최근 고점 대비 낙폭 및 회복 여부 |
| Correlation Score | 10 | 기존 포트폴리오와의 상관관계 분산 효과 |
| **Total** | **100** | 편입/증액/축소 판단 기준 |

### Action Rule

| Total Score | Action | 설명 |
|---:|---|---|
| 80 이상 | Increase | 신규 편입 또는 증액 가능 |
| 65~79 | Hold / Small Buy | 기존 보유 유지, 소액 편입 가능 |
| 50~64 | Hold / Watch | 관망 |
| 35~49 | Reduce | 비중 축소 검토 |
| 35 미만 | Exit / No Buy | 신규 매수 금지 또는 청산 |

---

## 3-3. Pullback Entry Rule

### 목적
“눌림목을 기다렸다가 진입했다”를 감이 아니라 규칙으로 설명한다.

```text
Alpha 포지션은 다음 조건을 만족할 때만 신규 진입 또는 증액한다.

1. 가격이 20일선 또는 60일선 위에 있어 중기 상승 추세가 유지될 것
2. 최근 고점 대비 -2%~-5% 조정을 받았을 것
3. RSI가 40~60 구간으로 식었을 것
4. Bollinger Band Z-score가 -0.5~-2.0 사이일 것
5. 주간 변동성이 포트폴리오 한도 이내일 것
6. Markov Regime이 Risk-On 또는 Neutral일 것
```

### 금요일 주문 반영
- 목요일 종가까지 조건을 관찰
- 금요일 3pm 전 Orders Report 작성
- 금요일 종가 기준 체결가로 Paper Trade 기록

---

## 3-4. Markov Regime Classifier

### 목적
ETF별 시장 국면을 3단계로 분류하여 CIO 의사결정에 반영한다.

| Regime | 조건 예시 | Action |
|---|---|---|
| Risk-On | 상승 추세 + 낮은 변동성 + 양호한 모멘텀 | Core 유지, Alpha 증액 가능 |
| Neutral | 방향성 약함 + 변동성 정상 | Core 유지, Alpha 소액 조정 |
| Risk-Off | 하락 추세 + 변동성 확대 + 손실 위험 증가 | 레버리지 축소, Hedge 확대 |

### 기존 V3와의 차이
- 기존 `range / transition / trend`는 단기 매매용 레짐
- V4는 포트폴리오용 `Risk-On / Neutral / Risk-Off`로 전환
- 기존 BB/RSI 계산 함수는 재사용하되, 판단 기준은 주간 ETF 운용에 맞게 변경

---

## 3-5. Portfolio Risk Budget

### 목적
교수님이 우려하는 “과도한 변동성”을 방지하고, 레버리지를 사용해도 리스크 관리가 있었다고 설명할 수 있게 한다.

### 핵심 지표

| 지표 | 목표/한도 예시 | 의미 |
|---|---:|---|
| Total Exposure | ≤ 130억 | 차입 포함 총 투자금 |
| Leverage | ≤ 30% | Cash borrowing 한도 |
| Short ETF Exposure | ≤ 30% | ETF borrowing 한도 |
| ETF Count | < 10 | 과제 제한 준수 |
| Expected Weekly Volatility | ≤ 1.5% | 포트폴리오 주간 변동성 목표 |
| 95% VaR | ≤ -2.0억 | 1주 예상 최대 손실 관리 |
| Max Drawdown Trigger | -3.0% | 누적 손실 시 알파 축소 |
| Benchmark Beta | 0.9~1.2 | 벤치마크 대비 민감도 |
| Single ETF Weight | ≤ 40억 | 단일 ETF 집중 방지 |
| Alpha Risk Contribution | ≤ 40% | 알파 포지션 위험 기여 제한 |

---

## 3-6. Risk Management Rules Generator

### 목적
첫 번째 금요일 3pm 제출용 Risk Management Rules를 자동 작성한다.

### 자동 생성 항목

| 항목 | 기본값 예시 |
|---|---|
| 개별 ETF 손절 | 매수가 대비 -5% 하락 시 전량 청산 |
| 개별 ETF 1차 축소 | 매수가 대비 -3% 하락 시 50% 축소 |
| Alpha 포지션 손절 | 주간 Signal Score 50 미만이면 축소 |
| 레버리지 축소 | 주간 손실 -1.5% 초과 시 레버리지 절반 축소 |
| 포트폴리오 방어 전환 | 누적 손실 -3% 초과 시 Core 중심 복귀 |
| 익절 | +5% 수익 또는 Score 하락 시 일부 익절 |
| 신규 주문 제한 | 전주 목요일 거래량의 25% 이하 |
| ETF Borrowing | 전체 자산의 30% 이내 |
| Cash Borrowing | 전체 자산의 30% 이내 |

---

## 3-7. Weekly Orders Report Builder

### 목적
매주 금요일 제출하는 `(Strategy &) Orders Report`를 자동 작성한다.

### 보고서 구성

```text
1. Market Background
   - 이번 주 핵심 시장 이슈
   - KOSPI200 / S&P500 / KRW-USD 흐름
   - 금리, 환율, 원자재, 섹터 이슈

2. Strategy
   - Core 100억: 벤치마크 복제
   - Alpha 30억: Markov Score 기반 전술 배분
   - 이번 주 증액/축소 사유

3. Risk Check
   - Exposure / Leverage / ETF Count
   - Weekly Volatility / VaR / Benchmark Beta
   - Risk Rule 위반 여부

4. Orders
   - Buy / Sell / Hold
   - ETF명, 금액, 목표 비중, 체결 기준
   - 금요일 종가 체결 원칙

5. Conclusion
   - 다음 주 관찰 포인트
   - 손절/익절 트리거
```

---

## 3-8. Weekly P/L & Benchmark Tracker

### 목적
월요일 Weekly P/L Report와 최종 발표용 성과 분석을 지원한다.

### 계산 항목

| 항목 | 설명 |
|---|---|
| Portfolio Return | 포트폴리오 주간/누적 수익률 |
| Benchmark Return | 40% KOSPI200 + 30% S&P500 Hedged + 30% S&P500 Unhedged |
| Active Return | Portfolio - Benchmark |
| Leverage Cost | 차입금 × 0.07% per week |
| Cash Interest | 현금 × 0.035% per week |
| Contribution by ETF | ETF별 수익 기여도 |
| Risk Contribution | ETF별 변동성 기여도 |
| Max Drawdown | 6주 내 최대 낙폭 |
| Tracking Error | 벤치마크 대비 변동성 |
| Information Ratio | Active Return / Tracking Error |

---

## 3-9. AI Investment Committee

### 목적
기존 AI 어시스턴트를 단타 코멘트가 아니라 투자위원회 보조 역할로 전환한다.

### AI 역할

| 역할 | 설명 |
|---|---|
| CIO Assistant | 이번 주 포트폴리오 비중 조정 제안 |
| CRO Checker | 리스크 룰 위반 여부 점검 |
| Research Summarizer | ETF별 시장 근거 정리 |
| Report Writer | Orders Report / P&L Report 문장 초안 생성 |

### AI 컨텍스트 자동 주입

```json
{
  "project": "6-week PaperTrade",
  "role": "CIO",
  "benchmark": {
    "kospi200": 0.40,
    "sp500_hedged": 0.30,
    "sp500_unhedged": 0.30
  },
  "portfolio": {
    "capital": 10000000000,
    "max_exposure": 13000000000,
    "positions": []
  },
  "risk": {
    "weekly_volatility": 0.012,
    "var_95": -180000000,
    "leverage": 0.25,
    "etf_count": 7
  },
  "orders": [],
  "weekly_signal_scores": []
}
```

---

## 4. 데이터 모델

## 4-1. Portfolio State

```javascript
window.AppState = {
  mode: 'papertrade',
  week: 1,
  capitalBase: 10000000000,
  maxBorrowingRatio: 0.30,
  maxExposure: 13000000000,
  benchmark: {
    kospi200: 0.40,
    sp500Hedged: 0.30,
    sp500Unhedged: 0.30,
  },
  universe: [],
  prices: {},
  signalScores: {},
  portfolio: {
    cash: 0,
    borrowedCash: 0,
    totalExposure: 0,
    positions: [],
  },
  riskReport: null,
  orders: [],
  weeklyPnL: [],
  aiContext: null,
};
```

## 4-2. ETF Position

```json
{
  "ticker": "069500.KS",
  "name": "KODEX 200",
  "asset_class": "Core Korea",
  "role": "Core",
  "currency_exposure": "KRW",
  "target_amount": 4000000000,
  "target_weight": 0.3077,
  "entry_price": 0,
  "current_price": 0,
  "quantity": 0,
  "stop_loss_pct": -0.05,
  "take_profit_pct": 0.05,
  "signal_score": 68,
  "regime": "Neutral"
}
```

## 4-3. Weekly Order

```json
{
  "week": 1,
  "date": "2026-xx-xx",
  "ticker": "379800.KS",
  "name": "KODEX 미국S&P500TR",
  "action": "BUY",
  "order_type": "Friday Close",
  "amount": 3000000000,
  "target_weight": 0.2308,
  "reason": "Core S&P500 unhedged benchmark exposure",
  "risk_check": "OK"
}
```

---

## 5. 기존 V3 기능 중 유지/변경/제거

| 기존 기능 | V4 처리 | 이유 |
|---|---|---|
| 캔들 차트 + RSI | 유지 | ETF별 기술적 점검에 사용 |
| 3-TF 분석 | 변경 | 5m/1h/1d → 1D/1W/4W 중심으로 변경 |
| LONG/SHORT 버튼 | 변경 | Buy / Reduce / Hold / Hedge로 변경 |
| Trade Planner | 변경 | 개별 포지션 크기 → 포트폴리오 배분 계산 |
| Monte Carlo | 유지/변경 | 단일 트레이드 TP/SL → 6주 포트폴리오 경로 시뮬레이션 |
| AI Assistant | 유지/변경 | 단타 코멘트 → 투자위원회/보고서 작성 보조 |
| Journal | 변경 | 매매일지 → Weekly Decision Log |
| Analytics | 변경 | R-multiple 중심 → 벤치마크 대비 성과 중심 |
| Crypto/Futures 단타 | 비활성화 | 과제 목적과 다름 |

---

## 6. V4 우선순위 로드맵

| 순위 | 기능 | 난이도 | 설명 |
|---:|---|---|---|
| 1 | PaperTrade Mode 전환 | 중 | 앱 제목/메뉴/흐름을 과제용으로 변경 |
| 2 | ETF Universe Manager | 중 | 10개 미만 ETF 후보 관리 |
| 3 | Weekly Signal Score | 중 | ETF별 점수와 Action 생성 |
| 4 | Portfolio Allocation Engine | 중상 | 100억 Core + 30억 Alpha 배분 계산 |
| 5 | Risk Budget Dashboard | 중상 | 변동성, VaR, 레버리지, ETF 개수 제한 점검 |
| 6 | Orders Report Builder | 중 | 금요일 제출용 보고서 자동 생성 |
| 7 | Weekly P/L Tracker | 중상 | 월요일 P/L 및 벤치마크 대비 성과 추적 |
| 8 | AI Investment Committee | 중 | AI 컨텍스트를 포트폴리오 기준으로 전환 |
| 9 | 6-week Monte Carlo | 상 | 6주 포트폴리오 경로 시뮬레이션 |

---

## 7. 최종 발표 스토리라인

```text
Our team used MarkovPortfolio, a weekly ETF allocation and risk management system.

The base 100 billion KRW portfolio replicated the class benchmark:
40% KOSPI200, 30% S&P500 hedged, and 30% S&P500 unhedged.

The additional 30 billion KRW leverage was not used for speculative trading.
It was allocated only to ETFs with strong weekly signal scores and acceptable risk contribution.

We used trend, pullback, volatility, RSI, Bollinger Band Z-score, VaR, and Markov regime classification
in order to control portfolio volatility and follow pre-defined stop-loss rules.

All trades were executed only at Friday closing prices.
```

---

## 8. 중요한 기술 제약사항

### 프론트엔드
- TradingView Lightweight Charts는 `@4.2.0` 고정
- 바닐라 JS + CDN 구조 유지
- npm/번들러 사용 금지
- 모든 신규 코드에는 한국어 주석 작성
- 금요일 종가 주문 모드가 기본값

### 백엔드
- yfinance 1.2.0+ MultiIndex 컬럼 처리 유지
- Pydantic v2 기준 `.model_dump()` 사용
- `/journal` 배열 직접 반환 규칙 유지 또는 `/decisions` 신규 API와 명확히 분리
- 기존 단타 API를 삭제하지 말고 `mode='papertrade'`에서 비활성화하는 방향 권장

---

## 9. V4 핵심 원칙

1. **수익률보다 설명 가능한 리스크 관리가 우선**
2. **Core는 벤치마크 복제, Alpha는 제한적으로만 사용**
3. **레버리지는 최대 30% 가능하지만 점수와 리스크 한도 통과 시에만 사용**
4. **눌림목 진입은 정량 조건으로만 인정**
5. **모든 매매는 금요일 종가 기준으로 기록**
6. **ETF 수는 항상 10개 미만 유지**
7. **보고서 자동화가 최종 과제 평가에 직접 연결되도록 설계**
