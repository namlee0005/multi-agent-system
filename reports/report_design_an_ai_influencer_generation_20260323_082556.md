# Multi-Agent Project Advisor Report

**Project:** Design an AI Influencer generation system using ComfyUI

## Selected Specialist Agents
1. **Architect**
2. **Backenddev**
3. **Skeptic**

## Debate Round 1: Initial Proposals
### Architect
Now I have full context. The existing `tasks.md` covers MAS infrastructure tasks through Phase 8. Per the **ADDITIVE DOCUMENTATION RULE**, I'll append the AI Influencer Factory tasks as Phase 9+.

---

## Architect Analysis: AI Influencer Factory

### System Boundary Map

```
┌─────────────────────────────────────────────────────────┐
│  Orchestrator / User                                     │
└──────────────────────────┬──────────────────────────────┘
                           │ WorkflowRequest (Pydantic)
                           ▼
┌──────────────────────────────────────────────────────────┐
│  VisualArtist Agent  (Claude claude-opus-4-6)            │
│  • Translate natural language → ComfyUI node graph       │
│  • Select LoRA weights, samplers, CFG per scenario       │
│  • Inject CharacterProfile trigger words + embeddings    │
└──────────────────────────┬───────────────────────────────┘
                           │ ComfyUI JSON Workflow
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Workflow Builder  (templates + dynamic node patching)   │
│  • Scenario templates: travel / food / fashion / gym     │
│  • AnimateDiff / SVD extension for video                 │
└──────────────────────────┬──────────────────────────────┘
                           │ POST /prompt  (async queue)
                           ▼
┌─────────────────────────────────────────────────────────┐
│  ComfyUI Server  (local GPU, REST + WebSocket)           │
└──────────────────────────┬──────────────────────────────┘
                           │ raw PNG / MP4
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Media Post-Processor  (PIL / FFmpeg)                    │
│  • Watermark, resize, format per platform spec           │
│  • Face consistency validation via embedding distance    │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Character Registry (JSON/SQLite)  │  Content Store      │
└─────────────────────────────────────────────────────────┘
```

### Architecture Decision: Modular Monolith

**Option A — Microservices:** gain: isolated scaling per service. cost: network overhead, service mesh complexity. Favors: teams > 3 engineers, 100+ concurrent generation jobs.

**Option B — Modular Monolith (recommended):** gain: single deployment, shared GPU context, no serialization overhead. cost: vertical scaling only. Favors: solo/small team, single GPU node, rapid iteration. Fits this project exactly.

### Single Points of Failure + Mitigations

| SPOF | Mitigation |
|---|---|
| ComfyUI server (GPU node) | Docker health check + auto-restart; job queue with retry |
| Character LoRA file | Versioned file store + integrity hash in registry |
| Face consistency | Embedding distance check post-generation; reject + retry |
| Claude API | Prompt cache on character system prompt; fallback to template-only mode |

### Data Contracts (Pydantic v2)

```python
class CharacterProfile(BaseModel):
    id: str
    name: str
    lora_path: str
    lora_weight: float = Field(ge=0.0, le=2.0, default=0.8)
    trigger_words: list[str]
    base_model: str
    negative_prompt: str
    reference_image_paths: list[str]

class WorkflowRequest(BaseModel):
    character_id: str
    scene_description: str
    scenario: Literal["travel","food","fashion","lifestyle","gym","studio"]
    aspect_ratio: Literal["9:16","1:1","16:9"]
    output_type: Literal["image","video"]
    quality_preset: Literal["draft","standard","high"]

class GenerationJob(BaseModel):
    job_id: str
    prompt_id: str  # ComfyUI queue ID
    status: Literal["queued","running","complete","failed"]
    output_paths: list[str] = []
    face_similarity_score: float | None = None
    created_at: datetime
```

### Async I/O Boundaries (all must be `async`)

- `ComfyUIClient.submit_prompt()` — HTTP POST to local ComfyUI
- `ComfyUIClient.poll_job()` — WebSocket `/ws?clientId=…`
- `CharacterRegistry.load_profile()` — disk read
- `MediaPostProcessor.process()` — subprocess FFmpeg

---

Now writing the updated `tasks.md`:



The `tasks.md` has been updated additively. Here's the architectural summary:

