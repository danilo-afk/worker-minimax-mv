import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

import handler


IMAGE = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\npreview").decode()
AUDIO = "data:audio/mpeg;base64," + base64.b64encode(b"ID3preview").decode()


def payload(**overrides):
    value = {"image": IMAGE, "audio": AUDIO, "prompt": "Uma cantora em cena", "duration_seconds": 8, "seed": 42}
    value.update(overrides)
    return value


class H3WorkerTests(unittest.TestCase):
    def test_default_author_preset(self):
        values = handler.validate_input(payload())
        workflow = handler.build_workflow(values, "ref.png", "ref.mp3")

        self.assertEqual((values["width"], values["height"]), (864, 480))
        self.assertEqual(values["frame_count"], 192)
        self.assertEqual(workflow["2"]["inputs"]["strength_model"], 0.7)
        self.assertEqual(workflow["3"]["inputs"]["shift_video"], 12.0)
        self.assertEqual(workflow["3"]["inputs"]["shift_audio"], 6.0)
        self.assertEqual(workflow["10"]["inputs"]["steps"], 4)
        self.assertEqual(workflow["10"]["inputs"]["scheduler"], "beta")
        self.assertEqual(workflow["11"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(workflow["18"]["inputs"]["codec"], "auto")

    def test_core_only_graph_and_reference_inputs(self):
        values = handler.validate_input(payload())
        workflow = handler.build_workflow(values, "ref.png", "ref.mp3")
        node_types = {node["class_type"] for node in workflow.values()}

        self.assertFalse(any(term in node_type.lower() for term in ("seedvr", "ltx", "film") for node_type in node_types))
        self.assertEqual(workflow["9"]["inputs"]["ref_images.ref_image_0"], ["7", 0])
        self.assertEqual(workflow["9"]["inputs"]["ref_audios.ref_audio_0"], ["8", 0])
        self.assertEqual(workflow["18"]["class_type"], "SaveVideo")

    def test_accepts_aspect_and_rejects_duration_outside_preview(self):
        values = handler.validate_input(payload(aspect="9:16"))
        self.assertLess(values["width"], values["height"])
        for duration in (4.99, 10.01):
            with self.subTest(duration=duration), self.assertRaisesRegex(handler.WorkerError, "duration_seconds"):
                handler.validate_input(payload(duration_seconds=duration))

    def test_manifest_uses_only_official_pinned_revisions(self):
        manifest_path = Path(__file__).parents[1] / "src" / "model_manifest.json"
        models = json.loads(manifest_path.read_text(encoding="utf-8"))["models"]
        self.assertEqual({model["repo_id"] for model in models}, {"Comfy-Org/MiniMax-H3", "lightx2v/Minimax-h3-Turbo"})
        self.assertEqual(len(models), 5)
        self.assertNotIn("nikdevs", manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("drbaph", manifest_path.read_text(encoding="utf-8"))

    @patch("handler.probe_video", return_value={"format": {"duration": "8.0"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]})
    @patch("handler.fetch_output_file", return_value=(b"mp4", None))
    def test_returns_mp4_base64_and_metadata(self, fetch_output, probe_video):
        values = handler.validate_input(payload())
        result = handler.parse_result({"outputs": {"18": {"video": [{"filename": "preview.mp4"}]}}}, values)

        self.assertEqual(result["video"], base64.b64encode(b"mp4").decode())
        self.assertTrue(result["has_video"])
        self.assertTrue(result["has_audio"])
        self.assertEqual(result["duration_seconds"], 8.0)


if __name__ == "__main__":
    unittest.main()
