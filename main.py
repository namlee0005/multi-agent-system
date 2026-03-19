#!/usr/bin/env python3
"""Multi-Agent Project Advisor — CLI entry point.

Usage:
    python main.py "Build a crypto dashboard with BTC/ETH prices and Polymarket events"
    python main.py "Build a SaaS invoicing app" --output report.md --verbose
    python main.py "Build a real-time chat app" --config my_config.yaml
    python main.py "Build a chat app" --headless --format json
"""

import argparse
import datetime
import io
import json
import os
import sys
import yaml

from orchestrator import Orchestrator

_REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


def build_markdown_report(result: dict) -> str:
    """Format the orchestrator output as a clean Markdown report."""
    md = f"# Multi-Agent Project Advisor Report\n\n"
    md += f"**Project:** {result.get('project_description', 'N/A')}\n\n"

    md += "## Selected Specialist Agents\n"
    for idx, agent in enumerate(result.get("selected_agents", []), 1):
        md += f"{idx}. **{agent.title()}**\n"
    md += "\n"

    if result.get("round1"):
        md += "## Debate Round 1: Initial Proposals\n"
        for agent, proposal in result["round1"].items():
            md += f"### {agent.title()}\n{proposal}\n\n"

    if result.get("round2"):
        md += "## Debate Round 2: Critiques & Refinements\n"
        for agent, refinement in result["round2"].items():
            md += f"### {agent.title()}\n{refinement}\n\n"

    if result.get("synthesis"):
        md += "## Final Synthesis & Architecture Recommendation\n"
        md += f"{result['synthesis']}\n"

    return md


