"""REST client for Vertex AI Memory Bank.

Provides access to Vertex AI Generative AI Memory Bank endpoints:
- retrieve: Search memories by query with scope filtering
- create: Add new memories to the bank

Requires Google Cloud authentication (ADC via gcloud or workload identity).

Usage:
    from ta_lab2.tools.data_tools.memory.memory_bank_rest import (
        MemoryBankConfig,
        MemoryBankREST
    )

    config = MemoryBankConfig(
        project_id="my-project",
        region="us-central1",
        reasoning_engine_id="12345",
        scope={"app": "ta_lab2", "env": "dev"}
    )

    client = MemoryBankREST(config)
    results = client.retrieve(
        user_id="user@example.com",
        query="How do I calculate EMA?",
        limit=5
    )

Dependencies:
    - google-auth: pip install google-auth
    - requests: pip install requests
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    import google.auth
    import google.auth.transport.requests
except ImportError:
    raise ImportError(
        "Google Auth libraries required. Install with: pip install google-auth"
    )

try:
    import requests
except ImportError:
    raise ImportError("Requests library required. Install with: pip install requests")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryBankConfig:
    """Configuration for Vertex AI Memory Bank.

    Attributes:
        project_id: GCP project ID
        region: GCP region (e.g., "us-central1")
        reasoning_engine_id: Numeric ID or full resource tail
        api_version: API version (default: "v1beta1")
        scope: Required scope dict for retrieve (e.g., {"app": "ta_lab2", "env": "dev"})
    """

    project_id: str
    region: str
    reasoning_engine_id: str  # numeric id or full resource tail
    api_version: str = "v1beta1"

    # REQUIRED for retrieve: must match memory scope exactly
    scope: Dict[str, str] = None  # e.g. {"app": "ta_lab2", "env": "dev"}


class MemoryBankREST:
    """REST client for Vertex AI Generative AI Memory Bank.

    Uses Vertex AI Generative AI REST endpoints for Memory Bank:
    - retrieve: projects.locations.reasoningEngines.memories.retrieve
    - create:   projects.locations.reasoningEngines.memories.create

    Authentication:
        Uses Application Default Credentials (ADC):
        - Local: gcloud auth application-default login
        - GCP: Workload identity or service account

    Note:
        Retrieve requires scope (map) and matches exactly.
    """

    def __init__(self, cfg: MemoryBankConfig):
        """Initialize Memory Bank REST client.

        Args:
            cfg: MemoryBankConfig with project, region, engine ID, and scope

        Raises:
            ValueError: If scope is missing or invalid
        """
        if not cfg.scope or not isinstance(cfg.scope, dict):
            raise ValueError(
                "cfg.scope is required and must be a dict, e.g. {'app':'ta_lab2','env':'dev'}"
            )
        self.cfg = cfg
        self._session = google.auth.transport.requests.AuthorizedSession(
            self._credentials()
        )

    def _credentials(self):
        """Get Google Cloud credentials via ADC."""
        # Uses ADC: gcloud auth application-default login OR workload identity in GCP
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return creds

    @property
    def _base(self) -> str:
        """Get base API URL."""
        return f"https://{self.cfg.region}-aiplatform.googleapis.com/{self.cfg.api_version}"

    @property
    def _engine_name(self) -> str:
        """Get full reasoning engine resource name."""
        # REST resource is:
        # projects/{project}/locations/{region}/reasoningEngines/{id}
        return f"projects/{self.cfg.project_id}/locations/{self.cfg.region}/reasoningEngines/{self.cfg.reasoning_engine_id}"

    def retrieve(
        self, *, user_id: str, query: str, limit: int = 5, filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve memories by semantic search.

        Args:
            user_id: User identifier
            query: Search query text
            limit: Maximum results to return (client-side cap)
            filter: Optional filter expression

        Returns:
            Response dict with 'memories' list

        Raises:
            RuntimeError: If API call fails
        """
        url = f"{self._base}/{self._engine_name}/memories:retrieve"
        body: Dict[str, Any] = {
            "scope": self.cfg.scope,
            "query": query,
            # Many list-style APIs accept pageSize; retrieve may return ranked results without it.
            # We still include limit as a client-side cap.
        }
        if filter:
            body["filter"] = filter

        resp = self._session.post(url, json=body, timeout=120)
        if resp.status_code >= 300:
            raise RuntimeError(f"retrieve failed: {resp.status_code} {resp.text}")

        data = resp.json()
        # Client-side cap
        if "memories" in data and isinstance(data["memories"], list):
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
        """Create a new memory in the bank.

        Args:
            user_id: User identifier
            text_content: Memory text content
            scope: Optional scope override (uses config scope if not provided)
            labels: Optional resource labels

        Returns:
            Response dict with created memory details

        Raises:
            RuntimeError: If API call fails
        """
        url = f"{self._base}/{self._engine_name}/memories"
        body: Dict[str, Any] = {
            "memory": {
                "scope": scope or self.cfg.scope,
                "textContent": text_content,
            }
        }
        # Some Google APIs accept "labels" on resources; keep optional.
        if labels:
            body["memory"]["labels"] = labels

        # Some APIs require user_id via header or within body; Memory Bank is user-scoped conceptually.
        # If your endpoint requires it explicitly, add it here.
        # body["userId"] = user_id

        resp = self._session.post(url, json=body, timeout=120)
        if resp.status_code >= 300:
            raise RuntimeError(f"create failed: {resp.status_code} {resp.text}")
        return resp.json()


__all__ = ["MemoryBankConfig", "MemoryBankREST"]
