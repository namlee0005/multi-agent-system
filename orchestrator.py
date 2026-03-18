"""Orchestrator: manages the debate flow between agents."""

import datetime
import json
import os
import re
import sys
import threading
import time
import uuid, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from agents import Agent, build_agents, build_planner
from backends.session_store import SessionStore
from context_store import ContextStore
from validator import validate_response
from exceptions import (
    BinaryNotFoundError,
    PipelineError,
    ValidationError,
    ReviewError,
    MASError,
)

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


# ─── Snapshot key sets per pipeline stage ─────────────────────────────────────

_SNAPSHOT_KEYS_ROUND1 = ["project_description"]
_SNAPSHOT_KEYS_ROUND2 = ["round1_compressed", "project_description", "errors"]
_SNAPSHOT_KEYS_SYNTHESIS = ["proposals", "challenges", "round1_compressed", "errors"]


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class Orchestrator:
    """Manages the multi-agent debate and produces a final recommendation."""

    MAX_RETRY_ATTEMPTS = 3

    _SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")

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
        # Validate CLI binaries at init — fail fast with typed error
        for backend, cfg in self.backend_config.items():
            cmd = cfg.get("command", "claude")
            if not shutil.which(cmd) and not os.path.isfile(cmd):
                raise BinaryNotFoundError(f"Backend binary not found: {cmd!r}")

        self.debate_config = config.get("debate", {})
        self.max_rounds = self.debate_config.get("max_rounds", 2)
        self.min_agents = self.debate_config.get("min_agents", 3)
        self.max_agents = self.debate_config.get("max_agents", 5)

        self.spec_content = ""
        if self.project_path:
            spec_path = os.path.join(self.project_path, "spec.md")
            with open(spec_path, "r") as f:
                self.spec_content = f"\n\n## Current spec.md\n{f.read()}"

        self.session_store = SessionStore()
        self.session_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.planner = build_planner(config, project_path=project_path, session_store=self.session_store)
        self.all_agents = build_agents(config, project_path=project_path, session_store=self.session_store)
        self.all_agents['planner'] = self.planner

        self.agent_skills: dict[str, str] = self._load_skills()
        self.context = ContextStore()
        self._log_lock = threading.Lock()

        self.session_log: dict = {
            "session_id": self.session_id,
            "start_time": datetime.datetime.utcnow().isoformat() + "Z",
            "entries": [],
        }

        # Phase 8.2: Warn operator if the previous session log was interrupted
        self._check_last_session_integrity()

    # ─── Session integrity check ───────────────────────────────────────────────

    def _check_last_session_integrity(self) -> None:
        """
        Scan logs/ for the most recent session-*.json and warn if it lacks
        an 'end_time', which indicates the previous session was interrupted
        (crash, SIGKILL, unhandled exception before _write_session_log ran).
        """
        import glob
        log_pattern = os.path.join("logs", "session-*.json")
        matches = sorted(glob.glob(log_pattern))  # lexicographic = chronological (timestamp prefix)
        if not matches:
            return
        last_log_path = matches[-1]
        try:
            with open(last_log_path, "r") as f:
                last_log = json.load(f)
        except (OSError, json.JSONDecodeError):
            return  # Unreadable log — not our problem to surface here

        if "end_time" not in last_log:
            sid = last_log.get("session_id", last_log_path)
            print(
                color(
                    f"⚠ WARNING: Previous session '{sid}' has no end_time — "
                    f"it may have been interrupted. Check {last_log_path} for details.",
                    "yellow",
                )
            )

    # ─── Skills loading ───────────────────────────────────────────────────────

    def _load_skills(self) -> dict[str, str]:
        skills: dict[str, str] = {}
        for agent in self.all_agents.values():
            skill_path = os.path.join(self._SKILLS_DIR, agent.name, "SKILL.md")
            if os.path.isfile(skill_path):
                with open(skill_path, "r") as f:
                    skills[agent.name] = f.read()
            else:
                skills[agent.name] = ""
        return skills

    def _build_system_prompt(self, agent_name: str, base_prompt: str) -> str:
        skill_content = self.agent_skills.get(agent_name, "")
        if not skill_content.strip():
            return base_prompt
        return f"{base_prompt}\n\n## Your Specialized Skills\n{skill_content}"

    # ─── Logging helpers ──────────────────────────────────────────────────────

    def _append_session_entry(self, entry: dict):
        with self._log_lock:
            self.session_log["entries"].append(entry)

    def _write_session_log(self):
        os.makedirs("logs", exist_ok=True)
        path = f"logs/session-{self.session_id}.json"
        self.session_log["end_time"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(path, "w") as f:
            json.dump(self.session_log, f, indent=2)
        print_status(f"Session log written → {path}")

    def _log_cli_call(
        self,
        agent_name: str,
        model: str,
        status: str,
        duration_s: float,
        detail: str = "",
        is_resumed: bool = False,
        skills_injected: bool = False,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ):
        os.makedirs("logs", exist_ok=True)
        record = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "agent": agent_name,
            "model": model,
            "status": status,
            "duration_s": round(duration_s, 3),
            "is_resumed": is_resumed,
            "skills_injected": skills_injected,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "detail": detail,
        }
        with open("logs/cli_calls.log", "a") as f:
            f.write(json.dumps(record) + "\n")

    # ─── Pre-write artifact gate ───────────────────────────────────────────────

    def _review_artifact(self, artifact_response: str, original_request: str) -> tuple[bool, str]:
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
        except MASError as e:
            review_response = ""
            review_status = "error"
            review_detail = str(e)
            with self._log_lock:
                print(color(f"  ✗ Code reviewer error: {e}", "red"))

        duration = time.monotonic() - start

        review_data: dict = {}
        if review_response:
            json_match = re.search(r'\{.*\}', review_response, re.DOTALL)
            if json_match:
                try:
                    review_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

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

    def _call_agent(
        self,
        key: str,
        request: str,
        ctx: dict,
        snapshot_keys: Optional[list[str]] = None,
    ) -> tuple[str, str, str, bool]:
        """
        Call a single agent with retry-with-feedback (up to MAX_RETRY_ATTEMPTS).

        Returns (agent_key, agent_name, response, success).
        success=False when status is 'error' or 'validation_failed'.
        """
        agent = self.all_agents[key]

        # Phase 8.3: Determine skills state before prompt mutation for real-time reporting
        skills_injected = bool(self.agent_skills.get(agent.name, "").strip())

        with self._log_lock:
            skills_label = color("Skills injected: True", "green") if skills_injected else color("Skills injected: False", "gray")
            print_status(f"Calling {agent.name} ({agent.backend}/{agent.model}) | {skills_label}")

        original_system_prompt = agent.system_prompt
        if skills_injected:
            agent.system_prompt = self._build_system_prompt(agent.name, original_system_prompt)
            os.makedirs("logs/prompts", exist_ok=True)
            prompt_log_path = (
                f"logs/prompts/{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{agent.name}.txt"
            )
            with open(prompt_log_path, "w") as f:
                f.write(agent.system_prompt)

        ctx["context_store"] = self.context.snapshot(keys=snapshot_keys)

        start = time.monotonic()
        status = "success"
        response = ""
        error_detail = ""
        retry_count = 0
        current_request = request

        try:
            for attempt in range(1, self.MAX_RETRY_ATTEMPTS + 1):
                try:
                    response = agent.respond(current_request, ctx, self.backend_config, project_path=self.project_path)
                except MASError as e:
                    status = "error"
                    error_detail = str(e)
                    response = f"**Error:** {e}"
                    with self._log_lock:
                        print(color(f"  ✗ {e}", "red"))
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

                break

        finally:
            agent.system_prompt = original_system_prompt

        duration = time.monotonic() - start

        last_result = getattr(agent, "last_call_result", None)
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
            "skills_injected": skills_injected,
            "is_resumed": last_result.is_resumed if last_result else False,
            "input_tokens": last_result.input_tokens if last_result else None,
            "output_tokens": last_result.output_tokens if last_result else None,
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
            is_resumed=last_result.is_resumed if last_result else False,
            skills_injected=skills_injected,
            input_tokens=last_result.input_tokens if last_result else None,
            output_tokens=last_result.output_tokens if last_result else None,
        )

        success = status == "success"
        return key, agent.name, response, success

    # ─── Compression gate ─────────────────────────────────────────────────────

    def _compress_proposals(self, proposals: dict[str, str]) -> str:
        TRUNCATION_LIMIT = 500
        summaries: dict[str, str] = {}
        stats = {"extracted": 0, "resummarized": 0, "truncated": 0}

        for agent_name, response in proposals.items():
            match = re.search(
                r"##\s+Summary\s*\n(.*?)(?=\n##\s|\Z)",
                response,
                re.DOTALL | re.IGNORECASE,
            )
            if match:
                summaries[agent_name] = match.group(1).strip()
                stats["extracted"] += 1
                continue

            try:
                resummary = self.planner.respond(
                    (
                        f"Summarize the following agent proposal in 3–5 concise bullet points. "
                        f"Preserve all concrete recommendations and note any conflicts.\n\n"
                        f"{response[:3000]}"
                    ),
                    {"round": "compression", "agent": agent_name},
                    self.backend_config,
                )
                summaries[agent_name] = resummary.strip()
                stats["resummarized"] += 1
            except MASError:
                summaries[agent_name] = response[:TRUNCATION_LIMIT]
                stats["truncated"] += 1

        compressed = "\n\n".join(
            f"### {agent_name}\n{summary}" for agent_name, summary in summaries.items()
        )
        self.context.set("round1_compressed", compressed)

        with self._log_lock:
            print_status(
                f"Compression gate: {stats['extracted']} self-extracted, "
                f"{stats['resummarized']} re-summarized, {stats['truncated']} truncated"
            )

        self._append_session_entry({
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "event": "compression_gate",
            "agents_compressed": len(proposals),
            "extracted": stats["extracted"],
            "resummarized": stats["resummarized"],
            "truncated": stats["truncated"],
        })

        return compressed

    # ─── Agent selection ──────────────────────────────────────────────────────

    def _select_agents(self, project_description: str) -> list[str]:
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

        selected = self._parse_agent_selection(response)

        valid = [a for a in selected if a in self.all_agents]
        if not valid:
            print_status("Could not parse agent selection, using defaults.")
            valid = ["researcher", "architect", "backend_dev", "devops"]

        valid = valid[: self.max_agents]
        if len(valid) < self.min_agents:
            for fallback in ["researcher", "architect", "backend_dev"]:
                if fallback not in valid:
                    valid.append(fallback)
                if len(valid) >= self.min_agents:
                    break

        print_status(f"Selected agents: {', '.join(valid)}")
        return valid

    def _parse_agent_selection(self, response: str) -> list[str]:
        json_match = re.search(r'\{[^{}]*"selected_agents"[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return data.get("selected_agents", [])
            except json.JSONDecodeError:
                pass

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
        Run one debate round in parallel. Raises PipelineError if >50% of agents fail.
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

        snapshot_keys = _SNAPSHOT_KEYS_ROUND2 if is_challenge_round else _SNAPSHOT_KEYS_ROUND1

        def call_agent_task(key: str) -> tuple[str, str, str, bool]:
            ctx = {
                "project_description": project_description,
                "round": round_label,
            }
            if is_challenge_round and self.context.get("round1_proposals"):
                ctx["previous_proposals"] = self.context["round1_proposals"]
                ctx["challenge_target"] = True
            return self._call_agent(key, request, ctx, snapshot_keys=snapshot_keys)

        with ThreadPoolExecutor(max_workers=len(selected_agent_keys)) as executor:
            future_to_key = {executor.submit(call_agent_task, key): key for key in selected_agent_keys}

            results: dict[str, tuple[str, str, bool]] = {}
            for future in as_completed(future_to_key):
                key, agent_name, response, success = future.result()
                results[key] = (agent_name, response, success)

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

        total = len(selected_agent_keys)
        if len(failed_agents) > total / 2:
            raise PipelineError(
                f"{round_label}: {len(failed_agents)}/{total} agents failed (>{50}% threshold). "
                f"Aborting pipeline. Failed: {', '.join(failed_agents)}"
            )

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
        print_header("Planner Synthesis")
        print_agent_header("Planner", "Synthesis")
        print_status("Synthesizing all proposals...")

        combined_proposals = {}
        combined_proposals.update({f"[R1] {k}": v for k, v in round1.items()})
        combined_proposals.update({f"[R2] {k}": v for k, v in round2.items()})

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
                    "context_store": self.context.snapshot(keys=_SNAPSHOT_KEYS_SYNTHESIS),
                },
                self.backend_config,
                project_path=self.project_path,
            )
        except MASError as e:
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
        print_header("Multi-Agent Project Advisor")
        print(color(f"Project: {project_description}\n", "bold"))

        spec_content = self.spec_content
        enriched_description = project_description + spec_content

        selected = self._select_agents(enriched_description)

        round1 = self._run_round(selected, enriched_description, round_num=1, is_challenge_round=False)
        self.context.set("round1_proposals", round1)

        self._compress_proposals(round1)

        round2 = self._run_round(selected, enriched_description, round_num=2, is_challenge_round=True)
        self.context.set("round2_proposals", round2)

        synthesis = self._synthesize(enriched_description, round1, round2)

        result = {
            "project_description": project_description,
            "selected_agents": selected,
            "round1": round1,
            "round2": round2,
            "synthesis": synthesis,
        }

        self._write_session_log()
        self.session_store.invalidate(self.project_path)
        return result

    def run_agent(self, agent_name: str, task_name: str, project_description: str):
        if agent_name not in self.all_agents:
            print(f"Error: Agent '{agent_name}' not found.", file=sys.stderr)
            sys.exit(1)

        spec_content = self.spec_content

        agent = self.all_agents[agent_name]
        print_agent_header(agent.name, f"Task: {task_name}")
        print_status(f"Calling {agent.name} for task '{task_name}' ({agent.backend}/{agent.model})...")

        ctx = {
            "project_description": project_description + spec_content,
            "task_name": task_name,
            "project_path": self.project_path,
            "round": f"task:{task_name}",
        }

        _, _, response, _ = self._call_agent(agent_name, task_name, ctx, snapshot_keys=None)
        if response.startswith("**Error:**"):
            print(color(f"  ✗ Error during agent {agent_name} task '{task_name}'", "red"))
            self._write_session_log()
            sys.exit(1)

        print_response(response)
        self._write_session_log()

    def run(self, project_description: str) -> dict:
        raise NotImplementedError("Use run_planner_debate or run_agent methods instead.")