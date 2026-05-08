"""
repository_papertrade.py — 과제용 데이터 파일 I/O 전담

papertrade_*.json 파일들에 대한 CRUD 작업만 담당합니다.
비즈니스 로직(점수 계산, 배분 알고리즘 등)은 포함하지 않습니다.

레이어 규칙:
- models.py의 도메인 모델만 알아야 합니다
- schemas.py import 금지 (API 경계 레이어 침범)
- service_*.py import 금지 (서비스 레이어 침범)

V2 repository_journal.py와 동일한 threading.Lock 패턴을 사용합니다.
파일 동시 접근으로 인한 데이터 손상을 방지하기 위해 클래스 단위 락을 사용합니다.

관리 파일:
- papertrade_universe.json   — ETF 유니버스 목록
- papertrade_snapshots.json  — 주간 포트폴리오 스냅샷
- papertrade_orders.json     — 주간 주문 내역
- papertrade_pnl.json        — 주간 손익 기록
"""

import json
import threading
from pathlib import Path
from typing import Optional

from config import (
    UNIVERSE_PATH,
    SNAPSHOTS_PATH,
    ORDERS_PATH,
    PNL_PATH,
    MAX_ETF_COUNT,
)
from models import ETFMeta, PortfolioSnapshot, WeeklyOrder, WeeklyPnL


