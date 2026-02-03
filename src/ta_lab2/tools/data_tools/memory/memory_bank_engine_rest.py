"""Memory Bank REST engine for semantic memory search and retrieval."""
from __future__ import annotations

# memory_bank_engine_rest.py

r"""
Quick knobs (optional)
You can control behavior via env vars (no code changes):
MB_ENABLE_GATING=1 (default true)
MB_MIN_QUERY_CHARS=12
MB_MAX_LIMIT=20
MB_ENABLE_CACHE=1 (default true)
MB_CACHE_TTL_SECONDS=600
MB_CACHE_MAX_ITEMS=256
"""


import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import google.auth
import google.auth.transport.requests


# =========================
# Config
# =========================

@dataclass(frozen=True)
class MBConfig:
    project_id: str
    region: str
    reasoning_engine_id: str
    scope: Dict[str, str]


def _env_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")


def _normalize_query(q: str) -> str:
    # Normalize for cache key: strip, collapse whitespace, lowercase
    q2 = (q or "").strip().lower()
    q2 = re.sub(r"\s+", " ", q2)
    return q2


# =========================
# Memory Bank REST Client
# =========================

class MemoryBankREST:
    def __init__(self, cfg: MBConfig):
        if not cfg.scope:
            raise ValueError("Memory scope is required (e.g. {'app':'ta_lab2'}).")
        self.cfg = cfg
        self._sess: Optional[google.auth.transport.requests.AuthorizedSession] = None

    def _get_session(self) -> google.auth.transport.requests.AuthorizedSession:
        if self._sess is None:
            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            self._sess = google.auth.transport.requests.AuthorizedSession(creds)
        return self._sess

    @property
    def base(self) -> str:
        return f"https://{self.cfg.region}-aiplatform.googleapis.com/v1beta1"

    @property
    def engine_name(self) -> str:
        return (
            f"projects/{self.cfg.project_id}/locations/{self.cfg.region}/"
            f"reasoningEngines/{self.cfg.reasoning_engine_id}"
        )

    def retrieve(self, *, query: str, limit: int = 5) -> Dict[str, Any]:
        url = f"{self.base}/{self.engine_name}/memories:retrieve"
        body = {"scope": self.cfg.scope, "query": query}
        sess = self._get_session()
        r = sess.post(url, json=body, timeout=120)
        if r.status_code >= 300:
            raise RuntimeError(f"retrieve failed: {r.status_code} {r.text}")
        data = r.json()
        if isinstance(data.get("memories"), list):
            data["memories"] = data["memories"][: max(0, limit)]
        return data

    def create(
        self,
        *,
        user_id: str,
        text_content: str,
        scope: Optional[Dict[str, str]] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base}/{self.engine_name}/memories"
        body: Dict[str, Any] = {
            "memory": {
                "scope": scope or self.cfg.scope,
                "textContent": text_content,
            }
        }
        if labels:
            body["memory"]["labels"] = labels

        sess = self._get_session()
        resp = sess.post(url, json=body, timeout=120)
        if resp.status_code >= 300:
            raise RuntimeError(f"create failed: {resp.status_code} {resp.text}")
        return resp.json()


# =========================
# Tiny TTL Cache (in-memory)
# =========================

class TTLCache:
    """
    Very small in-memory TTL cache for retrieval results.
    - Not persistent.
    - Good for reducing duplicate retrieval calls.
    """
    def __init__(self, *, max_items: int, ttl_seconds: int):
        self.max_items = max(0, int(max_items))
        self.ttl_seconds = max(0, int(ttl_seconds))
        self._store: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if self.max_items <= 0 or self.ttl_seconds <= 0:
            return None
        item = self._store.get(key)
        if not item:
            return None
        ts, val = item
        if (time.time() - ts) > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, val: Dict[str, Any]) -> None:
        if self.max_items <= 0 or self.ttl_seconds <= 0:
            return

        # Evict oldest if over capacity
        if len(self._store) >= self.max_items:
            oldest_key = min(self._store.items(), key=lambda kv: kv[1][0])[0]
            self._store.pop(oldest_key, None)

        self._store[key] = (time.time(), val)


# =========================
# Engine
# =========================

