"""Orchestrator: manages the debate flow between agents."""

import json
import re
import sys
from typing import Optional
from agents import Agent, build_agents, build_planner

# ─── Console helpers ──────────────────────────────────────────────────────────

COLORS = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "cyan":    "\033[96m",
    "yellow":  "\033[93m",
    "green":   "\033[92m",
    "red":     "\033[91m",
    "magenta": "\033[95m",
    "blue":    "\033[94m",
    "gray":    "\033[90m",
}

AGENT_COLORS = {
    "Planner":     "cyan",
    "Researcher":  "blue",
    "Architect":   "magenta",
    "BackendDev":  "yellow",
    "FrontendDev": "green",
    "DevOps":      "cyan",
    "Security":    "red",
    "Skeptic":     "gray",
}


def color(text: str, c: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{COLORS.get(c, '')}{text}{COLORS['reset']}"


def print_header(text: str):
    bar = "═" * 60
    print(f"\n{color(bar, 'bold')}")
    print(color(f"  {text}", "bold"))
    print(f"{color(bar, 'bold')}\n")


def print_agent_header(agent_name: str, round_label: str):
    c = AGENT_COLORS.get(agent_name, "reset")
    print(color(f"\n▶ [{round_label}] {agent_name}", c))
    print(color("─" * 50, "gray"))


def print_response(text: str):
    print(text)
    print()


def print_status(msg: str):
    print(color(f"  → {msg}", "gray"))


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class Orchestrator:
    """Manages the multi-agent debate and produces a final recommendation."""

    def __init__(self, config: dict, verbose: bool = True, project_path: Optional[str] = None):
        self.config = config
        self.verbose = verbose
        self.project_path = project_path
        self.backend_config = config.get("backends", {})
        self.debate_config = config.get("debate", {})
        self.max_rounds = self.debate_config.get("max_rounds", 2)
        self.min_agents = self.debate_config.get("min_agents", 3)
        self.max_agents = self.debate_config.get("max_agents", 5)

        self.planner = build_planner(config, project_path=project_path)
        self.all_agents = build_agents(config, project_path=project_path)

        # Shared context/memory dict — grows as the debate progresses
        self.context: dict = {}

    def _select_agents(self, project_description: str) -> list[str]:
        """Ask the Planner to select relevant agents for this project."""
        print_status("Planner is selecting relevant agents...")

        selection_request = (
            f"Analyze this project and select the 3-5 most relevant specialist agents.\n\n"
            f"Project: {project_description}\n\n"
            f"Available agents: researcher, architect, backend_dev, frontend_dev, devops, security, skeptic\n\n"
            f"Output ONLY a JSON object: {{\"selected_agents\": [\"agent1\", \"agent2\", ...]}}"
        )

        self.context["project_description"] = project_description
        self.context["round"] = "agent_selection"

        response = self.planner.respond(
            selection_request,
            {"project_description": project_description},
            self.backend_config,
        )

        # Parse JSON from response (handle markdown code blocks)
        selected = self._parse_agent_selection(response)

        # Validate and clamp
        valid = [a for a in selected if a in self.all_agents]
        if not valid:
            print_status("Could not parse agent selection, using defaults.")
            valid = ["researcher", "architect", "backend_dev", "devops"]

        valid = valid[: self.max_agents]
        if len(valid) < self.min_agents:
            # Add missing defaults
            for fallback in ["researcher", "architect", "backend_dev"]:
                if fallback not in valid:
                    valid.append(fallback)
                if len(valid) >= self.min_agents:
                    break

        print_status(f"Selected agents: {', '.join(valid)}")
        return valid

    def _parse_agent_selection(self, response: str) -> list[str]:
        """Extract the selected_agents list from a potentially messy LLM response."""
        # Try to find JSON block
        json_match = re.search(r'\{[^{}]*"selected_agents"[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return data.get("selected_agents", [])
            except json.JSONDecodeError:
                pass

        # Fallback: look for a list of known agent names in the text
        known = ["researcher", "architect", "backend_dev", "frontend_dev", "devops", "security", "skeptic"]
        found = [a for a in known if a in response.lower()]
        return found

    def _run_round(
        self,
        selected_agent_keys: list[str],
        project_description: str,
        round_num: int,
        is_challenge_round: bool = False,
    ) -> dict[str, str]:
        """Run one debate round: each agent responds."""
        round_label = f"Round {round_num}" + (" — Challenge" if is_challenge_round else " — Proposals")
        print_header(round_label)

        proposals: dict[str, str] = {}
        request = (
            "Based on the project description, challenge or build upon the previous proposals."
            if is_challenge_round
            else "Analyze this project from your specialist perspective and provide your recommendations."
        )

        for key in selected_agent_keys:
            agent = self.all_agents[key]
            print_agent_header(agent.name, round_label)

            ctx = {
                "project_description": project_description,
                "round": round_label,
            }
            if is_challenge_round and self.context.get("round1_proposals"):
                ctx["previous_proposals"] = self.context["round1_proposals"]
                ctx["challenge_target"] = True

            print_status(f"Calling {agent.name} ({agent.backend}/{agent.model})...")
            try:
                response = agent.respond(request, ctx, self.backend_config, project_path=self.project_path)
            except RuntimeError as e:
                response = f"**Error:** {e}"
                print(color(f"  ✗ {e}", "red"))

            proposals[agent.name] = response
            if self.verbose:
                print_response(response)
            else:
                # Show just the first line as a summary
                first_line = response.split("\n")[0][:80]
                print_status(f"Response: {first_line}...")

        return proposals

    def _synthesize(
        self,
        project_description: str,
        round1: dict[str, str],
        round2: dict[str, str],
    ) -> str:
        """Ask the Planner to synthesize all proposals into a final recommendation."""
        print_header("Planner Synthesis")
        print_agent_header("Planner", "Synthesis")
        print_status("Synthesizing all proposals...")

        combined_proposals = {}
        combined_proposals.update({f"[R1] {k}": v for k, v in round1.items()})
        combined_proposals.update({f"[R2] {k}": v for k, v in round2.items()})

        synthesis_request = (
            f"Synthesize all agent proposals into a final project recommendation.\n\n"
            f"Project: {project_description}\n\n"
            f"Produce a comprehensive document with:\n"
            f"1. Executive Summary\n"
            f"2. Recommended Tech Stack (with clear reasoning for each choice)\n"
            f"3. Architecture Overview (with diagram if helpful)\n"
            f"4. Key Risks & Mitigations\n"
            f"5. Implementation Phases (Phase 1/2/3 with milestones)\n"
            f"6. Open Questions & Next Steps\n\n"
            f"Resolve any disagreements between agents. Where agents conflict, explain the tradeoff and make a recommendation."
        )

        try:
            synthesis = self.planner.respond(
                synthesis_request,
                {
                    "project_description": project_description,
                    "round": "synthesis",
                    "previous_proposals": combined_proposals,
                },
                self.backend_config,
                project_path=self.project_path, # Pass project_path here
            )
        except RuntimeError as e:
            synthesis = f"**Synthesis failed:** {e}"
            print(color(f"  ✗ {e}", "red"))

        if self.verbose:
            print_response(synthesis)

        return synthesis

    def run_planner_debate(self, project_description: str) -> dict:
        """
        Execute the full debate flow and return a result dict with:
          - selected_agents: list of agent keys used
          - round1: dict of agent proposals
          - round2: dict of challenge responses
          - synthesis: final Planner recommendation
        """
        print_header("Multi-Agent Project Advisor")
        print(color(f"Project: {project_description}\n", "bold"))

        # Step 1: Planner selects agents
        selected = self._select_agents(project_description)

        # Step 2: Round 1 — Initial proposals
        round1 = self._run_round(selected, project_description, round_num=1, is_challenge_round=False)
        self.context["round1_proposals"] = round1

        # Step 3: Round 2 — Challenge/support round
        round2 = self._run_round(selected, project_description, round_num=2, is_challenge_round=True)
        self.context["round2_proposals"] = round2

        # Step 4: Planner synthesizes
        synthesis = self._synthesize(project_description, round1, round2)

        return {
            "project_description": project_description,
            "selected_agents": selected,
            "round1": round1,
            "round2": round2,
            "synthesis": synthesis,
        }

    def run_agent(self, agent_name: str, task_name: str, project_description: str):
        """Run a specific agent for a specific task (e.g., Architect updates tasks.md)."""
        if agent_name not in self.all_agents:
            print(f"Error: Agent '{agent_name}' not found.", file=sys.stderr)
            sys.exit(1)

        import os
        spec_content = ""
        if self.project_path:
            spec_path = os.path.join(self.project_path, "spec.md")
            if os.path.exists(spec_path):
                with open(spec_path, "r") as f:
                    spec_content = f"\n\n## Current spec.md\n{f.read()}"

        agent = self.all_agents[agent_name]
        print_agent_header(agent.name, f"Task: {task_name}")
        print_status(f"Calling {agent.name} for task '{task_name}' ({agent.backend}/{agent.model})...")

        ctx = {
            "project_description": project_description + spec_content,
            "task_name": task_name,
            "project_path": self.project_path,
        }

        try:
            response = agent.respond(task_name, ctx, self.backend_config, project_path=self.project_path)
            print_response(response)
        except RuntimeError as e:
            print(color(f"  ✗ Error during agent {agent_name} task '{task_name}': {e}", "red"))
            sys.exit(1)

    def run(self, project_description: str) -> dict: # Placeholder to ensure proper method calls
        raise NotImplementedError("Use run_planner_debate or run_agent methods instead.")
