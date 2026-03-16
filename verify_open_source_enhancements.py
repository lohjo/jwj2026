"""
verify_open_source_enhancements.py

Checks whether the enhancements documented in open-source-enhancements.md are
implemented in this repository and usable by end users.

Run: python verify_open_source_enhancements.py
Exit code:
  0 -> all enhancement checks pass
  1 -> one or more enhancement checks fail
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent

PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
INFO = "\033[36m[INFO]\033[0m"


@dataclass
class ToolStatus:
    tool: str
    implemented: bool
    usable: bool
    notes: list[str]

    @property
    def ok(self) -> bool:
        return self.implemented and self.usable


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _function_exists(path: str, function_name: str) -> bool:
    file_path = ROOT / path
    if not file_path.exists():
        return False
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(isinstance(node, ast.FunctionDef) and node.name == function_name for node in tree.body)


def check_promptfoo() -> ToolStatus:
    notes: list[str] = []
    cfg_path = ROOT / "promptfooconfig.yaml"
    if not cfg_path.exists():
        return ToolStatus("Promptfoo", False, False, ["promptfooconfig.yaml is missing"])

    cfg = cfg_path.read_text(encoding="utf-8")
    implemented = all(
        token in cfg
        for token in (
            "redteam:",
            "plugins:",
            "language:",
            "prompts:",
        )
    )
    usable = "gemini-2.5-flash" in cfg or "google:gemini" in cfg

    if implemented:
        notes.append("Config includes redteam, plugins, language and prompts")
    else:
        notes.append("Config is missing one or more required redteam sections")

    if usable:
        notes.append("Gemini target is configured for runnable evaluations")
    else:
        notes.append("No runnable Gemini target detected in promptfooconfig.yaml")

    return ToolStatus("Promptfoo", implemented, usable, notes)


def check_mirofish() -> ToolStatus:
    notes: list[str] = []
    predictor_exists = (ROOT / "research_agent" / "predictor.py").exists()
    predictor_fn = _function_exists("research_agent/predictor.py", "predict_misinfo_trends")
    agent_src = _read("research_agent/agent.py")
    wired = "predict_misinfo_trends" in agent_src

    implemented = predictor_exists and predictor_fn
    usable = implemented and wired

    if predictor_exists:
        notes.append("research_agent/predictor.py exists")
    else:
        notes.append("Missing research_agent/predictor.py")

    if predictor_fn:
        notes.append("predict_misinfo_trends() is defined")
    else:
        notes.append("predict_misinfo_trends() is not defined")

    if wired:
        notes.append("research_agent/agent.py references predictor integration")
    else:
        notes.append("predictor output is not wired into research_agent/agent.py")

    return ToolStatus("MiroFish", implemented, usable, notes)


def check_impeccable() -> ToolStatus:
    notes: list[str] = []
    skill_files = [
        ROOT / ".claude/commands/skills/distill/SKILL.md",
        ROOT / ".claude/commands/skills/colorize/SKILL.md",
        ROOT / ".claude/commands/skills/animate/SKILL.md",
    ]
    skills_present = all(path.exists() for path in skill_files)

    ui_src = _read("static/index.html")
    has_distill_evidence = "Impeccable /distill" in ui_src
    has_colorize_evidence = "Impeccable /colorize" in ui_src
    has_animate_evidence = "Impeccable /animate" in ui_src

    implemented = skills_present
    usable = has_distill_evidence and has_colorize_evidence and has_animate_evidence

    if implemented:
        notes.append("Impeccable command skills are installed in .claude/commands/skills")
    else:
        notes.append("One or more Impeccable command skill files are missing")

    if usable:
        notes.append("Web UI contains evidence of /distill, /colorize and /animate output")
    else:
        notes.append("Web UI does not show all expected /distill, /colorize, /animate evidence")

    return ToolStatus("Impeccable", implemented, usable, notes)


def check_openviking() -> ToolStatus:
    notes: list[str] = []
    requirements = _read("requirements.txt").lower()
    has_dep = "openviking" in requirements

    skill_cache_src = _read("research_agent/skill_cache.py").lower()
    agent_src = _read("research_agent/agent.py").lower()
    integrated = "openviking" in skill_cache_src or "openviking" in agent_src

    implemented = has_dep
    usable = has_dep and integrated

    if has_dep:
        notes.append("openviking dependency is declared")
    else:
        notes.append("openviking dependency is not declared in requirements.txt")

    if integrated:
        notes.append("research agent references openviking integration")
    else:
        notes.append("research agent does not reference openviking integration")

    return ToolStatus("OpenViking", implemented, usable, notes)


def collect_statuses() -> list[ToolStatus]:
    return [
        check_promptfoo(),
        check_mirofish(),
        check_impeccable(),
        check_openviking(),
    ]


def main() -> int:
    print("\n── Open-Source Enhancements Implementation Check ─────────────────────────")
    print(f"  {INFO}  Source of truth: open-source-enhancements.md")

    statuses = collect_statuses()

    print("\nTool status:\n")
    for status in statuses:
        tag = PASS if status.ok else FAIL
        impl = "yes" if status.implemented else "no"
        usable = "yes" if status.usable else "no"
        print(f"  {tag}  {status.tool}: implemented={impl}, usable={usable}")
        for note in status.notes:
            print(f"       - {note}")
        print()

    all_ok = all(status.ok for status in statuses)
    if all_ok:
        print(f"{PASS} All enhancements are implemented and user-usable.")
        return 0

    print(f"{FAIL} One or more enhancements are not fully implemented and usable yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
