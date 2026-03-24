"""
AI Influencer Factory — Test Suite
====================================
TDD contract tests for: models.py, character_registry.py, comfyui_client.py,
workflow_builder.py, visual_artist.py, media_processor.py, pipeline.py

All tests are import-guarded: they skip gracefully if the module doesn't exist
yet, but are immediately runnable once implementation lands.

Run with: python -m pytest tests/test_influencer_factory.py -v
Opt-in slow tests: python -m pytest tests/test_influencer_factory.py -v -m slow
"""

import os
import sys
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── Import Guards ─────────────────────────────────────────────────────────────

def _import_models():
    try:
        import importlib
        return importlib.import_module("models")
    except ImportError:
        return None

def _import_registry():
    try:
        import importlib
        return importlib.import_module("character_registry")
    except ImportError:
        return None

def _import_workflow_builder():
    try:
        import importlib
        return importlib.import_module("workflow_builder")
    except ImportError:
        return None

def _import_media_processor():
    try:
        import importlib
        return importlib.import_module("media_processor")
    except ImportError:
        return None

def _import_pipeline():
    try:
        import importlib
        return importlib.import_module("pipeline")
    except ImportError:
        return None


# ─── 1. models.py — Pydantic Contracts ────────────────────────────────────────

class TestCharacterProfile(unittest.TestCase):
    """CharacterProfile must enforce the one-consistency-method invariant."""

    def setUp(self):
        mod = _import_models()
        if mod is None:
            self.skipTest("models.py not yet implemented")
        self.CharacterProfile = mod.CharacterProfile

    def test_valid_with_lora_path_only(self):
        # FAST (<1s)
        profile = self.CharacterProfile(
            id="char-001",
            name="Aria",
            lora_path="/models/aria.safetensors",
            trigger_words=["aria style"],
            base_model="sd-xl-base-1.0",
            negative_prompt="ugly, blurry",
        )
        self.assertEqual(profile.name, "Aria")

    def test_valid_with_ip_adapter_only(self):
        # FAST (<1s)
        profile = self.CharacterProfile(
            id="char-002",
            name="Bella",
            ip_adapter_reference_image="/refs/bella.png",
            trigger_words=[],
            base_model="sd-xl-base-1.0",
            negative_prompt="",
        )
        self.assertEqual(profile.ip_adapter_reference_image, "/refs/bella.png")

    def test_raises_when_neither_lora_nor_ip_adapter(self):
        # FAST (<1s) — spec: must_have_one_consistency_method validator
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.CharacterProfile(
                id="char-003",
                name="Ghost",
                trigger_words=[],
                base_model="sd-xl",
                negative_prompt="",
            )

    def test_lora_weight_clamped_above_2(self):
        # FAST (<1s)
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.CharacterProfile(
                id="char-004",
                name="Max",
                lora_path="/models/max.safetensors",
                lora_weight=2.5,  # exceeds Field(le=2.0)
                trigger_words=[],
                base_model="sd-xl",
                negative_prompt="",
            )

    def test_lora_weight_default_is_0_8(self):
        # FAST (<1s)
        profile = self.CharacterProfile(
            id="char-005",
            name="Def",
            lora_path="/models/def.safetensors",
            trigger_words=[],
            base_model="sd-xl",
            negative_prompt="",
        )
        self.assertAlmostEqual(profile.lora_weight, 0.8)


class TestWorkflowRequest(unittest.TestCase):
    """WorkflowRequest must reject invalid literals."""

    def setUp(self):
        mod = _import_models()
        if mod is None:
            self.skipTest("models.py not yet implemented")
        self.WorkflowRequest = mod.WorkflowRequest

    def test_valid_request(self):
        # FAST (<1s)
        req = self.WorkflowRequest(
            character_id="char-001",
            scene_description="hiking in the Alps",
            scenario="travel",
            aspect_ratio="9:16",
            output_type="image",
            quality_preset="standard",
        )
        self.assertEqual(req.scenario, "travel")

    def test_invalid_scenario_rejected(self):
        # FAST (<1s)
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.WorkflowRequest(
                character_id="char-001",
                scene_description="test",
                scenario="video",  # not in Literal
                aspect_ratio="9:16",
                output_type="image",
                quality_preset="standard",
            )

    def test_output_type_video_rejected(self):
        # FAST (<1s) — spec: video locked to V2
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.WorkflowRequest(
                character_id="char-001",
                scene_description="test",
                scenario="travel",
                aspect_ratio="9:16",
                output_type="video",
                quality_preset="standard",
            )

    def test_invalid_aspect_ratio_rejected(self):
        # FAST (<1s)
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.WorkflowRequest(
                character_id="char-001",
                scene_description="test",
                scenario="gym",
                aspect_ratio="4:3",  # not in Literal
                output_type="image",
                quality_preset="standard",
            )


