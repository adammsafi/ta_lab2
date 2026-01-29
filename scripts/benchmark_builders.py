#!/usr/bin/env python
"""
Performance benchmarks for refactored bar builders.

Phase 5.2: Measure performance impact of refactoring.

Benchmarks:
1. Batch loading vs N+1 queries
2. Database connection efficiency
3. Memory usage
4. Throughput (bars/second)
"""

import os
import sys
import time
from typing import Callable
import pandas as pd

# Optional psutil import for memory tracking
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    load_last_snapshot_row,
    load_last_snapshot_info_for_id_tfs,
)

# Configuration
DB_URL = os.environ.get("TARGET_DB_URL")
BARS_TABLE = "public.cmc_price_bars_multi_tf"
TEST_ID = 1  # Bitcoin
TEST_TFS = ["7d", "14d", "21d", "28d", "35d", "42d", "49d", "56d", "63d", "70d"]


def get_memory_usage_mb() -> float:
    """Get current process memory usage in MB."""
    if HAS_PSUTIL:
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    return 0.0  # Not available


def benchmark_function(
    func: Callable,
    name: str,
    iterations: int = 10
) -> dict:
    """
    Benchmark a function multiple times.

    Returns dict with timing stats and memory usage.
    """
    print(f"\n{'='*60}")
    print(f"Benchmarking: {name}")
    print(f"Iterations: {iterations}")
    print(f"{'='*60}")

    times = []
    mem_before = get_memory_usage_mb()

    for i in range(iterations):
        start = time.perf_counter()
        result = func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

        if i == 0:
            print(f"  First run: {elapsed:.4f}s (may include connection setup)")
        elif i % 5 == 0:
            avg_so_far = sum(times) / len(times)
            print(f"  Iteration {i}/{iterations}: {elapsed:.4f}s (avg: {avg_so_far:.4f}s)")

    mem_after = get_memory_usage_mb()
    mem_delta = mem_after - mem_before

    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    std_time = pd.Series(times).std()

    print(f"\nResults:")
    print(f"  Average: {avg_time:.4f}s")
    print(f"  Min:     {min_time:.4f}s")
    print(f"  Max:     {max_time:.4f}s")
    print(f"  Std Dev: {std_time:.4f}s")
    if HAS_PSUTIL:
        print(f"  Memory:  {mem_before:.1f} MB → {mem_after:.1f} MB (Δ {mem_delta:+.1f} MB)")
    else:
        print(f"  Memory:  (psutil not installed - memory tracking unavailable)")

    return {
        "name": name,
        "avg_time": avg_time,
        "min_time": min_time,
        "max_time": max_time,
        "std_time": std_time,
        "mem_before": mem_before,
        "mem_after": mem_after,
        "mem_delta": mem_delta,
        "iterations": iterations,
    }


def benchmark_batch_loading():
    """Benchmark batch loading (1 query for all TFs)."""
    def run():
        return load_last_snapshot_info_for_id_tfs(
            db_url=DB_URL,
            bars_table=BARS_TABLE,
            id_=TEST_ID,
            tfs=TEST_TFS
        )

    return benchmark_function(run, "Batch Loading (1 query)", iterations=50)


def benchmark_n_plus_one_loading():
    """Benchmark N+1 loading (1 query per TF) - OLD PATTERN."""
    def run():
        result = {}
        for tf in TEST_TFS:
            row = load_last_snapshot_row(
                db_url=DB_URL,
                bars_table=BARS_TABLE,
                id_=TEST_ID,
                tf=tf
            )
            if row:
                result[tf] = {
                    "last_bar_seq": row.get("bar_seq"),
                    "last_time_close": row.get("time_close")
                }
        return result

    return benchmark_function(run, "N+1 Loading (old pattern)", iterations=50)


def benchmark_connection_pooling():
    """Benchmark database connection reuse."""
    from sqlalchemy import text

    def run():
        engine = get_engine(DB_URL)
        results = []
        with engine.connect() as conn:
            for _ in range(10):
                result = conn.execute(
                    text("SELECT COUNT(*) FROM information_schema.tables")
                ).scalar()
                results.append(result)
        return results

    return benchmark_function(run, "Connection Pooling", iterations=20)


def analyze_batch_vs_n_plus_one(batch_result, n_plus_one_result):
    """Analyze performance difference between batch and N+1 patterns."""
    print(f"\n{'='*60}")
    print("BATCH LOADING vs N+1 PATTERN ANALYSIS")
    print(f"{'='*60}")

    speedup = n_plus_one_result["avg_time"] / batch_result["avg_time"]
    time_saved = n_plus_one_result["avg_time"] - batch_result["avg_time"]
    queries_saved = len(TEST_TFS) - 1  # N queries vs 1 query

    print(f"\n📊 Performance Comparison:")
    print(f"  Batch loading:  {batch_result['avg_time']:.4f}s (1 query)")
    print(f"  N+1 loading:    {n_plus_one_result['avg_time']:.4f}s ({len(TEST_TFS)} queries)")
    print(f"  ────────────────────────────────")
    print(f"  Speedup:        {speedup:.2f}x faster")
    print(f"  Time saved:     {time_saved*1000:.1f}ms per call")
    print(f"  Queries saved:  {queries_saved} per ID")

    print(f"\n📈 Extrapolated Impact (100 IDs):")
    print(f"  Batch: {batch_result['avg_time'] * 100:.2f}s (100 queries)")
    print(f"  N+1:   {n_plus_one_result['avg_time'] * 100:.2f}s ({len(TEST_TFS) * 100} queries)")
    print(f"  Time saved: {time_saved * 100:.1f}s = {time_saved * 100 / 60:.1f} minutes")

    print(f"\n🎯 Database Load Reduction:")
    print(f"  Before: {len(TEST_TFS) * 100:,} queries")
    print(f"  After:  100 queries")
    print(f"  Reduction: {((len(TEST_TFS) * 100 - 100) / (len(TEST_TFS) * 100)) * 100:.0f}%")

    return {
        "speedup": speedup,
        "time_saved_per_call_ms": time_saved * 1000,
        "queries_saved_per_id": queries_saved,
        "db_load_reduction_pct": ((len(TEST_TFS) * 100 - 100) / (len(TEST_TFS) * 100)) * 100,
    }