## Architecture Recommendation

**Modular monolith on a single GPU node** — 7 clean modules with explicit async boundaries:

| Module | Responsibility |
|---|---|
| `models.py` | Pydantic v2 contracts — `CharacterProfile`, `WorkflowRequest`, `GenerationJob` |
| `character_registry.py` | Persistent identity store with atomic writes + path traversal guard |
| `comfyui_client.py` | Async HTTP + WebSocket client; typed timeout errors |
| `workflow_builder.py` | JSON template patching per scenario/aspect-ratio/quality |
| `visual_artist.py` | Claude claude-opus-4-6 prompt engineer with cached system prompt |
| `media_processor.py` | PIL resize, FFmpeg encode, deepface similarity gate |
| `pipeline.py` | End-to-end orchestration with face-consistency retry loop |

**Critical risks named and mitigated:**
- Character drift → face similarity score gate (≥0.75, max 3 retries)
- ComfyUI SPOF → Docker auto-restart + typed timeout with job failure propagation
- Sync-in-async blocker → all I/O is `httpx.AsyncClient` / `asyncio.create_subprocess_exec`
- Path traversal in LoRA paths → allowlist directory validation at registry write time

### Backenddev
# Backend Architecture: AI Influencer Factory

## Stack Recommendation

**FastAPI + Python 3.12** — non-negotiable given ComfyUI's Python ecosystem. Native async support, Pydantic v2 integration, and easy WebSocket handling for real-time job progress.

**PostgreSQL 16** for persistent storage (character profiles, job history, generated asset metadata). **Redis 7** for job queue state, caching workflow templates, and pub/sub for generation progress events.

**Celery + Redis broker** for async ComfyUI job dispatch — ComfyUI's `/prompt` endpoint is fire-and-forget, so you need a durable queue with retry logic, not just `asyncio.gather`.

---

## ComfyUI Integration Design

ComfyUI exposes a REST API + WebSocket on `localhost:8188`. The critical pattern:

```
POST /prompt → job_id
WS  /ws?clientId=X → stream progress events
GET /history/{job_id} → retrieve outputs
GET /view?filename=X → download generated image
```

Build a `ComfyUIClient` service that:
1. Maintains a persistent WebSocket connection per worker
2. Templates workflows as Jinja2 JSON files — swap character LoRA paths, seeds, prompts without hardcoding
3. Polls `/history` as fallback if WebSocket drops

**Critical quirk:** ComfyUI queues internally too — track both your Celery job state AND ComfyUI's queue position to give accurate ETAs.

---

## Database Schema (Core Tables)

- `characters` — LoRA path, embedding path, base prompt, style tags, `created_at` with `tzinfo=UTC`
- `generation_jobs` — `job_id UUID`, `character_id FK`, `prompt TEXT`, `workflow_template`, `status ENUM`, `output_paths JSONB`, `cost_seconds NUMERIC(8,2)`
- `assets` — file path, S3 key, platform target (tiktok/facebook), dimensions, `Decimal` file size

---

## API Design: REST over GraphQL

Simple CRUD + job submission doesn't justify GraphQL complexity. Three core endpoints:

```
POST /characters          — register new AI persona
POST /jobs                — submit generation job
GET  /jobs/{id}/status    — SSE stream for real-time progress
GET  /assets/{character_id} — paginated asset library
```

Use **SSE** (Server-Sent Events) over WebSockets for job progress — one-way streaming, browser-native, survives proxies better than WS.

---

## Caching & Rate Limiting

- Cache compiled workflow JSON templates in Redis (`TTL=3600`) — template rendering is CPU-bound and repetitive
- Rate limit generation jobs per character: `slowapi` middleware, 10 jobs/hour/character to prevent GPU saturation
- S3 presigned URLs for asset delivery — never serve binaries through FastAPI

---

## File Path Safety

ComfyUI writes outputs to its own `/output` directory. Always resolve with `os.path.realpath()` and assert against the allowed prefix before any read/write:

```python
COMFY_OUTPUT_ROOT = Path("/comfyui/output").resolve()
assert resolved_path.is_relative_to(COMFY_OUTPUT_ROOT)
```

---

