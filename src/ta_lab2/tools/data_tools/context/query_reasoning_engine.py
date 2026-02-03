"""Query Vertex AI reasoning engine for context-aware responses."""
from __future__ import annotations

# query_reasoning_engine.py

r"""
If you have the reasoning_engine_ref.json in the same folder (written by your deploy script), just:
python .\query_reasoning_engine.py

Or explicitly point to it:
$env:VERTEX_ENGINE_REF_PATH = "reasoning_engine_ref.json"
python .\query_reasoning_engine.py

Or bypass the file and set the resource name directly:
$env:VERTEX_ENGINE_RESOURCE_NAME = "projects/.../locations/.../reasoningEngines/..."
python .\query_reasoning_engine.py
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    import vertexai
    from vertexai.preview import reasoning_engines
except ImportError:
    print(
        "Error: Vertex AI library not installed. Install with: pip install google-cloud-aiplatform vertexai"
    )
    sys.exit(1)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


def load_engine_ref(path: Path) -> dict:
    """
    Load engine reference JSON written by create_reasoning_engine.py
    (default: reasoning_engine_ref.json).
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Engine ref file not found: {path}\n"
            "Either set VERTEX_ENGINE_RESOURCE_NAME, or set VERTEX_ENGINE_REF_PATH "
            "to the correct JSON file, or run create_reasoning_engine.py to generate it."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Engine ref file is not valid JSON: {path}") from e


def main() -> None:
    # Defaults
    project_id = _env("GCP_PROJECT_ID", "ta-lab2")
    region = _env("VERTEX_REGION", "us-central1")

    # Prefer explicit env var, otherwise fall back to ref file
    resource_name = _env("VERTEX_ENGINE_RESOURCE_NAME")

    if not resource_name:
        ref_path = Path(
            _env("VERTEX_ENGINE_REF_PATH", "reasoning_engine_ref.json")
        ).resolve()
        ref = load_engine_ref(ref_path)
        resource_name = ref.get("resource_name")

        # If ref file has these, prefer them
        project_id = ref.get("project_id", project_id)
        region = ref.get("region", region)

    if not resource_name:
        raise RuntimeError(
            "No engine resource name found.\n"
            "Set VERTEX_ENGINE_RESOURCE_NAME, or ensure reasoning_engine_ref.json contains resource_name."
        )

    vertexai.init(project=project_id, location=region)

    reasoning_engine = reasoning_engines.ReasoningEngine(resource_name)

    print(f"Querying Reasoning Engine: {reasoning_engine.resource_name}")
    query_text = _env("VERTEX_TEST_QUERY", "World")

    response = reasoning_engine.query(query=query_text)

    print("\nQuery:")
    print(query_text)
    print("\nResponse (pretty):")
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
