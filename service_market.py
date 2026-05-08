"""
service_market.py — MarkovPortfolio V4 시장 데이터 서비스

yfinance를 통해 ETF OHLCV 데이터와 현재가를 조회합니다.
V2의 TTL 캐시, MultiIndex 처리 패턴을 그대로 계승하되,
종목 목록을 선물/단주 중심에서 ETF 전용으로 전환합니다.

캐시 전략:
- 메모리 내 딕셔너리 사용 (서버 재시작 시 초기화)
- key: "{ticker}_{period}_{interval}"
- TTL: config.CACHE_TTL 초 (기본 60초)

yfinance 1.2.0+ MultiIndex 처리:
- download() 반환 시 컬럼이 ('Close', '069500.KS') 같은 튜플 형태
- droplevel(1)로 두 번째 레벨을 제거해 단순 문자열 컬럼으로 복원
"""

import time
from typing import Optional

import pandas as pd
import yfinance as yf

import config

# ── ETF 전용 종목 화이트리스트 ────────────────────────────────────────────

# 화이트리스트로 관리하는 이유:
# 임의 티커 입력 시 yfinance가 예상치 못한 데이터를 반환하거나
# 오류가 발생할 수 있으므로, 검증된 ETF 종목만 허용합니다.

# 한국 ETF (.KS 접미사 — KRX 상장 ETF)
# Core 벤치마크 복제 및 국내 시장 노출에 사용합니다.
_KR_ETF = {
    # ── Core 벤치마크 ──────────────────────────────────────────────────
    "069500.KS",  # KODEX 200 — 코스피200 추종, Core 40%
    "219480.KS",  # KODEX 미국S&P500선물(H) — 환헷지, Core 30%
    "379800.KS",  # KODEX 미국S&P500TR — 비헷지, Core 30%

    # ── Growth / Tech Alpha ────────────────────────────────────────────
    "426030.KS",  # TIME 미국나스닥100액티브 — 나스닥100 기반 액티브
    "456600.KS",  # TIME 글로벌AI인공지능액티브 — AI/반도체/데이터 인프라 테마
    "381180.KS",  # TIGER 미국필라델피아반도체나스닥 — 미국 반도체 사이클
    "305080.KS",  # TIGER 미국나스닥100 — QQQ 대체 국내 상장 ETF

    # ── Korea Alpha ────────────────────────────────────────────────────
    "091160.KS",  # KODEX 반도체 — 한국 반도체 업종
    "396500.KS",  # TIGER Fn반도체TOP10 — 삼성전자/SK하이닉스 중심
    "229200.KS",  # KODEX 코스닥150 — 국내 성장주/고베타

    # ── Hedge ──────────────────────────────────────────────────────────
    "273130.KS",  # KODEX 종합채권(AA-이상)액티브 — 주식 변동성 완화
    "148070.KS",  # KOSEF 국고채10년 — 금리 하락 국면 수익, 완충 역할
    "148020.KS",  # KOSEF 국고채10년 (구버전 코드) — 호환성 유지

    # ── Currency / Tactical ────────────────────────────────────────────
    "261240.KS",  # KODEX 미국달러선물 — 원/달러 상승 수혜, 환율 전략
    "195930.KS",  # TIGER 유로스탁스50(합성 H) — 유럽 경기 회복 분산

    # ── Short / Inverse ────────────────────────────────────────────────
    "114800.KS",  # KODEX 인버스 — KOSPI 하락 방어, -1x
    "252670.KS",  # KODEX 200선물인버스2X — 강한 하락장 헤지, -2x

    # ── 기존 유지 ─────────────────────────────────────────────────────
    "360750.KS",  # TIGER S&P500
    "133690.KS",  # TIGER MSCI Korea TR
    "102110.KS",  # TIGER 200
    "278530.KS",  # KODEX 200TR
    "371460.KS",  # TIGER MSCI USA
    "367380.KS",  # TIGER 미국S&P500
    "132030.KS",  # KODEX 골드선물(H)
}