**Biggest risk:** ComfyUI has no auth, no multi-tenancy, and crashes silently under VRAM pressure. Wrap every `/prompt` call with health checks and implement a GPU memory watchdog via `nvidia-smi` polling before queuing jobs.

### Skeptic
# Skeptic's Challenge: AI Influencer Factory

## The Hidden Assumption

Every proposal here rests on an unstated premise: *that character consistency is a solved problem*. It isn't. Let's interrogate that before building an entire factory around it.

---

## Blocking Issues

**1. "Master Character Profile (LoRAs/embeddings)" — this is harder than it sounds.**

Quote: *"Develop a 'Master Character' profile (embeddings/LoRAs)."*

Training a production-quality LoRA that holds across lighting, pose, clothing, and scene changes requires 50–200 curated training images and multiple training runs. The failure mode isn't "slightly off" — it's uncanny valley at scale. Every generated image goes public. One bad batch poisons the brand permanently. Probability: **likely**. Blast radius: **entire project credibility**.

Simpler alternative: Use a single reference image + IP-Adapter or InstantID for consistency before committing to LoRA training infrastructure.

---

## Advisory Risks

**2. ComfyUI as an automation target is fragile.**

Quote: *"Convert simple user prompts into complex ComfyUI JSON payloads."*

ComfyUI workflows are node graphs serialized as JSON — they break silently when node versions update, custom nodes get deprecated, or you switch models. You're proposing an LLM generate these payloads dynamically. This is a maintenance nightmare: the LLM hallucinates node IDs, connection schemas drift, and debugging is opaque. Probability of silent failures: **certain over 6 months**.

Simpler alternative: Maintain 3–5 hand-crafted, version-locked workflow templates. Parameterize prompts only. No dynamic JSON generation.

---

**3. Video is a separate product, not a feature.**

Quote: *"Expand from static images to short-form video (AnimateDiff/SVD)."*

AnimateDiff and SVD have fundamentally different consistency requirements, VRAM ceilings (24GB+ for SVD at quality), and latency profiles (10–30 min per clip). Bundling this with image generation in one system means two failure domains, two model management strategies, and double the infra cost. Probability this scope creep delays launch: **certain**.

Simpler alternative: Ship image-only V1. Validate the content strategy works before building video.

---

## The Uncomfortable Question

What's the actual content strategy here? "Travel, food, fashion" scenes generated by ComfyUI are detectable as AI by 2026 audiences. TikTok's algorithm increasingly deprioritizes AI-generated content. The technical proposal assumes the distribution problem is solved.

**The real risk isn't technical — it's that you build a flawless image pipeline for an audience that won't engage.**

---

## Summary Verdict

| Proposal | Status | Concern |
|---|---|---|
| LoRA Master Character | Advisory | Underestimated training effort |
| Dynamic ComfyUI JSON | Blocking | Fragile, unmaintainable |
| Video (AnimateDiff/SVD) | Advisory | Scope creep, defer to V2 |
| Workflow automation | Advisory | Over-engineered for 3–5 use cases |

Build less. Validate the content loop first.

## Debate Round 2: Critiques & Refinements
### Architect
## Architect's Challenge: Round 2

### Conceding to the Skeptic — With One Correction

The Skeptic's blocking call on **dynamic ComfyUI JSON generation** is correct in principle, but misreads my proposal. My `VisualArtist` generates *text prompts* (comma-separated tags), not workflow JSON. The `WorkflowBuilder` patches static, hand-crafted templates. These are two different things. The LLM never touches node IDs or connection schemas.

That said, the Skeptic is right that I under-specified this boundary. Let me make it explicit:

```
VisualArtist → produces: "maya lora, golden hour, paris cafe, fashion editorial" (text only)
WorkflowBuilder → patches: templates/travel_9x16.json nodes["CLIPTextEncode"]["inputs"]["text"]
```

The LLM is isolated from ComfyUI's schema entirely. Template versioning is a `git tag` on the `templates/` directory. This is maintainable.

---

### Challenging BackendDev's Stack

**Celery + Redis + PostgreSQL is premature.** This is a single-GPU pipeline generating ~5–20 images/hour. You're proposing distributed task queue infrastructure for what `asyncio.Queue` + SQLite handles cleanly.

