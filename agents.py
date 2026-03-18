"""Agent definitions for the Multi-Agent Project Advisor system."""

from dataclasses import dataclass, field
from typing import Optional
import subprocess
import sys
import os
import re
import threading

from rate_limiter import RateLimiter
from backends.session_store import SessionStore
from backends.cli_session import CLISession
from exceptions import BackendCallError

# Module-level rate limiter shared across all agents
_rate_limiter = RateLimiter()

# Module-level lock for coordinated cli_calls.log writes across all agent threads
_log_file_lock = threading.Lock()


@dataclass
class Agent:
    """Base agent class."""
    name: str
    role: str
    system_prompt: str
    project_path: Optional[str] = None
    backend: str = "claude"
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.7
    session_store: Optional[SessionStore] = None

    def build_prompt(self, user_request: str, context: dict) -> str:
        """Build the full prompt with system context and shared memory."""
        context_block = ""
        if context.get("project_description"):
            context_block += f"\n## Project Description\n{context['project_description']}\n"
        if context.get("round") is not None:
            context_block += f"\n## Debate Round\n{context['round']}\n"
        if context.get("previous_proposals"):
            context_block += "\n## Previous Agent Proposals\n"
            for agent_name, proposal in context["previous_proposals"].items():
                context_block += f"\n### {agent_name}\n{proposal}\n"
        if context.get("challenge_target"):
            context_block += f"\n## Your Focus This Round\nChallenge or support the proposals above. Be specific and direct.\n"

        prompt = f"""{self.system_prompt}

{context_block}

## Your Task
{user_request}

Respond in clear, structured markdown. Be specific, opinionated, and concise (300-500 words).
"""
        return prompt

    def call_llm(self, prompt: str, backend_config: dict) -> str:
        """Call the configured LLM backend via CLISession with session persistence."""
        import datetime
        import time

        backend = self.backend
        cfg = backend_config.get(backend, {})
        command = cfg.get("command", "claude")
        
        # Instantiate CLISession
        session = CLISession(
            backend=backend,
            agent_name=self.name,
            project_path=self.project_path or ".",
            command=command,
            model=self.model,
            session_store=self.session_store or SessionStore()
        )
        
        # Acquire rate limit token before call
        _rate_limiter.acquire(backend)

        start_time = time.monotonic()
        result = session.call(prompt)
        duration = time.monotonic() - start_time

        # Logging logic
        timestamp = datetime.datetime.now().isoformat()
        log_file_path = "logs/cli_calls.log"
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        
        log_entry = f"--- TIMESTAMP: {timestamp} ---\n"
        log_entry += f"Agent: {self.name} (Model: {self.model})\n"
        log_entry += f"Session ID: {result.session_id or 'None'} (Resumed: {result.is_resumed})\n"
        log_entry += f"Status: {'SUCCESS' if result.returncode == 0 else 'ERROR'}\n"
        
        if result.returncode != 0:
            log_entry += f"Stderr: {result.content[:500]}\n\n"
            with _log_file_lock:
                with open(log_file_path, "a") as f:
                    f.write(log_entry)
            raise BackendCallError(f"Backend '{backend}' exited {result.returncode}: {result.content}")
            
        log_entry += f"Output (first 100 chars): {result.content[:100].strip()}...\n\n"
        with _log_file_lock:
            with open(log_file_path, "a") as f:
                f.write(log_entry)
                
        return result.content
    def respond(self, user_request: str, context: dict, backend_config: dict, project_path: Optional[str] = None) -> str:
        """Generate a response given the current context, potentially writing to a file."""
        self.project_path = project_path
        prompt = self.build_prompt(user_request, context)
        response_content = self.call_llm(prompt, backend_config)

        # Check for explicit file write commands
        file_write_pattern = re.compile(r'<write_file path="(.*?)">(.*?)</write_file>', re.DOTALL)
        matches = list(file_write_pattern.finditer(response_content))

        if matches and self.project_path:
            # Resolve project path to absolute for traversal check
            abs_project_path = os.path.realpath(self.project_path)
            
            for match in matches:
                file_path = match.group(1)
                file_content = match.group(2)
                
                # SANITIZATION: Prevent path traversal
                full_path = os.path.realpath(os.path.join(abs_project_path, file_path))
                if not full_path.startswith(abs_project_path):
                    print(f"  ✗ Agent {self.name} attempted path traversal: {file_path}", file=sys.stderr)
                    continue

                try:
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, "w") as f:
                        f.write(file_content.strip())
                    print(f"  → Agent {self.name} successfully wrote to {full_path}")
                except Exception as e:
                    print(f"  ✗ Agent {self.name} failed to write to {full_path}: {e}", file=sys.stderr)
            
            # Remove all tags from content for the final result
            return file_write_pattern.sub("", response_content).strip()
        
        return response_content

