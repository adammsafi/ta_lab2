# src/ta_lab2/cli.py
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ----------------------------
# Optional imports (keep CLI usable even if some modules aren't present)
# ----------------------------

# Pipeline entrypoint (preferred: argv-delegating)
try:
    from ta_lab2.scripts.pipeline.refresh_all import main as pipeline_main  # type: ignore
except Exception:
    pipeline_main = None

# Older/in-repo pipeline fallback (DataFrame-style / config-driven)
try:
    from ta_lab2.pipeline import run_btc_pipeline  # type: ignore
except Exception:
    run_btc_pipeline = None

try:
    from ta_lab2.config import load_settings  # type: ignore
except Exception:
    load_settings = None

# Regime inspector (preferred: single callable returning JSON-serializable dict)
try:
    from ta_lab2.regimes.inspect import inspect_regimes  # type: ignore
except Exception:
    inspect_regimes = None

# Regime labelers (fallback path when inspect_regimes isn't available)
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # type: ignore

try:
    from ta_lab2.regimes.labelers import (  # type: ignore
        assess_data_budget,
        label_layer_daily,
        label_layer_intraday,
        label_layer_monthly,
        label_layer_weekly,
    )
except Exception:
    assess_data_budget = None  # type: ignore
    label_layer_daily = None  # type: ignore
    label_layer_intraday = None  # type: ignore
    label_layer_monthly = None  # type: ignore
    label_layer_weekly = None  # type: ignore

# Policy resolution helpers (fallback path)
try:
    from ta_lab2.regimes.policy import resolve_policy  # type: ignore
except Exception:
    resolve_policy = None  # type: ignore

# Table-aware resolver (optional)
try:
    from ta_lab2.regimes import resolve_policy_from_table  # type: ignore
except Exception:
    resolve_policy_from_table = None  # type: ignore

# Feature builder so labelers have EMAs/ATR when needed (optional)
try:
    from ta_lab2.regimes.feature_utils import ensure_regime_features  # type: ignore
except Exception:
    ensure_regime_features = None  # type: ignore

# DB tool (read-only)
try:
    from ta_lab2.tools.dbtool import main as dbtool_main  # type: ignore
except Exception:
    dbtool_main = None


# ----------------------------
# Commands
# ----------------------------
def cmd_pipeline(args: argparse.Namespace) -> int:
    """
    Preserve the original default behavior: run the BTC pipeline.

    Preference order:
      1) ta_lab2.scripts.pipeline.refresh_all.main (argv-delegating)
      2) ta_lab2.config.load_settings + ta_lab2.pipeline.run_btc_pipeline (in-repo fallback)
    """
    # Preferred modern entrypoint
    if pipeline_main is not None:
        argv: list[str] = []
        if getattr(args, "config", None):
            argv += ["--config", str(args.config)]
        return int(pipeline_main(argv))

    # Fallback to older in-repo behavior
    if load_settings is None or run_btc_pipeline is None:
        print("[ta-lab2 pipeline] pipeline entrypoint not available.")
        return 2

    settings = load_settings(str(args.config))
    return int(
        run_btc_pipeline(
            csv_path=settings.data_csv,
            out_dir=settings.out_dir,
            ema_windows=settings.ema_windows,
            resample=settings.resample,
        )
    )


@dataclass(frozen=True)
class RegimePolicy:
    size_mult: float = 1.0
    stop_mult: float = 1.0
    orders: int = 1
    pyramids: int = 0
    gross_cap: float = 1.0
    setups: str = "default"


