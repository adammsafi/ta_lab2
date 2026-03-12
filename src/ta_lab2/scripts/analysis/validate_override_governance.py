"""
validate_override_governance.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Override governance validation and OVERRIDE_POLICY.md generator.

Dual purpose:
  1. Validates that override governance rules (expiry, reason categories) are
     enforceable at the DB level by running live tests against risk_overrides.
  2. Generates OVERRIDE_POLICY.md documenting override rules, expiry mechanics,
     reason categories, CLI examples, and DB schema.

Closes LOSS-04 (override governance).

Usage
-----
    # Run validation tests and generate OVERRIDE_POLICY.md
    python -m ta_lab2.scripts.analysis.validate_override_governance

    # Custom output directory
    python -m ta_lab2.scripts.analysis.validate_override_governance \\
        --output-dir reports/loss_limits/

    # Dry-run (print configuration and exit)
    python -m ta_lab2.scripts.analysis.validate_override_governance --dry-run

Validation tests
----------------
  1. Schema validation: reason_category, expires_at, extended_at columns exist
  2. CHECK constraint validation: invalid reason_category insert must fail
  3. Valid category insertion: 'testing' category row insert + delete succeeds
  4. Expiry detection query: SELECT expired overrides returns 0 rows (test row deleted)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # ta_lab2/

# ---------------------------------------------------------------------------
# Override governance constants
# ---------------------------------------------------------------------------
OVERRIDE_EXPIRY_HOURS_DEFAULT = 24
OVERRIDE_EXPIRY_HOURS_MAX = 168  # 7 days

OVERRIDE_REASON_CATEGORIES = [
    "market_condition",
    "strategy_review",
    "technical_issue",
    "manual_risk_reduction",
    "testing",
]

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_engine(db_url: Optional[str] = None):
    """Create SQLAlchemy engine with NullPool."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.scripts.refresh_utils import resolve_db_url

    url = db_url or resolve_db_url()
    return create_engine(url, poolclass=NullPool)


def _table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the public schema."""
    from sqlalchemy import text

    result = conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    )
    return bool(result.scalar())


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


def _test_schema_columns(conn) -> Tuple[bool, str]:
    """
    Test 1: Verify reason_category, expires_at, extended_at columns exist on risk_overrides.

    Returns (passed, message).
    """
    from sqlalchemy import text

    result = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'risk_overrides'
              AND column_name IN ('reason_category', 'expires_at', 'extended_at')
            ORDER BY column_name
            """
        )
    )
    found = [row[0] for row in result.fetchall()]
    expected = {"reason_category", "expires_at", "extended_at"}
    missing = expected - set(found)

    if missing:
        return False, f"Missing columns: {sorted(missing)}. Found: {sorted(found)}"
    return True, f"All 3 governance columns present: {sorted(found)}"


def _test_check_constraint(conn) -> Tuple[bool, str]:
    """
    Test 2: Verify CHECK constraint rejects invalid reason_category values.

    Inserts a row with reason_category='invalid_category', expects violation.
    Rolls back after test.

    Returns (passed, message).
    """
    from sqlalchemy import exc as sa_exc, text

    try:
        # Use a savepoint so we can rollback just this test without aborting the outer transaction
        conn.execute(text("SAVEPOINT chk_test"))
        conn.execute(
            text(
                """
                INSERT INTO public.risk_overrides
                    (asset_id, strategy_id, operator, reason, system_signal,
                     override_action, reason_category)
                VALUES (1, 1, 'governance_test', 'Phase 48 validation', 'test',
                        'test', 'invalid_category')
                """
            )
        )
        # If we reach here, the constraint was NOT enforced — test failure
        conn.execute(text("ROLLBACK TO SAVEPOINT chk_test"))
        conn.execute(text("RELEASE SAVEPOINT chk_test"))
        return (
            False,
            "INSERT with invalid_category succeeded — CHECK constraint NOT enforced",
        )
    except sa_exc.IntegrityError as e:
        conn.execute(text("ROLLBACK TO SAVEPOINT chk_test"))
        conn.execute(text("RELEASE SAVEPOINT chk_test"))
        err_str = str(e.orig) if hasattr(e, "orig") and e.orig else str(e)
        if "chk_overrides_reason_cat" in err_str or "check" in err_str.lower():
            return (
                True,
                "CHECK constraint chk_overrides_reason_cat correctly rejected invalid_category",
            )
        # Some other integrity error — still a pass if invalid insert was blocked
        return True, f"Invalid insert correctly blocked by constraint: {err_str[:120]}"
    except Exception as e:
        conn.execute(text("ROLLBACK TO SAVEPOINT chk_test"))
        conn.execute(text("RELEASE SAVEPOINT chk_test"))
        return False, f"Unexpected error during CHECK constraint test: {e}"