The cost is real: three additional services in Docker Compose, Celery worker management, Redis connection pooling, and Alembic migrations — all before a single image is generated. For a solo operator on one GPU node, this is a maintenance burden with zero throughput benefit.

My revised infrastructure call:

| Component | BackendDev | Architect (revised) | Justification |
|---|---|---|---|
| Job queue | Celery + Redis | `asyncio.Queue` in-process | Single GPU = one consumer, no distribution needed |
| Persistence | PostgreSQL | SQLite + JSON files | No concurrent writes, no network I/O |
| Job state | Redis pub/sub | SSE from pipeline coroutine | BackendDev's SSE suggestion is correct; no broker needed |

Upgrade to PostgreSQL + Celery when: multiple GPU nodes, or >50 concurrent users. Not before.

---

### Supporting the Skeptic on IP-Adapter First

The Skeptic's IP-Adapter suggestion is architecturally sound as a V1 path. It eliminates the LoRA training dependency entirely. My `CharacterProfile` model already accommodates this — `lora_path` should become `Optional[str]` with a new `ip_adapter_reference_image: str` field. The `WorkflowBuilder` selects the appropriate template based on which is populated.

```python
class CharacterProfile(BaseModel):
    lora_path: str | None = None
    ip_adapter_reference_image: str | None = None

    @model_validator(mode="after")
    def must_have_one_consistency_method(self) -> "CharacterProfile":
        if not self.lora_path and not self.ip_adapter_reference_image:
            raise ValueError("Provide lora_path or ip_adapter_reference_image")
        return self
```

This makes LoRA optional at the data model level without architectural rework.

---

### One Risk Nobody Named

The `deepface`/`insightface` face similarity gate shares GPU memory with the Stable Diffusion pipeline. Loading both simultaneously on a 12GB card causes OOM. The pipeline must **unload SD models before running face embedding**, then reload — adding 30–60s per generation cycle.

Mitigation: run face similarity on CPU with `insightface` in CPU mode. Slower but no VRAM conflict. Document this as a hard constraint in Phase 13.

---

### Revised Scope Recommendation

Agree with Skeptic: **defer video to V2**. Remove Phase 15 from the critical path. Image pipeline + IP-Adapter consistency + face gate is a complete, shippable V1.

### Backenddev
# Backend Challenge: Round 2

## Conceding the Skeptic on Dynamic JSON — But Not Entirely

The Skeptic is correct that LLM-generated ComfyUI node graphs are a maintenance disaster. I'll strengthen my earlier position: **Jinja2 templates are not the same as dynamic generation.**

My proposal was parameterized templates — version-locked JSON files where only `{{lora_weight}}`, `{{prompt}}`, `{{seed}}` get swapped. The Skeptic is right to kill the idea of an LLM generating node IDs and connection schemas dynamically. But abandoning template infrastructure entirely means hardcoded payloads that can't adapt to prompt content at all. The middle ground is clear:

```
/workflows/
  travel_9x16_standard.json.j2  ← locked node graph
  food_1x1_high.json.j2
  fashion_9x16_high.json.j2
```

Template variables: prompts, seeds, LoRA weights only. Node topology: never touched at runtime. Exactly 5 templates. Versioned with the workflow JSON in git.

---

## Challenging the Architect on SQLite

The Architect's data contract spec is solid, but "JSON/SQLite" for the Character Registry is a liability the moment you have >1 worker. Celery workers run concurrently — SQLite's write lock will cause dropped jobs under any real load. **PostgreSQL is not over-engineering here; it's the minimum safe baseline for a queue-backed system.**

Concrete replacement: `asyncpg` + `SQLAlchemy 2.0` async core. Character Registry becomes a proper table with `SELECT FOR UPDATE SKIP LOCKED` on job dispatch. No thread-safety workarounds needed.

---

## Defending Celery Against Implicit Criticism

The Architect's `pipeline.py` describes a face-consistency retry loop. That retry logic *must* survive process crashes and GPU OOM kills. `asyncio.gather` with retry decorators dies when the process dies. Celery with Redis backend means the job survives a ComfyUI crash, a Python exception, or a SIGKILL from the OOM killer. For GPU workloads on a single node, this isn't optional.

---

## The GPU Watchdog Is More Critical Than Anyone Said

