# src/ta_lab2/time/dim_sessions.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine


@dataclass(frozen=True)
class SessionMeta:
    asset_id: int
    timezone: str
    session_open_local: str  # "HH:MM:SS"
    session_close_local: str
    is_24h: bool


class DimSessions:
    def __init__(self, df: pd.DataFrame):
        self._by_id = {
            int(row["asset_id"]): SessionMeta(
                asset_id=int(row["asset_id"]),
                timezone=row["timezone"],
                session_open_local=str(row["session_open_local"]),
                session_close_local=str(row["session_close_local"]),
                is_24h=bool(row["is_24h"]),
            )
            for _, row in df.iterrows()
        }

    @classmethod
    def from_db(cls, db_url: str) -> "DimSessions":
        engine = create_engine(db_url)
        df = pd.read_sql("SELECT * FROM dim_sessions", engine)
        return cls(df)

    def get_session(self, asset_id: int) -> Optional[SessionMeta]:
        return self._by_id.get(asset_id)
