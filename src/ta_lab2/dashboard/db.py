"""
Dashboard DB layer -- NullPool engine singleton.

This is the ONLY place the engine is created. All query functions receive
``_engine`` as a parameter (underscore-prefix prevents st.cache_data from
hashing it).
"""

import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import resolve_db_url


@st.cache_resource
def get_engine():
    """Return a NullPool SQLAlchemy engine using the project DB URL."""
    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=NullPool)
