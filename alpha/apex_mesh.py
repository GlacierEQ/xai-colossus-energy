"""
APEX Mesh Intelligence Layer
═══════════════════════════════
Hidden filesystem brain for cross-repo discovery, health monitoring,
event propagation, and coordinated orchestration.

Usage from any repo:
    from apex_mesh import Mesh
    mesh = Mesh()
    mesh.discover()           # Find all mesh nodes
    mesh.health_check()       # Poll all endpoints
    mesh.emit("thermal_alert", {"temp": 48.2, "zone": "L2-E"})  # Broadcast event
    mesh.invoke("power", "shed_load", {"zone": "L2-E", "pct": 30})  # Direct call
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ── Config ────────────────────────────────────────────────────────────────────

APEX_DIR = Path(os.environ.get("APEX_HOME", os.path.expanduser("~/.apex")))
MESH_DIR = APEX_DIR / "mesh"
OPS_DIR = APEX_DIR / "ops"
CACHE_DIR = APEX_DIR / "cache"

# Also check repo-local .apex/
REPO_APEX = Path(__file__).parent if "__file__" in dir() else Path(".")
REPO_APEX_DIR = REPO_APEX if REPO_APEX.name == ".apex" else REPO_APEX / ".apex"


def _load_json(path: Path) -> Dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class MeshNode:
    name: str
    endpoint: str
    protocol: str
    health_path: str
    healthy: Optional[bool] = None
    last_check: Optional[float] = None
    latency_ms: Optional[float] = None

@dataclass
class MeshEvent:
    event_type: str
    source: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: f"evt-{int(time.time()*1000)}")

@dataclass
class Runbook:
    name: str
    trigger: str
    steps: List[str]
    escalation: str


# ── Mesh ──────────────────────────────────────────────────────────────────────

class Mesh:
    """
    The APEX Mesh — cross-repo intelligence layer.
    Reads config from .apex/ hidden filesystem, provides discovery,
    health monitoring, event bus, and inter-service invocation.
    """

    def __init__(self, repo_name: str = "unknown"):
        self.repo_name = repo_name
        self._ecosystem = self._load_ecosystem()
        self._topology = self._load_topology()
        self._nodes: Dict[str, MeshNode] = {}
        self._event_log: List[MeshEvent] = []
        self._handlers: Dict[str, List[Callable]] = {}
        self._load_nodes()

    def _load_ecosystem(self) -> Dict:
        """Load ecosystem config from .apex/ecosystem.json"""
        for search in [REPO_APEX_DIR / "ecosystem.json", APEX_DIR / "ecosystem.json"]:
            data = _load_json(search)
            if data:
                return data
        return {}

    def _load_topology(self) -> Dict:
        """Load mesh topology from .apex/mesh/topology.json"""
        for search in [REPO_APEX_DIR / "mesh" / "topology.json", MESH_DIR / "topology.json"]:
            data = _load_json(search)
            if data:
                return data
        return {}

    def _load_nodes(self):
        """Initialize mesh nodes from topology config."""
        nodes_config = self._topology.get("nodes", {})
        for name, config in nodes_config.items():
            self._nodes[name] = MeshNode(
                name=name,
                endpoint=config.get("endpoint", ""),
                protocol=config.get("protocol", "http"),
                health_path=config.get("health_path", "/health"),
            )

    # ── Discovery ─────────────────────────────────────────────────────────

    def discover(self) -> Dict[str, MeshNode]:
        """Discover all mesh nodes. Returns current node map."""
        return dict(self._nodes)

    def get_repos(self) -> Dict[str, Dict]:
        """Get all repos in the ecosystem with their roles."""
        return self._ecosystem.get("repos", {})

    def get_pillars(self) -> Dict[str, Dict]:
        """Get all operational pillars with lead/backup assignments."""
        return self._ecosystem.get("pillars", {})

    def get_tier(self, tier: int) -> List[str]:
        """Get all repos at a specific tier level."""
        return [name for name, info in self._ecosystem.get("repos", {}).items() if info.get("tier") == tier]

    # ── Health ────────────────────────────────────────────────────────────

    def health_check(self, node_name: Optional[str] = None) -> Dict[str, bool]:
        """Check health of mesh nodes. Returns {name: healthy} map."""
        import urllib.request

        targets = {node_name: self._nodes[node_name]} if node_name else self._nodes
        results = {}

        for name, node in targets.items():
            url = f"{node.protocol}://{node.endpoint}{node.health_path}"
            start = time.time()
            try:
                req = urllib.request.Request(url, method="GET")
                resp = urllib.request.urlopen(req, timeout=5)
                node.healthy = resp.status == 200
                node.latency_ms = (time.time() - start) * 1000
            except Exception:
                node.healthy = False
                node.latency_ms = None
            node.last_check = time.time()
            results[name] = node.healthy

        # Save health state
        _save_json(MESH_DIR / "health.json", {
            "last_check": time.time(),
            "nodes": {n: {"healthy": node.healthy, "latency_ms": node.latency_ms} for n, node in self._nodes.items()},
            "overall_status": "healthy" if all(results.values()) else "degraded",
        })

        return results

    def get_health(self) -> Dict:
        """Read cached health state."""
        return _load_json(MESH_DIR / "health.json")

    # ── Events ────────────────────────────────────────────────────────────

    def emit(self, event_type: str, data: Dict[str, Any]) -> MeshEvent:
        """Emit an event to the mesh event bus."""
        event = MeshEvent(event_type=event_type, source=self.repo_name, data=data)
        self._event_log.append(event)

        # Persist to event log
        log_path = OPS_DIR / "events.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps({"id": event.event_id, "type": event.event_type, "source": event.source, "data": event.data, "ts": event.timestamp}) + "\n")

        # Trigger local handlers
        for handler in self._handlers.get(event_type, []) + self._handlers.get("*", []):
            try:
                handler(event)
            except Exception:
                pass

        return event

    def on(self, event_type: str, handler: Callable) -> None:
        """Register an event handler."""
        self._handlers.setdefault(event_type, []).append(handler)

    def get_events(self, event_type: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Read recent events from the log."""
        log_path = OPS_DIR / "events.jsonl"
        if not log_path.exists():
            return []

        events = []
        for line in log_path.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                evt = json.loads(line)
                if event_type and evt.get("type") != event_type:
                    continue
                events.append(evt)
            except json.JSONDecodeError:
                continue

        return events[-limit:]

    # ── Invocation ────────────────────────────────────────────────────────

    def invoke(self, node_name: str, capability: str, params: Dict[str, Any] = None) -> Dict:
        """Invoke a capability on a remote mesh node via HTTP."""
        import urllib.request

        node = self._nodes.get(node_name)
        if not node:
            return {"error": f"Unknown node: {node_name}"}

        url = f"{node.protocol}://{node.endpoint}/invoke/{capability}"
        data = json.dumps(params or {}).encode()

        try:
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e), "node": node_name, "capability": capability}

    # ── Runbooks ──────────────────────────────────────────────────────────

    def get_runbook(self, name: str) -> Optional[Runbook]:
        """Load a runbook by name."""
        runbooks = {}
        for search in [REPO_APEX_DIR / "ops" / "runbooks.json", OPS_DIR / "runbooks.json"]:
            runbooks = _load_json(search).get("runbooks", {})
            if runbooks:
                break
        rb = runbooks.get(name)
        if not rb:
            return None
        return Runbook(name=name, trigger=rb.get("trigger", ""), steps=rb.get("steps", []), escalation=rb.get("escalation", ""))

    def list_runbooks(self) -> List[str]:
        """List all available runbooks."""
        for search in [REPO_APEX_DIR / "ops" / "runbooks.json", OPS_DIR / "runbooks.json"]:
            runbooks = _load_json(search).get("runbooks", {})
            if runbooks:
                return list(runbooks.keys())
        return []

    def execute_runbook(self, name: str) -> Dict:
        """Execute a runbook — returns steps to execute."""
        rb = self.get_runbook(name)
        if not rb:
            return {"error": f"Runbook not found: {name}"}

        self.emit("runbook_triggered", {"runbook": name, "trigger": rb.trigger})

        return {
            "runbook": name,
            "trigger": rb.trigger,
            "steps": rb.steps,
            "escalation": rb.escalation,
            "status": "ready_for_execution",
            "triggered_at": time.time(),
        }

    # ── Context ───────────────────────────────────────────────────────────

    def get_context(self) -> Dict:
        """Get full mesh context for agent loading."""
        return {
            "ecosystem": self._ecosystem,
            "topology": self._topology,
            "health": self.get_health(),
            "recent_events": self.get_events(limit=10),
            "runbooks": self.list_runbooks(),
            "repo_name": self.repo_name,
        }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="APEX Mesh Intelligence")
    parser.add_argument("action", choices=["discover", "health", "context", "events", "runbooks", "invoke"])
    parser.add_argument("--node", type=str, help="Target node")
    parser.add_argument("--capability", type=str, help="Capability to invoke")
    parser.add_argument("--repo", type=str, default="cli", help="Source repo name")
    args = parser.parse_args()

    mesh = Mesh(repo_name=args.repo)

    if args.action == "discover":
        nodes = mesh.discover()
        repos = mesh.get_repos()
        print(f"\nMesh Nodes ({len(nodes)}):")
        for name, node in nodes.items():
            print(f"  {name}: {node.endpoint} [{node.protocol}]")
        print(f"\nEcosystem Repos ({len(repos)}):")
        for name, info in repos.items():
            print(f"  {name}: {info['role']} / {info['domain']} (tier {info['tier']})")

    elif args.action == "health":
        results = mesh.health_check(args.node)
        for name, ok in results.items():
            print(f"  {'✅' if ok else '❌'} {name}")

    elif args.action == "context":
        ctx = mesh.get_context()
        print(json.dumps(ctx, indent=2, default=str))

    elif args.action == "events":
        events = mesh.get_events(limit=20)
        for e in events:
            print(f"  [{e.get('type')}] {e.get('source')}: {json.dumps(e.get('data', {}))[:80]}")

    elif args.action == "runbooks":
        for name in mesh.list_runbooks():
            rb = mesh.get_runbook(name)
            print(f"  {name}: {rb.trigger}")

    elif args.action == "invoke":
        if not args.node or not args.capability:
            print("--node and --capability required")
            return
        result = mesh.invoke(args.node, args.capability)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
