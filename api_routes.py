"""
api_routes.py — MarkovPortfolio V4 API 라우터

과제용 /papertrade/* 엔드포인트와 공통 엔드포인트(chat, price, health)를 제공합니다.
모든 비즈니스 로직은 service_*.py에서 처리하고 여기서는 입출력만 담당합니다.
HTTPException 메시지는 한국어로 작성하여 프론트엔드에 바로 표시 가능합니다.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pathlib import Path
from typing import Optional

# 스키마 import
from schemas import (
    ETFAddRequest,
    ETFUniverseResponse,
    ScoreRunRequest,
    ScoreResponse,
    AllocationSuggestRequest,
    AllocationSuggestResponse,
    RiskCheckRequest,
    RiskCheckResponse,
    OrdersGenerateRequest,
    OrdersConfirmRequest,
    OrdersResponse,
    PnLUpdateRequest,
    PnLResponse,
    ReportRiskRulesRequest,
    ReportOrdersRequest,
    ReportWeeklyPnLRequest,
    ReportResponse,
    ChatRequest,
    ChatResponse,
)

# 도메인 모델 import
from models import (
    ETFMeta,
    WeeklySignalScore,
    PortfolioPosition,
    PortfolioSnapshot,
    WeeklyOrder,
)

# 저장소 import
from repository_papertrade import repo

# 서비스 import
from service_market import get_ohlcv, get_current_price, get_thursday_volume, VALID_TICKERS
from service_portfolio import suggest_portfolio, build_portfolio_snapshot
from service_risk_budget import check_violations
from service_weekly_score import score_all
from service_benchmark import get_benchmark_return, build_weekly_pnl, BENCHMARK_TICKERS
from service_report import generate_risk_rules, generate_orders_report, generate_weekly_pnl_report
from service_ai import chat as ai_chat
from config import BASE_CAPITAL

router = APIRouter()


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────

def _sum_buy(orders: list[WeeklyOrder]) -> float:
    """매수 주문 금액 합산"""
    buy_actions = {"BUY", "SHORT"}
    return sum(o.amount for o in orders if o.action in buy_actions)


def _sum_sell(orders: list[WeeklyOrder]) -> float:
    """매도 주문 금액 합산"""
    sell_actions = {"SELL", "REDUCE", "COVER"}
    return sum(o.amount for o in orders if o.action in sell_actions)


def _build_orders_response(orders: list[WeeklyOrder], week: int) -> OrdersResponse:
    """OrdersResponse 생성 헬퍼"""
    return OrdersResponse(
        orders=orders,
        week=week,
        total_buy_amount=_sum_buy(orders),
        total_sell_amount=_sum_sell(orders),
    )


# ── SPA / Health ──────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    """프론트엔드 index.html 서빙"""
    index_path = Path(__file__).parent / "frontend" / "index.html"
    if index_path.exists():
        return HTMLResponse(
            content=index_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="ko">
    <head><meta charset="UTF-8"><title>MarkovPortfolio V4</title></head>
    <body>
        <h1>MarkovPortfolio V4</h1>
        <p>서버 실행 중. <a href="/docs">API 문서</a></p>
    </body>
    </html>
    """)


@router.get("/health")
async def health_check():
    """서버 상태 확인"""
    return {"status": "ok", "version": "4.0.0"}


# ── 가격 데이터 ───────────────────────────────────────────────────────────

@router.get("/price/{ticker}")
async def get_price(ticker: str):
    """ETF 현재가 조회"""
    price = get_current_price(ticker)
    if price is None:
        raise HTTPException(
            status_code=404,
            detail=f"현재가 조회 실패: {ticker} — yfinance 응답 없음"
        )
    return {"ticker": ticker, "price": price}


@router.get("/price/{ticker}/ohlcv")
async def get_ticker_ohlcv(
    ticker: str,
    period: str = Query(default="3mo", description="조회 기간 (1mo, 3mo, 6mo, 1y)"),
    interval: str = Query(default="1d", description="캔들 단위 (1d, 1wk, 1mo)"),
):
    """ETF OHLCV 데이터 조회 (TradingView Lightweight Charts 호환 형식)"""
    data = get_ohlcv(ticker, period=period, interval=interval)
    return {"ticker": ticker, "data": data}


