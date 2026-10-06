from pathlib import Path

from chutku.core.event_log import EventLog
from chutku.core.memory import MemoryStore
from chutku.core.operation_journal import OperationJournal
from chutku.core.resource_grants import ResourceGrantStore
from chutku.core.capability_grants import CapabilityGrantStore
from chutku.policy.kernel import PolicyKernel
from chutku.runtime import Runtime
from chutku.tools.action_log_tools import register_action_log_tools
from chutku.tools.builtin import register_builtin_tools
from chutku.tools.registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_runtime(base: Path = PROJECT_ROOT, grant_id: str = "sandbox") -> Runtime:
    base = base.resolve()
    root = base / "sandbox"
    if root.is_symlink() or (root.exists() and getattr(root.lstat(), "st_file_attributes", 0) & 0x400):
        raise ValueError("The sandbox root must not be a link or reparse point.")
    root.mkdir(parents=True, exist_ok=True)
    grants = ResourceGrantStore(base / "data/resource_grants.db")
    capability_grants = CapabilityGrantStore(base / "data/capability_grants.db")
    grants.ensure_sandbox(root)
    grant = grants.get(grant_id)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    runtime = Runtime(registry, PolicyKernel(), EventLog(base / "data/chutku.db"),
                      OperationJournal(base / "data/operations.db"), grant.root,
                      MemoryStore(base / "data/memory.db"), resource_grants=grants,
                      resource_grant=grant, state_root=base, capability_grants=capability_grants)
    register_action_log_tools(registry, runtime)
    from chutku.rewind import register_rewind_tools
    register_rewind_tools(registry, runtime)
    return runtime