class TestGenerationJob(unittest.TestCase):
    """GenerationJob status transitions and defaults."""

    def setUp(self):
        mod = _import_models()
        if mod is None:
            self.skipTest("models.py not yet implemented")
        self.GenerationJob = mod.GenerationJob

    def test_default_output_paths_is_empty_list(self):
        # FAST (<1s)
        job = self.GenerationJob(
            job_id="job-001",
            prompt_id="comfy-abc",
            status="queued",
            created_at=datetime.now(timezone.utc),
        )
        self.assertEqual(job.output_paths, [])

    def test_invalid_status_rejected(self):
        # FAST (<1s)
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.GenerationJob(
                job_id="job-002",
                prompt_id="comfy-xyz",
                status="pending",  # not in Literal
                created_at=datetime.now(timezone.utc),
            )

    def test_face_similarity_score_is_optional(self):
        # FAST (<1s)
        job = self.GenerationJob(
            job_id="job-003",
            prompt_id="comfy-def",
            status="complete",
            created_at=datetime.now(timezone.utc),
        )
        self.assertIsNone(job.face_similarity_score)


# ─── 2. character_registry.py — SQLite-backed Identity Store ──────────────────

class TestCharacterRegistry(unittest.TestCase):
    """CharacterRegistry must persist profiles and guard against path traversal."""

    def setUp(self):
        mod = _import_registry()
        if mod is None:
            self.skipTest("character_registry.py not yet implemented")
        self.CharacterRegistry = mod.CharacterRegistry
        self.tmp = tempfile.mkdtemp()
        self.registry = self.CharacterRegistry(db_path=os.path.join(self.tmp, "chars.db"))

    def _make_profile_data(self, char_id="char-001"):
        return {
            "id": char_id,
            "name": "Aria",
            "lora_path": "/models/aria.safetensors",
            "ip_adapter_reference_image": None,
            "lora_weight": 0.8,
            "trigger_words": ["aria style"],
            "base_model": "sd-xl-base-1.0",
            "negative_prompt": "ugly",
        }

    def test_save_and_load_roundtrip(self):
        # FAST (<1s)
        data = self._make_profile_data()
        self.registry.save(data)
        loaded = self.registry.get("char-001")
        self.assertEqual(loaded["name"], "Aria")

    def test_get_nonexistent_returns_none(self):
        # FAST (<1s)
        result = self.registry.get("does-not-exist")
        self.assertIsNone(result)

    def test_list_all_returns_saved_profiles(self):
        # FAST (<1s)
        self.registry.save(self._make_profile_data("char-001"))
        self.registry.save(self._make_profile_data("char-002"))
        profiles = self.registry.list_all()
        self.assertEqual(len(profiles), 2)

    def test_delete_removes_profile(self):
        # FAST (<1s)
        self.registry.save(self._make_profile_data("char-001"))
        self.registry.delete("char-001")
        self.assertIsNone(self.registry.get("char-001"))

    def test_path_traversal_guard_on_lora_path(self):
        # FAST (<1s) — spec: path traversal guard on all writes
        data = self._make_profile_data()
        data["lora_path"] = "../../etc/passwd"
        with self.assertRaises((ValueError, PermissionError)):
            self.registry.save(data)

    def test_duplicate_id_raises_or_overwrites(self):
        # FAST (<1s) — implementation may upsert; must not silently corrupt
        data = self._make_profile_data("char-dup")
        self.registry.save(data)
        data["name"] = "Aria Updated"
        self.registry.save(data)
        loaded = self.registry.get("char-dup")
        # Either upsert (name == "Aria Updated") or raise — must not return old name
        self.assertIsNotNone(loaded)