# ── ETF Universe ──────────────────────────────────────────────────────────

@router.get("/papertrade/universe", response_model=ETFUniverseResponse)
async def get_universe():
    """ETF 유니버스 전체 조회"""
    universe = repo.get_universe()
    active_count = sum(1 for etf in universe if etf.enabled)
    return ETFUniverseResponse(universe=universe, count=active_count)


@router.post("/papertrade/universe", response_model=ETFUniverseResponse)
async def add_etf(request: ETFAddRequest):
    """ETF 유니버스에 종목 추가"""
    ticker = request.ticker.strip()
    ticker_upper = ticker.upper()
    valid_upper = {t.upper() for t in VALID_TICKERS}

    # 한국 ETF(.KS/.KQ)는 화이트리스트 없이 형식만 검증 (6자리 숫자 + .KS)
    is_kr_etf = (ticker_upper.endswith('.KS') or ticker_upper.endswith('.KQ')) \
                and ticker_upper.split('.')[0].isdigit()
    # 글로벌 ETF는 화이트리스트 확인 (또는 3-5자 알파벳)
    is_global_etf = ticker_upper in valid_upper or (ticker.isalpha() and 2 <= len(ticker) <= 5)

    if not is_kr_etf and not is_global_etf:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 티커 형식: {ticker}. 한국 ETF(6자리.KS) 또는 글로벌 ETF 코드를 입력하세요."
        )

    # 유니버스는 무제한 후보 풀로 관리 — 배분 시 상위 9개 자동 선택
    current_universe = repo.get_universe()

    etf = ETFMeta(**request.model_dump())
    try:
        updated = repo.add_etf(etf)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    active_count = sum(1 for e in updated if e.enabled)
    return ETFUniverseResponse(universe=updated, count=active_count)


@router.delete("/papertrade/universe/{ticker}")
async def delete_etf(ticker: str):
    """ETF 유니버스에서 종목 제거"""
    core_tickers = {"069500.KS", "219480.KS", "379800.KS"}

    removed = repo.remove_etf(ticker)
    if not removed:
        raise HTTPException(status_code=404, detail=f"ETF를 찾을 수 없습니다: {ticker}")

    updated = repo.get_universe()
    remaining_count = sum(1 for e in updated if e.enabled)
    response: dict = {"deleted": ticker, "count": remaining_count}

    # Core ETF 삭제 시 경고
    if ticker in core_tickers:
        response["warning"] = f"{ticker}는 Core 벤치마크 ETF입니다. Core 100억 구성이 불완전해집니다."

    return response


# ── Weekly Score ──────────────────────────────────────────────────────────

@router.get("/papertrade/score")
async def get_scores(week: int = Query(default=1, description="조회할 주차 번호")):
    """저장된 스냅샷에서 점수 조회 (세부 항목 필요 시 score/run 호출)"""
    snapshot = repo.get_snapshot_by_week(week)
    scores: list[WeeklySignalScore] = []

    if snapshot:
        for pos in snapshot.positions:
            if pos.signal_score is not None:
                scores.append(WeeklySignalScore(
                    ticker=pos.ticker,
                    week=week,
                    trend_score=0.0,
                    pullback_score=0.0,
                    volatility_score=0.0,
                    momentum_score=0.0,
                    drawdown_score=0.0,
                    correlation_score=0.0,
                    total_score=pos.signal_score,
                    regime=pos.regime or "Neutral",
                    action="Hold",
                    reason="스냅샷 복원 점수 — 세부 항목 재계산 필요",
                ))

    return ScoreResponse(scores=scores, week=week)