def load_config(path: str) -> dict:
    """Load YAML config, with helpful error messages."""
    if not os.path.exists(path):
        print(f"Error: Config file '{path}' not found.", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            print(f"Error parsing config '{path}': {e}", file=sys.stderr)
            sys.exit(1)


def default_output_path(project_description: str) -> str:
    """Generate a timestamped output filename inside the reports/ directory."""
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = "_".join(project_description.lower().split()[:5])
    slug = "".join(c if c.isalnum() or c == "_" else "" for c in slug)
    filename = f"report_{slug}_{timestamp}.md"
    return os.path.join(_REPORTS_DIR, filename)


def _safe_output_path(path: str) -> str:
    """
    Resolve the output path and ensure it stays inside reports/.
    If a bare filename or relative path is given, anchor it to reports/.
    Raises ValueError on path traversal attempts.
    """
    os.makedirs(_REPORTS_DIR, exist_ok=True)
    # If the caller gave a plain filename or relative path, anchor to reports/
    if not os.path.isabs(path):
        path = os.path.join(_REPORTS_DIR, path)
    resolved = os.path.realpath(path)
    reports_real = os.path.realpath(_REPORTS_DIR)
    if not resolved.startswith(reports_real + os.sep) and resolved != reports_real:
        raise ValueError(
            f"Output path '{path}' resolves outside reports/ ({resolved}). "
            "Use a relative filename or a path inside reports/."
        )
    return resolved


def parse_args():
    parser = argparse.ArgumentParser(
        description="Multi-Agent Project Advisor: debate-driven tech recommendations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "Build a crypto dashboard with BTC/ETH prices and Polymarket events"
  python main.py "Build a real-time multiplayer game" --output game_report.md
  python main.py "Build a B2B SaaS invoicing app" --config custom.yaml --quiet
  python main.py "Build a chat app" --headless --format json
        """,
    )
    parser.add_argument(
        "project",
        nargs="?",
        help="Project description (or use --project flag)",
    )
    parser.add_argument(
        "--project", "-p",
        dest="project_flag",
        help="Project description (alternative to positional arg)",
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to config YAML (default: config.yaml)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output filename (placed in reports/ if not absolute, default: auto-generated)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress verbose agent output (summary only)",
    )
    parser.add_argument(
        "--project-path",
        help="Path to the target project directory (for agent output like spec.md/tasks.md)",
    )
    parser.add_argument(
        "--mode",
        choices=["planner", "continue", "agent"],
        default="planner",
        help="Operation mode: 'planner' (run planner debate), 'continue' (resume pipeline after approval), 'agent' (run a specific agent)",
    )
    parser.add_argument(
        "--agent",
        help="Specific agent to run in 'agent' mode (e.g., Architect, BackendDev) — case-insensitive",
    )
    parser.add_argument(
        "--task",
        help="Specific task for the agent in 'agent' mode (e.g., update_tasks_md)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Suppress all output except the final result (for CI/automation use)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Final result output format: 'text' (default) or 'json'",
    )
    return parser.parse_args()


class _SuppressedStdout:
    """Context manager that redirects stdout to /dev/null."""
    def __enter__(self):
        self._original = sys.stdout
        sys.stdout = io.StringIO()
        return self

    def __exit__(self, *_):
        sys.stdout = self._original


def emit_result(output_format: str, success: bool, output_path: str = None,
                project: str = None, mode: str = None, message: str = None):
    """Write the final result to real stdout and exit with appropriate code."""
    if output_format == "json":
        payload = {
            "success": success,
            "mode": mode,
            "project": project,
            "output_path": output_path,
            "message": message,
        }
        print(json.dumps(payload))
    else:
        if success:
            print(message or f"Success: output written to {output_path}")
        else:
            print(f"Error: {message}", file=sys.stderr)

    sys.exit(0 if success else 2)


def main():
    args = parse_args()

    # Resolve project description
    project = args.project or args.project_flag
    if not project:
        print("Error: Provide a project description or specify a mode.", file=sys.stderr)
        print('Example: python main.py "Build a crypto dashboard" --project-path /path/to/project', file=sys.stderr)
        sys.exit(1)

    # Load config — errors go to stderr regardless of headless mode
    config = load_config(args.config)

    # In headless mode, suppress stdout for all intermediate output
    suppressor = _SuppressedStdout() if args.headless else _NoopContext()

    verbose = not args.quiet and not args.headless
    orchestrator = Orchestrator(config, verbose=verbose, project_path=args.project_path)

    if args.mode == "planner":
        # Resolve and sanitize output path before starting the run
        try:
            output_path = _safe_output_path(args.output) if args.output else default_output_path(project)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        with suppressor:
            print("\n" + "═" * 60)
            print("RUNNING PLANNER DEBATE")
            print("═" * 60)
            try:
                result = orchestrator.run_planner_debate(project)
            except KeyboardInterrupt:
                print("\n\nInterrupted by user.", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"\nFatal error during Planner debate: {e}", file=sys.stderr)
                if args.headless:
                    emit_result(args.output_format, success=False, project=project,
                                mode=args.mode, message=str(e))
                raise

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            report_md = build_markdown_report(result)
            with open(output_path, "w") as f:
                f.write(report_md)

            print(f"\n✓ Planner Report saved to: {output_path}")
            print("\n" + "═" * 60)
            print("PLANNER DEBATE COMPLETED - AWAITING HUMAN APPROVAL")
            print("═" * 60)
            print(f"Review the report at {output_path} and then run:")
            print(f"  python main.py --mode continue --project \"{project}\" --project-path {args.project_path} --output {output_path}")

        emit_result(
            args.output_format, success=True,
            output_path=output_path, project=project, mode=args.mode,
            message=f"Planner report saved to {output_path}",
        )

    elif args.mode == "continue":
        if not args.project_path or not args.output:
            print("Error: --project-path and --output are required in 'continue' mode.", file=sys.stderr)
            sys.exit(1)
        with suppressor:
            print("\n" + "═" * 60)
            print(f"CONTINUING PROJECT: {project}")
            print("═" * 60)
            try:
                orchestrator.run_agent(agent_name="Planner", task_name="write_spec_file", project_description=project)
                orchestrator.run_agent(agent_name="Planner", task_name="write_tasks_file", project_description=project)
            except Exception as e:
                print(f"\nFatal error during continue: {e}", file=sys.stderr)
                if args.headless:
                    emit_result(args.output_format, success=False, project=project,
                                mode=args.mode, message=str(e))
                raise

        emit_result(
            args.output_format, success=True,
            output_path=args.output, project=project, mode=args.mode,
            message="Pipeline continue completed successfully",
        )

    elif args.mode == "agent":
        if not args.agent or not args.task or not args.project_path:
            print("Error: --agent, --task, and --project-path are required in 'agent' mode.", file=sys.stderr)
            sys.exit(1)
        with suppressor:
            print("\n" + "═" * 60)
            print(f"RUNNING SPECIFIC AGENT: {args.agent} for task: {args.task}")
            print("═" * 60)
            try:
                orchestrator.run_agent(args.agent, args.task, project_description=project)
            except Exception as e:
                print(f"\nFatal error running agent: {e}", file=sys.stderr)
                if args.headless:
                    emit_result(args.output_format, success=False, project=project,
                                mode=args.mode, message=str(e))
                raise

        emit_result(
            args.output_format, success=True,
            output_path=args.project_path, project=project, mode=args.mode,
            message=f"Agent '{args.agent}' task '{args.task}' completed",
        )

    else:
        print("Error: Invalid mode specified.", file=sys.stderr)
        sys.exit(1)


class _NoopContext:
    """No-op context manager for non-headless mode."""
    def __enter__(self): return self
    def __exit__(self, *_): pass


if __name__ == "__main__":
    main()