import base64
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

import handler


IMAGE = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\npreview").decode()
AUDIO = "data:audio/mpeg;base64," + base64.b64encode(b"ID3preview").decode()
VIDEO = "data:video/mp4;base64," + base64.b64encode(b"\x00\x00\x00\x18ftypmp42preview").decode()


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

    def test_accepts_aspect_and_trained_duration_limit(self):
        values = handler.validate_input(payload(aspect="9:16"))
        self.assertLess(values["width"], values["height"])
        extended = handler.validate_input(payload(duration_seconds=15))
        self.assertEqual(extended["frame_count"], 362)
        for duration in (4.99, 15.01):
            with self.subTest(duration=duration), self.assertRaisesRegex(handler.WorkerError, "duration_seconds"):
                handler.validate_input(payload(duration_seconds=duration))

    def test_modo_reference_entrega_video_mudo_para_muxar_a_trilha(self):
        """Clipe musical precisa da trilha EXATA: o video sai mudo e o worker muxa o audio enviado."""
        values = handler.validate_input(payload())
        workflow = handler.build_workflow(values, "ref.png", "ref.mp3")

        self.assertEqual(values["audio_mode"], "reference")
        self.assertNotIn("audio", workflow["17"]["inputs"])

    def test_modo_generated_decodifica_o_audio_que_o_modelo_criou(self):
        """O latente do sampler e conjunto: decodificar com a VAE de audio devolve fala e ambiencia."""
        values = handler.validate_input(payload(audio_mode="generated"))
        workflow = handler.build_workflow(values, "ref.png", "ref.mp3")

        self.assertEqual(workflow["16"]["class_type"], "VAEDecodeAudio")
        self.assertEqual(workflow["16"]["inputs"]["samples"], ["14", 0])
        self.assertEqual(workflow["16"]["inputs"]["vae"], ["6", 0])
        self.assertEqual(workflow["17"]["inputs"]["audio"], ["16", 0])

    def test_audio_mode_invalido_e_recusado(self):
        with self.assertRaisesRegex(handler.WorkerError, "audio_mode"):
            handler.validate_input(payload(audio_mode="qualquer"))

    def test_ref_videos_enter_as_frames_keeping_input_audio(self):
        values = handler.validate_input(payload(ref_videos=[VIDEO, VIDEO]))
        workflow = handler.build_workflow(values, "ref.png", "ref.mp3", ["t/ref_video_0.mp4", "t/ref_video_1.mp4"])

        self.assertEqual(len(values["ref_videos"]), 2)
        self.assertEqual(workflow["100"]["class_type"], "LoadVideo")
        self.assertEqual(workflow["100"]["inputs"]["file"], "t/ref_video_0.mp4")
        self.assertEqual(workflow["101"]["class_type"], "GetVideoComponents")
        self.assertEqual(workflow["9"]["inputs"]["ref_videos.ref_video_0"], ["101", 0])
        self.assertEqual(workflow["9"]["inputs"]["ref_videos.ref_video_1"], ["103", 0])
        # a trilha dos vídeos de referência não entra: o áudio segue sendo o do input
        self.assertNotIn("ref_video_audios.ref_video_audio_0", workflow["9"]["inputs"])
        self.assertEqual(workflow["9"]["inputs"]["ref_audios.ref_audio_0"], ["8", 0])

    def test_ref_videos_are_optional_and_bounded(self):
        self.assertEqual(handler.validate_input(payload())["ref_videos"], [])
        self.assertNotIn("100", handler.build_workflow(handler.validate_input(payload()), "ref.png", "ref.mp3"))
        with self.assertRaisesRegex(handler.WorkerError, "no máximo 3"):
            handler.validate_input(payload(ref_videos=[VIDEO] * 4))
        with self.assertRaisesRegex(handler.WorkerError, "MP4 ou WebM"):
            handler.validate_input(payload(ref_videos=[IMAGE]))

    def test_extra_ref_images_become_picture_2_and_3(self):
        values = handler.validate_input(payload(ref_images=[IMAGE, IMAGE]))
        workflow = handler.build_workflow(
            values, "ref_0.png", "ref.mp3", None, ["t/ref_0.png", "t/ref_1.png", "t/ref_2.png"])

        self.assertEqual(len(values["ref_images"]), 3)
        self.assertEqual(workflow["7"]["inputs"]["image"], "ref_0.png")
        self.assertEqual(workflow["9"]["inputs"]["ref_images.ref_image_0"], ["7", 0])
        self.assertEqual(workflow["201"]["inputs"]["image"], "t/ref_1.png")
        self.assertEqual(workflow["9"]["inputs"]["ref_images.ref_image_1"], ["201", 0])
        self.assertEqual(workflow["9"]["inputs"]["ref_images.ref_image_2"], ["202", 0])

    def test_single_image_stays_the_default_and_limit_is_enforced(self):
        values = handler.validate_input(payload())
        self.assertEqual(len(values["ref_images"]), 1)
        workflow = handler.build_workflow(values, "ref.png", "ref.mp3", None, ["t/ref_0.png"])
        self.assertNotIn("201", workflow)
        self.assertNotIn("ref_images.ref_image_1", workflow["9"]["inputs"])
        with self.assertRaisesRegex(handler.WorkerError, "no máximo 3"):
            handler.validate_input(payload(ref_images=[IMAGE] * 3))

    def test_ref_image_size_defaults_to_match_and_accepts_max(self):
        default = handler.validate_input(payload())
        self.assertEqual(default["ref_image_size"], "match")
        self.assertEqual(handler.build_workflow(default, "r.png", "r.mp3")["9"]["inputs"]["ref_image_size"], "match")

        maximo = handler.validate_input(payload(ref_image_size="max"))
        self.assertEqual(handler.build_workflow(maximo, "r.png", "r.mp3")["9"]["inputs"]["ref_image_size"], "max")

        with self.assertRaisesRegex(handler.WorkerError, "ref_image_size"):
            handler.validate_input(payload(ref_image_size="gigante"))

    def test_audio_e_ajustado_a_duracao_do_clipe_antes_de_gerar(self):
        """O nó não trunca ref_audios: o corte tem que acontecer antes do H3, não só no mux."""
        values = handler.validate_input(payload(duration_seconds=8))
        self.assertEqual(values["generated_duration"], 192 / 24)

        chamadas = []

        def falso_run(cmd, **kwargs):
            chamadas.append(cmd)
            if cmd[0] == "ffprobe":
                return SimpleNamespace(stdout="20.0\n")
            Path(cmd[-1]).write_bytes(b"RIFF\x00\x00\x00\x00WAVEcortado")
            return SimpleNamespace(stdout="")

        with patch.object(handler.subprocess, "run", side_effect=falso_run):
            handler._fit_audio_to_clip(values)

        corte = [c for c in chamadas if c[0] == "ffmpeg"]
        self.assertTrue(corte, "deveria ter cortado o áudio de 20s para 8s")
        self.assertIn("-t", corte[0])
        self.assertEqual(corte[0][corte[0].index("-t") + 1], "8.000000")
        self.assertEqual(values["audio_suffix"], ".wav")

    def test_audio_curto_demais_e_recusado(self):
        values = handler.validate_input(payload(duration_seconds=8))

        def falso_run(cmd, **kwargs):
            return SimpleNamespace(stdout="3.0\n")

        with patch.object(handler.subprocess, "run", side_effect=falso_run):
            with self.assertRaisesRegex(handler.WorkerError, "3.000s e o clipe precisa de 8.000s"):
                handler._fit_audio_to_clip(values)

    def test_limite_de_video_cabe_no_payload_do_runpod(self):
        self.assertLessEqual(handler.MAX_VIDEO_BYTES * handler.MAX_REF_VIDEOS, handler.MAX_PAYLOAD_BYTES * 3)
        self.assertLess(handler.MAX_VIDEO_BYTES, handler.MAX_PAYLOAD_BYTES)

    def test_anchor_image_ancora_o_primeiro_frame_via_addguide(self):
        """Continuidade real entre blocos: o clipe COMECA no frame ancorado, em vez de
        apenas se inspirar no anterior (que era o que fazia a pose contaminar a cena)."""
        values = handler.validate_input(payload(anchor_image=IMAGE))
        self.assertIsNotNone(values["anchor_image"])
        self.assertEqual(values["anchor_frame_idx"], 0)

        workflow = handler.build_workflow(values, "ref.png", "ref.mp3", None, ["t/r0.png"], "t/anchor.png")
        self.assertEqual(workflow["300"]["class_type"], "LoadImage")
        self.assertEqual(workflow["300"]["inputs"]["image"], "t/anchor.png")
        self.assertEqual(workflow["301"]["class_type"], "MiniMaxH3AddGuide")
        self.assertEqual(workflow["301"]["inputs"]["frame_idx"], 0)
        self.assertEqual(workflow["301"]["inputs"]["image"], ["300", 0])
        self.assertEqual(workflow["301"]["inputs"]["latent"], ["9", 1])
        # o guider passa a consumir o conditioning ancorado, nao o cru
        self.assertEqual(workflow["13"]["inputs"]["conditioning"], ["301", 0])

    def test_sem_ancora_o_grafo_fica_igual_ao_de_antes(self):
        values = handler.validate_input(payload())
        self.assertIsNone(values["anchor_image"])
        workflow = handler.build_workflow(values, "ref.png", "ref.mp3")
        self.assertNotIn("300", workflow)
        self.assertNotIn("301", workflow)
        self.assertEqual(workflow["13"]["inputs"]["conditioning"], ["9", 0])

    def test_anchor_frame_idx_e_validado_contra_a_duracao(self):
        values = handler.validate_input(payload(anchor_image=IMAGE, anchor_frame_idx=-1))
        self.assertEqual(values["anchor_frame_idx"], -1)  # negativo conta do fim
        with self.assertRaisesRegex(handler.WorkerError, "anchor_frame_idx"):
            handler.validate_input(payload(anchor_image=IMAGE, anchor_frame_idx=999))

    def test_manifest_uses_only_official_pinned_revisions(self):
        manifest_path = Path(__file__).parents[1] / "src" / "model_manifest.json"
        models = json.loads(manifest_path.read_text(encoding="utf-8"))["models"]
        self.assertEqual({model["repo_id"] for model in models}, {"Comfy-Org/MiniMax-H3", "lightx2v/Minimax-h3-Turbo"})
        self.assertEqual(len(models), 5)
        self.assertNotIn("nikdevs", manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("drbaph", manifest_path.read_text(encoding="utf-8"))

    @patch("handler.mux_original_audio", return_value=(b"muxed-mp4", {"format": {"duration": "8.0"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}))
    @patch("handler.fetch_output_file", return_value=(b"mp4", None))
    def test_returns_mp4_with_original_audio_and_metadata(self, fetch_output, mux_original_audio):
        values = handler.validate_input(payload())
        result = handler.parse_result({"outputs": {"18": {"video": [{"filename": "preview.mp4"}]}}}, values)

        self.assertEqual(result["video"], base64.b64encode(b"muxed-mp4").decode())
        self.assertTrue(result["has_video"])
        self.assertTrue(result["has_audio"])
        self.assertEqual(result["duration_seconds"], 8.0)
        self.assertEqual(result["audio_source"], "input")
        mux_original_audio.assert_called_once_with(b"mp4", None, values)


if __name__ == "__main__":
    unittest.main()