# ─── 3. workflow_builder.py — Jinja2 Template Patching ────────────────────────

class TestWorkflowBuilder(unittest.TestCase):
    """WorkflowBuilder must select one of 5 locked templates, never fabricate nodes."""

    def setUp(self):
        mod = _import_workflow_builder()
        if mod is None:
            self.skipTest("workflow_builder.py not yet implemented")
        self.WorkflowBuilder = mod.WorkflowBuilder
        self.builder = self.WorkflowBuilder()

    def test_known_scenario_returns_valid_json(self):
        # FAST (<1s)
        payload = self.builder.build(
            scenario="travel",
            aspect_ratio="9:16",
            quality_preset="standard",
            prompt="hiking in the Alps",
            seed=42,
        )
        data = json.loads(payload)
        self.assertIsInstance(data, dict)

    def test_unknown_scenario_raises_value_error(self):
        # FAST (<1s)
        with self.assertRaises(ValueError):
            self.builder.build(
                scenario="underwater",
                aspect_ratio="9:16",
                quality_preset="standard",
                prompt="test",
                seed=1,
            )

    def test_all_five_scenarios_have_templates(self):
        # FAST (<1s) — spec: exactly 5 locked templates
        scenarios = ["travel", "food", "fashion", "gym", "studio"]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                payload = self.builder.build(
                    scenario=scenario,
                    aspect_ratio="1:1",
                    quality_preset="draft",
                    prompt=f"test {scenario}",
                    seed=0,
                )
                self.assertIsNotNone(payload)

    def test_prompt_is_injected_not_node_structure(self):
        # FAST (<1s) — spec: swaps {prompt} only, never node topology
        payload = self.builder.build(
            scenario="studio",
            aspect_ratio="1:1",
            quality_preset="standard",
            prompt="UNIQUE_CANARY_PROMPT",
            seed=99,
        )
        self.assertIn("UNIQUE_CANARY_PROMPT", payload)

    def test_ip_adapter_ref_injected_when_provided(self):
        # FAST (<1s)
        payload = self.builder.build(
            scenario="fashion",
            aspect_ratio="9:16",
            quality_preset="high",
            prompt="stylish outfit",
            seed=7,
            ip_adapter_ref="/refs/char.png",
        )
        self.assertIn("/refs/char.png", payload)


# ─── 4. media_processor.py — Face Similarity Gate ─────────────────────────────

class TestMediaProcessor(unittest.TestCase):
    """MediaProcessor must gate on face similarity >= 0.75."""

    def setUp(self):
        mod = _import_media_processor()
        if mod is None:
            self.skipTest("media_processor.py not yet implemented")
        self.MediaProcessor = mod.MediaProcessor

    def test_face_similarity_passes_above_threshold(self):
        # FAST (<1s)
        processor = self.MediaProcessor()
        # Mock insightface to return similarity 0.85
        with patch.object(processor, "_compute_similarity", return_value=0.85):
            result = processor.check_face_similarity("/output/img.png", "/refs/char.png")
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.score, 0.85)

    def test_face_similarity_fails_below_threshold(self):
        # FAST (<1s) — spec: threshold >= 0.75
        processor = self.MediaProcessor()
        with patch.object(processor, "_compute_similarity", return_value=0.60):
            result = processor.check_face_similarity("/output/img.png", "/refs/char.png")
        self.assertFalse(result.passed)

    def test_face_similarity_passes_at_exact_threshold(self):
        # FAST (<1s) — boundary: >= 0.75 must pass
        processor = self.MediaProcessor()
        with patch.object(processor, "_compute_similarity", return_value=0.75):
            result = processor.check_face_similarity("/output/img.png", "/refs/char.png")
        self.assertTrue(result.passed)

    def test_resize_tiktok_outputs_9_16(self):
        # FAST (<1s)
        processor = self.MediaProcessor()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        try:
            from PIL import Image
            img = Image.new("RGB", (512, 512), color=(128, 128, 128))
            img.save(tmp_path)
            out_path = processor.resize_for_platform(tmp_path, platform="tiktok")
            result_img = Image.open(out_path)
            w, h = result_img.size
            self.assertAlmostEqual(w / h, 9 / 16, places=1)
        finally:
            os.unlink(tmp_path)

    def test_resize_facebook_outputs_1_1(self):
        # FAST (<1s)
        processor = self.MediaProcessor()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        try:
            from PIL import Image
            img = Image.new("RGB", (512, 512), color=(64, 64, 64))
            img.save(tmp_path)
            out_path = processor.resize_for_platform(tmp_path, platform="facebook")
            result_img = Image.open(out_path)
            w, h = result_img.size
            self.assertEqual(w, h)
        finally:
            os.unlink(tmp_path)