@router.post("/papertrade/score/run", response_model=ScoreResponse)
async def run_scores(request: ScoreRunRequest):
    """ETF 주간 신호 점수 실시간 계산"""
    if request.tickers:
        target_tickers = request.tickers
    else:
        universe = repo.get_universe()
        target_tickers = [etf.ticker for etf in universe if etf.enabled]

    if not target_tickers:
        raise HTTPException(
            status_code=400,
            detail="점수를 계산할 ETF가 없습니다. 유니버스에 ETF를 추가하세요."
        )

    snapshot = repo.get_snapshot_by_week(request.week)
    current_positions = snapshot.positions if snapshot else []

    scores = score_all(
        tickers=target_tickers,
        week=request.week,
        portfolio=current_positions,
    )

    return ScoreResponse(scores=scores, week=request.week)


# ── Allocation ────────────────────────────────────────────────────────────

@router.post("/papertrade/allocation/suggest", response_model=AllocationSuggestResponse)
async def suggest_allocation(request: AllocationSuggestRequest):
    """Core + Alpha 포트폴리오 배분 제안"""
    universe = repo.get_universe()
    if not universe:
        raise HTTPException(status_code=400, detail="유니버스가 비어있습니다. ETF를 먼저 추가하세요.")

    active_tickers = [etf.ticker for etf in universe if etf.enabled]
    snapshot = repo.get_snapshot_by_week(request.week)
    current_positions = snapshot.positions if snapshot else []

    scores = score_all(
        tickers=active_tickers,
        week=request.week,
        portfolio=current_positions,
    )

    suggestion = suggest_portfolio(
        universe=universe,
        scores=scores,
        week=request.week,
        use_alpha=request.use_alpha,
        reserve_amount=request.reserve_amount,
    )

    # 거래량 캡으로 조정된 ETF에 대한 경고 메시지 생성
    # 프론트엔드에서 어떤 ETF가 유동성 제한을 받았는지 사용자에게 명시적으로 알립니다.
    volume_caps: dict[str, float] = suggestion.get("volume_caps", {})
    volume_warnings: list[str] = []
    for pos in suggestion["positions"]:
        if pos.ticker in volume_caps:
            cap = volume_caps[pos.ticker]
            # 배분 금액이 캡의 99% 이상이면 캡에 의해 실질적으로 제한된 것으로 판단합니다.
            # 99% 기준을 사용하는 이유: 부동소수점 반올림으로 인한 미세 차이를 허용하기 위해서입니다.
            if cap is not None and pos.target_amount >= cap * 0.99:
                vol = get_thursday_volume(pos.ticker)
                max_shares = int(vol * 0.25) if vol else 0
                volume_warnings.append(
                    f"{pos.ticker}: 거래량 캡 적용 "
                    f"({pos.target_amount/1e8:.1f}억 → 최대 {cap/1e8:.2f}억, "
                    f"목요거래량 {vol:,}주 × 25%={max_shares:,}주)"
                )

    return AllocationSuggestResponse(
        positions=suggestion["positions"],
        total_exposure=suggestion["total_exposure"],
        leverage_ratio=suggestion["leverage_ratio"],
        cash_remaining=suggestion.get("cash", 0.0),
        week=request.week,
        warnings=suggestion.get("warnings", []),
        volume_warnings=volume_warnings,
    )


# ── Risk Check ────────────────────────────────────────────────────────────

@router.post("/papertrade/risk/check", response_model=RiskCheckResponse)
async def check_risk(request: RiskCheckRequest):
    """포트폴리오 리스크 가드레일 10개 점검"""
    snapshot = repo.get_snapshot_by_week(request.week)
    if snapshot:
        borrowed_cash = snapshot.borrowed_cash
    else:
        # 스냅샷 미확정 시 포지션 합계에서 차입금 직접 계산
        # 총 익스포저 - 기본 자본 = 차입금
        total_from_positions = sum(p.target_amount for p in request.positions)
        borrowed_cash = max(0.0, total_from_positions - BASE_CAPITAL)

    all_pnl = repo.get_pnl()
    weekly_returns = [p.portfolio_return for p in all_pnl if p.week < request.week]
    benchmark_returns = [p.benchmark_return for p in all_pnl if p.week < request.week]

    risk_report = check_violations(
        positions=request.positions,
        borrowed_cash=borrowed_cash,
        week=request.week,
        weekly_returns=weekly_returns or None,
        benchmark_returns=benchmark_returns or None,
    )

    block_count = sum(1 for v in risk_report.violations if "(BLOCK)" in v)
    warn_count = sum(1 for v in risk_report.violations if "(WARN)" in v)

    return RiskCheckResponse(
        report=risk_report,
        passed=len(risk_report.violations) == 0,
        block_count=block_count,
        warn_count=warn_count,
    )


