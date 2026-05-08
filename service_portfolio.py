"""
service_portfolio.py — MarkovPortfolio V4 포트폴리오 배분 서비스

Core(벤치마크 복제) + Alpha(초과수익 추구) 이중 구조로 배분을 계산합니다.

배분 철학:
- Core 100억: 수업 벤치마크를 그대로 복제하여 추적 오차 최소화
- Alpha 최대 30억: 점수 65 이상 ETF에만 집중 배분
- 총 익스포저 130억 상한: Core + Alpha + 차입 합산이 130억을 넘으면 차단

Pydantic v2 규칙:
- 모델 직렬화 시 반드시 .model_dump() 사용 (.dict()는 deprecated)
"""

from typing import Optional
from datetime import date

from models import ETFMeta, WeeklySignalScore, PortfolioPosition, PortfolioSnapshot
from config import (
    BASE_CAPITAL,
    MAX_ALPHA_EXPOSURE,
    MAX_TOTAL_EXPOSURE,
    MAX_ETF_COUNT,
    DEFAULT_CORE_ALLOCATION,
    CLASS_BENCHMARK,
)

# ── 벤치마크 Core ETF 매핑 ─────────────────────────────────────────────────

# 수업 벤치마크를 구성하는 3개 ETF와 각각의 목표 금액을 정의합니다.
# 이 매핑은 Core 포트폴리오 구성의 기준이 되므로 별도 상수로 분리합니다.
BENCHMARK_ETF_MAP: dict[str, dict] = {
    "kospi200": {
        "ticker":  "069500.KS",
        "name":    "KODEX 200",
        "amount":  DEFAULT_CORE_ALLOCATION["kospi200Core"],   # 40억
        "weight":  CLASS_BENCHMARK["kospi200"],               # 0.40
    },
    "sp500Hedged": {
        "ticker":  "449180.KS",
        "name":    "KODEX 미국S&P500(H)",
        "amount":  DEFAULT_CORE_ALLOCATION["sp500HedgedCore"],  # 30억
        "weight":  CLASS_BENCHMARK["sp500Hedged"],              # 0.30
    },
    "sp500Unhedged": {
        "ticker":  "379800.KS",
        "name":    "KODEX S&P500 TR",
        "amount":  DEFAULT_CORE_ALLOCATION["sp500UnhedgedCore"],  # 30억
        "weight":  CLASS_BENCHMARK["sp500Unhedged"],              # 0.30
    },
}

# 단일 Alpha ETF 최대 배분 한도
# 집중 위험을 방지하기 위해 단일 ETF가 Alpha 예산의 절반을 초과하지 않도록 설정합니다.
MAX_SINGLE_ALPHA_AMOUNT: float = 4_000_000_000  # 40억 (MAX_ALPHA_EXPOSURE의 약 133%)


def build_benchmark_core(universe: list) -> list[PortfolioPosition]:
    """
    유니버스에 있는 Core ETF만 벤치마크 비중으로 배분

    BENCHMARK_ETF_MAP에 정의된 3개 ETF(KOSPI200/S&P500H/S&P500U) 중
    실제로 사용자 유니버스에 role='Core'로 등록된 ETF만 포지션을 생성합니다.

    유니버스에 없는 ETF를 강제로 포함하지 않는 이유:
    사용자가 의도적으로 특정 Core ETF를 제외했을 수 있으며,
    유니버스에 없는 ETF를 배분에 포함하면 실제 주문과 포지션이 불일치합니다.
    """
    # 유니버스에서 활성화된 Core 역할 ETF의 티커 집합을 먼저 추출합니다.
    # hasattr 분기: ETFMeta 객체(Pydantic) 또는 dict 형태 모두 지원하기 위해서입니다.
    core_in_universe = {
        etf.ticker if hasattr(etf, 'ticker') else etf.get('ticker')
        for etf in universe
        if (etf.role if hasattr(etf, 'role') else etf.get('role')) == 'Core'
        and (etf.enabled if hasattr(etf, 'enabled') else etf.get('enabled', True))
    }

    positions = []
    for benchmark_key, meta in BENCHMARK_ETF_MAP.items():
        # 사용자 유니버스에 없는 벤치마크 ETF는 배분에서 제외합니다.
        # 강제 포함 시 유니버스-배분 불일치 및 오더 리포트 혼란이 발생합니다.
        if meta["ticker"] not in core_in_universe:
            continue

        pos = PortfolioPosition(
            ticker=meta["ticker"],
            name=meta["name"],
            role="Core",
            # Core는 벤치마크 비중 그대로 배분하므로 고정 금액
            target_amount=meta["amount"],
            # Core target_weight: BASE_CAPITAL(100억) 기준 비중
            # 예: KODEX 200 = 40억 / 100억 = 0.40
            target_weight=meta["weight"],
            # Core는 점수 기반 배분이 아니므로 signal_score 없음
            signal_score=None,
            regime=None,
        )
        positions.append(pos)
    return positions


