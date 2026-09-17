"""PostgreSQL 전문검색 — trigram + simple tsvector 결합 (ARCHITECTURE.md §5.3).

한국어 형태소 사전(mecab-ko 등)을 설치 조건으로 걸지 않는다. 사내 오프라인 환경에서
빌드를 강제하는 것은 운영 리스크가 크기 때문이다. 대신 역할을 나눈다.

  · tsvector('simple')  : 영문·숫자·IP·장비명처럼 토큰 경계가 분명한 것에 강하다.
  · pg_trgm ILIKE       : 조사가 붙는 한국어("방화벽을", "방화벽의")를 잡는다.

둘을 OR 로 묶어 재현율을 확보하고, 랭킹은 ts_rank 로 준다.
형태소 분석기를 쓰게 되면 이 파일만 고치면 된다.
"""
from __future__ import annotations

from sqlalchemy import func, literal_column, or_
from sqlalchemy.sql.elements import ColumnElement

from app.models.handover import Handover
from app.search.backends.base import LIKE_ESCAPE, escape_like

#: 마이그레이션(a1b2c3d4e5f6)이 트리거로 채우는 컬럼. ORM 모델에는 없다.
_TSV = literal_column("handovers.search_tsv")
_CONFIG = "simple"


class PostgresSearch:
    name = "postgres-tsv+trgm"

    def _tsquery(self, q: str):
        return func.websearch_to_tsquery(_CONFIG, q)

    def text_condition(self, q: str) -> ColumnElement[bool]:
        term = q.strip()
        like = Handover.search_text.ilike(f"%{escape_like(term)}%", escape=LIKE_ESCAPE)
        # 2글자 이하는 trigram 인덱스를 탈 수 없어 순차 스캔이 된다. 그래도 ILIKE 를
        # 유지한다 — 이 도메인에서는 느린 것보다 놓치는 것이 훨씬 나쁘다(§92 1순위).
        return or_(_TSV.op("@@")(self._tsquery(term)), like)

    def rank_expression(self, q: str) -> ColumnElement | None:
        return func.ts_rank(_TSV, self._tsquery(q.strip()))