# ── Orders ────────────────────────────────────────────────────────────────

@router.get("/papertrade/orders")
async def get_orders(week: Optional[int] = Query(default=None, description="주차 (없으면 전체)")):
    """저장된 주문 내역 조회"""
    orders = repo.get_orders(week=week)
    target_week = week or (orders[-1].week if orders else 1)
    return _build_orders_response(orders, target_week)


@router.post("/papertrade/orders/generate", response_model=OrdersResponse)
async def generate_orders(request: OrdersGenerateRequest):
    """금요일 주문표 자동 생성 (현재 vs 제안 포지션 비교)"""
    universe = repo.get_universe()
    if not universe:
        raise HTTPException(status_code=400, detail="유니버스가 비어있습니다.")

    active_tickers = [etf.ticker for etf in universe if etf.enabled]
    snapshot = repo.get_snapshot_by_week(request.week)
    current_positions = snapshot.positions if snapshot else []

    scores = score_all(
        tickers=active_tickers,
        week=request.week,
        portfolio=current_positions,
    )

    suggestion = suggest_portfolio(
        universe=universe,
        scores=scores,
        week=request.week,
        use_alpha=True,
        reserve_amount=0,
    )

    proposed_positions = suggestion["positions"]
    borrowed_cash = suggestion.get("borrowed_cash", 0.0)

    all_pnl = repo.get_pnl()
    weekly_returns = [p.portfolio_return for p in all_pnl if p.week < request.week]
    benchmark_returns = [p.benchmark_return for p in all_pnl if p.week < request.week]

    risk_report = check_violations(
        positions=proposed_positions,
        borrowed_cash=borrowed_cash,
        week=request.week,
        weekly_returns=weekly_returns or None,
        benchmark_returns=benchmark_returns or None,
    )

    has_block = any("(BLOCK)" in v for v in risk_report.violations)
    has_warn = any("(WARN)" in v for v in risk_report.violations)
    risk_status = "BLOCK" if has_block else ("WARN" if has_warn else "OK")

    current_map = {pos.ticker: pos.target_amount for pos in current_positions}
    proposed_map = {pos.ticker: pos for pos in proposed_positions}
    threshold = 1_000_000  # 100만 원 이하 변화는 HOLD

    orders: list[WeeklyOrder] = []

    # 제안 포지션 처리
    for ticker, proposed_pos in proposed_map.items():
        current_amount = current_map.get(ticker, 0.0)
        proposed_amount = proposed_pos.target_amount
        delta = proposed_amount - current_amount

        if current_amount == 0.0 and proposed_amount > 0:
            action = "BUY"
            reason = f"신규 매수: {proposed_pos.role} 포지션 구성. 목표 {proposed_amount/1e8:.2f}억원"
            order_amount = proposed_amount
        elif delta > threshold:
            action = "BUY"
            reason = f"비중 확대: {delta/1e8:.2f}억원 추가 ({current_amount/1e8:.2f}억 → {proposed_amount/1e8:.2f}억)"
            order_amount = delta
        elif delta < -threshold:
            action = "REDUCE"
            reason = f"비중 축소: {abs(delta)/1e8:.2f}억원 매도 ({current_amount/1e8:.2f}억 → {proposed_amount/1e8:.2f}억)"
            order_amount = abs(delta)
        else:
            action = "HOLD"
            reason = f"보유 유지: 변화량 {delta/1e6:.1f}만원 (임계값 이하)"
            order_amount = 0.0

        orders.append(WeeklyOrder(
            week=request.week,
            date=request.date,
            ticker=ticker,
            action=action,
            order_type="Friday Close",
            amount=order_amount,
            target_weight=proposed_pos.target_weight,
            reason=reason,
            risk_check=risk_status if action != "HOLD" else "OK",
        ))

    # 제안에 없는 기존 포지션 → 전량 매도
    for ticker, current_amount in current_map.items():
        if ticker not in proposed_map and current_amount > 0:
            orders.append(WeeklyOrder(
                week=request.week,
                date=request.date,
                ticker=ticker,
                action="SELL",
                order_type="Friday Close",
                amount=current_amount,
                target_weight=0.0,
                reason=f"전량 청산: 배분 제안에서 제외 ({current_amount/1e8:.2f}억원)",
                risk_check=risk_status,
            ))

    if orders:
        repo.save_orders(orders)

    return _build_orders_response(orders, request.week)