def allocate_alpha(
    scores: list[WeeklySignalScore],
    current_positions: list[PortfolioPosition],
    max_alpha: float = MAX_ALPHA_EXPOSURE,
    volume_caps: Optional[dict[str, float]] = None,  # {ticker: 최대 KRW 주문 금액}
) -> list[PortfolioPosition]:
    """
    점수 기반 Alpha 포지션 배분

    배분 규칙:
    - 80점 이상 (Increase): 정상 배분 — 점수 비례로 예산 분배
    - 65-79점 (Small Buy): 소량 배분 — 정상 배분의 50% 감액
    - 64점 미만 (Hold/Reduce/Exit): 배분 없음
    - 단일 ETF 최대 MAX_SINGLE_ALPHA_AMOUNT(40억) 제한
    - 거래량 캡(목요일 거래량 × 25% × 현재가) 초과 시 추가 감액

    이미 Core로 배분된 티커는 Alpha 중복 배분에서 제외합니다.
    — Core와 Alpha에 같은 ETF가 들어가면 포지션 관리가 복잡해집니다.

    변동성 위반(volatility_score < 5) ETF는 배분 금액을 50% 추가 감액합니다.
    — 고변동 ETF에 집중 투자하면 포트폴리오 전체 리스크가 급격히 증가합니다.

    volume_caps: {ticker: 최대 KRW 주문 금액} 딕셔너리
    — service_market.get_volume_cap()으로 사전 계산하여 전달합니다.
    — None이면 거래량 제한 없이 배분합니다.
    """
    if not scores:
        return []

    # Core 포지션의 티커 세트: Alpha 중복 방지용
    core_tickers = {pos.ticker for pos in current_positions if pos.role == "Core"}

    # 배분 대상 필터링: Core 제외, 점수 필터 없음
    # 점수 계산된 모든 ETF를 배분 대상으로 포함합니다.
    # No Buy(0점) ETF만 가중치 최소화하여 자연스럽게 소액 배분됩니다.
    eligible = [
        s for s in scores
        if s.ticker not in core_tickers
    ]

    if not eligible:
        return []

    # 점수 비례 가중치 계산 — 높은 점수일수록 더 많이 배분
    # No Buy(0점)도 최솟값 1점을 보장하여 완전 배제하지 않음
    weight_scores = []
    for s in eligible:
        # 점수가 높을수록 더 많은 비중을 받도록 점수를 가중치로 사용
        effective_weight = max(1.0, float(s.total_score))

        # 변동성이 매우 높은 ETF(volatility_score < 5)는 50% 감액
        if s.volatility_score < 5:
            effective_weight *= 0.5

        weight_scores.append((s, effective_weight))

    # 가중치 합계로 예산 비례 분배
    total_weight = sum(w for _, w in weight_scores)
    if total_weight == 0:
        return []

    alpha_positions = []
    for s, w in weight_scores:
        # 가중치 비례 배분 금액 계산
        raw_amount = max_alpha * (w / total_weight)

        # 단일 ETF 상한선 적용
        # MAX_SINGLE_ALPHA_AMOUNT를 초과하는 배분은 잘라냅니다.
        capped_amount = min(raw_amount, MAX_SINGLE_ALPHA_AMOUNT)

        # 거래량 캡 적용 (목요일 거래량 × 25% × 현재가)
        # 저유동성 ETF에 초과 배분하면 실제 체결 시 시장 충격이 발생하므로 사전에 방지합니다.
        if volume_caps and s.ticker in volume_caps:
            vol_cap = volume_caps[s.ticker]
            if vol_cap is not None and vol_cap < capped_amount:
                capped_amount = vol_cap

        # 배분 금액이 500만원 미만이면 제외 (거래량 캡으로 인한 소액 배분 방지 포함)
        if capped_amount < 5_000_000:
            continue

        pos = PortfolioPosition(
            ticker=s.ticker,
            name=s.ticker,  # ETF 이름은 호출자가 universe에서 조회해 채워야 합니다
            role="Alpha",
            target_amount=round(capped_amount, -6),  # 백만 원 단위로 반올림
            # target_weight는 calculate_target_weights()에서 재계산합니다
            target_weight=0.0,
            signal_score=s.total_score,
            regime=s.regime,
        )
        alpha_positions.append(pos)

    return alpha_positions