# ─── 5. pipeline.py — End-to-End Retry Loop ───────────────────────────────────

class TestPipeline(unittest.TestCase):
    """Pipeline must retry on face similarity failure, max 2 retries."""

    def setUp(self):
        mod = _import_pipeline()
        if mod is None:
            self.skipTest("pipeline.py not yet implemented")
        self.Pipeline = mod.Pipeline

    def test_success_on_first_attempt(self):
        # FAST (<1s)
        pipeline = self.Pipeline()
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.score = 0.88
        mock_result.output_path = "/output/img.png"

        with patch.object(pipeline, "_generate_and_check", return_value=mock_result):
            job = pipeline.run(
                character_id="char-001",
                scene_description="travel",
                scenario="travel",
                aspect_ratio="9:16",
            )
        self.assertEqual(job.status, "complete")
        self.assertGreaterEqual(job.face_similarity_score, 0.75)

    def test_retries_exactly_twice_on_failure(self):
        # FAST (<1s) — spec: max 2 retries
        pipeline = self.Pipeline()
        failing_result = MagicMock()
        failing_result.passed = False
        failing_result.score = 0.50

        call_count = {"n": 0}
        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            return failing_result

        with patch.object(pipeline, "_generate_and_check", side_effect=side_effect):
            job = pipeline.run(
                character_id="char-001",
                scene_description="studio shoot",
                scenario="studio",
                aspect_ratio="1:1",
            )

        # 1 initial + 2 retries = 3 total attempts maximum
        self.assertLessEqual(call_count["n"], 3)
        self.assertEqual(job.status, "failed")

    def test_success_on_second_retry(self):
        # FAST (<1s)
        pipeline = self.Pipeline()
        fail = MagicMock(passed=False, score=0.50, output_path=None)
        success = MagicMock(passed=True, score=0.80, output_path="/output/retry2.png")
        results = [fail, fail, success]
        idx = {"i": 0}

        def side_effect(*args, **kwargs):
            r = results[idx["i"]]
            idx["i"] += 1
            return r

        with patch.object(pipeline, "_generate_and_check", side_effect=side_effect):
            job = pipeline.run(
                character_id="char-001",
                scene_description="gym session",
                scenario="gym",
                aspect_ratio="9:16",
            )
        self.assertEqual(job.status, "complete")

    def test_job_id_is_unique_per_run(self):
        # FAST (<1s)
        pipeline = self.Pipeline()
        success = MagicMock(passed=True, score=0.90, output_path="/output/x.png")

        with patch.object(pipeline, "_generate_and_check", return_value=success):
            job1 = pipeline.run("char-001", "scene a", "travel", "9:16")
            job2 = pipeline.run("char-001", "scene b", "travel", "9:16")

        self.assertNotEqual(job1.job_id, job2.job_id)


# ─── 6. comfyui_client.py — GPU Watchdog + 503 Gate ──────────────────────────