@router.post("/papertrade/orders/confirm", response_model=OrdersResponse)
async def confirm_orders(request: OrdersConfirmRequest):
    """주문 확정 및 포트폴리오 스냅샷 저장 (BLOCK 이중 차단)"""
    blocked = [o for o in request.orders if o.risk_check == "BLOCK"]
    if blocked:
        tickers = [o.ticker for o in blocked]
        raise HTTPException(
            status_code=400,
            detail=f"BLOCK 주문이 있어 확정 불가: {tickers}. 리스크 위반을 먼저 해소하세요."
        )

    if request.orders:
        repo.save_orders(request.orders)

    from datetime import date as date_module

    snapshot = repo.get_snapshot_by_week(request.week)
    position_map: dict[str, PortfolioPosition] = {}
    if snapshot:
        for pos in snapshot.positions:
            position_map[pos.ticker] = pos

    universe = repo.get_universe()

    # 주문 액션에 따라 포지션 업데이트
    for order in request.orders:
        if order.action in ("SELL", "COVER"):
            position_map.pop(order.ticker, None)

        elif order.action == "REDUCE":
            if order.ticker in position_map:
                existing = position_map[order.ticker]
                new_amount = max(0.0, existing.target_amount - order.amount)
                if new_amount < 1_000_000:
                    position_map.pop(order.ticker, None)
                else:
                    position_map[order.ticker] = PortfolioPosition(
                        ticker=existing.ticker,
                        name=existing.name,
                        role=existing.role,
                        target_amount=new_amount,
                        target_weight=order.target_weight,
                        signal_score=existing.signal_score,
                        regime=existing.regime,
                    )

        elif order.action == "HOLD":
            pass  # 포지션 변화 없음

        else:  # BUY, SHORT 등 매수 방향
            if order.ticker in position_map:
                existing = position_map[order.ticker]
                position_map[order.ticker] = PortfolioPosition(
                    ticker=existing.ticker,
                    name=existing.name,
                    role=existing.role,
                    target_amount=existing.target_amount + order.amount,
                    target_weight=order.target_weight,
                    signal_score=existing.signal_score,
                    regime=existing.regime,
                )
            else:
                etf_meta = next((e for e in universe if e.ticker == order.ticker), None)
                position_map[order.ticker] = PortfolioPosition(
                    ticker=order.ticker,
                    name=etf_meta.name if etf_meta else order.ticker,
                    role=etf_meta.role if etf_meta else "Alpha",
                    target_amount=order.amount,
                    target_weight=order.target_weight,
                )

    confirmed_positions = list(position_map.values())
    total_exposure = sum(pos.target_amount for pos in confirmed_positions)
    borrowed_cash = max(0.0, total_exposure - BASE_CAPITAL)
    remaining_cash = max(0.0, BASE_CAPITAL - total_exposure)

    new_snapshot = PortfolioSnapshot(
        week=request.week,
        date=date_module.today().isoformat(),
        base_capital=BASE_CAPITAL,
        borrowed_cash=borrowed_cash,
        cash=remaining_cash,
        total_exposure=total_exposure,
        positions=confirmed_positions,
    )
    repo.save_snapshot(new_snapshot)

    return _build_orders_response(request.orders, request.week)