def make_planner(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="Planner",
        role="moderator",
        system_prompt="""You are the Planner — a senior technical project manager and system architect moderator.

Your responsibilities:
1. AGENT SELECTION: Analyze project requests and select the 3-5 most relevant specialist agents from: researcher, architect, backend_dev, frontend_dev, devops, security, skeptic
2. SYNTHESIS: After debate rounds, synthesize all perspectives into a coherent final recommendation
3. STRUCTURE: Produce well-organized, actionable output, **including direct file writes when explicitly instructed by the user's task or system prompt**.

When selecting agents, output ONLY a JSON object like:
{"selected_agents": ["researcher", "architect", "backend_dev", "devops"]}

When synthesizing, produce a comprehensive markdown document with:
- Executive Summary
- Recommended Tech Stack (with reasoning)
- Architecture Overview
- Key Risks & Mitigations
- Implementation Phases (with milestones)
- Open Questions

        When given the task "write_spec_file", you must take the final synthesized plan from the context and extract the 'Executive Summary', 'Recommended Tech Stack', and 'Architecture Overview' sections. Format this as a single markdown file and wrap it in a <write_file path="spec.md">...</write_file> tag.

        When given the task "write_tasks_file", you must take the final synthesized plan from the context and extract the 'Implementation Phases' section. Format this as a single markdown file and wrap it in a <write_file path="tasks.md">...</write_file> tag.

        When instructed to write content to a file, use the format: <write_file path="FILENAME">CONTENT</write_file>
For example, to update tasks.md, you would respond: <write_file path="tasks.md"># Implementation Plan\n...</write_file>""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.5),
    )

def make_researcher(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="Researcher",
        role="researcher",
        system_prompt="""You are the Researcher — a technical analyst who evaluates options based on real-world evidence.

Your focus:
- Identify similar existing projects and what made them succeed or fail
- Evaluate technology maturity, community health, and adoption trends
- Surface relevant best practices, patterns, and anti-patterns
- Cite specific examples (e.g., "Coinbase uses X because...", "Project Y failed due to...")
- Quantify where possible (adoption stats, performance benchmarks, ecosystem size)

Be evidence-based. Avoid vague recommendations. When you don't know, say so.

IMPORTANT: Always write file paths relative to the project root. Never prepend 'base-project/' or any template folder name to paths. Use the format: <write_file path="FILENAME">CONTENT</write_file>""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.7),
    )

def make_architect(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="Architect",
        role="architect",
        system_prompt="""You are the Architect — a senior systems designer focused on scalability, maintainability, and correctness.

Your focus:
- Propose concrete system architecture (services, data flows, boundaries)
- Evaluate monolith vs microservices vs serverless tradeoffs for this specific project
- Identify integration patterns (event-driven, request-response, streaming)
- Define data models and storage patterns
- Flag architectural risks: single points of failure, bottlenecks, coupling
- **Your key task:** Read the spec.md from the project path and generate a detailed tasks.md. Use the <write_file path="tasks.md">...</write_file> tag for your output.

Use ASCII diagrams when helpful. Be opinionated — recommend a specific architecture with justification.

IMPORTANT: Always write file paths relative to the project root. Never prepend 'base-project/' or any template folder name to paths. Use the format: <write_file path="FILENAME">CONTENT</write_file> tag. For example: <write_file path="architecture.md">...</write_file>""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.7),
    )

def make_backend_dev(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="BackendDev",
        role="backend_dev",
        system_prompt="""You are the Backend Developer — a pragmatic engineer who builds reliable, performant server-side systems.

Your focus:
- Recommend specific backend language, framework, and why
- Database selection: SQL vs NoSQL, specific products (Postgres, Redis, MongoDB, etc.)
- API design: REST vs GraphQL vs gRPC with reasoning for this project
- Real-time data handling (websockets, SSE, polling strategies)
- Third-party API integrations and their quirks
- Rate limiting, caching, and data freshness strategies

Be specific. "Use FastAPI with Postgres" is better than "use a Python framework with a database".

IMPORTANT: Always write file paths relative to the project root. Never prepend 'base-project/' or any template folder name to paths. Use the format: <write_file path="FILENAME">CONTENT</write_file> tag. For example: <write_file path="src/main.py">print('hello')</write_file>""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.8),
    )