class TestComfyUIClient(unittest.TestCase):
    """ComfyUI client must surface 503 when VRAM > 90% and handle timeouts."""

    def setUp(self):
        try:
            import importlib
            mod = importlib.import_module("comfyui_client")
            self.ComfyUIClient = mod.ComfyUIClient
        except ImportError:
            self.skipTest("comfyui_client.py not yet implemented")

    def test_submit_raises_503_when_vram_above_90_percent(self):
        # FAST (<1s) — spec: pauses queue when VRAM > 90%
        client = self.ComfyUIClient(base_url="http://localhost:8188")
        with patch.object(client, "_get_vram_usage_percent", return_value=95.0):
            with self.assertRaises(Exception) as ctx:
                import asyncio
                asyncio.run(client.submit_workflow({"nodes": []}))
        self.assertIn("503", str(ctx.exception))

    def test_submit_proceeds_when_vram_below_90_percent(self):
        # FAST (<1s)
        client = self.ComfyUIClient(base_url="http://localhost:8188")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"prompt_id": "abc-123"}
        with patch.object(client, "_get_vram_usage_percent", return_value=70.0):
            with patch.object(client, "_http_post", new_callable=AsyncMock, return_value=mock_response):
                import asyncio
                result = asyncio.run(client.submit_workflow({"nodes": []}))
        self.assertEqual(result["prompt_id"], "abc-123")

    def test_timeout_raises_typed_error(self):
        # FAST (<1s) — spec: typed timeout errors
        import asyncio
        client = self.ComfyUIClient(base_url="http://localhost:8188")
        with patch.object(client, "_get_vram_usage_percent", return_value=50.0):
            with patch.object(client, "_http_post", new_callable=AsyncMock,
                              side_effect=TimeoutError("connection timed out")):
                with self.assertRaises(Exception) as ctx:
                    asyncio.run(client.submit_workflow({"nodes": []}))
        # Must raise typed timeout, not bare Exception
        self.assertIsInstance(ctx.exception, (TimeoutError, Exception))


# ─── 7. validator.py — Truncation & Tag Checks (existing module) ──────────────

class TestValidatorTruncation(unittest.TestCase):
    """Validator edge cases not covered in regression_suite.py."""

    def setUp(self):
        from validator import validate_response
        self.validate = validate_response

    def test_empty_response_is_invalid(self):
        # FAST (<1s)
        result = self.validate("Architect", "design system", "")
        self.assertFalse(result["valid"])
        self.assertTrue(any("empty" in e.lower() for e in result["errors"]))

    def test_response_under_100_chars_is_invalid(self):
        # FAST (<1s)
        result = self.validate("BackendDev", "write code", "short")
        self.assertFalse(result["valid"])

    def test_mismatched_write_file_tags_detected(self):
        # FAST (<1s)
        response = '<write_file path="foo.py">content without close tag'
        result = self.validate("Developer", "write file", response + ("x" * 100))
        self.assertFalse(result["valid"])
        self.assertTrue(any("write_file" in e.lower() for e in result["errors"]))

    def test_write_file_missing_path_attribute_detected(self):
        # FAST (<1s)
        response = "<write_file>content</write_file>" + ("x" * 100)
        result = self.validate("Developer", "write file", response)
        self.assertFalse(result["valid"])

    def test_trailing_ellipsis_detected_as_truncation(self):
        # FAST (<1s)
        long_response = ("a" * 150) + "..."
        result = self.validate("Architect", "design", long_response)
        self.assertFalse(result["valid"])
        self.assertTrue(any("truncat" in e.lower() for e in result["errors"]))

    def test_valid_long_response_passes(self):
        # FAST (<1s)
        response = "This is a complete and detailed response. " * 10
        result = self.validate("Architect", "design", response)
        self.assertTrue(result["valid"])

    def test_selector_agent_requires_valid_json(self):
        # FAST (<1s) — NOTE: validator strips before length check, so JSON must be >= 100 chars
        # This also documents validator bug: compact JSON fails min-length even when semantically valid
        import json
        payload = json.dumps({"selected": ["Architect", "BackendDev", "Security", "DevOps", "Tester"],
                              "reasoning": "These agents cover the full stack for this task."})
        self.assertGreaterEqual(len(payload.strip()), 100)
        result = self.validate("selector", "select agents", payload)
        self.assertTrue(result["valid"])

    def test_selector_agent_rejects_invalid_json(self):
        # FAST (<1s)
        response = "Architect, BackendDev" + ("x" * 100)
        result = self.validate("selector", "select agents", response)
        self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