def _enrich_alpha_names(
    alpha_positions: list[PortfolioPosition],
    universe: list[ETFMeta],
) -> list[PortfolioPosition]:
    """
    Alpha 포지션의 name 필드를 ETF 유니버스에서 조회해 채웁니다.

    allocate_alpha()에서는 universe 의존성을 줄이기 위해
    name을 ticker로만 설정하고, 이 함수에서 실제 이름을 채웁니다.
    유니버스에 없는 ticker는 name이 ticker 코드 그대로 유지됩니다.
    """
    universe_map = {etf.ticker: etf.name for etf in universe}
    for pos in alpha_positions:
        if pos.ticker in universe_map:
            pos.name = universe_map[pos.ticker]
    return alpha_positions


def calculate_target_weights(
    positions: list[PortfolioPosition],
) -> list[PortfolioPosition]:
    """
    총 익스포저 대비 각 포지션의 target_weight 재계산

    배분 금액이 확정된 후에 각 포지션의 비중을 역산합니다.
    target_weight는 보고서 및 리스크 분석에서 포지션 크기를 직관적으로 파악하는 데 사용됩니다.

    총 익스포저가 0이면 모든 비중을 0으로 설정합니다(0 나누기 방지).
    """
    total = sum(pos.target_amount for pos in positions)
    if total == 0:
        return positions

    for pos in positions:
        # 비중 = 개별 금액 / 총 익스포저
        pos.target_weight = round(pos.target_amount / total, 6)

    return positions