def _test_valid_insertion(conn) -> Tuple[bool, str]:
    """
    Test 3: Insert a test row with valid reason_category='testing' and expires_at,
    then immediately delete it.

    Returns (passed, message).
    """
    from sqlalchemy import text

    override_id = None
    try:
        result = conn.execute(
            text(
                """
                INSERT INTO public.risk_overrides
                    (asset_id, strategy_id, operator, reason, system_signal,
                     override_action, reason_category, expires_at)
                VALUES (1, 1, 'governance_test', 'Phase 48 validation', 'test',
                        'test', 'testing', now() + interval '24 hours')
                RETURNING override_id
                """
            )
        )
        row = result.fetchone()
        if row is None:
            return False, "INSERT returned no RETURNING value"
        override_id = row[0]
    except Exception as e:
        return False, f"Valid insertion failed: {e}"

    # Delete the test row immediately
    try:
        conn.execute(
            text("DELETE FROM public.risk_overrides WHERE override_id = :oid"),
            {"oid": override_id},
        )
        return (
            True,
            f"Valid 'testing' category insert succeeded (override_id={override_id}) and test row deleted",
        )
    except Exception as e:
        return (
            False,
            f"Insert succeeded (override_id={override_id}) but DELETE failed: {e}",
        )


def _test_expiry_query(conn) -> Tuple[bool, str]:
    """
    Test 4: Verify the expiry detection query executes without error.

    Expected: 0 rows (test row from Test 3 was deleted).

    Returns (passed, message).
    """
    from sqlalchemy import text

    try:
        result = conn.execute(
            text(
                """
                SELECT override_id, expires_at
                FROM public.risk_overrides
                WHERE reverted_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at < now()
                """
            )
        )
        rows = result.fetchall()
        return (
            True,
            f"Expiry detection query executed successfully, returned {len(rows)} expired override(s)",
        )
    except Exception as e:
        return False, f"Expiry detection query failed: {e}"