# ── PnL ──────────────────────────────────────────────────────────────────

@router.get("/papertrade/pnl")
async def get_pnl(week: Optional[int] = Query(default=None, description="주차 (없으면 전체)")):
    """주간 손익 기록 조회"""
    if week is not None:
        pnl = repo.get_pnl_by_week(week)
        if pnl is None:
            raise HTTPException(
                status_code=404,
                detail=f"{week}주차 P/L 데이터가 없습니다. pnl/update를 먼저 실행하세요."
            )
        return PnLResponse(pnl=pnl, benchmark_detail={})

    all_pnl = repo.get_pnl()
    return {"pnl_list": [p.model_dump() for p in all_pnl], "count": len(all_pnl)}


@router.post("/papertrade/pnl/update", response_model=PnLResponse)
async def update_pnl(request: PnLUpdateRequest):
    """금요일 종가 기반 주간 P&L 계산 및 저장"""
    snapshot = repo.get_snapshot_by_week(request.week)
    if not snapshot:
        raise HTTPException(
            status_code=400,
            detail=f"{request.week}주차 스냅샷이 없습니다. orders/confirm을 먼저 실행하세요."
        )

    prev_snapshot = repo.get_snapshot_by_week(request.week - 1)

    portfolio_return = 0.0
    contribution_by_etf: dict[str, float] = {}
    total_investment = snapshot.total_exposure or snapshot.base_capital

    for pos in snapshot.positions:
        ticker = pos.ticker
        current_price = request.friday_prices.get(ticker)

        # 진입가 결정: 현재 스냅샷 → 이전 스냅샷 순으로 탐색
        entry_price = pos.entry_price
        if entry_price is None and prev_snapshot:
            prev_pos = next((p for p in prev_snapshot.positions if p.ticker == ticker), None)
            if prev_pos:
                entry_price = prev_pos.current_price or prev_pos.entry_price

        if current_price and entry_price and entry_price > 0:
            pos_return = (current_price - entry_price) / entry_price
        else:
            pos_return = 0.0

        weight = pos.target_amount / total_investment if total_investment > 0 else 0.0
        contribution = weight * pos_return
        contribution_by_etf[ticker] = round(contribution, 6)
        portfolio_return += contribution

    # 벤치마크 수익률 계산
    prev_prices: dict[str, float] = {}
    if prev_snapshot:
        for pos in prev_snapshot.positions:
            if pos.current_price:
                prev_prices[pos.ticker] = pos.current_price
            elif pos.entry_price:
                prev_prices[pos.ticker] = pos.entry_price
    prev_prices.update(request.benchmark_prices)

    benchmark_return = get_benchmark_return(
        friday_prices=request.friday_prices,
        prev_prices=prev_prices,
    )

    benchmark_detail: dict[str, float] = {}
    for key, b_ticker in BENCHMARK_TICKERS.items():
        curr = request.friday_prices.get(b_ticker)
        prev = prev_prices.get(b_ticker)
        if curr and prev and prev > 0:
            benchmark_detail[key] = round((curr - prev) / prev, 6)

    all_pnl = repo.get_pnl()
    prev_pnl_list = [p for p in all_pnl if p.week < request.week]

    weekly_pnl = build_weekly_pnl(
        week=request.week,
        date=request.date,
        portfolio_return=round(portfolio_return, 6),
        benchmark_return=benchmark_return,
        borrowed_cash=snapshot.borrowed_cash,
        total_capital=snapshot.base_capital,
        cash_held=snapshot.cash,
        contribution_by_etf=contribution_by_etf,
        prev_pnl_list=prev_pnl_list,
    )

    repo.save_pnl(weekly_pnl)
    return PnLResponse(pnl=weekly_pnl, benchmark_detail=benchmark_detail)