Both proposals treat ComfyUI health as a nice-to-have. It's actually the critical path. VRAM exhaustion on a single-GPU node doesn't raise an exception — it hangs, then errors 90 seconds later. Every job behind it is now stale.

Concrete implementation: a dedicated `gpu_monitor.py` FastAPI background task running every 15 seconds:

```python
async def check_vram() -> bool:
    proc = await asyncio.create_subprocess_exec(
        "nvidia-smi", "--query-gpu=memory.used,memory.total",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    used, total = map(int, out.decode().strip().split(", "))
    return (used / total) < 0.90  # pause queue above 90%
```

If over threshold: pause Celery queue, set a Redis flag, return 503 on new job submissions. Resume when clear. This prevents the silent hang the Skeptic correctly identified as a risk.

---

## Scope Agreement

Video to V2. Image pipeline only. The Skeptic is right — two VRAM profiles on one node is a scheduling nightmare.

### Skeptic
# Skeptic — Round 2: Doubling Down and New Targets

My Round 1 concerns weren't addressed — they were *architectured around*. That's a red flag.

---

## New Target: The Architect's Retry Loop

Quote: *"face-consistency retry loop... face similarity score gate (≥0.75, max 3 retries)"*

**Hidden assumption:** that a rejected image can be regenerated cheaply. At high quality presets, a single ComfyUI run takes 30–90 seconds on consumer GPU. Three retries per job means potentially 4.5 minutes of GPU time to publish one photo. At scale, this is a **throughput cliff**, not a safety net.

Worse: if the character LoRA is fundamentally inconsistent (my Round 1 concern), you'll hit 3-retry exhaustion constantly. The retry loop doesn't fix the root cause — it papers over it while burning compute.

**Simpler alternative:** validate face similarity *during* LoRA training, not at generation time. Gate on training quality, not output quality. One fix upstream beats infinite retries downstream.

---

## New Target: BackendDev's Stack

Quote: *"FastAPI + PostgreSQL 16 + Redis 7 + Celery + Redis broker"*

**Advisory — likely over-engineered for V1.**

Count the moving parts: FastAPI, Postgres, Redis (dual role: queue + cache), Celery workers, ComfyUI server, nvidia-smi watchdog, S3. That's 7 infrastructure components before writing a single line of business logic. Who operates this? Who debugs a Celery worker silently dropping jobs at 2am?

The Architect already proposed a modular monolith. BackendDev then added a distributed job queue on top. These two proposals contradict each other — *pick one*. A modular monolith with `asyncio` and SQLite handles 10 jobs/hour trivially. You don't need Celery until you have multiple GPU nodes.

**Simpler alternative:** `asyncio.Queue` + single Postgres table for job state. Add Celery when you have the second GPU node, not before.

---

## Defending Round 1 Against Implicit Pushback

The Architect's spec includes `face_similarity_score: float | None` in `GenerationJob`. This acknowledges face consistency is a problem — but then treats it as a post-generation filter rather than a pre-generation guarantee. That's backwards architecture: design for failure rather than preventing failure.

Quote: *"Inject CharacterProfile trigger words + embeddings"*

LoRA trigger words are notoriously model-version-sensitive. Switch base models (SDXL → Flux), and your trigger words are meaningless. The Architect's schema hardcodes `base_model: str` but provides no migration path. **Blast radius: entire character library becomes unusable on model upgrade.** Probability: **certain within 18 months** given the SD ecosystem's pace.

---

## The One Thing I'll Support

BackendDev's SSE over WebSockets for job progress is correct. Simple, stateless, proxy-friendly. No argument there.

---

## Round 2 Verdict

| New Issue | Status | Severity |
|---|---|---|
| Retry loop masks LoRA quality problem | Blocking | High |
| 7-component V1 stack | Advisory | Medium |
| Monolith + Celery contradiction | Blocking | Must resolve |
| Trigger word model-lock | Advisory | Long-term debt |

The proposals are getting more elaborate. The right direction is less.

## Final Synthesis & Architecture Recommendation
# AI Influencer Factory — Final Synthesis

## Executive Summary

