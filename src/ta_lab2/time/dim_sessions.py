# src/ta_lab2/time/dim_sessions.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL


@dataclass(frozen=True)
class SessionKey:
    asset_class: str
    region: str
    venue: str
    asset_key_type: str
    asset_key: str
    session_type: str = "PRIMARY"


@dataclass(frozen=True)
class SessionMeta:
    asset_id: Optional[int]
    timezone: str
    session_open_local: str  # "HH:MM:SS"
    session_close_local: str
    is_24h: bool


def _resolve_db_url(db_url: Optional[str]) -> str:
    url = db_url or TARGET_DB_URL
    if not url:
        raise RuntimeError("No DB URL provided AND TARGET_DB_URL missing in ta_lab2.config.")
    return url


class DimSessions:
    def __init__(self, df: pd.DataFrame):
        self._by_key: Dict[SessionKey, SessionMeta] = {}
        self._by_id: Dict[int, Tuple[SessionKey, SessionMeta]] = {}

        for _, row in df.iterrows():
            key = SessionKey(
                asset_class=str(row["asset_class"]),
                region=str(row["region"]),
                venue=str(row["venue"]),
                asset_key_type=str(row["asset_key_type"]),
                asset_key=str(row["asset_key"]),
                session_type=str(row["session_type"]),
            )

            asset_id_val = row.get("asset_id")
            asset_id = int(asset_id_val) if pd.notna(asset_id_val) else None

            meta = SessionMeta(
                asset_id=asset_id,
                timezone=str(row["timezone"]),
                session_open_local=str(row["session_open_local"]),
                session_close_local=str(row["session_close_local"]),
                is_24h=bool(row["is_24h"]),
            )

            self._by_key[key] = meta
            if asset_id is not None:
                self._by_id[asset_id] = (key, meta)

    @classmethod
    def from_db(cls, db_url: Optional[str] = None) -> "DimSessions":
        url = _resolve_db_url(db_url)
        engine = create_engine(url)
        df = pd.read_sql("SELECT * FROM public.dim_sessions", engine)
        return cls(df)

    def get_session_by_key(self, key: SessionKey) -> Optional[SessionMeta]:
        return self._by_key.get(key)

    def get_session(self, asset_id: int) -> Optional[SessionMeta]:
        pair = self._by_id.get(asset_id)
        return pair[1] if pair else None

    # -----------------------------
    # DST-safe session windows (DB truth) — by composite key (recommended)
    # -----------------------------
    def session_windows_utc_by_key(
        self,
        *,
        key: SessionKey,
        start_date: date,
        end_date: date,
        db_url: Optional[str] = None,
    ) -> pd.DataFrame:
        if end_date < start_date:
            raise ValueError(f"end_date ({end_date}) < start_date ({start_date})")

        sql = text(
            """
            WITH d AS (
              SELECT gs::date AS session_date
              FROM generate_series(
                CAST(:start_date AS date),
                CAST(:end_date   AS date),
                interval '1 day'
              ) AS gs
            )
            SELECT
              r.asset_class,
              r.region,
              r.venue,
              r.asset_key_type,
              r.asset_key,
              r.session_type,
              r.session_date,
              r.timezone,
              r.session_open_local,
              r.session_close_local,
              r.is_24h,
              r.open_utc,
              r.close_utc
            FROM d
            CROSS JOIN LATERAL public.dim_session_instants_for_date(
              :asset_class,
              :region,
              :venue,
              :asset_key_type,
              :asset_key,
              :session_type,
              d.session_date
            ) AS r
            ORDER BY r.session_date;
            """
        )

        params = {
            "start_date": start_date,
            "end_date": end_date,
            "asset_class": key.asset_class,
            "region": key.region,
            "venue": key.venue,
            "asset_key_type": key.asset_key_type,
            "asset_key": key.asset_key,
            "session_type": key.session_type,
        }

        url = _resolve_db_url(db_url)
        engine = create_engine(url)
        with engine.connect() as conn:
            return pd.read_sql(sql, conn, params=params)

    def session_window_utc_for_date_by_key(
        self,
        *,
        key: SessionKey,
        session_date: date,
        db_url: Optional[str] = None,
    ) -> pd.DataFrame:
        return self.session_windows_utc_by_key(
            key=key,
            start_date=session_date,
            end_date=session_date,
            db_url=db_url,
        )

    # -----------------------------
    # Optional asset_id API (works only if asset_id is populated)
    # -----------------------------
    def session_windows_utc(
        self,
        *,
        asset_id: int,
        start_date: date,
        end_date: date,
        db_url: Optional[str] = None,
    ) -> pd.DataFrame:
        s = self.get_session(asset_id)
        if s is None:
            raise KeyError(f"asset_id={asset_id} not found in dim_sessions (or asset_id is NULL)")

        sql = text(
            """
            WITH d AS (
              SELECT gs::date AS session_date
              FROM generate_series(
                CAST(:start_date AS date),
                CAST(:end_date   AS date),
                interval '1 day'
              ) AS gs
            )
            SELECT
              :asset_id::bigint AS asset_id,
              d.session_date,
              :timezone::text AS timezone,
              :open_local::time AS session_open_local,
              :close_local::time AS session_close_local,
              :is_24h::boolean AS is_24h,
              inst.open_utc,
              inst.close_utc
            FROM d
            CROSS JOIN LATERAL public.session_instants_for_date(
              d.session_date,
              :timezone::text,
              :open_local::time,
              :close_local::time,
              :is_24h::boolean
            ) AS inst
            ORDER BY d.session_date;
            """
        )

        params = {
            "asset_id": int(asset_id),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": s.timezone,
            "open_local": s.session_open_local,
            "close_local": s.session_close_local,
            "is_24h": bool(s.is_24h),
        }

        url = _resolve_db_url(db_url)
        engine = create_engine(url)
        with engine.connect() as conn:
            return pd.read_sql(sql, conn, params=params)

    def session_window_utc_for_date(
        self,
        *,
        asset_id: int,
        session_date: date,
        db_url: Optional[str] = None,
    ) -> pd.DataFrame:
        return self.session_windows_utc(
            asset_id=asset_id,
            start_date=session_date,
            end_date=session_date,
            db_url=db_url,
        )
