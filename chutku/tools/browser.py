"""Bounded Playwright automation using fresh profiles and semantic locators."""
from __future__ import annotations

from pathlib import Path
import os
import sys
from urllib.parse import urlsplit

from chutku.tools.registry import Risk, Tool, ToolResult, Verification


MAX_STEPS = 20
MAX_TEXT = 4096
_BROWSERS = {
    "edge": [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
             Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe"],
    "chrome": [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
               Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe"],
}
_LOCATOR = {"type": "object", "properties": {
    "by": {"type": "string", "enum": ["role", "label", "test_id"]},
    "value": {"type": "string", "minLength": 1, "maxLength": 512},
    "role": {"type": "string", "maxLength": 64}},
    "required": ["by", "value"], "additionalProperties": False}
_INSPECT_SCHEMA = {"type": "object", "properties": {
    "url": {"type": "string", "maxLength": 2048}, "browser": {"type": "string", "enum": ["edge", "chrome"]}},
    "required": ["url", "browser"], "additionalProperties": False}
_WORKFLOW_SCHEMA = {"type": "object", "properties": {
    "url": {"type": "string", "maxLength": 2048}, "browser": {"type": "string", "enum": ["edge", "chrome"]},
    "steps": {"type": "array", "minItems": 1, "maxItems": MAX_STEPS, "items": {"type": "object"}}},
    "required": ["url", "browser", "steps"], "additionalProperties": False}


def _url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError("URL must be a bounded string.")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only credential-free explicit HTTP or HTTPS URLs are accepted.")


def _browser(value):
    if value not in _BROWSERS:
        raise ValueError("Choose edge or chrome.")
    if not any(path.is_file() for path in _BROWSERS[value]):
        raise ValueError(f"The selected {value} executable is not installed.")


def _locator(value):
    if not isinstance(value, dict) or set(value) not in ({"by", "value"}, {"by", "value", "role"}):
        raise ValueError("Locator requires a bounded semantic identity.")
    if value.get("by") not in {"role", "label", "test_id"} or not isinstance(value.get("value"), str) or not 1 <= len(value["value"]) <= 512:
        raise ValueError("Invalid semantic locator.")
    if value["by"] == "role" and (not isinstance(value.get("role"), str) or not 1 <= len(value["role"]) <= 64):
        raise ValueError("Role locators require an exact role.")
    if value["by"] != "role" and "role" in value:
        raise ValueError("role is only valid for role locators.")


def _validate_inspect(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"url", "browser"}:
        raise ValueError("Provide only url and browser.")
    _url(arguments["url"]); _browser(arguments["browser"])


def _validate_workflow(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"url", "browser", "steps"}:
        raise ValueError("Provide url, browser and steps.")
    _url(arguments["url"]); _browser(arguments["browser"])
    if not isinstance(arguments["steps"], list) or not 1 <= len(arguments["steps"]) <= MAX_STEPS:
        raise ValueError("Workflow requires 1-20 steps.")
    for step in arguments["steps"]:
        if not isinstance(step, dict) or step.get("action") not in {"fill", "click", "select"}:
            raise ValueError("Only fill, click and select actions are supported.")
        required = {"action", "locator", "expect"} | ({"text"} if step["action"] == "fill" else {"option"} if step["action"] == "select" else set())
        if set(step) != required:
            raise ValueError("Browser step does not match its exact contract.")
        _locator(step["locator"])
        if "text" in step and (not isinstance(step["text"], str) or len(step["text"]) > MAX_TEXT):
            raise ValueError("Fill text is too large.")
        if "option" in step and (not isinstance(step["option"], str) or len(step["option"]) > 512):
            raise ValueError("Select option is invalid.")
        expect = step["expect"]
        if not isinstance(expect, dict) or set(expect) != {"locator", "property", "expected"}:
            raise ValueError("Each step requires an exact postcondition.")
        _locator(expect["locator"])
        if (expect["property"] not in {"text", "value", "checked"}
                or expect["property"] == "checked" and type(expect["expected"]) is not bool
                or expect["property"] in {"text", "value"} and not isinstance(expect["expected"], str)):
            raise ValueError("Invalid browser postcondition.")


def _executable(name):
    return next(path for path in _BROWSERS[name] if path.is_file())


def _locate(page, spec):
    if spec["by"] == "label": return page.get_by_label(spec["value"], exact=True)
    if spec["by"] == "test_id": return page.get_by_test_id(spec["value"])
    return page.get_by_role(spec["role"], name=spec["value"], exact=True)


def _assert(locator, expect):
    if locator.count() != 1: return False
    if expect["property"] == "text": return locator.inner_text(timeout=2000) == expect["expected"]
    if expect["property"] == "value": return locator.input_value(timeout=2000) == expect["expected"]
    return locator.is_checked(timeout=2000) is expect["expected"]


def _session(arguments, workflow=False):
    if sys.platform != "win32": raise OSError("Browser automation requires Windows.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise OSError("Pinned Playwright is not installed.") from error
    with sync_playwright() as api:
        browser = api.chromium.launch(executable_path=str(_executable(arguments["browser"])), headless=False,
                                      args=["--disable-extensions", "--no-first-run"], timeout=15000)
        try:
            context = browser.new_context(accept_downloads=False)
            page = context.new_page(); page.goto(arguments["url"], wait_until="domcontentloaded", timeout=15000)
            if not workflow:
                return {"requested_url": arguments["url"], "final_url": page.url, "title": page.title()[:512],
                        "headings": page.get_by_role("heading").all_inner_texts()[:20],
                        "buttons": page.get_by_role("button").all_inner_texts()[:30]}
            completed = 0
            for step in arguments["steps"]:
                target = _locate(page, step["locator"])
                count = target.count()
                if count != 1: raise OSError(f"Semantic locator at step {completed + 1} matched {count} elements, expected one.")
                if step["action"] == "fill": target.fill(step["text"], timeout=3000)
                elif step["action"] == "select": target.select_option(label=step["option"], timeout=3000)
                else: target.click(timeout=3000)
                if not _assert(_locate(page, step["expect"]["locator"]), step["expect"]):
                    raise OSError("Browser action postcondition was not verified.")
                completed += 1
            return {"final_url": page.url, "steps_completed": completed, "verified": completed == len(arguments["steps"])}
        finally:
            browser.close()


def _inspect(arguments, _context):
    try: output = _session(arguments)
    except OSError as error: return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult(output | {"provenance": "external_untrusted"}, Verification.PASS,
                      {"requested_url": output["requested_url"], "final_url": output["final_url"], "title": "[REDACTED]", "content": "[REDACTED]"})


def _workflow(arguments, _context):
    try: output = _session(arguments, True)
    except OSError as error: return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult(output, Verification.PASS if output.get("verified") else Verification.FAIL)


def register_browser_tools(registry):
    registry.register(Tool("browser.inspect", "Open one explicit HTTP(S) URL in a fresh visible browser profile and return bounded untrusted structure.",
        Risk.OBSERVATION, _inspect, _validate_inspect, required_capability="browser.navigate", argument_schema=_INSPECT_SCHEMA,
        prerequisites=("pinned Playwright", "installed Edge or Chrome",), reversibility="browser_closes_after_observation", success_predicate="page_dom_loaded_and_bounded_structure_returned", network_egress=True))
    registry.register(Tool("browser.workflow", "Run 1-20 reviewed semantic browser actions in a fresh visible profile with a postcondition after every action.",
        Risk.EXTERNAL_SIDE_EFFECT, _workflow, _validate_workflow, frozenset({"steps"}), required_capability="browser.input",
        argument_schema=_WORKFLOW_SCHEMA, prerequisites=("pinned Playwright", "installed Edge or Chrome",),
        reversibility="site_dependent", success_predicate="every_semantic_action_postcondition_verified", network_egress=True))
