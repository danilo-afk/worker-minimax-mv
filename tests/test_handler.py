import json
import unittest
from pathlib import Path

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
                "duration_seconds": 30,
            }
        )

        self.assertNotIn("55", workflow)
        self.assertEqual(workflow["45"]["inputs"]["caption"], "Structured caption")
        self.assertEqual(workflow["45"]["inputs"]["lyrics"], "[Intro]\nLyrics\n[Outro]")

    def test_rejects_duration_outside_model_limits(self):
        with self.assertRaisesRegex(handler.WorkerError, "duration_seconds"):
            handler.build_workflow({"idea": "test", "duration_seconds": 10})

    def test_accepts_platform_prompt_as_idea(self):
        workflow, _ = handler.build_workflow({"prompt": "A cinematic synth-pop anthem"})

        self.assertEqual(workflow["55"]["inputs"]["idea"], "A cinematic synth-pop anthem")

    def test_all_links_point_to_existing_nodes(self):
        workflow, _ = handler.build_workflow({"idea": "test", "duration_seconds": 30})

        for node in workflow.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], workflow)


if __name__ == "__main__":
    unittest.main()
