from __future__ import annotations

import argparse
import json
from chutku.chat import reply, run_chat
from chutku.runtime import Runtime
from chutku.app import create_runtime


def _runtime(grant_id="sandbox") -> Runtime:
    return create_runtime(grant_id=grant_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chutku text-first runtime")
    parser.add_argument("--resource-grant", default="sandbox",
                        help="Runtime-owned resource grant ID for filesystem tools (default: sandbox).")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("tools")
    subparsers.add_parser("doctor", help="Check foundation health without opening apps, microphone or model")
    plan = subparsers.add_parser("plan", help="Inspect deterministic understanding without executing anything")
    plan.add_argument("message", nargs="+")
    sequence = subparsers.add_parser("sequence", help="Review up to six explicit commands; add --execute to run")
    sequence.add_argument("--step", action="append", required=True)
    sequence.add_argument("--execute", action="store_true")
    control = subparsers.add_parser("control", help="Pause/resume actions independently of the running dashboard")
    control.add_argument("action", choices=("pause", "resume", "status", "stop"))
    brain = subparsers.add_parser("brain", help="Preview a general typed-tool plan with the local model; never execute automatically")
    brain.add_argument("message", nargs="+")
    brain.add_argument("--consult-gemini", action="store_true",
                       help="Also send the exact request text to Google's Gemini API for advisory consensus")
    dashboard = subparsers.add_parser("dashboard", help="Start the local Chutku dashboard")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--open", action="store_true", dest="open_browser", help="Open the dashboard in your default browser")
    workflow = subparsers.add_parser("workflow", help="Preview a project setup recipe; add --execute to run it")
    workflow.add_argument("name")
    workflow.add_argument("--execute", action="store_true")
    subparsers.add_parser("chat", help="Start the interactive deterministic text console")
    history = subparsers.add_parser("history", help="Show recent task audit summaries")
    history.add_argument("--limit", type=int, default=10)
    trace = subparsers.add_parser("trace", help="Show the safe audit trace for one task ID")
    trace.add_argument("task_id")
    run = subparsers.add_parser("run")
    run.add_argument("tool")
    run.add_argument("--args", default="{}", help="JSON object arguments")
    ask = subparsers.add_parser("ask", help="Run a supported plain-language command")
    ask.add_argument("message", nargs="+", help="Supported request text; words are joined safely.")
    access = subparsers.add_parser("access", help="List, add or revoke explicit filesystem resource grants")
    access_sub = access.add_subparsers(dest="access_action", required=True)
    access_sub.add_parser("list")
    add = access_sub.add_parser("grant")
    add.add_argument("root")
    add.add_argument("--permission", choices=("observe", "modify"), default="observe")
    revoke = access_sub.add_parser("revoke")
    revoke.add_argument("grant_id")
    authority = subparsers.add_parser("authority", help="List, grant or revoke exact non-filesystem PC capabilities")
    authority_sub = authority.add_subparsers(dest="authority_action", required=True)
    authority_sub.add_parser("list")
    authority_grant = authority_sub.add_parser("grant")
    authority_grant.add_argument("capability")
    authority_revoke = authority_sub.add_parser("revoke")
    authority_revoke.add_argument("capability")
    autostart = subparsers.add_parser("autostart", help="Start Chutku automatically when you sign in to Windows")
    autostart.add_argument("autostart_action", choices=("on", "off", "status"))
    gemini = subparsers.add_parser("gemini", help="Configure Gemini as the secondary planner (off unless cloud.gemini is granted)")
    gemini.add_argument("gemini_action", choices=("status", "set-key"))
    subparsers.add_parser("open", help="Open the running Chutku dashboard in your browser")
    reflexes = subparsers.add_parser("reflex", help="Learned instant skills: list, compile, enable or disable")
    reflexes.add_argument("reflex_action", choices=("list", "compile", "enable", "disable"))
    reflexes.add_argument("reflex_id", nargs="?")
    namespace = parser.parse_args()
    if namespace.command == "open":
        from chutku.dashboard import open_running_dashboard
        print(open_running_dashboard())
        return
    if namespace.command == "reflex":
        from chutku import reflex
        from chutku.app import PROJECT_ROOT
        if namespace.reflex_action == "compile":
            with create_runtime() as runtime:
                print(json.dumps(reflex.compile_all(PROJECT_ROOT, runtime.registry), indent=2, ensure_ascii=False))
        elif namespace.reflex_action == "list":
            print(json.dumps(reflex.summary(PROJECT_ROOT), indent=2, ensure_ascii=False))
        else:
            if not namespace.reflex_id:
                raise SystemExit("Give the skill id (see: reflex list).")
            changed = reflex.set_enabled(PROJECT_ROOT, namespace.reflex_id, namespace.reflex_action == "enable")
            if changed is None:
                raise SystemExit(f"No skill with id {namespace.reflex_id}.")
            print(json.dumps({"id": changed["id"], "enabled": changed["enabled"]}))
        return
    if namespace.command == "autostart":
        from chutku.autostart import autostart
        print(json.dumps(autostart(namespace.autostart_action), indent=2))
        return
    if namespace.command == "gemini":
        from chutku import cloud_planner
        if namespace.gemini_action == "set-key":
            import getpass
            cloud_planner.store_key(getpass.getpass("Gemini API key (input hidden): "))
            print("Stored in Windows Credential Manager as", cloud_planner.CREDENTIAL_TARGET)
        else:
            print(json.dumps({"key_available": bool(cloud_planner.api_key()),
                              "enabled_by_capability": cloud_planner.fallback_planner() is not None,
                              "enable_with": "python -m chutku.cli authority grant cloud.gemini"}, indent=2))
        return
    if namespace.command == "plan":
        from chutku.planning import plan_request
        print(json.dumps(plan_request(" ".join(namespace.message)).to_dict(), indent=2))
        return
    if namespace.command == "doctor":
        from chutku.app import PROJECT_ROOT
        from chutku.doctor import inspect_foundation
        report = inspect_foundation(PROJECT_ROOT)
        print(json.dumps(report, indent=2))
        if not report["ready"]:
            raise SystemExit(1)
        return
    if namespace.command == "control":
        from chutku.app import PROJECT_ROOT
        from chutku.core.action_control import ActionControl
        from chutku.core.execution_lock import ExecutionBusy
        controller = ActionControl(PROJECT_ROOT)
        try:
            if namespace.action == "stop":
                controller.stop()
            elif namespace.action == "pause":
                controller.pause()
            elif namespace.action == "resume":
                controller.resume()
        except (OSError, ExecutionBusy) as error:
            parser.exit(1, f"Could not change action control: {error}\n")
        print("Actions paused. An in-flight OS action may finish." if controller.paused else "Actions enabled.")
        return
    if namespace.command == "dashboard":
        from chutku.dashboard import serve
        if not 0 <= namespace.port <= 65535:
            parser.error("Port must be between 0 and 65535.")
        try:
            serve(namespace.port, namespace.open_browser)
        except OSError as error:
            parser.exit(1, f"Dashboard could not start: {error}\nIf it is already running, use its existing session link or choose another --port.\n")
        return
    runtime = _runtime(namespace.resource_grant)
    try:
        _dispatch(namespace, runtime, parser)
    finally:
        runtime.close()


def _dispatch(namespace, runtime: Runtime, parser) -> None:
    if namespace.command == "authority":
        try:
            if namespace.authority_action == "list":
                result = [grant.public() for grant in runtime.capability_grants.list()]
            elif namespace.authority_action == "grant":
                result = runtime.capability_grants.grant(namespace.capability).public()
            else:
                result = runtime.capability_grants.revoke(namespace.capability).public()
            print(json.dumps(result, indent=2))
        except (OSError, ValueError) as error:
            parser.exit(1, f"PC capability could not be changed: {error}\n")
        return
    if namespace.command == "access":
        try:
            if namespace.access_action == "list":
                result = [grant.public() for grant in runtime.resource_grants.list()]
            elif namespace.access_action == "grant":
                result = runtime.resource_grants.grant(namespace.root, {namespace.permission}).public()
            else:
                result = runtime.resource_grants.revoke(namespace.grant_id).public()
            print(json.dumps(result, indent=2))
        except (OSError, ValueError) as error:
            parser.exit(1, f"Access grant could not be changed: {error}\n")
        return
    if namespace.command == "sequence":
        from chutku.plans import build_plan, run_plan
        try:
            plan = build_plan(namespace.step, runtime)
            result = run_plan(plan, runtime) if namespace.execute else plan
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if namespace.execute and result["state"] != "COMPLETED":
                raise SystemExit(1)
        except (ValueError, OSError) as error:
            parser.exit(1, f"Plan could not run: {error}\n")
        return
    if namespace.command == "brain":
        from chutku.brain import preview_tool_plan, preview_dual_tool_plan
        try:
            message = " ".join(namespace.message)
            proposal = (preview_dual_tool_plan(message, runtime, cloud_consent=True)
                        if namespace.consult_gemini else preview_tool_plan(message, runtime))
            print(json.dumps(proposal, indent=2, ensure_ascii=False))
            print("Preview only. Use the dashboard to review and run supported steps.")
        except (OSError, ValueError, RuntimeError, KeyError, PermissionError) as error:
            parser.exit(1, f"Local planning did not complete: {error}\n")
        return
    if namespace.command == "workflow":
        from chutku.workflows import project_plan, preflight, run_project
        try:
            plan = project_plan(namespace.name, runtime.granted_root)
            if namespace.execute:
                result = run_project(plan, runtime)
                print(json.dumps(result, indent=2))
                if result["state"] != "COMPLETED":
                    raise SystemExit(1)
            else:
                preflight(plan, runtime)
                print(json.dumps(plan, indent=2))
                print("Preview only. Add --execute to run this recipe.")
        except ValueError as error:
            parser.error(str(error))
        return
    if namespace.command == "tools":
        print("\n".join(f"{tool.name}: {tool.description}" for tool in runtime.registry.list()))
        return
    if namespace.command == "chat":
        run_chat(runtime)
        return
    if namespace.command == "history":
        try:
            tasks = runtime.event_log.recent_tasks(namespace.limit)
        except ValueError as error:
            parser.error(str(error))
        if not tasks:
            print("No recorded tasks.")
            return
        print("Recent tasks (sensitive arguments and tool output are not shown):")
        for task in tasks:
            print(f"{task['timestamp']} | {task['state']} | {task['tool']} | {task['task_id']}")
        return
    if namespace.command == "trace":
        trace_events = runtime.event_log.safe_trace(namespace.task_id)
        if not trace_events:
            print("No audit trace found for that task ID.")
            return
        for event in trace_events:
            print(f"{event['timestamp']} | {event['event_type']} | {json.dumps(event['details'], sort_keys=True)}")
        return
    if namespace.command == "ask":
        print(reply(" ".join(namespace.message), runtime))
        return
    try:
        arguments = json.loads(namespace.args)
        if not isinstance(arguments, dict):
            raise ValueError("--args must be a JSON object")
    except (json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(runtime.run(namespace.tool, arguments), default=str, indent=2))


if __name__ == "__main__":
    main()
