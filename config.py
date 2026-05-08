"""
config.py — MarkovPortfolio V4 전역 설정

모든 모듈이 이 파일을 통해 설정값을 읽습니다.
환경변수(API 키 등)는 .env 파일에서 로드하여 코드에 하드코딩하지 않습니다.

V2 대비 변경사항:
- Gemini 제거, Claude 단일 AI로 통일 (과제 제출 목적)
- trading_journal.json 대신 papertrade_*.json 4개 파일로 분리
- 과제 도메인 상수(자본금, 이자율 등) 추가
"""

from pathlib import Path
from dotenv import load_dotenv
import os

# 프로젝트 루트를 기준으로 .env를 명시적으로 찾아 로드합니다.
# 다른 디렉터리에서 uvicorn을 실행해도 올바른 .env를 읽기 위해 절대 경로를 사용합니다.
BASE_DIR: Path = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ── AI API 키 ────────────────────────────────────────────────────────────
# 하드코딩 금지: .env 파일에 ANTHROPIC_API_KEY=sk-ant-... 형식으로 저장하세요.
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")


# ── 서버 설정 ────────────────────────────────────────────────────────────
# 로컬 개발 전용 바인딩. 외부 노출이 필요하면 0.0.0.0으로 변경하세요.
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))


# ── 파일 경로 ────────────────────────────────────────────────────────────
# 과제용 데이터와 기존 매매 일지를 섞지 않기 위해 papertrade_* 접두사로 분리합니다.
# Path 객체로 관리해 Windows/Unix 경로 구분자 문제를 방지합니다.
DATA_DIR: Path = BASE_DIR / "data"

UNIVERSE_PATH: Path   = DATA_DIR / "papertrade_universe.json"    # ETF 유니버스
SNAPSHOTS_PATH: Path  = DATA_DIR / "papertrade_snapshots.json"   # 주간 포트폴리오 스냅샷
ORDERS_PATH: Path     = DATA_DIR / "papertrade_orders.json"      # 주간 주문 내역
PNL_PATH: Path        = DATA_DIR / "papertrade_pnl.json"         # 주간 손익 기록


# ── 캐시 설정 ────────────────────────────────────────────────────────────
# yfinance OHLCV 결과를 메모리에 캐시합니다.
# 60초면 동일 종목 반복 요청 시 API 호출 없이 재사용 가능합니다.
CACHE_TTL: int = int(os.getenv("CACHE_TTL", "60"))


# ── Claude 모델 설정 ─────────────────────────────────────────────────────
# 모델명을 한 곳에서 관리하면 버전 업그레이드 시 이 파일만 수정하면 됩니다.
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


# ── 과제 도메인 상수 ─────────────────────────────────────────────────────
# 수업 과제 규칙을 코드에 산재시키지 않고 여기서 중앙 관리합니다.
# 변경 시 이 파일만 수정하면 모든 서비스에 일관되게 반영됩니다.

BASE_CAPITAL: float          = 10_000_000_000   # 기본 자본: 100억 원
MAX_BORROWING: float         = 3_000_000_000    # 최대 차입: 30억 원
MAX_TOTAL_EXPOSURE: float    = 13_000_000_000   # 총 익스포저 상한: 130억 원
MAX_ALPHA_EXPOSURE: float    = 3_000_000_000    # Alpha 배분 최대: 30억 원

WEEKLY_CASH_INTEREST: float  = 0.00035  # 현금 이자: 주간 0.035%
WEEKLY_BORROW_COST: float    = 0.00070  # 차입 이자: 주간 0.07%
MAX_ETF_COUNT: int           = 9        # ETF 개수 상한: 10개 미만 (9개까지 허용)
MAX_SHORT_RATIO: float       = 0.30     # Short/ETF 차입 비율 상한: 30%
MAX_LEVERAGE_RATIO: float    = 0.30     # 레버리지 비율 상한: 30%

# 벤치마크 비중: 코스피200 40%, S&P500 헷지 30%, S&P500 비헷지 30%
CLASS_BENCHMARK: dict = {
    "kospi200":       0.40,
    "sp500Hedged":    0.30,
    "sp500Unhedged":  0.30,
}

# Core 배분 기본값: 100억을 벤치마크 비중대로 분배
DEFAULT_CORE_ALLOCATION: dict = {
    "kospi200Core":       4_000_000_000,   # 40억
    "sp500HedgedCore":    3_000_000_000,   # 30억
    "sp500UnhedgedCore":  3_000_000_000,   # 30억
}

# 리스크 위반 임계값: 이 값을 초과하면 BLOCK 또는 WARN 처리합니다.
RISK_THRESHOLDS: dict = {
    "max_weekly_volatility": 0.015,       # 주간 변동성 1.5% 이내
    "min_var_95":            -200_000_000, # 95% VaR 최대 손실 2억 원
    "max_benchmark_beta":    1.20,         # 벤치마크 대비 베타 1.2 이내
}