# 글로벌 ETF (미국 상장 — 달러 기준)
# Alpha 포지션 및 글로벌 분산에 사용합니다.
_GLOBAL_ETF = {
    "SPY",   # SPDR S&P500 — 미국 대형주 벤치마크
    "QQQ",   # Invesco Nasdaq 100 — 기술주 성장
    "IEF",   # iShares 7-10년 미국채 — 중기채 안전자산
    "TLT",   # iShares 20년+ 미국채 — 장기채 금리 헷지
    "GLD",   # SPDR Gold Shares — 금 현물 연동
    "VNQ",   # Vanguard 부동산 리츠 — 실물 자산 분산
    "EEM",   # iShares 이머징 마켓 — 신흥국 분산
    "VTI",   # Vanguard 전미 주식 — 미국 전체 시장
    "AGG",   # iShares 미국 채권 집합 — 미국 채권 전체
    "VEA",   # Vanguard 선진국 제외 미국 — 유럽/일본
    "IEMG",  # iShares Core 이머징 마켓 — EEM 저비용 대안
    "LQD",   # iShares 투자등급 회사채 — 크레딧 스프레드 노출
    "HYG",   # iShares 하이일드 회사채 — 위험 선호 지표
    "VWO",   # Vanguard 이머징 마켓 — EEM 대안
    "DIA",   # SPDR 다우존스 30 — 가치주 벤치마크
    "IWM",   # iShares 러셀2000 — 미국 소형주
    "XLF",   # SPDR 금융 섹터 — 금리 민감 섹터
    "XLE",   # SPDR 에너지 섹터 — 원자재/인플레 헷지
    "XLV",   # SPDR 헬스케어 섹터 — 방어 섹터
    "SQQQ",  # ProShares UltraPro Short QQQ — 나스닥 -3x (강한 숏)
    "SH",    # ProShares Short S&P500 — S&P500 -1x
    "PSQ",   # ProShares Short QQQ — 나스닥 -1x
}

# 환율 지표 (시장 분석 참고용)
# 환율 방향성이 헷지/비헷지 ETF 선택에 영향을 미치므로 포함합니다.
_FX = {
    "KRW=X",   # 원/달러 환율 — 한국 ETF 환 리스크 모니터링
    "USDKRW=X", # 동일 환율 (yfinance 대체 표기)
}

# 전체 허용 종목 집합 — 세 그룹의 합집합
VALID_TICKERS: set = _KR_ETF | _GLOBAL_ETF | _FX


# ── 캐시 ─────────────────────────────────────────────────────────────────

# {key: (timestamp, data)} 형식으로 TTL 캐시 관리
# 딕셔너리를 사용하는 이유: Redis 등 외부 의존성 없이 단순하게 구현
_cache: dict[str, tuple[float, any]] = {}


def _cache_get(key: str):
    """
    캐시에서 값 조회

    TTL 초과 시 None을 반환하여 fresh 조회를 유도합니다.
    만료된 항목은 즉시 삭제하여 메모리 낭비를 방지합니다.
    """
    if key not in _cache:
        return None
    ts, data = _cache[key]
    # TTL 초과 시 만료 처리 (오래된 데이터 사용 방지)
    if time.time() - ts > config.CACHE_TTL:
        del _cache[key]
        return None
    return data


def _cache_set(key: str, data) -> None:
    """
    캐시에 현재 타임스탬프와 함께 데이터를 저장합니다.
    타임스탬프를 함께 저장하는 이유: _cache_get에서 TTL 경과 여부를 판단하기 위함입니다.
    """
    _cache[key] = (time.time(), data)


def is_valid_ticker(ticker: str) -> bool:
    """
    화이트리스트에 등록된 티커인지 검증합니다.

    대소문자를 통일하지 않는 이유:
    한국 ETF는 '069500.KS' 처럼 소문자 .ks가 있고,
    글로벌은 'SPY' 처럼 대문자이므로 원본 형태를 그대로 비교합니다.
    단, 대문자 비교도 함께 시도하여 사용자 입력 오류를 방지합니다.
    """
    return ticker in VALID_TICKERS or ticker.upper() in VALID_TICKERS


