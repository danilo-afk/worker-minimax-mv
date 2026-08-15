import json
import unittest
from pathlib import Path
from unittest.mock import patch

import handler


class BuildWorkflowTests(unittest.TestCase):
    def test_builds_author_recommended_planner_workflow(self):
        payload = json.loads(Path("test_input.json").read_text(encoding="utf-8"))["input"]

        workflow, values = handler.build_workflow(payload)

        self.assertEqual(workflow["55"]["inputs"]["duration_seconds"], 60)
        self.assertEqual(workflow["45"]["inputs"]["max_duration"], 90)
        self.assertEqual(workflow["45"]["inputs"]["seed"], 3877326292)
        self.assertEqual(workflow["50"]["inputs"]["seed"], 3877326292)
        self.assertEqual(workflow["50"]["inputs"]["steps"], 30)
        self.assertEqual(workflow["50"]["inputs"]["cfg"], 1.7)
        self.assertEqual(workflow["50"]["inputs"]["sampler_name"], "euler")
        self.assertFalse(workflow["55"]["inputs"]["keep_model_loaded"])
        self.assertEqual(values["max_duration"], 90)

    def test_manual_caption_and_lyrics_bypass_planner(self):
        workflow, _ = handler.build_workflow(
            {
                "caption": "Structured caption",
                "lyrics": "[Intro]\nLyrics\n[Outro]",
                "duration_seconds": 8,
            }
        )

        self.assertNotIn("55", workflow)
        self.assertEqual(workflow["45"]["inputs"]["caption"], "Structured caption")
        self.assertEqual(workflow["45"]["inputs"]["lyrics"], "[Intro]\nLyrics\n[Outro]")
        self.assertEqual(workflow["45"]["inputs"]["max_duration"], 12)

    def test_rejects_duration_outside_model_limits(self):
        with self.assertRaisesRegex(handler.WorkerError, "duration_seconds"):
            handler.build_workflow({"idea": "test", "duration_seconds": 0.03})

        with self.assertRaisesRegex(handler.WorkerError, "duration_seconds"):
            handler.build_workflow({"idea": "test", "duration_seconds": 360.01})

    def test_accepts_short_and_long_requested_durations(self):
        for duration in (8, 20):
            with self.subTest(duration=duration):
                workflow, values = handler.build_workflow(
                    {"idea": "test", "duration_seconds": duration}
                )

                self.assertEqual(workflow["55"]["inputs"]["duration_seconds"], duration)
                self.assertEqual(values["duration"], duration)

    def test_accepts_platform_prompt_as_idea(self):
        workflow, _ = handler.build_workflow({"prompt": "A cinematic synth-pop anthem"})

        self.assertEqual(workflow["55"]["inputs"]["idea"], "A cinematic synth-pop anthem")

    def test_all_links_point_to_existing_nodes(self):
        workflow, _ = handler.build_workflow({"idea": "test", "duration_seconds": 30})

        for node in workflow.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], workflow)

    def test_handler_propagates_errors_to_runpod(self):
        with self.assertRaisesRegex(handler.WorkerError, "input deve ser um objeto"):
            handler.handler({"input": None})

    @patch("handler.parse_result", return_value={"audio": "ok"})
    @patch("handler.wait_for_history", return_value={"outputs": {}})
    @patch("handler.queue_workflow", return_value="prompt-1")
    @patch("handler.wait_for_comfyui")
    @patch("handler.bootstrap_models")
    def test_handler_bootstraps_models_inside_first_job(
        self,
        bootstrap,
        wait_for_comfyui,
        queue_workflow,
        wait_for_history,
        parse_result,
    ):
        result = handler.handler({"input": {"idea": "test", "duration_seconds": 30}})

        bootstrap.assert_called_once_with()
        wait_for_comfyui.assert_called_once_with()
        queue_workflow.assert_called_once()
        wait_for_history.assert_called_once_with("prompt-1")
        parse_result.assert_called_once()
        self.assertEqual(result, {"audio": "ok"})


if __name__ == "__main__":
    unittest.main()