def _detect_repo_root(start: Path) -> Path:
    """Walk upward looking for pyproject.toml or .git. Fall back to start."""
    p = start.resolve()
    for _ in range(50):
        if (p / "pyproject.toml").exists() or (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start.resolve()


def _load_regime_policy(repo_root: Path, policy_path: Optional[Path]) -> RegimePolicy:
    """
    Optional YAML overlay for flat policy overrides.
    Defaults to <repo_root>/configs/regime_policies.yaml if present.
    """
    try:
        import yaml  # type: ignore
    except Exception:
        return RegimePolicy()

    default_path = repo_root / "configs" / "regime_policies.yaml"
    path = policy_path or (default_path if default_path.exists() else None)
    if path is None:
        return RegimePolicy()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _get(name: str, cast, default):
        if name not in data:
            return default
        try:
            return cast(data[name])
        except Exception:
            return default

    return RegimePolicy(
        size_mult=_get("size_mult", float, 1.0),
        stop_mult=_get("stop_mult", float, 1.0),
        orders=_get("orders", int, 1),
        pyramids=_get("pyramids", int, 0),
        gross_cap=_get("gross_cap", float, 1.0),
        setups=_get("setups", str, "default"),
    )


def _read_df(path: Path) -> Any:
    if pd is None:
        raise RuntimeError("pandas is not available; cannot read CSV for regime labeling fallback.")
    return pd.read_csv(path)


def _ensure_feats_if_possible(df: Any, tag: str) -> Any:
    if df is None:
        return None
    if ensure_regime_features is None:
        return df
    try:
        return ensure_regime_features(df, tag=tag)
    except Exception:
        return df


def _maybe_load_policy_table(policy_path: Optional[Path], repo_root: Path) -> Optional[Any]:
    """
    Load a policy *table* (not the flat overrides) if present.
    This is intentionally permissive: it returns whatever YAML parses to.
    """
    try:
        import yaml  # type: ignore
    except Exception:
        return None

    candidate_paths: list[Path] = []
    if policy_path is not None:
        candidate_paths.append(policy_path)
    default_table = repo_root / "configs" / "regime_policy_table.yaml"
    if default_table.exists():
        candidate_paths.append(default_table)

    for p in candidate_paths:
        try:
            if p.exists():
                return yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def _coerce_label(x: Any) -> Any:
    """
    Normalize labeler outputs so fallback mode resembles the ATTACHED behavior:

    - If a labeler returns a Series/DataFrame, use the last observation (.iloc[-1]).
    - Convert numpy scalar -> Python scalar when possible.
    - Otherwise, return as-is.
    """
    if x is None:
        return None

    # pandas normalization (ATTACHED-style: last row)
    if pd is not None:
        try:
            if hasattr(pd, "DataFrame") and isinstance(x, pd.DataFrame):  # type: ignore[attr-defined]
                if len(x.index) == 0:
                    return None
                return x.iloc[-1].to_dict()
            if hasattr(pd, "Series") and isinstance(x, pd.Series):  # type: ignore[attr-defined]
                if len(x.index) == 0:
                    return None
                return x.iloc[-1]
        except Exception:
            pass

    # numpy scalar -> python scalar
    try:
        import numpy as np  # type: ignore

        if isinstance(x, np.generic):  # type: ignore[attr-defined]
            return x.item()
    except Exception:
        pass

    return x


def _merge_policy_overrides(resolved: Any, pol: RegimePolicy) -> Any:
    overrides = {
        "size_mult": pol.size_mult,
        "stop_mult": pol.stop_mult,
        "orders": pol.orders,
        "pyramids": pol.pyramids,
        "gross_cap": pol.gross_cap,
        "setups": pol.setups,
    }
    if isinstance(resolved, dict):
        merged = dict(resolved)
        merged.update(overrides)
        return merged
    return overrides


def _present_regime_result_text(symbol: str, budget: Any, L0: Any, L1: Any, L2: Any, L3: Any, resolved: Any) -> None:
    print(f"Symbol: {symbol}")
    print(f"Budget tier: {getattr(budget, 'tier', None) if budget is not None else None}")
    print(f"L0 (Monthly): {L0}")
    print(f"L1 (Weekly):  {L1}")
    print(f"L2 (Daily):   {L2}")
    print(f"L3 (Intra):   {L3}")
    print("Resolved policy:")
    if isinstance(resolved, dict):
        print(json.dumps(resolved, indent=2, sort_keys=True))
    else:
        print(resolved)


def _present_regime_result_json(symbol: str, budget: Any, L0: Any, L1: Any, L2: Any, L3: Any, resolved: Any) -> None:
    payload = {
        "symbol": symbol,
        "budget": {"tier": getattr(budget, "tier", None)} if budget is not None else None,
        "layers": {"L0": L0, "L1": L1, "L2": L2, "L3": L3},
        "resolved_policy": resolved,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_regime_inspect(args: argparse.Namespace) -> int:
    """
    Inspect multi-timeframe regimes and resolved policy.

    Behavior changes vs the earlier pasted version:
      - Adds --format {text,json} (default: text) to avoid "surprise JSON"
      - Normalizes fallback label outputs to ATTACHED-like last-observation behavior
      - Uses a common presenter so inspector/fallback return the same output shape
    """
    repo_root = _detect_repo_root(Path.cwd())
    pol = _load_regime_policy(repo_root, args.policy)

    # ----------------------------
    # Path 1: preferred inspector
    # ----------------------------
    if inspect_regimes is not None:
        out = inspect_regimes(
            symbol=args.symbol,
            monthly_path=args.monthly,
            weekly_path=args.weekly,
            daily_path=args.daily,
            intraday_path=args.intraday,
            policy_overrides={
                "size_mult": pol.size_mult,
                "stop_mult": pol.stop_mult,
                "orders": pol.orders,
                "pyramids": pol.pyramids,
                "gross_cap": pol.gross_cap,
                "setups": pol.setups,
            },
        )

        # Try to normalize inspector output into the same "presentation payload"
        # without assuming too much about the inspector's exact structure.
        budget = None
        L0 = L1 = L2 = L3 = None
        resolved = None

        if isinstance(out, dict):
            budget = out.get("budget", None)
            layers = out.get("layers", out.get("layer_labels", out.get("regimes", None)))
            if isinstance(layers, dict):
                L0 = _coerce_label(layers.get("L0"))
                L1 = _coerce_label(layers.get("L1"))
                L2 = _coerce_label(layers.get("L2"))
                L3 = _coerce_label(layers.get("L3"))
            resolved = out.get("resolved_policy", out.get("policy", out.get("resolved", None)))

        resolved = _merge_policy_overrides(resolved, pol)

        if args.format == "json":
            _present_regime_result_json(args.symbol, budget, L0, L1, L2, L3, resolved)
        else:
            _present_regime_result_text(args.symbol, budget, L0, L1, L2, L3, resolved)

        return 0

    # ----------------------------
    # Path 2: fallback labelers
    # ----------------------------
    if pd is None:
        print("[ta-lab2 regime-inspect] inspect_regimes not available and pandas is not installed.")
        return 2
    if any(
        x is None
        for x in (
            assess_data_budget,
            label_layer_monthly,
            label_layer_weekly,
            label_layer_daily,
            label_layer_intraday,
        )
    ):
        print("[ta-lab2 regime-inspect] inspect_regimes not available and regime labelers are not available.")
        return 2

    df_m = _read_df(args.monthly) if args.monthly and args.monthly.exists() else None
    df_w = _read_df(args.weekly) if args.weekly and args.weekly.exists() else None
    df_d = _read_df(args.daily) if args.daily and args.daily.exists() else None
    df_i = _read_df(args.intraday) if args.intraday and args.intraday.exists() else None

    df_m = _ensure_feats_if_possible(df_m, "M")
    df_w = _ensure_feats_if_possible(df_w, "W")
    df_d = _ensure_feats_if_possible(df_d, "D")
    df_i = _ensure_feats_if_possible(df_i, "I")

    budget = assess_data_budget(df_m=df_m, df_w=df_w, df_d=df_d, df_i=df_i)  # type: ignore

    # Normalize output shape: last observation if labelers return Series/DataFrame
    L0 = _coerce_label(label_layer_monthly(df_m) if df_m is not None else None)  # type: ignore
    L1 = _coerce_label(label_layer_weekly(df_w) if df_w is not None else None)  # type: ignore
    L2 = _coerce_label(label_layer_daily(df_d) if df_d is not None else None)  # type: ignore
    L3 = _coerce_label(label_layer_intraday(df_i) if df_i is not None else None)  # type: ignore

    # Policy resolution: prefer table-aware resolver if available
    policy_table = _maybe_load_policy_table(args.policy, repo_root)
    resolved: Any = None
    if resolve_policy_from_table is not None and policy_table is not None:
        try:
            resolved = resolve_policy_from_table(L0=L0, L1=L1, L2=L2, L3=L3, policy_table=policy_table)  # type: ignore
        except Exception:
            resolved = None

    if resolved is None and resolve_policy is not None:
        try:
            resolved = resolve_policy(L0=L0, L1=L1, L2=L2, L3=L3)  # type: ignore
        except Exception:
            resolved = None

    resolved = _merge_policy_overrides(resolved, pol)

    if args.format == "json":
        _present_regime_result_json(args.symbol, budget, L0, L1, L2, L3, resolved)
    else:
        _present_regime_result_text(args.symbol, budget, L0, L1, L2, L3, resolved)

    return 0


def cmd_db(args: argparse.Namespace) -> int:
    """
    Read-only DB helper. Delegates to ta_lab2.tools.dbtool CLI.

    Fixes:
      - Pass global --limit (NOT --agg-limit)
      - Only pass --agg-limit within the agg subcommand, and only if not None
      - Avoid ever stringifying None into argv
      - Allow --limit after subcommands via per-subparser --limit
      - Use --sql for query/explain (matches dbtool)
    """
    if dbtool_main is None:
        print("[ta-lab2 db] dbtool not available. Did you create src/ta_lab2/tools/dbtool.py?")
        return 2

    argv: list[str] = []

    # Global dbtool flags
    if getattr(args, "timeout_ms", None) is not None:
        argv += ["--timeout-ms", str(args.timeout_ms)]
    if getattr(args, "idle_tx_timeout_ms", None) is not None:
        argv += ["--idle-tx-timeout-ms", str(args.idle_tx_timeout_ms)]

    # Global limit (safe): can come from parent `db --limit` or a per-subcommand override
    if hasattr(args, "limit") and getattr(args, "limit") is not None:
        argv += ["--limit", str(getattr(args, "limit"))]

    # Subcommand within dbtool
    argv.append(args.db_cmd)

    if args.db_cmd == "tables":
        if getattr(args, "schema", None):
            argv += ["--schema", args.schema]

    elif args.db_cmd == "schemas":
        pass

    elif args.db_cmd == "profile-cols":
        argv += [args.schema, args.table]
        if getattr(args, "cols", None):
            argv += ["--cols", args.cols]
        if getattr(args, "topn", None) is not None:
            argv += ["--topn", str(args.topn)]

    elif args.db_cmd == "profile-time":
        argv += [args.schema, args.table]
        if getattr(args, "ts_col", None):
            argv += ["--ts-col", args.ts_col]
        if getattr(args, "bucket", None):
            argv += ["--bucket", args.bucket]
        if getattr(args, "start", None):
            argv += ["--start", args.start]
        if getattr(args, "end", None):
            argv += ["--end", args.end]
        if getattr(args, "missing_threshold", None) is not None:
            argv += ["--missing-threshold", str(args.missing_threshold)]

    elif args.db_cmd in ("describe", "indexes", "constraints", "keys", "profile", "dupes"):
        argv += [args.schema, args.table]
        if args.db_cmd == "dupes":
            argv += ["--key", args.key]
            if getattr(args, "where", None):
                argv += ["--where", args.where]
            if getattr(args, "having", None):
                argv += ["--having", args.having]
            if getattr(args, "order_by", None):
                argv += ["--order-by", args.order_by]

    elif args.db_cmd in ("query", "explain"):
        argv += ["--sql", args.sql]

    elif args.db_cmd == "agg":
        argv += [args.schema, args.table]
        argv += ["--select", args.select]
        if getattr(args, "where", None):
            argv += ["--where", args.where]
        if getattr(args, "group_by", None):
            argv += ["--group-by", args.group_by]
        if getattr(args, "having", None):
            argv += ["--having", args.having]
        if getattr(args, "order_by", None):
            argv += ["--order-by", args.order_by]
        if getattr(args, "agg_limit", None) is not None:
            argv += ["--agg-limit", str(args.agg_limit)]

    elif args.db_cmd == "snapshot":
        argv += ["--out", args.out]

    elif args.db_cmd == "snapshot-md":
        if getattr(args, "in_path", None):
            argv += ["--in-path", args.in_path]
        argv += ["--out", args.out]

    return int(dbtool_main(argv))


# ----------------------------
# Main / Parser
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ta-lab2",
        description="ta_lab2 CLI",
    )
    sub = ap.add_subparsers(dest="cmd")

    # Subcommand: pipeline (preserves original behavior)
    p_pipeline = sub.add_parser("pipeline", help="Run the BTC pipeline (original default behavior)")
    p_pipeline.add_argument(
        "--config",
        "-c",
        default="config/default.yaml",
        help="Path to YAML config relative to project root (default: config/default.yaml)",
    )
    p_pipeline.set_defaults(func=cmd_pipeline)

    # Subcommand: regime-inspect
    p_reg = sub.add_parser("regime-inspect", help="Inspect multi-timeframe regimes and resolved policy")
    p_reg.add_argument("--symbol", required=True, help="Symbol label for printing (e.g., BTCUSD)")
    p_reg.add_argument("--monthly", type=Path, help="CSV with monthly bars (optional)")
    p_reg.add_argument("--weekly", type=Path, help="CSV with weekly bars (optional)")
    p_reg.add_argument("--daily", type=Path, help="CSV with daily bars (optional)")
    p_reg.add_argument("--intraday", type=Path, help="CSV with intraday bars (e.g., 4H/1H) (optional)")
    p_reg.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="Optional YAML overlay (defaults to <repo_root>/configs/regime_policies.yaml if present)",
    )
    p_reg.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text). Use json for stable machine-readable output.",
    )
    p_reg.set_defaults(func=cmd_regime_inspect)

    # Subcommand: db (read-only Postgres introspection/query)
    p_db = sub.add_parser(
        "db",
        help=(
            "Read-only Postgres helper "
            "(schemas/tables/describe/indexes/constraints/keys/query/explain/profile/profile-cols/profile-time/dupes/agg/snapshot/snapshot-md)"
        ),
    )
    p_db.add_argument("--timeout-ms", type=int, default=15_000, help="statement_timeout in ms (default: 15000)")
    p_db.add_argument(
        "--idle-tx-timeout-ms",
        type=int,
        default=15_000,
        help="idle_in_transaction_session_timeout in ms (default: 15000)",
    )
    p_db.add_argument("--limit", type=int, default=200, help="default LIMIT / output limit (default: 200)")

    db_sub = p_db.add_subparsers(dest="db_cmd", required=True)

    def _db_add_limit(sp: argparse.ArgumentParser) -> None:
        """
        Allow `--limit` after the db subcommand (e.g., `ta-lab2 db tables --limit 20`).
        Use SUPPRESS so it doesn't overwrite the parent default unless explicitly provided.
        """
        sp.add_argument(
            "--limit",
            type=int,
            default=argparse.SUPPRESS,
            help="Override output limit for this command (defaults to db --limit)",
        )

    p_db_schemas = db_sub.add_parser("schemas", help="List non-system schemas + object counts")
    _db_add_limit(p_db_schemas)
    p_db_schemas.set_defaults(func=cmd_db)

    p_db_tables = db_sub.add_parser("tables", help="List tables (optionally for one schema)")
    _db_add_limit(p_db_tables)
    p_db_tables.add_argument("--schema", type=str, default=None, help="Schema name (optional)")
    p_db_tables.set_defaults(func=cmd_db)

    p_db_desc = db_sub.add_parser("describe", help="Describe columns for a table")
    _db_add_limit(p_db_desc)
    p_db_desc.add_argument("schema", type=str)
    p_db_desc.add_argument("table", type=str)
    p_db_desc.set_defaults(func=cmd_db)

    p_db_indexes = db_sub.add_parser("indexes", help="List indexes for a table (incl. method/unique/primary)")
    _db_add_limit(p_db_indexes)
    p_db_indexes.add_argument("schema", type=str)
    p_db_indexes.add_argument("table", type=str)
    p_db_indexes.set_defaults(func=cmd_db)

    p_db_constraints = db_sub.add_parser("constraints", help="List constraints for a table")
    _db_add_limit(p_db_constraints)
    p_db_constraints.add_argument("schema", type=str)
    p_db_constraints.add_argument("table", type=str)
    p_db_constraints.set_defaults(func=cmd_db)

    p_db_keys = db_sub.add_parser("keys", help="List PK + UNIQUE keys for a table")
    _db_add_limit(p_db_keys)
    p_db_keys.add_argument("schema", type=str)
    p_db_keys.add_argument("table", type=str)
    p_db_keys.set_defaults(func=cmd_db)

    p_db_query = db_sub.add_parser("query", help="Run a safe read-only SQL query (SELECT/WITH/EXPLAIN only)")
    _db_add_limit(p_db_query)
    p_db_query.add_argument("--sql", required=True, help="SQL to execute")
    p_db_query.set_defaults(func=cmd_db)

    p_db_explain = db_sub.add_parser("explain", help="EXPLAIN (ANALYZE FALSE) for a safe query")
    _db_add_limit(p_db_explain)
    p_db_explain.add_argument("--sql", required=True, help="SQL to explain")
    p_db_explain.set_defaults(func=cmd_db)

    p_db_profile = db_sub.add_parser("profile", help="Table profile: rowcount + sample")
    _db_add_limit(p_db_profile)
    p_db_profile.add_argument("schema", type=str)
    p_db_profile.add_argument("table", type=str)
    p_db_profile.set_defaults(func=cmd_db)

    p_db_profile_cols = db_sub.add_parser("profile-cols", help="Column profiling from pg_stats")
    _db_add_limit(p_db_profile_cols)
    p_db_profile_cols.add_argument("schema", type=str)
    p_db_profile_cols.add_argument("table", type=str)
    p_db_profile_cols.add_argument("--cols", default=None, help="Comma-separated column list (optional)")
    p_db_profile_cols.add_argument("--topn", type=int, default=20, help="Top-N values to show per column (default: 20)")
    p_db_profile_cols.set_defaults(func=cmd_db)

    p_db_profile_time = db_sub.add_parser("profile-time", help="Bucketed time coverage + missing detection")
    _db_add_limit(p_db_profile_time)
    p_db_profile_time.add_argument("schema", type=str)
    p_db_profile_time.add_argument("table", type=str)
    p_db_profile_time.add_argument("--ts-col", default="timestamp", help="Timestamp column name (default: timestamp)")
    p_db_profile_time.add_argument("--bucket", default="1 day", help="Bucket size for coverage (default: 1 day)")
    p_db_profile_time.add_argument("--start", default=None, help="Optional start timestamp (inclusive)")
    p_db_profile_time.add_argument("--end", default=None, help="Optional end timestamp (exclusive)")
    p_db_profile_time.add_argument(
        "--missing-threshold",
        type=float,
        default=0.5,
        help="Mark bucket as missing if coverage < threshold (default: 0.5)",
    )
    p_db_profile_time.set_defaults(func=cmd_db)

    p_db_dupes = db_sub.add_parser("dupes", help="Group-by key integrity probe (duplicate detector)")
    _db_add_limit(p_db_dupes)
    p_db_dupes.add_argument("schema", type=str)
    p_db_dupes.add_argument("table", type=str)
    p_db_dupes.add_argument("--key", required=True, help="Comma-separated key columns (e.g., id,tf,period,ts)")
    p_db_dupes.add_argument("--where", default=None, help="Optional WHERE clause (without 'WHERE')")
    p_db_dupes.add_argument("--having", default=None, help="Optional HAVING clause (without 'HAVING')")
    p_db_dupes.add_argument("--order-by", default=None, help="Optional ORDER BY clause (without 'ORDER BY')")
    p_db_dupes.set_defaults(func=cmd_db)

    p_db_agg = db_sub.add_parser("agg", help="Safe single-table aggregation builder")
    _db_add_limit(p_db_agg)
    p_db_agg.add_argument("schema", type=str)
    p_db_agg.add_argument("table", type=str)
    p_db_agg.add_argument("--select", required=True, help="SELECT list (e.g., count(*) as n)")
    p_db_agg.add_argument("--where", default=None, help="Optional WHERE clause (without 'WHERE')")
    p_db_agg.add_argument("--group-by", dest="group_by", default=None, help="GROUP BY clause (without 'GROUP BY')")
    p_db_agg.add_argument("--having", default=None, help="HAVING clause (without 'HAVING')")
    p_db_agg.add_argument("--order-by", dest="order_by", default=None, help="ORDER BY clause (without 'ORDER BY')")
    p_db_agg.add_argument(
        "--agg-limit",
        dest="agg_limit",
        type=int,
        default=None,
        help="Output limit for this query (overrides db --limit)",
    )
    p_db_agg.set_defaults(func=cmd_db)

    p_db_snap = db_sub.add_parser("snapshot", help="Write DB schema snapshot JSON (all non-system schemas)")
    _db_add_limit(p_db_snap)
    p_db_snap.add_argument("--out", type=str, required=True, help="Output path (e.g., artifacts/db_schema_snapshot.json)")
    p_db_snap.set_defaults(func=cmd_db)

    p_db_snap_md = db_sub.add_parser("snapshot-md", help="Write a DB schema snapshot Markdown (optionally from JSON)")
    _db_add_limit(p_db_snap_md)
    p_db_snap_md.add_argument(
        "--in-path",
        dest="in_path",
        type=str,
        default=None,
        help="Optional input JSON snapshot path (if omitted, snapshot is generated live from DB)",
    )
    p_db_snap_md.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output Markdown path (e.g., artifacts/db_schema_snapshot.md)",
    )
    p_db_snap_md.set_defaults(func=cmd_db)

    # Back-compat: if no subcommand is given, behave like old CLI (run pipeline)
    ap.add_argument(
        "--config",
        "-c",
        default="config/default.yaml",
        help=argparse.SUPPRESS,
    )
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    # Back-compat path: no subcommand provided -> run pipeline with top-level --config
    if args.cmd is None:
        shim = argparse.Namespace(config=args.config)
        return cmd_pipeline(shim)

    if hasattr(args, "func") and callable(args.func):
        return int(args.func(args))

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