def get_ohlcv(
    ticker: str,
    period: str = "3mo",
    interval: str = "1d",
) -> list[dict]:
    """
    ETF OHLCV 데이터 조회

    TradingView Lightweight Charts 호환 형식으로 반환합니다.
    time 필드가 Unix timestamp인 이유:
    TradingView 라이브러리가 UTC 초 단위 정수를 요구합니다.

    주간 ETF 분석용으로 period="3mo", interval="1wk" 조합도 지원합니다.
    — 점수 계산 시 충분한 주간 데이터(약 12주)를 확보하기 위해 3개월을 기본값으로 설정합니다.

    yfinance 1.2.0+ MultiIndex 처리:
    단일 종목 download()도 ('Close', '069500.KS') 같은 튜플 컬럼을 반환합니다.
    droplevel(1)로 두 번째 레벨(티커명)을 제거해야 row['Close']로 접근 가능합니다.
    """
    cache_key = f"{ticker}_{period}_{interval}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,    # 터미널 진행바 출력 억제 (서버 로그 오염 방지)
            auto_adjust=True,  # 분할/배당 조정 자동 적용
        )

        # yfinance 1.2.0+에서 컬럼이 ('Open', '069500.KS') 같은 MultiIndex 튜플로 반환됨
        # 두 번째 레벨(티커명)을 제거해 단순 문자열 컬럼으로 되돌립니다
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        if df.empty:
            return []

        # DataFrame → TradingView 형식 딕셔너리 목록으로 변환
        result = []
        for ts, row in df.iterrows():
            # pandas Timestamp → Unix timestamp (초 단위 정수)
            # UTC 기준으로 변환하는 이유: TradingView가 UTC 기준으로 캔들을 그립니다
            unix_ts = int(ts.timestamp())
            result.append({
                "time":   unix_ts,
                "open":   round(float(row["Open"]),   4),
                "high":   round(float(row["High"]),   4),
                "low":    round(float(row["Low"]),    4),
                "close":  round(float(row["Close"]),  4),
                "volume": round(float(row["Volume"]), 2),
            })

        # 시간 오름차순 정렬 (TradingView 요구사항: 과거 → 현재 순)
        result.sort(key=lambda x: x["time"])

        _cache_set(cache_key, result)
        return result

    except Exception as e:
        # yfinance 오류는 빈 리스트 반환 (UI가 데이터 없음으로 처리하게 함)
        print(f"[service_market] OHLCV 조회 실패 ({ticker}): {e}")
        return []


def get_current_price(ticker: str) -> Optional[float]:
    """
    ETF 현재가 조회

    1분봉 데이터에서 마지막 종가를 현재가로 사용합니다.
    실시간 호가(bid/ask) 대신 종가를 사용하는 이유:
    ETF는 장 중에도 체결이 연속적으로 일어나므로
    1분봉 종가가 충분히 최신 가격을 반영합니다.

    한국 ETF의 경우 장 마감 후에는 당일 종가가 반환됩니다.
    조회 실패 시 None 반환 (0.0이 아닌 None으로 호출자가 "실패"를 구분할 수 있게 함)
    """
    cache_key = f"{ticker}_price"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        # 가장 최근 1분봉을 조회해 현재가 추정
        # period="1d"를 사용하는 이유: "1m" period 최대 7일이지만 1분봉 1개만 필요하므로 최소 기간 사용
        df = yf.download(
            ticker,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=True,
        )

        # yfinance 1.2.0+에서 동일한 MultiIndex 문제가 현재가 조회에도 발생
        # droplevel로 티커명 레벨을 제거해 단순 컬럼명으로 복원합니다
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        if df.empty:
            return None

        price = round(float(df["Close"].iloc[-1]), 4)
        _cache_set(cache_key, price)
        return price

    except Exception as e:
        print(f"[service_market] 현재가 조회 실패 ({ticker}): {e}")
        return None


def get_weekly_prices(
    ticker: str,
    weeks: int = 12,
) -> list[dict]:
    """
    주간 종가 데이터 조회 (점수 계산용)

    weekly score 계산에 필요한 주간 시계열을 반환합니다.
    weeks=12는 약 3개월치로, 추세/모멘텀/낙폭 계산에 충분한 기간입니다.
    반환값에는 weekly OHLCV가 포함되어 있어 RSI, 이동평균 등을 계산할 수 있습니다.
    """
    # 주 단위 데이터는 "3mo"가 약 12주를 커버합니다
    # 더 많은 주간 데이터가 필요하면 "6mo"로 확장 가능합니다
    period_map = {
        4:  "1mo",
        8:  "2mo",
        12: "3mo",
        24: "6mo",
        52: "1y",
    }
    # 요청 주 수에 맞는 가장 가까운 기간 선택
    period = "3mo"  # 기본값
    for w, p in sorted(period_map.items()):
        if weeks <= w:
            period = p
            break

    return get_ohlcv(ticker, period=period, interval="1wk")


def get_daily_prices(
    ticker: str,
    days: int = 60,
) -> list[dict]:
    """
    일간 종가 데이터 조회 (이동평균 계산용)

    20일/60일 이동평균 계산을 위해 일간 데이터를 반환합니다.
    60일 이동평균은 최소 60개의 일간 데이터가 필요합니다.
    """
    # 60일 이동평균 계산을 위해 최소 "3mo" (약 65 거래일) 사용
    period_map = {
        20: "1mo",
        60: "3mo",
        120: "6mo",
        252: "1y",
    }
    period = "3mo"
    for d, p in sorted(period_map.items()):
        if days <= d:
            period = p
            break

    return get_ohlcv(ticker, period=period, interval="1d")
