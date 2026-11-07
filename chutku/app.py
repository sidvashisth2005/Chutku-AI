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
    from chutku.tools.timeline_tools import register_timeline_tools
    register_timeline_tools(registry, runtime)
    from chutku.skills import register_skill_tools   # X15: skill.* tools and the owner-approved skills
    register_skill_tools(registry, base)
    from chutku.skill_import import register_import_tools   # X17: skills learned from GitHub projects
    register_import_tools(registry, base)
    from chutku.evolve import register_evolve_tools   # Y2: improvement ideas; only the owner approves one
    register_evolve_tools(registry, base)
    from chutku.learning_inbox import register_learning_tools   # H10-H13, H27, H28: learning with the owner's OK
    register_learning_tools(registry, base)
    from chutku.goals import register_goal_tools   # H24: standing goals, checked from the PC
    register_goal_tools(registry, base)
    from chutku.backup import register_backup_tools   # H25: memory backups (restore only from the CLI, Chutku stopped)
    register_backup_tools(registry, base)
    from chutku.for_each import register_for_each_tool   # H14: one step repeats a tool for a list's items
    register_for_each_tool(registry)
    from chutku.doctor import register_doctor_tools   # H26: 'khud ko theek karo'
    register_doctor_tools(registry, base)
    from chutku.blueprints import register_blueprint_tools   # H23: ready-made automations
    register_blueprint_tools(registry)
    from chutku.board import register_board_tools   # H15: task board + background research
    register_board_tools(registry, base)
    from chutku.gateway.telegram import register_telegram_tools   # H16: handoff to Telegram
    register_telegram_tools(registry, base)
    return runtime
