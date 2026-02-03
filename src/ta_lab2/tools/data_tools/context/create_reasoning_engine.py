"""Create and deploy Vertex AI reasoning engine with memory bank integration."""
from __future__ import annotations

# create_reasoning_engine.py (using memory_bank_engine_rest)
r"""
Install dependencies:
pip install "google-cloud-aiplatform" "vertexai" "requests" "google-auth" "cloudpickle==3.0.0"

If you plan to enable the optional router deps:
pip install rank-bm25 rapidfuzz

Authenticate to GCP:
gcloud auth application-default login

Set required environment variables:
Must set:
VERTEX_STAGING_BUCKET
VERTEX_MEMORY_AGENT_ID

$env:GCP_PROJECT_ID = "ta-lab2"              # or your project id
$env:VERTEX_REGION = "us-central1"           # change if needed
$env:VERTEX_STAGING_BUCKET = "gs://YOUR_BUCKET_NAME"
$env:VERTEX_MEMORY_AGENT_ID = "YOUR_MEMORY_AGENT_ID"
$env:VERTEX_MEMORY_SCOPE_JSON = '{"app":"ta_lab2","user_id":"adam"}'
$env:VERTEX_REQUIRE_USER_ID_IN_SCOPE = "1"

Optional extra environment variables:
$env:VERTEX_ENABLE_ROUTER_DEPS = "1"
# $env:VERTEX_EXTRA_REQUIREMENTS = "somepkg,otherpkg==1.2.3"
# $env:VERTEX_EXTRA_PACKAGES = "router.py,utils.py"
# $env:VERTEX_PACKAGE_ALL_PY = "1"
# $env:VERTEX_ENGINE_REF_PATH = "reasoning_engine_ref.json"
# $env:VERTEX_ENGINE_DISPLAY_NAME = "ta_lab2 Memory Engine (REST)"
# $env:VERTEX_ENGINE_DESCRIPTION = "Memory engine for ta_lab2 using REST"

To run from the directory containing this file:
python .\create_reasoning_engine.py

"""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

try:
    import vertexai
    from vertexai.preview import reasoning_engines
except ImportError:
    print(
        "Error: Vertex AI library not installed. Install with: pip install google-cloud-aiplatform vertexai"
    )
    import sys

    sys.exit(1)

# Import the self-contained engine
try:
    from ta_lab2.tools.data_tools.memory.memory_bank_engine_rest import (
        TA_Lab2_Memory_Engine,
    )
except ImportError:
    print(
        "Error: memory_bank_engine_rest.py not found in ta_lab2.tools.data_tools.memory."
    )
    print(
        "This script requires the memory_bank_engine_rest.py engine file to be migrated."
    )
    import sys

    sys.exit(1)


# =========================
# Config
# =========================


@dataclass(frozen=True)
class Config:
    project_id: str
    region: str
    staging_bucket: str
    memory_agent_id: str
    memory_scope: Dict[str, str]
    display_name: str
    description: str
    engine_ref_path: Path

    # New: dependency + packaging controls
    enable_router_deps: bool
    extra_requirements: List[str]
    extra_packages: List[str]

    # New: scope validation controls
    require_user_id_in_scope: bool


def _env_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")


def _parse_csv_env(name: str) -> List[str]:
    """
    Comma-separated env var -> list[str], trimming whitespace.
    Empty/missing -> [].
    """
    raw = os.getenv(name, "")
    items = [x.strip() for x in raw.split(",")]
    return [x for x in items if x]


def _validate_scope(scope: object, require_user_id: bool) -> Dict[str, str]:
    """
    Fail fast on scope shape and required keys.
    - Always require "app" (prevents accidental global memory usage).
    - Optionally require "user_id" (for per-user isolation).
    """
    if not isinstance(scope, dict):
        raise ValueError("VERTEX_MEMORY_SCOPE_JSON must decode to a JSON object/dict")

    # Ensure keys/values are strings (Vertex Memory Bank scope is typically string-keyed).
    out: Dict[str, str] = {}
    for k, v in scope.items():
        if not isinstance(k, str):
            raise ValueError("VERTEX_MEMORY_SCOPE_JSON keys must be strings")
        if not isinstance(v, str):
            raise ValueError(
                f'VERTEX_MEMORY_SCOPE_JSON value for key "{k}" must be a string'
            )
        out[k] = v

    if "app" not in out or not out["app"].strip():
        raise ValueError(
            'VERTEX_MEMORY_SCOPE_JSON must include a non-empty string key: "app"'
        )

    if require_user_id and ("user_id" not in out or not out["user_id"].strip()):
        raise ValueError(
            'VERTEX_MEMORY_SCOPE_JSON must include a non-empty string key: "user_id" '
            "when VERTEX_REQUIRE_USER_ID_IN_SCOPE=1"
        )

    return out