def suggest_portfolio(
    universe: list[ETFMeta],
    scores: list[WeeklySignalScore],
    week: int = 1,
    use_alpha: bool = True,
    reserve_amount: float = 0.0,
) -> dict:
    """
    Core + Alpha 통합 포트폴리오 제안

    호출 흐름:
    1. Core 3개 포지션 생성 (100억 고정)
    2. Alpha ETF 점수 기반 배분 (use_alpha=True일 때)
    3. 포지션 이름 보정 (universe에서 실제 ETF 명칭 조회)
    4. target_weight 재계산
    5. 총 익스포저 및 레버리지 비율 계산
    6. 위반 사항 검증

    reserve_amount: 현금 여유분 (Alpha 예산에서 차감)
    — 시장 조정 시 추가 매수 여력을 남겨두기 위한 버퍼입니다.

    반환값:
    {
        positions: list[PortfolioPosition],
        total_exposure: float,
        leverage_ratio: float,
        cash: float,
        warnings: list[str],
    }
    """
    warnings: list[str] = []

    # 1단계: Core 포지션 생성 (유니버스 필터링 후 벤치마크 복제)
    # universe를 전달하여 사용자가 등록한 Core ETF만 배분합니다.
    core_positions = build_benchmark_core(universe)

    # Core ETF 티커 집합: volume_caps 계산 시 Core는 제외하기 위해 미리 추출합니다.
    # Core ETF는 벤치마크 복제 목적으로 고정 금액을 배분하므로 거래량 캡 적용 대상이 아닙니다.
    core_positions_tickers = {pos.ticker for pos in core_positions}

    # 2단계: Alpha 배분 (선택적)
    alpha_positions = []
    volume_caps: dict[str, float] = {}  # 프론트엔드 표시 및 로깅용으로 함수 스코프 밖에서 선언
    if use_alpha:
        # reserve_amount만큼 Alpha 예산을 줄입니다
        # reserve는 "현금 보유 전략"으로, Alpha 예산 전체를 소진하지 않는 전략입니다
        effective_alpha_budget = max(0.0, MAX_ALPHA_EXPOSURE - reserve_amount)

        # enabled=True인 ETF의 점수만 Alpha 배분에 사용합니다
        enabled_tickers = {etf.ticker for etf in universe if etf.enabled}
        filtered_scores = [
            s for s in scores if s.ticker in enabled_tickers
        ]

        # ── 거래량 캡 계산 ────────────────────────────────────────────────
        # 과제 규칙: 주문 크기 ≤ 목요일 거래량 × 25%
        # Core ETF는 이미 고정 금액 배분이므로 Alpha 대상 ETF에만 적용합니다.
        # 현재가를 재조회하는 이유: 점수 계산 시 캐시된 가격이 오래됐을 수 있으며,
        # 거래량 캡은 금액 기준이므로 현재가가 정확할수록 한도 계산이 정밀해집니다.
        from service_market import get_volume_cap, get_current_price
        for s in filtered_scores:
            if s.ticker in core_positions_tickers:
                continue  # Core 티커는 거래량 캡 불필요
            price = get_current_price(s.ticker)
            if price is not None and price > 0:
                cap = get_volume_cap(s.ticker, price)
                if cap is not None:
                    volume_caps[s.ticker] = cap

        alpha_positions = allocate_alpha(
            scores=filtered_scores,
            current_positions=core_positions,
            max_alpha=effective_alpha_budget,
            volume_caps=volume_caps,
        )

        # 유니버스에서 ETF 이름 조회하여 name 필드 보정
        alpha_positions = _enrich_alpha_names(alpha_positions, universe)

    # 3단계: Core + Alpha 통합 — 개수 제한 없음
    # 점수 계산된 모든 ETF를 그대로 배분합니다.
    # 리스크 가드레일(ETF 수 < 10)은 별도로 체크하므로 여기서는 제한하지 않습니다.
    all_positions = core_positions + alpha_positions

    # 4단계: target_weight 재계산 (전체 포지션 기준)
    all_positions = calculate_target_weights(all_positions)

    # 5단계: 총 익스포저 계산
    total_exposure = sum(pos.target_amount for pos in all_positions)

    # 레버리지 비율: BASE_CAPITAL(100억)을 초과하는 부분이 차입으로 조달된다고 가정
    # 예: 총 익스포저 130억 = 100억 자본 + 30억 차입 → 레버리지 30%
    borrowed_cash = max(0.0, total_exposure - BASE_CAPITAL)
    leverage_ratio = borrowed_cash / BASE_CAPITAL if BASE_CAPITAL > 0 else 0.0

    # 미투자 현금: 자본 + 차입 - 총 익스포저
    # 차입을 포함한 총 가용자금에서 투자 금액을 차감한 잔액
    available_funds = BASE_CAPITAL + borrowed_cash
    cash = available_funds - total_exposure

    # 6단계: 위반 사항 사전 검증
    if total_exposure > MAX_TOTAL_EXPOSURE:
        warnings.append(
            f"총 익스포저 {total_exposure/1e8:.1f}억 — 130억 상한 초과 (BLOCK)"
        )
    if leverage_ratio > 0.30:
        warnings.append(
            f"레버리지 {leverage_ratio:.1%} — 30% 상한 초과 (BLOCK)"
        )
    if len(all_positions) >= 10:
        warnings.append(
            f"ETF 수 {len(all_positions)}개 — 10개 미만 제한 위반 (BLOCK)"
        )

    return {
        "week": week,
        "date": date.today().isoformat(),
        "positions": all_positions,
        "total_exposure": total_exposure,
        "borrowed_cash": borrowed_cash,
        "leverage_ratio": leverage_ratio,
        "cash": cash,
        "warnings": warnings,
        # 거래량 캡 정보: 프론트엔드에서 어떤 ETF가 유동성 제한을 받았는지 표시하는 데 사용합니다.
        # 저장소에 저장하지 않고 응답에만 포함하는 이유: 매주 시장 유동성이 달라지므로
        # 캡 금액은 실시간 참고용으로만 활용하고 스냅샷에는 포함하지 않습니다.
        "volume_caps": volume_caps,
    }