class PaperTradeRepository:
    """
    과제용 데이터 저장소

    싱글톤 인스턴스로 사용합니다 (모듈 하단의 repo = PaperTradeRepository()).
    모든 파일 I/O는 이 클래스를 통해서만 수행하여 데이터 일관성을 보장합니다.

    _lock을 클래스 변수로 선언하는 이유:
    싱글톤 패턴이지만 혹시 실수로 인스턴스가 여러 개 생성되어도
    같은 락을 공유하여 동시성 문제를 방지하기 위해서입니다.
    """

    _lock = threading.Lock()

    # ── 공통 내부 헬퍼 ──────────────────────────────────────────────────

    def _load_json(self, path: Path) -> list[dict]:
        """
        JSON 파일에서 원시 딕셔너리 목록을 로드합니다.

        파일이 없거나 파싱 실패 시 빈 리스트를 반환합니다.
        — 첫 실행이나 파일 손상 시에도 서버가 중단되지 않도록 합니다.
        """
        if not path.exists():
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                # 최상위가 리스트가 아닌 경우 방어 처리
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            # 파일 손상 시 빈 리스트 반환 (데이터 손실 감수, 서버 중단 방지)
            return []

    def _save_json(self, path: Path, data: list[dict]) -> None:
        """
        딕셔너리 목록을 JSON 파일에 저장합니다.

        indent=2로 사람이 읽고 편집하기 쉽게 합니다.
        ensure_ascii=False로 한글이 깨지지 않도록 합니다.
        부모 디렉터리가 없으면 자동 생성합니다.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── ETF Universe CRUD ────────────────────────────────────────────────

    def get_universe(self) -> list[ETFMeta]:
        """
        전체 ETF 유니버스 조회

        파싱 실패한 개별 항목은 건너뜁니다.
        — 스키마 변경으로 인한 이전 데이터 호환성 문제 대응입니다.
        """
        raw = self._load_json(UNIVERSE_PATH)
        universe = []
        for item in raw:
            try:
                universe.append(ETFMeta(**item))
            except Exception:
                # 잘못된 형식의 데이터는 무시하고 계속 진행
                continue
        return universe

    def save_universe(self, universe: list[ETFMeta]) -> None:
        """
        전체 ETF 유니버스 저장

        전체를 덮어씁니다. 부분 업데이트가 필요하면 add_etf/remove_etf를 사용하세요.
        model_dump()를 사용하는 이유: Pydantic v2에서 .dict()가 deprecated되었습니다.
        """
        with self._lock:
            data = [etf.model_dump() for etf in universe]
            self._save_json(UNIVERSE_PATH, data)

    def add_etf(self, etf: ETFMeta) -> list[ETFMeta]:
        """
        ETF 유니버스에 종목 추가

        중복 ticker는 업데이트로 처리합니다 (같은 ticker가 있으면 정보를 갱신합니다).
        ETF 10개 미만 제약: enabled=True인 항목이 MAX_ETF_COUNT를 초과하면 ValueError를 발생시킵니다.
        반환값: 업데이트된 전체 유니버스 (프론트엔드 즉시 반영용)
        """
        with self._lock:
            raw = self._load_json(UNIVERSE_PATH)

            # 기존 ticker 확인 — 중복이면 업데이트
            found = False
            for i, item in enumerate(raw):
                if item.get("ticker") == etf.ticker:
                    raw[i] = etf.model_dump()
                    found = True
                    break

            if not found:
                # 유니버스는 무제한 후보 풀 — 배분 시 상위 9개 자동 선택
                enabled_count = sum(
                    1 for item in raw if item.get("enabled", True)
                )
                # 새로 추가하는 ETF도 enabled라면 한도 초과 여부 확인
                raw.append(etf.model_dump())

            self._save_json(UNIVERSE_PATH, raw)

        return self.get_universe()

    def remove_etf(self, ticker: str) -> bool:
        """
        ETF 유니버스에서 종목 제거

        실제로 존재했던 종목을 제거한 경우에만 True를 반환합니다.
        물리적으로 삭제하는 이유: disabled로 처리하면 과거 스냅샷과 불일치가 생깁니다.
        """
        with self._lock:
            raw = self._load_json(UNIVERSE_PATH)
            original_len = len(raw)
            filtered = [item for item in raw if item.get("ticker") != ticker]

            if len(filtered) == original_len:
                # 해당 ticker가 존재하지 않았음
                return False

            self._save_json(UNIVERSE_PATH, filtered)
            return True

    # ── Portfolio Snapshots ──────────────────────────────────────────────

    def get_snapshots(self) -> list[PortfolioSnapshot]:
        """
        전체 포트폴리오 스냅샷 조회 (주차 오름차순 정렬)

        week 기준으로 정렬하여 시계열 분석이 용이하도록 합니다.
        """
        raw = self._load_json(SNAPSHOTS_PATH)
        snapshots = []
        for item in raw:
            try:
                snapshots.append(PortfolioSnapshot(**item))
            except Exception:
                continue
        # 주차 오름차순: 1주차 → 2주차 → ... (누적 수익률 계산에 필요)
        snapshots.sort(key=lambda s: s.week)
        return snapshots

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """
        포트폴리오 스냅샷 저장 (해당 주차 upsert)

        같은 week가 이미 있으면 덮어씁니다.
        — 주차 내 재계산이 가능하도록 하기 위해서입니다.
        """
        with self._lock:
            raw = self._load_json(SNAPSHOTS_PATH)

            # 같은 week 스냅샷이 있으면 업데이트
            found = False
            for i, item in enumerate(raw):
                if item.get("week") == snapshot.week:
                    raw[i] = snapshot.model_dump()
                    found = True
                    break

            if not found:
                raw.append(snapshot.model_dump())

            self._save_json(SNAPSHOTS_PATH, raw)

    def get_snapshot_by_week(self, week: int) -> Optional[PortfolioSnapshot]:
        """
        특정 주차의 포트폴리오 스냅샷 조회

        존재하지 않으면 None을 반환합니다.
        — 호출자(라우터)가 404 처리를 결정하게 합니다.
        """
        raw = self._load_json(SNAPSHOTS_PATH)
        for item in raw:
            if item.get("week") == week:
                try:
                    return PortfolioSnapshot(**item)
                except Exception:
                    return None
        return None

    # ── Weekly Orders ────────────────────────────────────────────────────

    def get_orders(self, week: Optional[int] = None) -> list[WeeklyOrder]:
        """
        주문 내역 조회

        week=None이면 전체 주문을 반환합니다.
        week를 지정하면 해당 주차의 주문만 필터링합니다.
        """
        raw = self._load_json(ORDERS_PATH)
        orders = []
        for item in raw:
            if week is not None and item.get("week") != week:
                continue
            try:
                orders.append(WeeklyOrder(**item))
            except Exception:
                continue
        # 주차 → ticker 순으로 정렬 (보고서 가독성을 위해)
        orders.sort(key=lambda o: (o.week, o.ticker))
        return orders

    def save_orders(self, orders: list[WeeklyOrder]) -> None:
        """
        주간 주문 목록 저장 (해당 주차 전체 교체)

        같은 week의 기존 주문을 모두 지우고 새 주문으로 교체합니다.
        — 재계산 시 이전 주문이 남아있으면 중복이 생기기 때문입니다.
        """
        if not orders:
            return

        target_week = orders[0].week

        with self._lock:
            raw = self._load_json(ORDERS_PATH)

            # 해당 주차의 기존 주문 제거
            filtered = [item for item in raw if item.get("week") != target_week]

            # 새 주문 추가
            for order in orders:
                filtered.append(order.model_dump())

            self._save_json(ORDERS_PATH, filtered)

    # ── Weekly PnL ───────────────────────────────────────────────────────

    def get_pnl(self) -> list[WeeklyPnL]:
        """
        전체 주간 손익 기록 조회 (주차 오름차순 정렬)

        누적 수익률 계산을 위해 반드시 주차 오름차순으로 반환합니다.
        """
        raw = self._load_json(PNL_PATH)
        pnl_list = []
        for item in raw:
            try:
                pnl_list.append(WeeklyPnL(**item))
            except Exception:
                continue
        pnl_list.sort(key=lambda p: p.week)
        return pnl_list

    def save_pnl(self, pnl: WeeklyPnL) -> None:
        """
        주간 손익 기록 저장 (해당 주차 upsert)

        같은 week가 있으면 덮어씁니다.
        — 금요일 종가 입력 후 재계산이 가능하도록 합니다.
        """
        with self._lock:
            raw = self._load_json(PNL_PATH)

            found = False
            for i, item in enumerate(raw):
                if item.get("week") == pnl.week:
                    raw[i] = pnl.model_dump()
                    found = True
                    break

            if not found:
                raw.append(pnl.model_dump())

            self._save_json(PNL_PATH, raw)

    def get_pnl_by_week(self, week: int) -> Optional[WeeklyPnL]:
        """
        특정 주차의 손익 기록 조회

        존재하지 않으면 None을 반환합니다.
        """
        raw = self._load_json(PNL_PATH)
        for item in raw:
            if item.get("week") == week:
                try:
                    return WeeklyPnL(**item)
                except Exception:
                    return None
        return None


# 싱글톤 인스턴스 — 모든 라우터와 서비스에서 이 객체를 import하여 사용합니다.
# 인스턴스를 하나만 생성하는 이유: Lock 상태를 공유하여 동시성을 보장하기 위해서입니다.
repo = PaperTradeRepository()
