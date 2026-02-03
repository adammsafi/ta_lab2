from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# Helpers
# -----------------------------

def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                raise RuntimeError(f"Invalid JSON on line {i} in {path}: {e}") from e
    return rows


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def write_text(path: Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def run_subprocess(cmd: List[str], log_path: Path) -> Tuple[int, str]:
    """
    Run command, capture stdout+stderr, write to log, return (returncode, combined_output).
    """
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + ("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or "")
    write_text(log_path, out)
    return proc.returncode, out


def script_supports_overrides(script_path: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, str(script_path), "-h"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    txt = (proc.stdout or "") + (proc.stderr or "")
    return "--overrides" in txt


@dataclass
class ChecksResult:
    ok: bool
    failures: List[Dict[str, Any]]


def run_invariants(children_path: Path, out_dir: Path) -> ChecksResult:
    final_p = out_dir / "final_memory.jsonl"
    review_p = out_dir / "review_queue.jsonl"
    dec_p = out_dir / "decision_log.jsonl"

    failures: List[Dict[str, Any]] = []

    # invariant: decision_log lines == children lines
    children_rows = count_lines(children_path)
    decisions_rows = count_lines(dec_p)
    if decisions_rows != children_rows:
        failures.append(
            {"check": "decisions_match_children", "children": children_rows, "decisions": decisions_rows}
        )

    # invariant: no empty-content accepts
    empty: List[Dict[str, Any]] = []
    if final_p.exists():
        for i, o in enumerate(read_jsonl(final_p), 1):
            if not str(o.get("content") or "").strip():
                empty.append(
                    {"line": i, "title": o.get("title"), "registry_key": o.get("registry_key")}
                )
    if empty:
        failures.append({"check": "no_empty_content_accepts", "count": len(empty), "examples": empty[:25]})

    # invariant: registry_key unique in final
    if final_p.exists():
        seen = set()
        dup = 0
        for o in read_jsonl(final_p):
            rk = o.get("registry_key")
            if rk in seen:
                dup += 1
            else:
                seen.add(rk)
        if dup:
            failures.append({"check": "unique_registry_key_final", "duplicate_count": dup})

    ok = len(failures) == 0
    return ChecksResult(ok=ok, failures=failures)


def pick_first_review_key(review_path: Path) -> Optional[str]:
    if not review_path.exists():
        return None
    with review_path.open("r", encoding="utf-8") as f:
        line = f.readline().strip()
        if not line:
            return None
        o = json.loads(line)
        meta = o.get("_decision_meta") or {}
        return meta.get("registry_key")


def write_overrides_file(path: Path, registry_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"registry_key": registry_key, "decision": "accept", "note": "test promote 1 key"}
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="Path to instantiate_final_memories.py")
    ap.add_argument("--children", required=True, help="Path to memory_children.jsonl")
    ap.add_argument("--repo-root", required=True, help="Repo root used for evidence search")
    ap.add_argument("--base-out", required=True, help="Base output dir (runner will create a timestamped folder)")
    ap.add_argument("--key-mode", default="conflict_key_title", help="Key mode to pass through")
    ap.add_argument("--run-id", default=None, help="Optional run id; default uses timestamp")
    ap.add_argument("--with-overrides-test", action="store_true", help="Also run an overrides promotion test")
    args = ap.parse_args()

    script_path = Path(args.script)
    children_path = Path(args.children)
    repo_root = Path(args.repo_root)
    base_out = Path(args.base_out)

    if not script_path.exists():
        raise FileNotFoundError(f"instantiate script not found: {script_path}")
    if not children_path.exists():
        raise FileNotFoundError(f"children jsonl not found: {children_path}")
    if not repo_root.exists():
        raise FileNotFoundError(f"repo root not found: {repo_root}")

    run_id = args.run_id or now_stamp()
    run_dir = base_out / "test_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1) Main run
    main_log = run_dir / "instantiate.log.txt"
    cmd = [
        sys.executable,
        str(script_path),
        "--children",
        str(children_path),
        "--out-dir",
        str(run_dir),
        "--repo-root",
        str(repo_root),
        "--key-mode",
        str(args.key_mode),
    ]

    rc, _ = run_subprocess(cmd, main_log)
    if rc != 0:
        write_json(run_dir / "runner_result.json", {"ok": False, "stage": "main_run", "returncode": rc})
        print(f"[FAIL] main_run rc={rc}. See: {main_log}")
        sys.exit(rc)

    # 2) Metrics + invariants
    final_p = run_dir / "final_memory.jsonl"
    review_p = run_dir / "review_queue.jsonl"
    dec_p = run_dir / "decision_log.jsonl"

    metrics = {
        "accepted": count_lines(final_p),
        "review": count_lines(review_p),
        "decisions": count_lines(dec_p),
        "run_dir": str(run_dir),
    }
    write_json(run_dir / "metrics.json", metrics)
    write_text(run_dir / "metrics.txt", f"accepted={metrics['accepted']}\nreview={metrics['review']}\ndecisions={metrics['decisions']}\n")

    checks = run_invariants(children_path, run_dir)
    write_json(run_dir / "checks.json", {"ok": checks.ok, "failures": checks.failures})

    result: Dict[str, Any] = {"ok": True, "run_dir": str(run_dir), "metrics": metrics, "checks_ok": checks.ok}
    if not checks.ok:
        result["ok"] = False
        result["stage"] = "invariants"
        write_json(run_dir / "runner_result.json", result)
        print(f"[FAIL] invariants failed. See: {run_dir / 'checks.json'}")
        sys.exit(2)

    # 3) Optional overrides test
    if args.with_overrides_test:
        if not script_supports_overrides(script_path):
            print("[WARN] overrides test skipped: instantiate script does not advertise --overrides in -h output.")
        else:
            override_dir = run_dir / "override_test"
            override_dir.mkdir(parents=True, exist_ok=True)

            rk = pick_first_review_key(review_p)
            if not rk:
                result["override_test"] = {"ok": False, "reason": "no review key found (empty review queue?)"}
                write_json(run_dir / "runner_result.json", result)
                print("[WARN] overrides test skipped: no review key found.")
                print(f"[OK] Saved run artifacts: {run_dir}")
                return

            write_text(override_dir / "promoted_key.txt", rk)
            overrides_path = override_dir / "decision_overrides_TEST.jsonl"
            write_overrides_file(overrides_path, rk)

            override_log = override_dir / "instantiate_with_overrides.log.txt"
            cmd2 = [
                sys.executable,
                str(script_path),
                "--children", str(children_path),
                "--out-dir", str(override_dir),
                "--repo-root", str(repo_root),
                "--key-mode", str(args.key_mode),
                "--overrides", str(overrides_path),
            ]

            rc2, _ = run_subprocess(cmd2, override_log)
            if rc2 != 0:
                result["override_test"] = {"ok": False, "stage": "override_run", "returncode": rc2}
                write_json(run_dir / "runner_result.json", result)
                print(f"[FAIL] override_run rc={rc2}. See: {override_log}")
                sys.exit(rc2)

            base_acc = metrics["accepted"]
            base_rev = metrics["review"]
            test_acc = count_lines(override_dir / "final_memory.jsonl")
            test_rev = count_lines(override_dir / "review_queue.jsonl")

            final_keys = set(o["registry_key"] for o in read_jsonl(override_dir / "final_memory.jsonl"))
            review_keys = set(((o.get("_decision_meta") or {}).get("registry_key")) for o in read_jsonl(override_dir / "review_queue.jsonl"))

            override_result = {
                "base": {"accepted": base_acc, "review": base_rev},
                "override": {"accepted": test_acc, "review": test_rev},
                "observed_delta": {"accepted": test_acc - base_acc, "review": test_rev - base_rev},
                "promoted_registry_key": rk,
                "key_moved": {"in_final": rk in final_keys, "in_review": rk in review_keys},
            }
            write_json(override_dir / "override_test_result.json", override_result)

            result["override_test"] = override_result
            if not (override_result["key_moved"]["in_final"] and not override_result["key_moved"]["in_review"]):
                result["ok"] = False
                result["stage"] = "override_invariants"
                write_json(run_dir / "runner_result.json", result)
                print(f"[FAIL] overrides test did not move key. See: {override_dir / 'override_test_result.json'}")
                sys.exit(3)

    write_json(run_dir / "runner_result.json", result)
    print(f"[OK] Saved run artifacts: {run_dir}")
    if args.with_overrides_test:
        print(f"[OK] Overrides test artifacts: {run_dir / 'override_test'}")


if __name__ == "__main__":
    main()
