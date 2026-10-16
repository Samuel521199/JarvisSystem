"""Offline diagnostics boundary tests: no vault, microphone or real HTTP access."""
from __future__ import annotations

from contextlib import asynccontextmanager, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "adapters" / "models" / "provider-native"))

import httpx
from jarvis_models import gateway


def load_tool(name):
    spec = importlib.util.spec_from_file_location("jarvis_test_" + name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jarvis-diagnostics-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def wav(self, name, rate, channels, frames):
        path = self.base / name
        # Two-channel fixtures have a known average, so resampling is verified
        # as well as acceptance without loading any speech model.
        frame = struct.pack("<h", 8192) if channels == 1 else struct.pack("<hh", 16384, 0)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(frame * frames)
        return path

    def test_fresh_model_status_creates_no_directory_or_database(self):
        model_probe = load_tool("model_probe")
        data_dir = self.base / "not-created" / "data"
        output = io.StringIO()
        arguments = ["model_probe.py", "--status", "--data-dir", str(data_dir)]
        with patch.object(sys, "argv", arguments), redirect_stdout(output), \
             patch.object(model_probe, "read_config", return_value={"default_provider": "local"}), \
             patch.object(model_probe, "load", return_value={}) as vault_load, \
             patch("jarvis_models.vault.load", side_effect=AssertionError("Real vault access forbidden")), \
             patch.object(model_probe, "ProbeJournal", side_effect=AssertionError("Status created a journal")) as journal, \
             patch.object(model_probe, "probe", side_effect=AssertionError("Status dispatched a model")) as probe:
            code = model_probe.main()
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["probe_calls"], {})
        vault_load.assert_called_once_with()
        journal.assert_not_called()
        probe.assert_not_called()
        self.assertFalse(data_dir.parent.exists())
        self.assertEqual(list(self.base.iterdir()), [])

    def test_pcm16_over_fifteen_seconds_is_rejected_before_inference(self):
        speech_probe = load_tool("speech_probe")
        for rate, channels in ((8000, 1), (16000, 1), (48000, 2)):
            with self.subTest(rate=rate, channels=channels):
                path = self.wav(f"too-long-{rate}-{channels}.wav", rate, channels, rate * 15 + 1)
                self.assertLess(path.stat().st_size, 12_000_000)
                with self.assertRaisesRegex(ValueError, "at most 15 seconds"):
                    speech_probe.samples_16k(path)

    def test_short_pcm16_is_accepted_and_normalized_to_sixteen_khz(self):
        import numpy as np
        speech_probe = load_tool("speech_probe")
        for rate, channels in ((8000, 2), (16000, 1), (48000, 2)):
            with self.subTest(rate=rate, channels=channels):
                frames = rate * 15 - 1
                path = self.wav(f"short-{rate}-{channels}.wav", rate, channels, frames)
                samples = speech_probe.samples_16k(path)
                self.assertEqual(samples.shape, (round(frames * 16000 / rate),))
                self.assertEqual(samples.dtype, np.float32)
                self.assertTrue(np.allclose(samples, 0.25))

    def test_exact_fifteen_second_boundary_is_accepted(self):
        speech_probe = load_tool("speech_probe")
        path = self.wav("exact-boundary.wav", 16000, 1, 16000 * 15)
        self.assertEqual(len(speech_probe.samples_16k(path)), 240000)

    def test_local_probe_disables_proxy_environment_in_default_client(self):
        requests = []
        constructors = []

        class MemoryOnlyClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                requests.append((method, url, kwargs))
                response = httpx.Response(200, request=httpx.Request(method, url),
                    json={"choices": [{"message": {"content": "LOCAL_TEST_OK"}}]})
                try:
                    yield response
                finally:
                    await response.aclose()

        def make_client(*args, **kwargs):
            constructors.append((args, kwargs))
            # This double cannot open a socket even if the production flag regresses.
            return MemoryOnlyClient()

        config = {"default_provider": "local", "max_prompt_bytes": 128, "max_output_tokens": 16,
                  "providers": {"local": {"model": "test-local",
                      "endpoint": "http://127.0.0.1:18180/v1/chat/completions"}}}
        forbidden_credentials = Mock(side_effect=AssertionError("Local probe read credentials"))
        proxy_environment = {"HTTP_PROXY": "http://proxy.invalid:9", "HTTPS_PROXY": "http://proxy.invalid:9",
                             "ALL_PROXY": "http://proxy.invalid:9", "NO_PROXY": ""}
        with patch.dict(os.environ, proxy_environment), \
             patch.object(gateway.httpx, "AsyncClient", side_effect=make_client) as factory:
            result = gateway.probe(config, "local", "test", self.base / "probe-data", lambda: None,
                                   credentials_loader=forbidden_credentials)
        self.assertEqual(result["status"], "SUCCEEDED", result)
        self.assertEqual(result["text"], "LOCAL_TEST_OK")
        factory.assert_called_once()
        self.assertIs(constructors[0][1].get("trust_env"), False)
        self.assertIs(constructors[0][1].get("follow_redirects"), False)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][:2], ("POST", "http://127.0.0.1:18180/v1/chat/completions"))
        self.assertEqual(requests[0][2]["headers"], {})
        forbidden_credentials.assert_not_called()


if __name__ == "__main__":
    unittest.main()