def _collect_extra_packages(here: Path) -> List[str]:
    """
    Future-proof packaging:
    - Always include memory_bank_engine_rest.py (required by the deployed engine).
    - Optionally include additional python files (comma-separated paths) via VERTEX_EXTRA_PACKAGES.
    - Optionally include all *.py in the directory when VERTEX_PACKAGE_ALL_PY=1 (handy as the engine grows).
    """
    pkgs: List[str] = []

    engine_file = here / "memory_bank_engine_rest.py"
    if not engine_file.exists():
        raise RuntimeError(f"Expected engine file not found: {engine_file}")
    pkgs.append(str(engine_file))

    # Explicit extra packages (paths can be relative to this file's directory)
    extra_paths = _parse_csv_env("VERTEX_EXTRA_PACKAGES")
    for p in extra_paths:
        path = (here / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
        if not path.exists():
            raise RuntimeError(f"VERTEX_EXTRA_PACKAGES path not found: {path}")
        pkgs.append(str(path))

    # Bulk include all local .py files if desired
    if _env_bool("VERTEX_PACKAGE_ALL_PY", default=False):
        for f in sorted(here.glob("*.py")):
            # Avoid duplicates
            s = str(f.resolve())
            if s not in pkgs:
                pkgs.append(s)

    return pkgs


def load_config() -> Config:
    project_id = os.getenv("GCP_PROJECT_ID", "ta-lab2")
    region = os.getenv("VERTEX_REGION", "us-central1")
    staging_bucket = _env_required("VERTEX_STAGING_BUCKET")
    memory_agent_id = _env_required("VERTEX_MEMORY_AGENT_ID")

    # New: scope validation controls
    require_user_id_in_scope = _env_bool(
        "VERTEX_REQUIRE_USER_ID_IN_SCOPE", default=False
    )

    scope_raw = os.getenv("VERTEX_MEMORY_SCOPE_JSON", '{"app": "ta_lab2"}')
    try:
        scope_obj = json.loads(scope_raw)
    except json.JSONDecodeError as e:
        raise ValueError("Invalid JSON in VERTEX_MEMORY_SCOPE_JSON") from e

    scope = _validate_scope(scope_obj, require_user_id=require_user_id_in_scope)

    display_name = os.getenv(
        "VERTEX_ENGINE_DISPLAY_NAME", "ta_lab2 Memory Engine (REST)"
    )
    description = os.getenv(
        "VERTEX_ENGINE_DESCRIPTION", "Memory engine for ta_lab2 using REST"
    )
    engine_ref_path = Path(
        os.getenv("VERTEX_ENGINE_REF_PATH", "reasoning_engine_ref.json")
    ).resolve()

    # New: dependency controls
    enable_router_deps = _env_bool("VERTEX_ENABLE_ROUTER_DEPS", default=False)
    extra_requirements = _parse_csv_env("VERTEX_EXTRA_REQUIREMENTS")

    here = Path(__file__).resolve().parent
    extra_packages = _collect_extra_packages(here)

    return Config(
        project_id=project_id,
        region=region,
        staging_bucket=staging_bucket,
        memory_agent_id=memory_agent_id,
        memory_scope=scope,
        display_name=display_name,
        description=description,
        engine_ref_path=engine_ref_path,
        enable_router_deps=enable_router_deps,
        extra_requirements=extra_requirements,
        extra_packages=extra_packages,
        require_user_id_in_scope=require_user_id_in_scope,
    )


# =========================
# Deploy
# =========================


def save_engine_ref(path: Path, resource_name: str, cfg: Config) -> None:
    payload = {
        "resource_name": resource_name,
        "project_id": cfg.project_id,
        "region": cfg.region,
        "display_name": cfg.display_name,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        # Helpful: keep the scope you deployed with, so query scripts can default to it
        "memory_scope": cfg.memory_scope,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    cfg = load_config()

    vertexai.init(
        project=cfg.project_id, location=cfg.region, staging_bucket=cfg.staging_bucket
    )

    # Base requirements
    requirements: List[str] = [
        "google-cloud-aiplatform",
        "cloudpickle==3.0.0",
        "requests",
        "google-auth",
    ]

    # New: optional lightweight “mem0-style router” deps (cheap lexical triage)
    # Keep these optional so you don't bloat the deployed image unless you need them.
    if cfg.enable_router_deps:
        requirements.extend(
            [
                "rank-bm25",
                "rapidfuzz",
            ]
        )

    # New: user-provided extras
    requirements.extend(cfg.extra_requirements)

    print("\nStarting Reasoning Engine deployment with REST-based Memory Bank:")
    print(f"  Project ID: {cfg.project_id}")
    print(f"  Region: {cfg.region}")
    print(f"  Staging Bucket: {cfg.staging_bucket}")
    print(f"  Display Name: {cfg.display_name}")
    print(f"  Memory Agent ID: {cfg.memory_agent_id}")
    print(f"  Memory Scope: {json.dumps(cfg.memory_scope)}")
    print(f"  Require user_id in scope: {cfg.require_user_id_in_scope}")
    print(f"  Enable router deps: {cfg.enable_router_deps}")
    print(f"  Requirements: {requirements}")
    print(f"  Extra packages: {cfg.extra_packages}")
    print(f"  Engine ref path: {cfg.engine_ref_path}\n")

    app_cfg_dict = {
        "project_id": cfg.project_id,
        "region": cfg.region,
        "reasoning_engine_id": cfg.memory_agent_id,
        "scope": cfg.memory_scope,
    }

    print("Deploying Reasoning Engine...")
    reasoning_engine = reasoning_engines.ReasoningEngine.create(
        TA_Lab2_Memory_Engine(app_cfg_dict),
        display_name=cfg.display_name,
        description=cfg.description,
        requirements=requirements,
        extra_packages=cfg.extra_packages,
    )

    print(
        f"\nReasoning Engine created. Resource name: {reasoning_engine.resource_name}"
    )
    save_engine_ref(cfg.engine_ref_path, reasoning_engine.resource_name, cfg)
    print(f"Saved engine reference to: {cfg.engine_ref_path}")


if __name__ == "__main__":
    main()