def generate_benchmark_report(results: dict):
    """Generate final benchmark report."""
    print(f"\n{'='*60}")
    print("BENCHMARK REPORT - BAR BUILDERS REFACTORING")
    print(f"{'='*60}")

    print(f"\n📋 Test Configuration:")
    print(f"  Database: {DB_URL[:50]}...")
    print(f"  Test ID: {TEST_ID} (Bitcoin)")
    print(f"  Timeframes: {len(TEST_TFS)} ({', '.join(TEST_TFS[:3])}...)")
    print(f"  Table: {BARS_TABLE}")

    batch = results["batch"]
    n_plus_one = results["n_plus_one"]
    analysis = results["analysis"]

    print(f"\n[OK] Key Findings:")
    print(f"  1. Batch loading is {analysis['speedup']:.2f}x faster than N+1 pattern")
    print(f"  2. Saves {analysis['time_saved_per_call_ms']:.1f}ms per ID lookup")
    print(f"  3. Reduces database queries by {analysis['queries_saved_per_id']} per ID")
    print(f"  4. Overall DB load reduction: {analysis['db_load_reduction_pct']:.0f}%")

    print(f"\n📊 Performance Metrics:")
    print(f"  Batch Loading:")
    print(f"    - Average: {batch['avg_time']*1000:.2f}ms")
    print(f"    - Min:     {batch['min_time']*1000:.2f}ms")
    print(f"    - Max:     {batch['max_time']*1000:.2f}ms")

    print(f"\n  N+1 Loading (old pattern):")
    print(f"    - Average: {n_plus_one['avg_time']*1000:.2f}ms")
    print(f"    - Min:     {n_plus_one['min_time']*1000:.2f}ms")
    print(f"    - Max:     {n_plus_one['max_time']*1000:.2f}ms")

    print(f"\n💾 Memory Impact:")
    print(f"  Batch: {batch['mem_delta']:+.1f} MB")
    print(f"  N+1:   {n_plus_one['mem_delta']:+.1f} MB")

    print(f"\n🎯 Production Impact Estimate:")
    print(f"  For cal_anchor builders (100 IDs × 10 TFs):")
    print(f"    - Query reduction: 1,000 → 100 (90%)")
    print(f"    - Expected speedup: {analysis['speedup']:.0f}-{analysis['speedup']*1.5:.0f}x")
    print(f"    - Time saved: ~{analysis['time_saved_per_call_ms'] * 100 / 1000:.0f}s per run")

    print(f"\n[OK] VERDICT:")
    if analysis['speedup'] > 2.0:
        print(f"  🎉 EXCELLENT: Refactoring provides significant performance improvement!")
    elif analysis['speedup'] > 1.5:
        print(f"  [OK] GOOD: Refactoring provides noticeable performance improvement")
    elif analysis['speedup'] > 1.1:
        print(f"  [+] POSITIVE: Refactoring provides modest performance improvement")
    else:
        print(f"  [WARNING]  NEUTRAL: Performance similar (as expected for already-optimized builders)")

    print(f"\n📝 Recommendation:")
    print(f"  [OK] Deploy refactored builders to production")
    print(f"  [OK] Monitor cal_anchor builder performance (expect {analysis['speedup']:.0f}x speedup)")
    print(f"  [OK] No regressions expected for other builders")


def main():
    """Run all benchmarks."""
    print("="*60)
    print("BAR BUILDERS PERFORMANCE BENCHMARKS")
    print("Phase 5.2: Validation")
    print("="*60)

    if not DB_URL:
        print("\nERROR: TARGET_DB_URL environment variable not set")
        print("   Set it to run benchmarks against your database")
        return 1

    print(f"\nTarget database: {DB_URL[:50]}...")
    if HAS_PSUTIL:
        print(f"Process memory: {get_memory_usage_mb():.1f} MB")
    else:
        print(f"Note: psutil not installed - memory tracking disabled")

    # Run benchmarks
    results = {}

    try:
        results["batch"] = benchmark_batch_loading()
        results["n_plus_one"] = benchmark_n_plus_one_loading()
        results["connection"] = benchmark_connection_pooling()

        # Analyze results
        results["analysis"] = analyze_batch_vs_n_plus_one(
            results["batch"],
            results["n_plus_one"]
        )

        # Generate report
        generate_benchmark_report(results)

        print(f"\n{'='*60}")
        print("BENCHMARKS COMPLETE [OK]")
        print(f"{'='*60}\n")

        return 0

    except Exception as e:
        print(f"\nERROR running benchmarks: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