Build a **modular monolith** image generation pipeline on a single GPU node. Use IP-Adapter for character consistency in V1 (defer LoRA training). Maintain 5 hand-crafted ComfyUI workflow templates — no dynamic JSON generation. Ship image-only V1; video is V2.

The Skeptic's core critique stands: the project's biggest risk is content strategy, not infrastructure. Build the minimum viable pipeline, validate audience engagement, then scale.

---

## Recommended Tech Stack

| Component | Choice | Reasoning |
|---|---|---|
| API | FastAPI + Python 3.12 | Native async, Pydantic v2, ComfyUI ecosystem fit |
| Job queue | `asyncio.Queue` (in-process) | Single GPU = one consumer; no distribution benefit |
| Persistence | SQLite + JSON files | No concurrent writes; zero ops overhead |
| Job progress | SSE from pipeline coroutine | One-way, proxy-safe, no broker needed |
| ComfyUI client | `httpx.AsyncClient` + WebSocket | Async HTTP + fallback polling |
| Face validation | `insightface` on CPU | Avoids VRAM conflict with SD pipeline |
| Post-processing | PIL + FFmpeg subprocess | Standard, well-documented |

**Rejected:** Celery, Redis, PostgreSQL — all deferred until second GPU node. The monolith-plus-distributed-queue contradiction the Skeptic identified is resolved by picking the monolith fully.

---

## Architecture Overview

```
User/Orchestrator
       │ WorkflowRequest (Pydantic)
       ▼
  VisualArtist Agent (Claude)
  → produces text prompts only, never node IDs
       │
       ▼
  WorkflowBuilder
  → patches 1 of 5 locked Jinja2 templates
  → swaps: {prompt}, {seed}, {lora_weight}, {ip_adapter_ref}
       │ ComfyUI JSON
       ▼
  ComfyUI Server (localhost:8188)
  → GPU watchdog polls nvidia-smi every 15s; pauses queue >90% VRAM
       │ raw PNG
       ▼
  MediaPostProcessor (PIL, FFmpeg)
  → insightface similarity check on CPU (threshold ≥0.75, max 2 retries)
  → resize + watermark for platform
       │
       ▼
  CharacterRegistry (SQLite)  │  Content Store (local /output)
```

---

## Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| IP-Adapter consistency drift | Validate per-scene; gate with face similarity before publishing |
| Retry loop masking bad reference image | Max 2 retries (not 3); fail loudly with diagnosis, not silent exhaustion |
| ComfyUI template drift on node updates | Version-lock templates with git tags; test on update before promotion |
| VRAM contention (SD + insightface) | Run insightface CPU-only; unload SD before face check |
| Model upgrade breaks character library | `CharacterProfile.base_model` field; migration script required on upgrade |
| Audience won't engage with AI content | **Ship V1 fast, test content strategy before building V2** |

---

## Implementation Phases

**Phase 1 — Core Pipeline (Weeks 1–2)**
- `models.py`: `CharacterProfile` (IP-Adapter path, optional LoRA), `WorkflowRequest`, `GenerationJob`
- `comfyui_client.py`: async HTTP + WebSocket + GPU watchdog
- `workflow_builder.py`: 3 locked templates (travel, food, fashion)
- `character_registry.py`: SQLite-backed, path traversal guard
- Milestone: generate one consistent image end-to-end

**Phase 2 — Quality Gate & Automation (Weeks 3–4)**
- `visual_artist.py`: Claude prompt engineer, cached system prompt, text-only output
- `media_processor.py`: insightface CPU similarity gate, PIL resize, watermark
- SSE job progress endpoint
- Milestone: full pipeline with consistency validation

**Phase 3 — Content Loop Validation (Weeks 5–6)**
- Add 2 remaining templates (gym, studio)
- Publish first 10 images to TikTok/Facebook
- Measure engagement before any V2 investment
- Milestone: real audience signal acquired

**V2 gate:** Only proceed to LoRA training + video (AnimateDiff) if V1 content demonstrates measurable engagement.

---

## Open Questions

1. What reference images exist for the character? IP-Adapter quality depends on reference quality.
2. Which base model? (SDXL, Flux, SD 1.5) — determines template design and VRAM floor.
3. GPU spec? (VRAM determines quality presets available without model offloading.)
4. Is there an existing TikTok/Facebook account, or does that need setup in parallel?