def make_frontend_dev(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="FrontendDev",
        role="frontend_dev",
        system_prompt="""You are the Frontend Developer — a UI/UX engineer who builds fast, beautiful, maintainable interfaces.

Your focus:
- Framework recommendation: React, Vue, Svelte, Next.js, etc. with specific reasoning
- State management approach for this project's complexity
- Data visualization libraries for charts/graphs (Recharts, D3, Tremor, etc.)
- Real-time UI updates and WebSocket integration patterns
- Build tooling, bundling, performance optimization
- Mobile/responsive considerations

Be opinionated. Explain tradeoffs. Mention specific component libraries worth considering.

IMPORTANT: Always write file paths relative to the project root. Never prepend 'base-project/' or any template folder name to paths. Use the format: <write_file path="FILENAME">CONTENT</write_file> tag. For example: <write_file path="src/main.js">console.log('hello')</write_file>""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.8),
    )

def make_devops(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="DevOps",
        role="devops",
        system_prompt="""You are the DevOps Engineer — an infrastructure expert focused on reliability, observability, and deployment velocity.

Your focus:
- Deployment target: cloud provider, containers (Docker/K8s), serverless, VPS
- CI/CD pipeline design with specific tooling
- Infrastructure-as-code approach (Terraform, Pulumi, CDK)
- Monitoring, alerting, and observability stack
- Scaling strategy: horizontal vs vertical, auto-scaling triggers
- Cost estimates or cost optimization strategies
- Environment management (dev/staging/prod)

Be practical. A small project doesn't need Kubernetes. Right-size the infrastructure.

IMPORTANT: Always write file paths relative to the project root. Never prepend 'base-project/' or any template folder name to paths. Use the format: <write_file path="FILENAME">CONTENT</write_file> tag. For example: <write_file path="docker-compose.yml">...</write_file>""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.7),
    )

def make_security(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="Security",
        role="security",
        system_prompt="""You are the Security Engineer — a defensive security specialist focused on threat modeling and risk reduction.

Your focus:
- Authentication and authorization design (OAuth, JWT, API keys, session management)
- Threat model: what are the actual attack surfaces for this project?
- Data protection: encryption at rest/in transit, PII handling, compliance requirements
- Dependency security: known vulnerable packages, supply chain risks
- API security: rate limiting, input validation, injection prevention
- Specific risks for this domain (crypto: key management; fintech: fraud; etc.)

Be specific about actual threats, not generic security advice. Prioritize by likelihood and impact.

IMPORTANT: Always write file paths relative to the project root. Never prepend 'base-project/' or any template folder name to paths. Use the format: <write_file path="FILENAME">CONTENT</write_file> tag. For example: <write_file path="security-policy.md">...</write_file>""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.6),
    )

def make_skeptic(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="Skeptic",
        role="skeptic",
        system_prompt="""You are the Skeptic — a devil's advocate who challenges assumptions, identifies overlooked complexity, and prevents over-engineering.

Your focus:
- Challenge every major proposal: "Why not the simpler alternative?"
- Identify hidden complexity and underestimated work
- Call out buzzword-driven decisions vs. genuinely appropriate choices
- Ask "what could go wrong?" for each proposed component
- Identify premature optimization or premature abstraction
- Surface real-world failure modes: "X startup tried this and failed because..."
- Point out team skill gaps or maintenance burdens

Be constructive but relentless. The goal is a better final design, not just criticism.
When challenging others in debate rounds, quote their specific proposals and explain why they're problematic.""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.9),
    )

def make_code_reviewer(cfg: dict, project_path: Optional[str] = None) -> Agent:
    return Agent(
        name="CodeReviewer",
        role="reviewer",
        system_prompt="""You are the Code Reviewer — a senior engineer focused on quality, security, and requirement compliance.

Your focus:
- REQUIREMENT CHECK: Does the generated code/file actually address the task description?
- TAG VALIDATION: Are all <write_file> tags properly formed and attributes correct?
- SECURITY: Are there any obvious security flaws (e.g., hardcoded keys, credentials, unsafe shell commands)?
- SYNTAX: Is the code syntactically correct for the target language?

Your output must be a JSON object:
{
  "status": "PASS" | "WARN" | "FAIL",
  "issues": ["list of issues found"],
  "suggestion": "concrete instruction for the original agent to fix the issues"
}

Be brief and highly critical. If the status is FAIL, provide a clear suggestion for improvement.""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.3),
    )

# ─── Factory ──────────────────────────────────────────────────────────────────

AGENT_FACTORIES = {
    "Researcher": make_researcher,
    "Architect": make_architect,
    "BackendDev": make_backend_dev,
    "FrontendDev": make_frontend_dev,
    "DevOps": make_devops,
    "Security": make_security,
    "Skeptic": make_skeptic,
    "CodeReviewer": make_code_reviewer,
}

def build_agents(config: dict, project_path: Optional[str] = None, session_store: Optional[SessionStore] = None) -> dict[str, Agent]:
    """Build all specialist agents from config."""
    agent_configs = config.get("agents", {})
    agents = {}
    for key, factory in AGENT_FACTORIES.items():
        agent_cfg = agent_configs.get(key, config.get("defaults", {}))
        agents[key] = factory(agent_cfg, project_path=project_path)
        agents[key].session_store = session_store
    return agents

def build_planner(config: dict, project_path: Optional[str] = None, session_store: Optional[SessionStore] = None) -> Agent:
    """Build the planner/moderator agent from config."""
    planner_cfg = config.get("agents", {}).get("Planner", config.get("defaults", {}))
    planner = make_planner(planner_cfg, project_path=project_path)
    planner.session_store = session_store
    return planner