# ── Reports ───────────────────────────────────────────────────────────────

@router.post("/papertrade/report/risk-rules", response_model=ReportResponse)
async def report_risk_rules(request: ReportRiskRulesRequest):
    """리스크 규칙 마크다운 보고서 생성 (교수 제출용)"""
    markdown = generate_risk_rules(week=request.week)

    if request.include_violations:
        snapshot = repo.get_snapshot_by_week(request.week)
        if snapshot:
            all_pnl = repo.get_pnl()
            weekly_returns = [p.portfolio_return for p in all_pnl if p.week < request.week]
            benchmark_returns = [p.benchmark_return for p in all_pnl if p.week < request.week]
            risk_report = check_violations(
                positions=snapshot.positions,
                borrowed_cash=snapshot.borrowed_cash,
                week=request.week,
                weekly_returns=weekly_returns or None,
                benchmark_returns=benchmark_returns or None,
            )
            if risk_report.violations:
                lines = ["", "---", "", f"## {request.week}주차 현재 위반 항목", ""]
                lines += [f"- {v}" for v in risk_report.violations]
                markdown = markdown + "\n" + "\n".join(lines)

    return ReportResponse(markdown=markdown, week=request.week)


@router.post("/papertrade/report/orders", response_model=ReportResponse)
async def report_orders(request: ReportOrdersRequest):
    """Orders Report 마크다운 보고서 생성 (5섹션)"""
    orders = repo.get_orders(week=request.week)

    snapshot = repo.get_snapshot_by_week(request.week)
    if not snapshot:
        raise HTTPException(
            status_code=400,
            detail=f"{request.week}주차 스냅샷이 없습니다. orders/confirm을 먼저 실행하세요."
        )

    all_pnl = repo.get_pnl()
    weekly_returns = [p.portfolio_return for p in all_pnl if p.week < request.week]
    benchmark_returns = [p.benchmark_return for p in all_pnl if p.week < request.week]

    risk_report = check_violations(
        positions=snapshot.positions,
        borrowed_cash=snapshot.borrowed_cash,
        week=request.week,
        weekly_returns=weekly_returns or None,
        benchmark_returns=benchmark_returns or None,
    )

    universe = repo.get_universe()
    active_tickers = [etf.ticker for etf in universe if etf.enabled]
    scores: list[WeeklySignalScore] = []
    if active_tickers:
        scores = score_all(tickers=active_tickers, week=request.week, portfolio=snapshot.positions)

    from datetime import date as date_module
    report_date = orders[0].date if orders else date_module.today().isoformat()

    markdown = generate_orders_report(
        week=request.week,
        date=report_date,
        orders=orders,
        risk_report=risk_report,
        scores=scores,
        market_summary=request.market_background or "",
    )

    if request.strategy_note:
        markdown += f"\n\n**추가 전략 메모:**\n\n{request.strategy_note}"

    return ReportResponse(markdown=markdown, week=request.week)


@router.post("/papertrade/report/weekly-pnl", response_model=ReportResponse)
async def report_weekly_pnl(request: ReportWeeklyPnLRequest):
    """주간 P&L 보고서 마크다운 생성"""
    pnl = repo.get_pnl_by_week(request.week)
    if pnl is None:
        raise HTTPException(
            status_code=404,
            detail=f"{request.week}주차 P/L 데이터가 없습니다. pnl/update를 먼저 실행하세요."
        )

    all_pnl = repo.get_pnl()
    markdown = generate_weekly_pnl_report(week=request.week, pnl=pnl, all_pnl=all_pnl)
    return ReportResponse(markdown=markdown, week=request.week)


# ── AI Committee ──────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """AI 투자위원회 채팅 (역할별 시스템 프롬프트 적용)"""
    try:
        response_text = ai_chat(
            message=request.message,
            role=request.role,
            context=request.context,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI 서비스 오류: {str(e)}")

    return ChatResponse(response=response_text, role=request.role)
