#!/usr/bin/env python3
"""
Mastermind Sidecar — AEON-777 Integration
================================================================
Lightweight orchestrator reference that each AEON-777 repo includes.
Provides task submission, health reporting, and chain execution.

Usage:
    from mastermind_sidecar import MastermindSidecar
    sidecar = MastermindSidecar(domain="cooling")
    sidecar.report_health({"status": "ok", "tick": 1})
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class HealthReport:
    domain: str
    status: str
    tick_count: int
    anomalies: int = 0
    timestamp: float = field(default_factory=time.time)
    metadata: Optional[Dict[str, Any]] = None


class MastermindSidecar:
    """
    Lightweight sidecar that connects AEON-777 repos to the Mastermind orchestrator.
    
    Each repo includes this sidecar to:
    1. Report health status to the orchestrator
    2. Submit tasks for cross-domain execution
    3. Chain operations across subsystems
    4. Maintain local shadow memory
    """

    def __init__(self, domain: str, base_dir: str = "."):
        self.domain = domain
        self.base_dir = Path(base_dir).resolve()
        self.shadow_memory_path = self.base_dir / "tests" / ".shadow_memory.json"
        self.health_log = []
        self.task_queue = []

    def report_health(self, report: Dict[str, Any]) -> None:
        """Report health status to the sidecar log."""
        health = HealthReport(
            domain=self.domain,
            status=report.get("status", "unknown"),
            tick_count=report.get("tick", 0),
            anomalies=report.get("anomalies", 0),
            metadata=report.get("metadata"),
        )
        self.health_log.append(health)

    def submit_task(self, task_id: str, description: str, priority: str = "P2") -> str:
        """Submit a task for cross-domain execution."""
        task = {
            "task_id": task_id,
            "domain": self.domain,
            "description": description,
            "priority": priority,
            "submitted_at": time.time(),
        }
        self.task_queue.append(task)
        return task_id

    def chain_tasks(self, task_ids: list) -> list:
        """Chain multiple tasks for sequential execution."""
        chain = {
            "chain_id": f"chain-{int(time.time())}",
            "domain": self.domain,
            "tasks": task_ids,
            "created_at": time.time(),
        }
        return task_ids

    def update_shadow_memory(self, key: str, value: Any) -> None:
        """Update local shadow memory."""
        memory = {}
        if self.shadow_memory_path.exists():
            try:
                memory = json.loads(self.shadow_memory_path.read_text())
            except Exception:
                pass
        
        memory[key] = value
        memory["last_updated"] = time.time()
        
        self.shadow_memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.shadow_memory_path.write_text(json.dumps(memory, indent=2))

    def get_shadow_memory(self, key: str = None) -> Any:
        """Read from local shadow memory."""
        if not self.shadow_memory_path.exists():
            return None
        
        try:
            memory = json.loads(self.shadow_memory_path.read_text())
            if key:
                return memory.get(key)
            return memory
        except Exception:
            return None

    def summary(self) -> Dict[str, Any]:
        """Return sidecar status."""
        return {
            "domain": self.domain,
            "health_reports": len(self.health_log),
            "pending_tasks": len(self.task_queue),
            "shadow_memory_exists": self.shadow_memory_path.exists(),
        }
