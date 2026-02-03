"""Orchestrator CLI commands.

Per ORCH-10: CLI interface for task submission and results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Optional


def build_orchestrator_parser() -> argparse.ArgumentParser:
    """Build CLI parser for orchestrator commands."""
    ap = argparse.ArgumentParser(
        prog="ta-lab2 orchestrator",
        description="AI Orchestrator CLI - Route tasks across Claude, ChatGPT, Gemini",
    )
    sub = ap.add_subparsers(dest="orch_cmd", required=True)

    # Submit single task
    p_submit = sub.add_parser("submit", help="Submit a task for execution")
    p_submit.add_argument("--prompt", "-p", required=True, help="Task prompt")
    p_submit.add_argument(
        "--type",
        "-t",
        default="code_generation",
        choices=[
            "code_generation",
            "research",
            "data_analysis",
            "refactoring",
            "documentation",
            "code_review",
            "sql_db_work",
            "testing",
            "debugging",
            "planning",
        ],
        help="Task type (default: code_generation)",
    )
    p_submit.add_argument(
        "--platform",
        default=None,
        choices=["claude_code", "chatgpt", "gemini"],
        help="Platform hint (optional - will use cost-optimized routing if not specified)",
    )
    p_submit.add_argument("--chain-id", default=None, help="Workflow chain ID")
    p_submit.add_argument(
        "--timeout", type=int, default=300, help="Timeout in seconds (default: 300)"
    )
    p_submit.add_argument("--output", "-o", help="Output file for result")
    p_submit.set_defaults(func=cmd_submit)

    # Execute batch from file
    p_batch = sub.add_parser("batch", help="Execute batch of tasks from JSON file")
    p_batch.add_argument(
        "--input", "-i", required=True, help="Input JSON file with tasks"
    )
    p_batch.add_argument("--output", "-o", help="Output JSON file for results")
    p_batch.add_argument(
        "--parallel", type=int, default=5, help="Max parallel tasks (default: 5)"
    )
    p_batch.add_argument(
        "--fallback", action="store_true", help="Enable fallback routing on failures"
    )
    p_batch.set_defaults(func=cmd_batch)

    # Show status
    p_status = sub.add_parser("status", help="Show orchestrator status")
    p_status.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    p_status.set_defaults(func=cmd_status)

    # Show costs
    p_costs = sub.add_parser("costs", help="Show cost summary")
    p_costs.add_argument("--chain-id", help="Filter by chain ID")
    p_costs.add_argument(
        "--date", help="Date to summarize (YYYY-MM-DD, default: today)"
    )
    p_costs.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    p_costs.set_defaults(func=cmd_costs)

    # Quota status
    p_quota = sub.add_parser("quota", help="Show quota status")
    p_quota.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )
    p_quota.set_defaults(func=cmd_quota)

    return ap


def cmd_submit(args: argparse.Namespace) -> int:
    """Submit a single task."""
    from .core import Task, TaskType, Platform, TaskConstraints
    from .execution import AsyncOrchestrator
    from .adapters import (
        AsyncChatGPTAdapter,
        AsyncClaudeCodeAdapter,
        AsyncGeminiAdapter,
    )
    from .quota import QuotaTracker
    from .routing import TaskRouter
    from .cost import CostTracker

    # Build task
    task = Task(
        type=TaskType(args.type),
        prompt=args.prompt,
        platform_hint=Platform(args.platform) if args.platform else None,
        metadata={"chain_id": args.chain_id} if args.chain_id else {},
        constraints=TaskConstraints(timeout_seconds=args.timeout),
    )

    async def run():
        # Initialize adapters
        quota = QuotaTracker()
        adapters = {
            Platform.CHATGPT: AsyncChatGPTAdapter(),
            Platform.CLAUDE_CODE: AsyncClaudeCodeAdapter(),
            Platform.GEMINI: AsyncGeminiAdapter(quota_tracker=quota),
        }

        cost_tracker = CostTracker()

        async with AsyncOrchestrator(
            adapters=adapters,
            router=TaskRouter(),
            quota_tracker=quota,
        ) as orch:
            result = await orch.execute_with_fallback(task)

            # Record cost
            cost_tracker.record(task, result, chain_id=args.chain_id)

            # Display result
            print(f"\nTask ID: {result.task.task_id}")
            print(f"Platform: {result.platform.value}")
            print(f"Success: {result.success}")
            print(f"Duration: {result.duration_seconds:.2f}s")
            print(f"Cost: ${result.cost:.4f}")

            if result.success:
                print(f"\n--- Output ---\n{result.output}")
            else:
                print(f"\n--- Error ---\n{result.error}")

            # Save to file if requested
            if args.output:
                output_data = {
                    "task_id": result.task.task_id,
                    "platform": result.platform.value,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                    "cost": result.cost,
                    "duration_seconds": result.duration_seconds,
                }
                Path(args.output).write_text(json.dumps(output_data, indent=2))
                print(f"\nResult saved to: {args.output}")

            return 0 if result.success else 1

    return asyncio.run(run())


def cmd_batch(args: argparse.Namespace) -> int:
    """Execute batch of tasks from JSON file."""
    from .core import Task, TaskType, Platform, TaskConstraints
    from .execution import AsyncOrchestrator
    from .adapters import (
        AsyncChatGPTAdapter,
        AsyncClaudeCodeAdapter,
        AsyncGeminiAdapter,
    )
    from .quota import QuotaTracker
    from .routing import TaskRouter
    from .cost import CostTracker

    # Load tasks from file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {args.input}")
        return 1

    try:
        tasks_data = json.loads(input_path.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in input file: {e}")
        return 1

    # Convert to Task objects
    tasks = []
    for item in tasks_data:
        task = Task(
            type=TaskType(item.get("type", "code_generation")),
            prompt=item["prompt"],
            platform_hint=Platform(item["platform"]) if item.get("platform") else None,
            metadata=item.get("metadata", {}),
            constraints=TaskConstraints(timeout_seconds=item.get("timeout", 300))
            if item.get("timeout")
            else None,
        )
        tasks.append(task)

    print(f"Loaded {len(tasks)} tasks from {args.input}")

    async def run():
        quota = QuotaTracker()
        adapters = {
            Platform.CHATGPT: AsyncChatGPTAdapter(),
            Platform.CLAUDE_CODE: AsyncClaudeCodeAdapter(),
            Platform.GEMINI: AsyncGeminiAdapter(quota_tracker=quota),
        }

        cost_tracker = CostTracker()

        async with AsyncOrchestrator(
            adapters=adapters,
            router=TaskRouter(),
            quota_tracker=quota,
            max_concurrent=args.parallel,
        ) as orch:
            # Execute with or without fallback
            if args.fallback:
                aggregated = await orch.execute_parallel_with_fallback(tasks)
            else:
                aggregated = await orch.execute_parallel(tasks)

            # Record costs
            for result in aggregated.results:
                cost_tracker.record(result.task, result)

            # Display summary
            print("\n=== Batch Complete ===")
            print(f"Total: {len(tasks)} tasks")
            print(f"Success: {aggregated.success_count}")
            print(f"Failed: {aggregated.failure_count}")
            print(f"Success Rate: {aggregated.success_rate:.1%}")
            print(f"Total Cost: ${aggregated.total_cost:.4f}")
            print(f"Total Duration: {aggregated.total_duration:.2f}s")

            # By platform breakdown
            print("\nBy Platform:")
            for platform, results in aggregated.by_platform.items():
                success = sum(1 for r in results if r.success)
                cost = sum(r.cost for r in results)
                print(f"  {platform}: {success}/{len(results)} success, ${cost:.4f}")

            # Save results if requested
            if args.output:
                output_data = {
                    "total_tasks": len(tasks),
                    "success_count": aggregated.success_count,
                    "failure_count": aggregated.failure_count,
                    "success_rate": aggregated.success_rate,
                    "total_cost": aggregated.total_cost,
                    "total_duration": aggregated.total_duration,
                    "results": [
                        {
                            "task_id": r.task.task_id,
                            "platform": r.platform.value,
                            "success": r.success,
                            "output": r.output[:500] + "..."
                            if len(r.output) > 500
                            else r.output,
                            "error": r.error,
                            "cost": r.cost,
                        }
                        for r in aggregated.results
                    ],
                }
                Path(args.output).write_text(json.dumps(output_data, indent=2))
                print(f"\nResults saved to: {args.output}")

            return 0 if aggregated.failure_count == 0 else 1

    return asyncio.run(run())


def cmd_status(args: argparse.Namespace) -> int:
    """Show orchestrator status."""
    from .adapters import (
        AsyncChatGPTAdapter,
        AsyncClaudeCodeAdapter,
        AsyncGeminiAdapter,
    )
    from .quota import QuotaTracker
    from .core import Platform

    quota = QuotaTracker()

    # Get adapter statuses
    adapters = {
        Platform.CHATGPT: AsyncChatGPTAdapter(),
        Platform.CLAUDE_CODE: AsyncClaudeCodeAdapter(),
        Platform.GEMINI: AsyncGeminiAdapter(quota_tracker=quota),
    }

    if args.format == "json":
        status = {
            "adapters": {p.value: a.get_adapter_status() for p, a in adapters.items()},
            "quota": quota.get_status(),
        }
        print(json.dumps(status, indent=2, default=str))
    else:
        print("=== Orchestrator Status ===\n")
        print("Adapters:")
        for platform, adapter in adapters.items():
            status = adapter.get_adapter_status()
            icon = "OK" if status["is_implemented"] else "XX"
            print(f"  [{icon}] {platform.value}: {status['status']}")

        print("\n" + quota.display_status())

    return 0


def cmd_costs(args: argparse.Namespace) -> int:
    """Show cost summary."""
    from datetime import datetime
    from .cost import CostTracker

    tracker = CostTracker()

    # Parse date if provided
    date = None
    if args.date:
        try:
            date = datetime.fromisoformat(args.date)
        except ValueError:
            print("Error: Invalid date format. Use YYYY-MM-DD")
            return 1

    if args.chain_id:
        # Show chain-specific costs
        chain_cost = tracker.get_chain_cost(args.chain_id)
        chain_tasks = tracker.get_chain_tasks(args.chain_id)

        if args.format == "json":
            output = {
                "chain_id": args.chain_id,
                "total_cost": chain_cost,
                "task_count": len(chain_tasks),
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "platform": t.platform,
                        "cost": t.cost_usd,
                        "tokens": t.input_tokens + t.output_tokens,
                    }
                    for t in chain_tasks
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"Chain: {args.chain_id}")
            print(f"Total Cost: ${chain_cost:.4f}")
            print(f"Tasks: {len(chain_tasks)}")
            print("\nTask Breakdown:")
            for t in chain_tasks:
                print(f"  {t.task_id}: ${t.cost_usd:.4f} ({t.platform})")
    else:
        # Show session summary
        if args.format == "json":
            summary = tracker.get_session_summary(date)
            print(json.dumps(summary, indent=2))
        else:
            print(tracker.display_summary(date))

    return 0


def cmd_quota(args: argparse.Namespace) -> int:
    """Show quota status."""
    from .quota import QuotaTracker

    quota = QuotaTracker()

    if args.format == "json":
        print(json.dumps(quota.get_status(), indent=2, default=str))
    else:
        print(quota.display_status())

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint."""
    ap = build_orchestrator_parser()
    args = ap.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        ap.print_help()
        return 2

    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