class TA_Lab2_Memory_Engine:
    """
    Reasoning Engine app: uses Memory Bank via REST.
    Adds: retrieval gating + TTL caching to reduce retrieval calls/cost.
    IMPORTANT: No vertexai.agent imports.
    """

    def __init__(self, cfg_dict: Dict[str, Any]):
        self.project_id = cfg_dict["project_id"]
        self.region = cfg_dict["region"]
        self.reasoning_engine_id = cfg_dict["reasoning_engine_id"]
        self.scope = cfg_dict["scope"]

        self.mb = MemoryBankREST(MBConfig(
            project_id=self.project_id,
            region=self.region,
            reasoning_engine_id=self.reasoning_engine_id,
            scope=self.scope,
        ))

        # Tunables (safe defaults)
        self.min_query_chars = _env_int("MB_MIN_QUERY_CHARS", 12)
        self.max_limit = _env_int("MB_MAX_LIMIT", 20)
        self.cache_ttl_seconds = _env_int("MB_CACHE_TTL_SECONDS", 600)  # 10 min
        self.cache_max_items = _env_int("MB_CACHE_MAX_ITEMS", 256)
        self.enable_cache = _env_bool("MB_ENABLE_CACHE", True)
        self.enable_gating = _env_bool("MB_ENABLE_GATING", True)

        self.cache = TTLCache(
            max_items=self.cache_max_items if self.enable_cache else 0,
            ttl_seconds=self.cache_ttl_seconds if self.enable_cache else 0,
        )

    def _clamp_limit(self, limit: int) -> int:
        try:
            n = int(limit)
        except Exception:
            n = 5
        if n < 0:
            n = 0
        if n > self.max_limit:
            n = self.max_limit
        return n

    def _should_retrieve(self, query: str) -> Tuple[bool, str]:
        """
        Cheap “mem0-style” gate to avoid calling Memory Bank unnecessarily.
        Returns (should_retrieve, reason).
        """
        q = (query or "").strip()
        if not q:
            return False, "empty_query"

        q_norm = _normalize_query(q)

        # Skip very short / low-signal messages
        if len(q_norm) < self.min_query_chars:
            return False, "too_short"

        # Skip small-talk / acknowledgements
        smalltalk = {
            "hi", "hey", "hello", "thanks", "thank you", "ok", "okay", "k",
            "lol", "lmao", "cool", "nice", "got it", "sounds good", "yup", "yep"
        }
        if q_norm in smalltalk:
            return False, "smalltalk"

        # Heuristic: if user explicitly references memory, allow retrieval
        memory_triggers = ("remember", "last time", "previous", "earlier", "we talked", "you said", "remind me")
        if any(t in q_norm for t in memory_triggers):
            return True, "explicit_memory_trigger"

        # Heuristic: if query looks like a concrete task/question, retrieve
        # (This is conservative; you can tighten later)
        if "?" in q_norm:
            return True, "question_mark"

        # If it includes named-entity-ish tokens (very rough), retrieve
        # Example: "Emily", "Lisbel", "ta_lab2", etc.
        if re.search(r"\b[a-z0-9_]{3,}\b", q_norm):
            return True, "has_tokens"

        return True, "default"

    def query(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """
        Returns a dict with:
        - ok
        - query
        - scope
        - retrieved (bool)
        - cache_hit (bool)
        - gate_reason
        - memory_bank (optional)
        """
        try:
            limit_n = self._clamp_limit(limit)
            q_norm = _normalize_query(query)

            retrieved = False
            cache_hit = False
            gate_reason = "gating_disabled"

            # Gate retrieval
            if self.enable_gating:
                should, gate_reason = self._should_retrieve(query)
                if not should:
                    return {
                        "ok": True,
                        "query": query,
                        "limit": limit_n,
                        "scope": self.scope,
                        "retrieved": False,
                        "cache_hit": False,
                        "gate_reason": gate_reason,
                    }

            # Cache
            if self.enable_cache and q_norm:
                cached = self.cache.get(f"{q_norm}|{limit_n}")
                if cached is not None:
                    cache_hit = True
                    return {
                        "ok": True,
                        "query": query,
                        "limit": limit_n,
                        "scope": self.scope,
                        "retrieved": True,
                        "cache_hit": True,
                        "gate_reason": gate_reason,
                        "memory_bank": cached,
                    }

            # Retrieve from Memory Bank
            mb_data = self.mb.retrieve(query=query, limit=limit_n)
            retrieved = True

            if self.enable_cache and q_norm:
                self.cache.set(f"{q_norm}|{limit_n}", mb_data)

            return {
                "ok": True,
                "query": query,
                "limit": limit_n,
                "scope": self.scope,
                "retrieved": retrieved,
                "cache_hit": cache_hit,
                "gate_reason": gate_reason,
                "memory_bank": mb_data,
            }

        except Exception as e:
            return {
                "ok": False,
                "query": query,
                "error": str(e),
                "scope": self.scope,
                "retrieved": False,
                "cache_hit": False,
            }