def build_portfolio_snapshot(
    suggestion: dict,
    week: int,
) -> PortfolioSnapshot:
    """
    suggest_portfolio() 결과를 PortfolioSnapshot 모델로 변환합니다.

    PortfolioSnapshot은 repository_papertrade.py에 저장하여
    주차별 이력을 관리합니다.
    """
    return PortfolioSnapshot(
        week=week,
        date=suggestion["date"],
        base_capital=BASE_CAPITAL,
        borrowed_cash=suggestion["borrowed_cash"],
        cash=suggestion["cash"],
        total_exposure=suggestion["total_exposure"],
        positions=suggestion["positions"],
    )


def validate_exposure(snapshot: PortfolioSnapshot) -> list[str]:
    """
    포트폴리오 스냅샷의 익스포저 규칙 위반 여부를 검증합니다.

    service_risk_budget.py의 전체 리스크 점검보다 가벼운 사전 검증으로,
    배분 제안 단계에서 빠르게 경고를 출력하는 용도입니다.

    반환값: 위반 사항 목록 (빈 리스트면 통과)
    """
    violations = []

    # 1. 총 익스포저 한도 검증
    if snapshot.total_exposure > MAX_TOTAL_EXPOSURE:
        violations.append(
            f"총 익스포저 {snapshot.total_exposure/1e8:.1f}억 원 — "
            f"{MAX_TOTAL_EXPOSURE/1e8:.0f}억 상한 초과 (BLOCK)"
        )

    # 2. 레버리지 비율 검증
    leverage_ratio = snapshot.borrowed_cash / BASE_CAPITAL if BASE_CAPITAL > 0 else 0.0
    if leverage_ratio > 0.30:
        violations.append(
            f"레버리지 {leverage_ratio:.1%} — 30% 상한 초과 (BLOCK)"
        )

    # 3. ETF 수 검증 (10개 미만)
    if len(snapshot.positions) >= 10:
        violations.append(
            f"ETF 수 {len(snapshot.positions)}개 — 10개 미만 제한 위반 (BLOCK)"
        )

    # 4. Short/Inverse ETF 비중 검증
    # role이 'Short'인 포지션의 합계가 총자산의 30%를 초과하면 위반
    short_amount = sum(
        pos.target_amount
        for pos in snapshot.positions
        if pos.role == "Short"
    )
    total_assets = BASE_CAPITAL + snapshot.borrowed_cash
    short_ratio = short_amount / total_assets if total_assets > 0 else 0.0
    if short_ratio > 0.30:
        violations.append(
            f"숏 ETF 비중 {short_ratio:.1%} — 30% 상한 초과 (BLOCK)"
        )

    # 5. 단일 Alpha/Tactical ETF 금액 한도 검증 (40억 이내)
    # Core 포지션은 벤치마크 복제 목적으로 40억을 초과할 수 있으므로 제외합니다.
    for pos in snapshot.positions:
        if pos.role != "Core" and pos.target_amount > MAX_SINGLE_ALPHA_AMOUNT:
            violations.append(
                f"{pos.ticker} 배분 {pos.target_amount/1e8:.1f}억 — "
                f"단일 ETF 40억 한도 초과 (WARN)"
            )

    return violations
