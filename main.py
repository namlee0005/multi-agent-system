#!/usr/bin/env python3
"""Multi-Agent Project Advisor — CLI entry point.

Usage:
    python main.py "Build a crypto dashboard with BTC/ETH prices and Polymarket events"
    python main.py "Build a SaaS invoicing app" --output report.md --verbose
    python main.py "Build a real-time chat app" --config my_config.yaml
"""

import argparse
import datetime
import os
import sys
import yaml

from orchestrator import Orchestrator

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
    """Generate a timestamped output filename from the project description."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Slugify the first few words
    slug = "_".join(project_description.lower().split()[:5])
    slug = "".join(c if c.isalnum() or c == "_" else "" for c in slug)
    return f"report_{slug}_{timestamp}.md"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Multi-Agent Project Advisor: debate-driven tech recommendations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "Build a crypto dashboard with BTC/ETH prices and Polymarket events"
  python main.py "Build a real-time multiplayer game" --output game_report.md
  python main.py "Build a B2B SaaS invoicing app" --config custom.yaml --quiet
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
        help="Output markdown file path (default: auto-generated)",
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
        help="Specific agent to run in 'agent' mode (e.g., architect, developer)",
    )
    parser.add_argument(
        "--task",
        help="Specific task for the agent in 'agent' mode (e.g., update_tasks_md)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve project description
    project = args.project or args.project_flag
    if not project:
        print("Error: Provide a project description or specify a mode.", file=sys.stderr)
        print('Example: python main.py "Build a crypto dashboard" --project-path /path/to/project', file=sys.stderr)
        sys.exit(1)

    # Load config
    config = load_config(args.config)

    # Initialize Orchestrator
    verbose = not args.quiet
    orchestrator = Orchestrator(config, verbose=verbose, project_path=args.project_path)

    if args.mode == "planner":
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
            raise

        # Build and save markdown report
        output_path = args.output or default_output_path(project)
        report_md = build_markdown_report(result)
        with open(output_path, "w") as f:
            f.write(report_md)
        print(f"\n✓ Planner Report saved to: {output_path}")

        # Signal for human approval
        print("\n" + "═" * 60)
        print("PLANNER DEBATE COMPLETED - AWAITING HUMAN APPROVAL")
        print("═" * 60)
        print(f"Review the report at {output_path} and then run:")
        print(f"  python main.py --mode continue --project \"{project}\" --project-path {args.project_path} --output {output_path}")
        sys.exit(0)

    elif args.mode == "continue":
        if not args.project_path or not args.output:
            print("Error: --project-path and --output are required in 'continue' mode.", file=sys.stderr)
            sys.exit(1)
        print("\n" + "═" * 60)
        print(f"CONTINUING PROJECT: {project}")
        print("═" * 60)
        orchestrator.run_agent(agent_name="planner", task_name="write_spec_file", project_description=project)
        orchestrator.run_agent(agent_name="planner", task_name="write_tasks_file", project_description=project)
        sys.exit(0)

    elif args.mode == "agent":
        if not args.agent or not args.task or not args.project_path:
            print("Error: --agent, --task, and --project-path are required in 'agent' mode.", file=sys.stderr)
            sys.exit(1)
        print("\n" + "═" * 60)
        print(f"RUNNING SPECIFIC AGENT: {args.agent} for task: {args.task}")
        print("═" * 60)
        orchestrator.run_agent(args.agent, args.task, project_description=project)
        sys.exit(0)

    else:
        print("Error: Invalid mode specified.", file=sys.stderr)
        sys.exit(1)

    return {} # Should not reach here in normal flow


if __name__ == "__main__":
    main()