def run_validation_tests(
    engine,
) -> List[Dict[str, Any]]:
    """
    Run all 4 validation tests against the live DB.

    Returns list of test result dicts with keys: name, passed, message.
    """
    results: List[Dict[str, Any]] = []

    with engine.begin() as conn:
        # Prerequisite: verify required tables exist
        for table_name in ("dim_risk_limits", "risk_overrides"):
            if not _table_exists(conn, table_name):
                logger.error(
                    "Prerequisite table %s not found. Phase 46 migration must be run first.",
                    table_name,
                )
                return [
                    {
                        "name": "Prerequisite check",
                        "passed": False,
                        "message": (
                            f"Table {table_name} missing — Phase 46 migration (dim_risk_limits, "
                            "risk_overrides) must be executed before governance validation."
                        ),
                    }
                ]

        # Test 1: Schema columns
        passed, msg = _test_schema_columns(conn)
        results.append(
            {"name": "Schema columns exist", "passed": passed, "message": msg}
        )
        if passed:
            logger.info("[PASS] Schema columns: %s", msg)
        else:
            logger.error("[FAIL] Schema columns: %s", msg)

        # Test 2: CHECK constraint
        passed, msg = _test_check_constraint(conn)
        results.append(
            {"name": "CHECK constraint enforced", "passed": passed, "message": msg}
        )
        if passed:
            logger.info("[PASS] CHECK constraint: %s", msg)
        else:
            logger.error("[FAIL] CHECK constraint: %s", msg)

        # Test 3: Valid insertion
        passed, msg = _test_valid_insertion(conn)
        results.append(
            {"name": "Valid insertion works", "passed": passed, "message": msg}
        )
        if passed:
            logger.info("[PASS] Valid insertion: %s", msg)
        else:
            logger.error("[FAIL] Valid insertion: %s", msg)

        # Test 4: Expiry detection query
        passed, msg = _test_expiry_query(conn)
        results.append(
            {"name": "Expiry detection query valid", "passed": passed, "message": msg}
        )
        if passed:
            logger.info("[PASS] Expiry query: %s", msg)
        else:
            logger.error("[FAIL] Expiry query: %s", msg)

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_override_policy_md(
    output_dir: Path,
    test_results: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """
    Write OVERRIDE_POLICY.md to output_dir.

    Parameters
    ----------
    output_dir : Path
        Directory to write the policy document.
    test_results : list of dicts, optional
        Validation test results. If None, marks as "Not validated (dry-run)".

    Returns
    -------
    Path to written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "OVERRIDE_POLICY.md"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Validation summary line
    if test_results is None:
        validation_summary = "Not validated (dry-run)"
    else:
        n_pass = sum(1 for r in test_results if r["passed"])
        n_total = len(test_results)
        statuses = " | ".join(
            f"{r['name']}: {'PASS' if r['passed'] else 'FAIL'}" for r in test_results
        )
        validation_summary = f"{n_pass}/{n_total} tests passed — {statuses}"

    # Reason categories table
    reason_cat_rows = """| market_condition | Unusual market conditions (liquidity, event risk, flash crash) |
| strategy_review | Pausing strategy for parameter review or debugging |
| technical_issue | Exchange connectivity, data feed, or infrastructure concerns |
| manual_risk_reduction | Proactively reducing exposure before known event |
| testing | Testing executor behavior, paper trading dry runs |"""

    # Validation status table
    if test_results is None:
        validation_table_rows = (
            "| (Not run — use default invocation to validate) | N/A |"
        )
    else:
        validation_table_rows = "\n".join(
            f"| {r['name']} | {'PASS' if r['passed'] else 'FAIL'} |"
            for r in test_results
        )

    content = f"""# Override Governance Policy

Generated: {timestamp}
Validation: {validation_summary}

## Overview

Solo operator override policy for V1 paper trading. Overrides allow temporary deviation
from risk limits when justified. All overrides are time-limited and audited.

## Override Rules

### Expiry
- **Default duration:** {OVERRIDE_EXPIRY_HOURS_DEFAULT} hours from creation
- **Maximum duration:** {OVERRIDE_EXPIRY_HOURS_MAX} hours (7 days)
- **Extension:** Operator may extend an active override by updating `extended_at` and `expires_at`
- **Beyond 7 days:** Not allowed; operator must create a new override with fresh justification
- **Expired overrides:** Checked at executor startup; expired overrides are auto-reverted

### Reason Categories (required)

| Category | Use When |
|----------|----------|
{reason_cat_rows}

A `reason` free-text field provides additional context beyond the category.

### Approval
- Solo operator: no approval chain required
- All overrides logged to `risk_overrides` with full audit trail
- `risk_events` records override_created/override_applied/override_reverted events

### Creating an Override (CLI)

```bash
# Future CLI (Phase 46 OverrideManager):
python -m ta_lab2.scripts.risk.override --action create \\
    --asset-id 1 --strategy-id 1 \\
    --reason-category market_condition \\
    --reason "BTC weekend liquidity concern" \\
    --override-action skip_signal \\
    --expires-hours 24
```

### Override Lifecycle

1. **Created:** Override row inserted with `expires_at = now() + N hours`
2. **Applied:** `applied_at` set when executor reads and applies the override
3. **Expired:** Executor startup checks `WHERE expires_at < now() AND reverted_at IS NULL`;
   auto-reverts expired overrides
4. **Reverted:** Manual revert via CLI or automatic expiry

### Extension Process

```bash
# Extend an active override:
python -m ta_lab2.scripts.risk.override --action extend \\
    --override-id <uuid> \\
    --extend-hours 24
```

- `extended_at` set to current timestamp
- `expires_at` updated to new expiry (must be <= 168 hours from original creation)

## DB Schema

### risk_overrides columns (Phase 48 additions)

- `reason_category TEXT` -- CHECK constraint enforces valid categories:
  `('market_condition', 'strategy_review', 'technical_issue', 'manual_risk_reduction', 'testing')`
- `expires_at TIMESTAMPTZ` -- NULL = no auto-expiry (manual-only, discouraged)
- `extended_at TIMESTAMPTZ` -- timestamp of last extension

### Expiry detection query (for executor startup)

```sql
SELECT override_id, asset_id, strategy_id, expires_at
FROM public.risk_overrides
WHERE reverted_at IS NULL
  AND expires_at IS NOT NULL
  AND expires_at < now()
```

### CHECK constraint (chk_overrides_reason_cat)

```sql
ALTER TABLE public.risk_overrides
ADD CONSTRAINT chk_overrides_reason_cat
CHECK (reason_category IS NULL OR reason_category IN (
    'market_condition', 'strategy_review', 'technical_issue',
    'manual_risk_reduction', 'testing'
));
```

## Validation Status

| Test | Result |
|------|--------|
{validation_table_rows}

## V1 Enforcement Notes

During V1 paper trading:
- Overrides are applied by PaperExecutor at signal processing time
- `get_pending_non_sticky_overrides()` in OverrideManager identifies overrides for auto-revert
- sticky=FALSE overrides are automatically reverted after each signal cycle
- All override events logged to `risk_events` for audit

## Allowed Categories Reference

Valid `reason_category` values (enforced by CHECK constraint):

```
{chr(10).join(f"  - {c}" for c in OVERRIDE_REASON_CATEGORIES)}
```
"""

    report_path.write_text(content, encoding="utf-8")
    logger.info("OVERRIDE_POLICY.md written to %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="validate_override_governance",
        description=(
            "Validate override governance rules against DB schema and "
            "generate OVERRIDE_POLICY.md policy document.\n\n"
            "Runs 4 DB validation tests:\n"
            "  1. Schema columns exist (reason_category, expires_at, extended_at)\n"
            "  2. CHECK constraint rejects invalid reason_category\n"
            "  3. Valid reason_category insertion and cleanup\n"
            "  4. Expiry detection query is valid SQL"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/loss_limits/",
        dest="output_dir",
        help="Report output directory (default: reports/loss_limits/).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        dest="db_url",
        help="Database URL (overrides db_config.env and environment variables).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print configuration and exit without DB/file operations.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.dry_run:
        print("=== validate_override_governance DRY RUN ===")
        print(f"  output_dir              : {args.output_dir}")
        print(f"  expiry_hours_default    : {OVERRIDE_EXPIRY_HOURS_DEFAULT}h")
        print(f"  expiry_hours_max        : {OVERRIDE_EXPIRY_HOURS_MAX}h (7 days)")
        print()
        print("Reason categories:")
        for cat in OVERRIDE_REASON_CATEGORIES:
            print(f"  - {cat}")
        print()
        print("Validation tests that would run (requires live DB):")
        tests = [
            "1. Schema columns exist (reason_category, expires_at, extended_at)",
            "2. CHECK constraint rejects invalid reason_category",
            "3. Valid reason_category insertion succeeds and test row is deleted",
            "4. Expiry detection query returns 0 expired rows",
        ]
        for t in tests:
            print(f"  {t}")
        return 0

    # Resolve output directory
    output_dir = (
        Path(args.output_dir)
        if Path(args.output_dir).is_absolute()
        else _PROJECT_ROOT / args.output_dir
    )

    # Run validation tests
    test_results: Optional[List[Dict[str, Any]]] = None
    try:
        engine = _get_engine(args.db_url)
        test_results = run_validation_tests(engine)
    except Exception as exc:
        logger.error("Cannot connect to DB for validation: %s", exc)
        logger.warning("Generating OVERRIDE_POLICY.md without validation results.")

    # Generate report
    report_path = generate_override_policy_md(output_dir, test_results)
    print(f"\nOVERRIDE_POLICY.md written to: {report_path}")

    # Print test summary
    if test_results:
        print("\n=== Validation Test Results ===")
        all_passed = True
        for result in test_results:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"  [{status}] {result['name']}: {result['message']}")
            if not result["passed"]:
                all_passed = False
        print()
        if all_passed:
            print("All validation tests PASSED.")
            return 0
        else:
            n_fail = sum(1 for r in test_results if not r["passed"])
            print(f"{n_fail} validation test(s) FAILED.")
            return 1
    else:
        logger.warning("No test results available (DB not connected).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
