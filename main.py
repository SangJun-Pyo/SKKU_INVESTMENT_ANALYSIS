"""
main.py — MarkovPortfolio V4 FastAPI 앱 진입점

서버 설정, 미들웨어, 라우터 등록을 담당합니다.
비즈니스 로직은 service_*.py에 있고, 여기서는 조립만 합니다.

V2 대비 변경사항:
- 관리 JSON 파일이 4개로 증가 (universe, snapshots, orders, pnl)
- 모두 data/ 디렉터리 하위에 생성됩니다
- Gemini 관련 설정 제거
"""

import sys
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

# Python 3.13 + Windows socketpair() 버그 패치
# socket.socketpair()의 _fallback_socketpair 구현이 WinError 10014를 발생시키는 문제를
# 127.0.0.1 루프백 소켓 쌍으로 직접 대체하여 해결합니다.
if sys.platform == "win32":
    import socket as _socket_mod

    def _fixed_socketpair(family=_socket_mod.AF_INET,
                          type=_socket_mod.SOCK_STREAM,
                          proto=0):
        listener = _socket_mod.socket(family, type, proto)
        listener.setsockopt(_socket_mod.SOL_SOCKET, _socket_mod.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        client = _socket_mod.socket(family, type, proto)
        try:
            client.setblocking(True)
            client.connect(("127.0.0.1", port))
            server, _ = listener.accept()
        except Exception:
            client.close()
            raise
        finally:
            listener.close()
        return server, client

    _socket_mod.socketpair = _fixed_socketpair

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import config
from api_routes import router


# ── 정적 파일 캐시 방지 미들웨어 ─────────────────────────────────────────
# 왜 필요한가: 브라우저는 304 Not Modified 응답을 받으면 캐시된 파일을 그대로 씁니다.
# 개발 중 app.js 등을 수정해도 브라우저가 이전 버전을 보여주는 문제가 발생합니다.
# /static/ 경로의 모든 응답에 캐시 무효화 헤더를 추가해 항상 최신 파일을 받도록 합니다.
class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            # Cache-Control: no-store — 브라우저가 응답을 캐시에 저장하지 못하게 합니다.
            # no-cache — 저장해도 서버에 재검증 요청을 보내도록 강제합니다.
            # must-revalidate — 만료된 캐시는 반드시 재검증 후 사용합니다.
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            # Pragma: no-cache — HTTP/1.0 호환성을 위한 구형 헤더입니다.
            response.headers["Pragma"] = "no-cache"
            # Expires: 0 — 과거 시간으로 설정해 즉시 만료 처리합니다.
            response.headers["Expires"] = "0"
        return response


# ── 라이프사이클 이벤트 ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 라이프사이클 이벤트 핸들러

    서버 시작 시 데이터 디렉터리와 JSON 파일들을 초기화합니다.
    yield 전: startup (초기화), yield 후: shutdown (정리)

    JSON 파일을 미리 생성하는 이유:
    repository_papertrade.py의 _load_json()은 파일이 없으면 빈 리스트를 반환하지만,
    save_json() 호출 전에 파일이 존재하지 않으면 부모 디렉터리 생성이 필요합니다.
    미리 생성해두면 첫 번째 쓰기 요청에서 에러가 발생하지 않습니다.
    """
    # data/ 디렉터리 생성 (없으면 자동 생성)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[startup] 데이터 디렉터리: {config.DATA_DIR}")

    # 4개 JSON 파일 초기화 — 파일이 없을 때만 빈 배열로 생성합니다.
    # 기존 데이터가 있는 경우 덮어쓰지 않기 위해 exists() 체크를 먼저 합니다.
    init_files = [
        (config.UNIVERSE_PATH,   "ETF 유니버스"),
        (config.SNAPSHOTS_PATH,  "포트폴리오 스냅샷"),
        (config.ORDERS_PATH,     "주간 주문"),
        (config.PNL_PATH,        "주간 손익"),
    ]

    for file_path, label in init_files:
        if not file_path.exists():
            file_path.write_text("[]", encoding="utf-8")
            print(f"[startup] {label} 파일 생성: {file_path.name}")
        else:
            print(f"[startup] {label} 파일 확인: {file_path.name}")

    print(f"[startup] 서버 준비 완료 — http://{config.HOST}:{config.PORT}")
    print(f"[startup] Claude 모델: {config.CLAUDE_MODEL}")
    print(f"[startup] 기본 자본: {config.BASE_CAPITAL:,.0f} 원")
    print(f"[startup] 총 익스포저 상한: {config.MAX_TOTAL_EXPOSURE:,.0f} 원")

    yield  # 서버 실행 중

    # 종료 시: 현재는 별도 정리 작업 없음 (파일 기반이라 flush 불필요)
    print("[shutdown] MarkovPortfolio V4 서버 종료")


# ── 앱 생성 ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="MarkovPortfolio V4",
    description="과제용 포트폴리오 관리 + AI Investment Committee",
    version="4.0.0",
    lifespan=lifespan,
)


# ── 미들웨어 등록 ─────────────────────────────────────────────────────────

# CORS를 allow_origins=["*"]로 설정하는 이유:
# 로컬 개발 환경에서 포트 차이(예: 3000 vs 8000)로 인한 CORS 오류를 방지합니다.
# 프로덕션 배포 시에는 특정 도메인으로 제한해야 합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 캐시 방지 미들웨어 등록 순서 주의:
# 미들웨어는 등록 역순(LIFO)으로 실행됩니다.
# NoCacheStaticMiddleware가 CORSMiddleware보다 나중에 등록되어
# 실행 시에는 NoCacheStaticMiddleware가 먼저 처리합니다.
# 이렇게 하는 이유: 캐시 헤더 추가 후 CORS 헤더가 덮어쓰이지 않도록 합니다.
app.add_middleware(NoCacheStaticMiddleware)


# ── 라우터 등록 ──────────────────────────────────────────────────────────

# 모든 API 엔드포인트는 api_routes.py에 정의됩니다.
# prefix 없이 등록하는 이유: 라우터 내부에서 /papertrade/* 경로를 직접 정의합니다.
app.include_router(router)


# ── 정적 파일 서빙 ────────────────────────────────────────────────────────

# /static 경로로 frontend/ 디렉터리를 서빙합니다.
# 예: GET /static/app.js → frontend/app.js 파일 반환
# index.html은 api_routes.py의 GET / 엔드포인트가 처리합니다.
_frontend_dir = Path(__file__).parent / "frontend"
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")
    print(f"[startup] 정적 파일 서빙: {_frontend_dir}")
else:
    # frontend/ 디렉터리가 없어도 서버는 시작됩니다 (API만 사용 가능)
    print("[startup] 경고: frontend/ 디렉터리가 없습니다. 정적 파일 서빙 비활성화.")
