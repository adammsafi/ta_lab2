"""Enrich memory headers with OpenAI-generated titles and tags (Step 2)."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# OpenAI Python SDK (new style)
# pip install openai
from openai import OpenAI

FM_START = "---\n"
FM_END = "\n---\n"


def has_front_matter(text: str) -> bool:
    t = text.lstrip("\ufeff\r\n\t ")
    return t.startswith(FM_START) and (FM_END in t[len(FM_START) :])


def split_front_matter(text: str) -> Tuple[Optional[str], str]:
    t = text.lstrip("\ufeff\r\n\t ")
    if not has_front_matter(text):
        return None, text
    end_idx = t.find(FM_END, len(FM_START))
    fm = t[len(FM_START) : end_idx]
    rest = t[end_idx + len(FM_END) :]
    return fm, rest


def parse_front_matter_minimal(fm: str) -> Dict[str, Any]:
    """
    Minimal YAML front-matter parser for the restricted schema we emit.
    Supports:
      key: value
      key:
        - item
    """
    out: Dict[str, Any] = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.lstrip().startswith("#"):
            i += 1
            continue

        if re.match(r"^[A-Za-z0-9_]+:\s*$", line):
            key = line.split(":")[0].strip()
            # list block
            items: List[str] = []
            i += 1
            # special-case "  []"
            if i < len(lines) and lines[i].strip() == "[]":
                out[key] = []
                i += 1
                continue
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                items.append(lines[i].lstrip()[2:].strip().strip('"'))
                i += 1
            out[key] = items
            continue

        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            # unquote if quoted
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            if val == "null":
                out[key] = None
            elif val in ("true", "false"):
                out[key] = val == "true"
            else:
                # int?
                if re.fullmatch(r"-?\d+", val):
                    out[key] = int(val)
                else:
                    out[key] = val
        i += 1
    return out


def yaml_escape(s: str) -> str:
    if s is None:
        return '""'
    needs_quotes = (
        s == ""
        or s.strip() != s
        or any(ch in s for ch in [":", "#", "{", "}", "[", "]", "\n", "\r", "\t", '"'])
    )
    if not needs_quotes:
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_dump_simple(d: Dict[str, Any]) -> str:
    lines: List[str] = []
    for k, v in d.items():
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {yaml_escape(str(item))}")
        else:
            if v is None:
                lines.append(f"{k}: null")
            elif isinstance(v, bool):
                lines.append(f"{k}: {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"{k}: {v}")
            else:
                lines.append(f"{k}: {yaml_escape(str(v))}")
    return "\n".join(lines) + "\n"


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def clip_text(body: str, max_chars: int) -> str:
    if len(body) <= max_chars:
        return body
    # Take first + last halves (keeps context + resolution)
    half = max_chars // 2
    return body[:half] + "\n\n[...CLIPPED...]\n\n" + body[-half:]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Enrich Memory Header v1 semantic fields using OpenAI Structured Outputs (Responses API)."
    )
    ap.add_argument("--kept-manifest", required=True, help="Path to kept_manifest.csv")
    ap.add_argument("--model", default="gpt-5.2", help="Model name (default gpt-5.2)")
    ap.add_argument(
        "--reasoning-effort",
        default="high",
        choices=["none", "medium", "high", "xhigh"],
        help="Reasoning effort level (default high)",
    )
    ap.add_argument(
        "--max-chars",
        type=int,
        default=12000,
        help="Max chars of body to send (default 12000)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Do not write files")
    ap.add_argument(
        "--run-manifest-out",
        default="memory_enrich_run_manifest.json",
        help="Where to write run manifest JSON",
    )
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY env var is not set.")

    client = OpenAI()

    SCHEMA_NAME = "memory_semantic_fields"
    SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "maxLength": 600},
            "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
            "projects": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "people": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["summary", "tags", "projects", "people", "confidence"],
    }

    kept_rows = read_csv(Path(args.kept_manifest))

    processed = 0
    skipped = 0
    errors: List[Dict[str, Any]] = []

    for kr in kept_rows:
        cid = (kr.get("id") or "").strip()
        dest = (
            kr.get("dest_path") or kr.get("resolved_path") or kr.get("src_path") or ""
        ).strip()
        if not cid or not dest:
            continue
        md_path = Path(dest)
        if not md_path.exists():
            skipped += 1
            continue

        text = md_path.read_text(encoding="utf-8", errors="replace")
        fm_raw, body = split_front_matter(text)
        if fm_raw is None:
            # step 1 not run yet
            skipped += 1
            continue

        fm = parse_front_matter_minimal(fm_raw)

        # Skip if already enriched (summary non-empty AND confidence set)
        if (
            str(fm.get("summary") or "").strip()
            and str(fm.get("confidence") or "").strip()
        ):
            skipped += 1
            continue

        title = str(fm.get("title") or "").strip()
        sample = clip_text(body, args.max_chars)

        system_prompt = (
            "You are helping build structured 'memory headers' for archived ChatGPT conversations.\n"
            "Return ONLY the JSON fields required by the schema.\n"
            "Do NOT include IDs, dates, filenames, or any extra keys.\n"
            "Tags should be short, reusable concepts. Projects should be high-level buckets.\n"
            "People should be named entities if clearly present; otherwise empty.\n"
        )

        user_prompt = f"Title: {title}\n" f"Conversation (clipped):\n{sample}\n"

        try:
            resp = client.responses.create(
                model=args.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                reasoning={"effort": args.reasoning_effort},
                text={
                    "format": {
                        "type": "json_schema",
                        "name": SCHEMA_NAME,
                        "schema": SCHEMA,
                        "strict": True,
                    }
                },
            )

            # Prefer parsed if available
            data = None
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    parsed = getattr(c, "parsed", None)
                    if parsed:
                        data = parsed
                        break
                if data:
                    break

            if data is None:
                raw_text = getattr(resp, "output_text", "") or ""
                if not raw_text:
                    for item in getattr(resp, "output", []) or []:
                        for c in getattr(item, "content", []) or []:
                            t = getattr(c, "text", None)
                            if t:
                                raw_text = t
                                break
                        if raw_text:
                            break

                if not raw_text:
                    raise ValueError(
                        "No JSON text returned by model (output_text/content.text empty)."
                    )

                data = json.loads(raw_text)

            # Merge into front matter (only semantic fields)
            fm["summary"] = data["summary"]
            fm["tags"] = data["tags"]
            fm["projects"] = data["projects"]
            fm["people"] = data["people"]
            fm["confidence"] = data["confidence"]

            new_text = FM_START + yaml_dump_simple(fm) + FM_END + body

            if args.dry_run:
                print(f"[DRY] would enrich: {md_path.name}")
            else:
                md_path.write_text(new_text, encoding="utf-8")

            processed += 1

        except Exception as e:
            errors.append(
                {"conversation_id": cid, "path": str(md_path), "error": repr(e)}
            )

    manifest = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "max_chars": args.max_chars,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }
    Path(args.run_manifest_out).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print("\n=== Summary ===")
    print(json.dumps({k: manifest[k] for k in ["processed", "skipped"]}, indent=2))
    print(f"run_manifest: {args.run_manifest_out}")
    if errors:
        print(f"errors: {len(errors)} (see manifest)")


if __name__ == "__main__":
    main()
