"""
ta_lab2 Memory Integration with mem0
Provides semantic search and cross-platform memory management
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

try:
    from mem0 import Memory
    MEM0_AVAILABLE = True
except ImportError:
    MEM0_AVAILABLE = False
    print("⚠️  mem0 not installed. Install with: pip install mem0ai")


class TA_Lab2_Memory:
    """Memory management for ta_lab2 project across AI platforms"""
    
    def __init__(self, base_path: str = ".memory"):
        self.base_path = Path(base_path)
        self.mem0 = Memory() if MEM0_AVAILABLE else None
        
        # Initialize mem0 with project context
        if self.mem0:
            self._init_mem0_context()
    
    def _init_mem0_context(self):
        """Initialize mem0 with ta_lab2 project context"""
        project_context = """
        Project: ta_lab2 - Multi-timeframe Technical Analysis Lab
        Tech Stack: Python, PostgreSQL, pandas, pytest
        Purpose: BTC/crypto technical analysis with regime labeling
        Key Components:
        - Multi-timeframe resampling (daily, weekly, monthly, quarterly)
        - EMA calculations with derivatives
        - Regime classification (L1-L4 layers)
        - Policy resolution for trading decisions
        - SQL views for efficient queries
        """
        
        if self.mem0:
            self.mem0.add(
                project_context,
                user_id="ta_lab2",
                metadata={"type": "project_context", "timestamp": datetime.now().isoformat()}
            )
    
    def add_decision(
        self,
        category: str,
        description: str,
        rationale: str = "",
        platform: str = "Python",
        status: str = "active"
    ) -> str:
        """
        Add a decision to memory
        
        Args:
            category: architecture, features, regimes, data
            description: What was decided
            rationale: Why this decision was made
            platform: Which AI platform/tool was used
            status: active, deprecated, superseded
            
        Returns:
            Decision ID
        """
        decision_file = self.base_path / "decisions" / f"{category}.json"
        
        with open(decision_file, 'r') as f:
            data = json.load(f)
        
        decision_id = os.urandom(4).hex()
        entry = {
            "id": decision_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": description,
            "rationale": rationale,
            "platform": platform,
            "status": status
        }
        
        data["decisions"].append(entry)
        
        with open(decision_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Add to mem0 for semantic search
        if self.mem0:
            self.mem0.add(
                f"{category} decision: {description}. Rationale: {rationale}",
                user_id="ta_lab2",
                metadata={
                    "type": "decision",
                    "category": category,
                    "decision_id": decision_id,
                    "platform": platform
                }
            )
        
        return decision_id
    
    def add_goal(
        self,
        description: str,
        priority: str = "medium",
        status: str = "active",
        platform: str = "Python"
    ) -> str:
        """Add a goal to memory"""
        goal_file = self.base_path / "goals" / "active.json"
        
        with open(goal_file, 'r') as f:
            data = json.load(f)
        
        goal_id = os.urandom(4).hex()
        entry = {
            "id": goal_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": description,
            "priority": priority,
            "status": status,
            "platform": platform
        }
        
        data["goals"].append(entry)
        
        with open(goal_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Add to mem0
        if self.mem0:
            self.mem0.add(
                f"Goal: {description}",
                user_id="ta_lab2",
                metadata={
                    "type": "goal",
                    "goal_id": goal_id,
                    "priority": priority,
                    "platform": platform
                }
            )
        
        return goal_id
    
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Semantic search across all memory
        
        Args:
            query: Natural language search query
            limit: Max results to return
            
        Returns:
            List of relevant memory entries
        """
        if not self.mem0:
            print("⚠️  mem0 not available. Install with: pip install mem0ai")
            return []
        
        results = self.mem0.search(query, user_id="ta_lab2", limit=limit)
        return results
    
    def get_recent_decisions(self, category: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """Get recent decisions, optionally filtered by category"""
        decisions = []
        
        categories = [category] if category else ["architecture", "features", "regimes", "data"]
        
        for cat in categories:
            decision_file = self.base_path / "decisions" / f"{cat}.json"
            if decision_file.exists():
                with open(decision_file, 'r') as f:
                    data = json.load(f)
                    for dec in data["decisions"]:
                        dec["category"] = cat
                    decisions.extend(data["decisions"])
        
        # Sort by timestamp and limit
        decisions.sort(key=lambda x: x["timestamp"], reverse=True)
        return decisions[:limit]
    
    def get_active_goals(self, priority: Optional[str] = None) -> List[Dict]:
        """Get active goals, optionally filtered by priority"""
        goal_file = self.base_path / "goals" / "active.json"
        
        with open(goal_file, 'r') as f:
            data = json.load(f)
        
        goals = data["goals"]
        
        if priority:
            goals = [g for g in goals if g.get("priority") == priority]
        
        return sorted(goals, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("priority", "medium"), 1))
    
    def sync_platform(self, platform: str, session_note: str = "") -> str:
        """Record platform sync and return session ID"""
        session_id = os.urandom(4).hex()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Update platform state
        platform_state = {
            "last_platform": platform,
            "last_sync": timestamp,
            "session_id": session_id
        }
        
        state_file = self.base_path / "sync" / "platform_state.json"
        with open(state_file, 'w') as f:
            json.dump(platform_state, f, indent=2)
        
        # Log session
        sessions_file = self.base_path / "context" / "sessions.json"
        with open(sessions_file, 'r') as f:
            sessions_data = json.load(f)
        
        session_entry = {
            "id": session_id,
            "timestamp": timestamp,
            "platform": platform,
            "note": session_note
        }
        
        sessions_data["sessions"].append(session_entry)
        
        with open(sessions_file, 'w') as f:
            json.dump(sessions_data, f, indent=2)
        
        return session_id
    
    def get_context_summary(self) -> Dict[str, Any]:
        """Get a summary of current project state for AI platforms"""
        return {
            "recent_decisions": self.get_recent_decisions(limit=5),
            "active_goals": self.get_active_goals(),
            "platform_state": self._get_platform_state()
        }
    
    def _get_platform_state(self) -> Dict:
        """Get current platform state"""
        state_file = self.base_path / "sync" / "platform_state.json"
        with open(state_file, 'r') as f:
            return json.load(f)


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ta_lab2 Memory System")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Add decision
    add_dec = subparsers.add_parser("add-decision", help="Add a decision")
    add_dec.add_argument("category", choices=["architecture", "features", "regimes", "data"])
    add_dec.add_argument("description")
    add_dec.add_argument("--rationale", default="")
    add_dec.add_argument("--platform", default="Python")
    
    # Add goal
    add_goal = subparsers.add_parser("add-goal", help="Add a goal")
    add_goal.add_argument("description")
    add_goal.add_argument("--priority", choices=["high", "medium", "low"], default="medium")
    
    # Search
    search = subparsers.add_parser("search", help="Search memory")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    
    # Summary
    subparsers.add_parser("summary", help="Get context summary")
    
    args = parser.parse_args()
    memory = TA_Lab2_Memory()
    
    if args.command == "add-decision":
        dec_id = memory.add_decision(
            args.category,
            args.description,
            args.rationale,
            args.platform
        )
        print(f"✓ Added decision [{dec_id}]")
    
    elif args.command == "add-goal":
        goal_id = memory.add_goal(args.description, args.priority)
        print(f"✓ Added goal [{goal_id}]")
    
    elif args.command == "search":
        results = memory.search(args.query, args.limit)
        print(f"\n🔍 Search results for: {args.query}\n")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result.get('memory', 'N/A')}")
            print(f"   Relevance: {result.get('score', 0):.2f}")
            print()
    
    elif args.command == "summary":
        summary = memory.get_context_summary()
        print("\n📝 Project Context Summary\n")
        print("Recent Decisions:")
        for dec in summary["recent_decisions"][:3]:
            print(f"  • [{dec['category']}] {dec['description']}")
        print("\nActive Goals:")
        for goal in summary["active_goals"][:3]:
            print(f"  • [{goal.get('priority', 'medium').upper()}] {goal['description']}")
        print(f"\nLast Platform: {summary['platform_state']['last_platform']}")
        print(f"Last Sync: {summary['platform_state']['last_sync']}")
