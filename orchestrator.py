"""Orchestrator: manages the debate flow between agents."""

import datetime
import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from agents import Agent, build_agents, build_planner
from context_store import ContextStore
from validator import validate_response

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
    "Planner":      "cyan",
    "Researcher":   "blue",
    "Architect":    "magenta",
    "BackendDev":   "yellow",
    "FrontendDev":  "green",
    "DevOps":       "cyan",
    "Security":     "red",
    "Skeptic":      "gray",
    "CodeReviewer": "magenta",
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

    MAX_RETRY_ATTEMPTS = 3

    def __init__(
        self,
        config: dict,
        verbose: bool = True,
        project_path: Optional[str] = None,
        skip_review: bool = False,
    ):
        self.config = config
        self.verbose = verbose
        self.project_path = project_path
        self.skip_review = skip_review
        self.backend_config = config.get("backends", {})
        self.debate_config = config.get("debate", {})
        self.max_rounds = self.debate_config.get("max_rounds", 2)
        self.min_agents = self.debate_config.get("min_agents", 3)
        self.max_agents = self.debate_config.get("max_agents", 5)

        self.planner = build_planner(config, project_path=project_path)
        self.all_agents = build_agents(config, project_path=project_path)
        self.all_agents['planner'] = self.planner

        # Shared context/memory store — thread-safe, grows as the debate progresses
        self.context = ContextStore()

        # Lock for thread-safe log/console writes
        self._log_lock = threading.Lock()

        # Session tracking
        self.session_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.session_log: dict = {
            "session_id": self.session_id,
            "start_time": datetime.datetime.utcnow().isoformat() + "Z",
            "entries": [],
        }

    # ─── Logging helpers ──────────────────────────────────────────────────────

    def _append_session_entry(self, entry: dict):
        """Thread-safe append to the in-memory session log entries."""
        with self._log_lock:
            self.session_log["entries"].append(entry)

    def _write_session_log(self):
        """Flush the full session log to logs/session-{id}.json."""
        os.makedirs("logs", exist_ok=True)
        path = f"logs/session-{self.session_id}.json"
        self.session_log["end_time"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(path, "w") as f:
            json.dump(self.session_log, f, indent=2)
        print_status(f"Session log written → {path}")

    def _log_cli_call(self, agent_name: str, model: str, status: str, duration_s: float, detail: str = ""):
        """Append a structured JSON line to logs/cli_calls.log."""
        os.makedirs("logs", exist_ok=True)
        record = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "agent": agent_name,
            "model": model,
            "status": status,
            "duration_s": round(duration_s, 3),
            "detail": detail,
        }
        with open("logs/cli_calls.log", "a") as f:
            f.write(json.dumps(record) + "\n")

    # ─── Pre-write artifact gate ───────────────────────────────────────────────

    def _review_artifact(self, artifact_response: str, original_request: str) -> tuple[bool, str]:
        """
        Invoke the code_reviewer agent to review a response containing <write_file> tags.

        Returns (passed, feedback) where:
          - passed=True  → reviewer returned PASS or WARN
          - passed=False → reviewer returned FAIL, or reviewer errored
        """
        if "code_reviewer" not in self.all_agents:
            with self._log_lock:
                print_status(color("⚠ code_reviewer agent not found — skipping artifact gate", "yellow"))
            return True, ""

        reviewer = self.all_agents["code_reviewer"]

        review_request = (
            "You are reviewing a proposed file artifact before it is written to disk.\n\n"
            "## Original task\n"
            f"{original_request}\n\n"
            "## Proposed artifact\n"
            f"{artifact_response}\n\n"
            "Evaluate the artifact for correctness, security issues, and whether it fulfills the task.\n"
            "Respond with a JSON object exactly as specified in your system prompt:\n"
            '{"status": "PASS" | "WARN" | "FAIL", "issues": [...], "suggestion": "..."}'
        )

        with self._log_lock:
            print_status(f"Code review gate: invoking {reviewer.name} ({reviewer.backend}/{reviewer.model})...")

        start = time.monotonic()
        review_status = "success"
        review_detail = ""

        try:
            review_response = reviewer.respond(
                review_request,
                {"round": "code_review"},
                self.backend_config,
                project_path=self.project_path,
            )
        except RuntimeError as e:
            review_response = ""
            review_status = "error"
            review_detail = str(e)
            with self._log_lock:
                print(color(f"  ✗ Code reviewer error: {e}", "red"))

        duration = time.monotonic() - start

        # Parse JSON verdict from reviewer response
        review_data: dict = {}
        if review_response:
            json_match = re.search(r'\{.*\}', review_response, re.DOTALL)
            if json_match:
                try:
                    review_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        # Reviewer errors are treated as FAIL — never silently allow bad artifacts through
        if review_status == "error":
            passed = False
            feedback = f"Reviewer error: {review_detail}"
        else:
            verdict = review_data.get("status", "").upper()
            passed = verdict in ("PASS", "WARN")
            if not passed:
                issues = review_data.get("issues", [])
                suggestion = review_data.get("suggestion", "")
                feedback_parts = issues + ([suggestion] if suggestion else [])
                feedback = "; ".join(feedback_parts) if feedback_parts else review_response[:200]
            else:
                feedback = ""

        # Determine log status label
        if review_status == "error":
            gate_status = "review_error"
        elif passed:
            gate_status = "review_pass"
        else:
            gate_status = "review_fail"

        with self._log_lock:
            if review_status == "error":
                print_status(color(f"  ✗ Code review errored — artifact BLOCKED", "red"))
            elif passed:
                print_status(color(f"  ✓ Code review PASSED", "green"))
            else:
                print_status(color(f"  ✗ Code review FAILED: {feedback}", "red"))

        # Record passed artifacts in the context store
        if passed:
            self.context.append("artifacts", {
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "content": artifact_response,
                "original_request": original_request[:200],
            })

        self._append_session_entry({
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "agent": reviewer.name,
            "agent_key": "code_reviewer",
            "backend": reviewer.backend,
            "model": reviewer.model,
            "round": "code_review",
            "status": gate_status,
            "duration_s": round(duration, 3),
            **({"error": review_detail} if review_detail else {}),
            **({"review_feedback": feedback} if feedback else {}),
        })
        self._log_cli_call(
            agent_name=reviewer.name,
            model=reviewer.model,
            status=gate_status,
            duration_s=duration,
            detail=review_detail or str(review_data)[:120],
        )

        return passed, feedback

    # ─── Core agent call ──────────────────────────────────────────────────────

    def _call_agent(self, key: str, request: str, ctx: dict) -> tuple[str, str, str, bool]:
        """
        Call a single agent with retry-with-feedback (up to MAX_RETRY_ATTEMPTS).
        On validation failure, errors are appended to the prompt for the next attempt.
        If the validated response contains <write_file> tags and skip_review is False,
        the code_reviewer agent gates the artifact; on FAIL the feedback is fed back
        to the original agent for another attempt (counted against MAX_RETRY_ATTEMPTS).
        Records timing, appends a session entry, and logs the CLI call.
        Returns (agent_key, agent_name, response, success).
        success=False when status is 'error' or 'validation_failed'.
        """
        agent = self.all_agents[key]

        with self._log_lock:
            print_status(f"Calling {agent.name} ({agent.backend}/{agent.model})...")

        # Enrich context with a snapshot of prior outputs so agents can reference them
        ctx["context_store"] = self.context.snapshot()

        start = time.monotonic()
        status = "success"
        response = ""
        error_detail = ""
        retry_count = 0
        current_request = request

        for attempt in range(1, self.MAX_RETRY_ATTEMPTS + 1):
            try:
                response = agent.respond(current_request, ctx, self.backend_config, project_path=self.project_path)
            except RuntimeError as e:
                status = "error"
                error_detail = str(e)
                response = f"**Error:** {e}"
                with self._log_lock:
                    print(color(f"  ✗ {e}", "red"))
                # Record error in the context store
                self.context.append("errors", {
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "agent": agent.name,
                    "agent_key": key,
                    "round": ctx.get("round", ""),
                    "error": error_detail,
                })
                break

            validation = validate_response(agent.name, current_request, response)
            if not validation["valid"]:
                # Validation failed — log and prepare retry prompt
                retry_count = attempt
                validation_errors = validation.get("errors", [])
                suggestions = validation.get("suggestions", "")

                with self._log_lock:
                    print_status(
                        color(
                            f"  ⚠ {agent.name} validation failed (attempt {attempt}/{self.MAX_RETRY_ATTEMPTS}): "
                            + "; ".join(validation_errors),
                            "gray",
                        )
                    )

                if attempt < self.MAX_RETRY_ATTEMPTS:
                    feedback_block = (
                        "\n\n---\n"
                        "**Your previous response did not pass validation. Please correct the following issues:**\n"
                        + "\n".join(f"- {err}" for err in validation_errors)
                    )
                    if suggestions:
                        feedback_block += f"\n\n**Suggestions:** {suggestions}"
                    current_request = request + feedback_block
                else:
                    status = "validation_failed"
                    error_detail = "; ".join(validation_errors)
                    self.context.append("errors", {
                        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                        "agent": agent.name,
                        "agent_key": key,
                        "round": ctx.get("round", ""),
                        "error": f"validation_failed: {error_detail}",
                    })
                continue

            # Validation passed — check for <write_file> artifacts
            if not self.skip_review and re.search(r"<write_file\b", response, re.IGNORECASE):
                review_passed, review_feedback = self._review_artifact(response, current_request)
                if not review_passed:
                    retry_count = attempt
                    if attempt < self.MAX_RETRY_ATTEMPTS:
                        feedback_block = (
                            "\n\n---\n"
                            "**Your previous response was rejected by the code reviewer. "
                            "Please revise the artifact to address the following issues:**\n"
                            f"- {review_feedback}"
                        )
                        current_request = request + feedback_block
                        continue
                    else:
                        # Exhausted retries on review failure
                        status = "review_failed"
                        error_detail = review_feedback
                        self.context.append("errors", {
                            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                            "agent": agent.name,
                            "agent_key": key,
                            "round": ctx.get("round", ""),
                            "error": f"review_failed: {error_detail}",
                        })
                        break

            # Passed both validation and (if applicable) code review
            break

        duration = time.monotonic() - start

        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "agent": agent.name,
            "agent_key": key,
            "backend": agent.backend,
            "model": agent.model,
            "round": ctx.get("round", ""),
            "status": status,
            "duration_s": round(duration, 3),
            "retry_count": retry_count,
        }
        if error_detail:
            entry["error"] = error_detail

        self._append_session_entry(entry)
        self._log_cli_call(
            agent_name=agent.name,
            model=agent.model,
            status=status,
            duration_s=duration,
            detail=error_detail or response[:120].replace("\n", " "),
        )

        success = status == "success"
        return key, agent.name, response, success

    # ─── Agent selection ──────────────────────────────────────────────────────

    def _select_agents(self, project_description: str) -> list[str]:
        """Ask the Planner to select relevant agents for this project."""
        print_status("Planner is selecting relevant agents...")

        selection_request = (
            f"Analyze this project and select the 3-5 most relevant specialist agents.\n\n"
            f"Project: {project_description}\n\n"
            f"Available agents: researcher, architect, backend_dev, frontend_dev, devops, security, skeptic\n\n"
            f"Output ONLY a JSON object: {{\"selected_agents\": [\"agent1\", \"agent2\", ...]}}"
        )

        self.context.set("project_description", project_description)
        self.context.set("round", "agent_selection")

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

    # ─── Debate rounds ────────────────────────────────────────────────────────

    def _run_round(
        self,
        selected_agent_keys: list[str],
        project_description: str,
        round_num: int,
        is_challenge_round: bool = False,
    ) -> dict[str, str]:
        """
        Run one debate round: each agent responds in parallel via ThreadPoolExecutor.
        Failed agents (error or exhausted validation retries) are filtered from the
        returned proposals. Raises RuntimeError if more than 50% of agents fail.
        """
        round_label = f"Round {round_num}" + (" — Challenge" if is_challenge_round else " — Proposals")
        print_header(round_label)

        proposals: dict[str, str] = {}
        failed_agents: list[str] = []

        request = (
            "Based on the project description, challenge or build upon the previous proposals."
            if is_challenge_round
            else "Analyze this project from your specialist perspective and provide your recommendations."
        )

        def call_agent_task(key: str) -> tuple[str, str, str, bool]:
            ctx = {
                "project_description": project_description,
                "round": round_label,
            }
            if is_challenge_round and self.context.get("round1_proposals"):
                ctx["previous_proposals"] = self.context["round1_proposals"]
                ctx["challenge_target"] = True
            return self._call_agent(key, request, ctx)

        # Fan out all agent calls in parallel
        with ThreadPoolExecutor(max_workers=len(selected_agent_keys)) as executor:
            future_to_key = {executor.submit(call_agent_task, key): key for key in selected_agent_keys}

            results: dict[str, tuple[str, str, bool]] = {}
            for future in as_completed(future_to_key):
                key, agent_name, response, success = future.result()
                results[key] = (agent_name, response, success)

        # Print results in original agent order for deterministic output
        # and separate successes from failures
        for key in selected_agent_keys:
            agent_name, response, success = results[key]
            with self._log_lock:
                print_agent_header(agent_name, round_label)
                if self.verbose:
                    print_response(response)
                else:
                    first_line = response.split("\n")[0][:80]
                    print_status(f"Response: {first_line}...")

            if success:
                proposals[agent_name] = response
                # Store in the appropriate typed bucket
                bucket = "challenges" if is_challenge_round else "proposals"
                self.context.append(bucket, {
                    "round": round_num,
                    "agent": agent_name,
                    "agent_key": key,
                    "response": response,
                })
            else:
                failed_agents.append(agent_name)
                with self._log_lock:
                    print_status(color(f"⚠ {agent_name} excluded from proposals (failed after all retries)", "red"))

        # Abort if majority of agents failed
        total = len(selected_agent_keys)
        if len(failed_agents) > total / 2:
            raise RuntimeError(
                f"{round_label}: {len(failed_agents)}/{total} agents failed (>{50}% threshold). "
                f"Aborting pipeline. Failed: {', '.join(failed_agents)}"
            )

        # Persist failed agents in context so _synthesize can reference them
        context_key = f"round{round_num}_failed_agents"
        self.context.set(context_key, failed_agents)
        if failed_agents:
            print_status(color(f"Round {round_num} failures: {', '.join(failed_agents)}", "yellow"))

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

        # Build a failure notice for the prompt if any agents failed
        failure_notice = ""
        all_failed: list[str] = []
        for round_key in ("round1_failed_agents", "round2_failed_agents"):
            all_failed.extend(self.context.get(round_key, []))

        if all_failed:
            unique_failed = sorted(set(all_failed))
            failure_notice = (
                f"\n\n**Note:** The following agents failed to produce valid responses and are "
                f"excluded from the proposals above: {', '.join(unique_failed)}. "
                f"Acknowledge this gap in your synthesis and note any perspectives that may be missing."
            )

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
            f"{failure_notice}"
        )

        start = time.monotonic()
        status = "success"
        error_detail = ""

        try:
            synthesis = self.planner.respond(
                synthesis_request,
                {
                    "project_description": project_description,
                    "round": "synthesis",
                    "previous_proposals": combined_proposals,
                    "context_store": self.context.snapshot(),
                },
                self.backend_config,
                project_path=self.project_path,
            )
        except RuntimeError as e:
            synthesis = f"**Synthesis failed:** {e}"
            status = "error"
            error_detail = str(e)
            print(color(f"  ✗ {e}", "red"))

        duration = time.monotonic() - start
        self._append_session_entry({
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "agent": self.planner.name,
            "agent_key": "planner",
            "backend": self.planner.backend,
            "model": self.planner.model,
            "round": "synthesis",
            "status": status,
            "duration_s": round(duration, 3),
            **({"error": error_detail} if error_detail else {}),
        })
        self._log_cli_call(
            agent_name=self.planner.name,
            model=self.planner.model,
            status=status,
            duration_s=duration,
            detail=error_detail or synthesis[:120].replace("\n", " "),
        )

        if self.verbose:
            print_response(synthesis)

        return synthesis

    # ─── Public entry points ──────────────────────────────────────────────────

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
        self.context.set("round1_proposals", round1)

        # Step 3: Round 2 — Challenge/support round
        round2 = self._run_round(selected, project_description, round_num=2, is_challenge_round=True)
        self.context.set("round2_proposals", round2)

        # Step 4: Planner synthesizes
        synthesis = self._synthesize(project_description, round1, round2)

        result = {
            "project_description": project_description,
            "selected_agents": selected,
            "round1": round1,
            "round2": round2,
            "synthesis": synthesis,
        }

        self._write_session_log()
        return result

    def run_agent(self, agent_name: str, task_name: str, project_description: str):
        """Run a specific agent for a specific task (e.g., Architect updates tasks.md)."""
        if agent_name not in self.all_agents:
            print(f"Error: Agent '{agent_name}' not found.", file=sys.stderr)
            sys.exit(1)

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
            "round": f"task:{task_name}",
        }

        _, _, response, _ = self._call_agent(agent_name, task_name, ctx)
        if response.startswith("**Error:**"):
            print(color(f"  ✗ Error during agent {agent_name} task '{task_name}'", "red"))
            self._write_session_log()
            sys.exit(1)

        print_response(response)
        self._write_session_log()

    def run(self, project_description: str) -> dict:  # Placeholder to ensure proper method calls
        raise NotImplementedError("Use run_planner_debate or run_agent methods instead.")
