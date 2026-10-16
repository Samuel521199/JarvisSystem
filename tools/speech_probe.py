#!/usr/bin/env python3
"""File-only speech smoke test. Never opens a microphone or authenticates an owner."""
from pathlib import Path
import argparse
import gc
import json
import os
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime/node-host"))


def samples_16k(path):
    import numpy as np
    if path.stat().st_size > 12_000_000:
        raise ValueError("WAV exceeds input size limit")
    with wave.open(str(path), "rb") as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        if wav.getsampwidth() != 2 or channels not in (1, 2) or not 8000 <= rate <= 48000:
            raise ValueError("Expected PCM16 mono/stereo WAV at 8-48kHz")
        if not 0 < wav.getnframes() <= rate * 15:
            raise ValueError("Expected at most 15 seconds of audio per ASR segment")
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1)
    if rate != 16000:
        audio = np.interp(np.arange(round(len(audio) * 16000 / rate)) * rate / 16000,
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio


def verify_component_files(base, component_ids):
    from manage_models import load_manifest, target_path, verify_file
    catalog, files = load_manifest(ROOT / "config/model-profiles/local-candidates.json")
    entries = files.values() if isinstance(files, dict) else files
    for entry in entries:
        if entry["component"] in component_ids and not verify_file(target_path(base, entry["path"]), entry):
            raise ValueError("Missing or modified model artifact: " + entry["id"])


def selftest(base: Path, output: Path, guard, source_wav=None):
    import numpy as np
    import sherpa_onnx as sherpa
    guard()
    verify_component_files(base, {"sensevoice-int8", "vits-aishell3-low", "campplus-zh", "silero-vad"})
    output.mkdir(parents=True, exist_ok=True)
    timings = {}
    started = time.monotonic()
    tts_dir = base / "tts/vits-aishell3-low"
    config = sherpa.OfflineTtsConfig(model=sherpa.OfflineTtsModelConfig(
        vits=sherpa.OfflineTtsVitsModelConfig(model=str(tts_dir / "model.onnx"),
                lexicon=str(tts_dir / "lexicon.txt"), tokens=str(tts_dir / "tokens.txt")),
        num_threads=2, provider="cpu"),
        rule_fsts=",".join(str(tts_dir / name) for name in ["phone.fst", "date.fst", "number.fst"]))
    if not config.validate():
        raise ValueError("Invalid TTS model configuration")
    tts = sherpa.OfflineTts(config)
    guard()
    text = "你好，我是你的本地助手。现在正在测试语音识别和语音合成。"
    audio = tts.generate(text, sid=0, speed=1.0)
    guard()
    pcm = (np.clip(audio.samples, -1, 1) * 32767).astype("<i2")
    wav_path = output / "synthetic-speech-test.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(audio.sample_rate)
        wav.writeframes(pcm.tobytes())
    timings["tts_seconds_including_load"] = round(time.monotonic() - started, 3)
    report = {"synthetic_audio": str(wav_path), "tts_sample_rate": audio.sample_rate,
              "tts_duration_seconds": round(len(pcm) / audio.sample_rate, 3), "tts_prompt": text}
    del tts, audio, pcm
    gc.collect()
    guard()
    started = time.monotonic()
    stt_dir = base / "stt/sensevoice-small"
    recognizer = sherpa.OfflineRecognizer.from_sense_voice(
        model=str(stt_dir / "model.int8.onnx"), tokens=str(stt_dir / "tokens.txt"),
        language="zh", use_itn=True, num_threads=2, provider="cpu")
    test_paths = [("synthetic_transcript", wav_path),
                  ("publisher_fixture_transcript", stt_dir / "test_wavs/zh.wav")]
    if source_wav:
        test_paths.append(("provided_file_transcript", source_wav))
    for name, path in test_paths:
        guard()
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples_16k(path))
        recognizer.decode_stream(stream)
        report[name] = stream.result.text
    timings["asr_seconds_including_load"] = round(time.monotonic() - started, 3)
    del recognizer
    gc.collect()
    guard()
    started = time.monotonic()
    cfg = sherpa.SpeakerEmbeddingExtractorConfig(
        model=str(base / "speaker/campplus-zh/model.onnx"), num_threads=1, provider="cpu")
    extractor = sherpa.SpeakerEmbeddingExtractor(cfg)
    stream = extractor.create_stream()
    stream.accept_waveform(16000, samples_16k(wav_path))
    stream.input_finished()
    if not extractor.is_ready(stream):
        raise ValueError("Synthetic sample insufficient for embedding test")
    embedding = np.asarray(extractor.compute(stream))
    report["speaker_embedding_dimensions"] = int(embedding.size)
    report["speaker_embedding_finite"] = bool(np.all(np.isfinite(embedding)))
    report["speaker_embedding_valid"] = bool(embedding.ndim == 1 and embedding.size == 192
        and np.all(np.isfinite(embedding)) and np.linalg.norm(embedding) > 0)
    report["owner_enrolled"] = False
    report["voice_authentication_granted"] = False
    timings["speaker_seconds_including_load"] = round(time.monotonic() - started, 3)
    del extractor, embedding
    gc.collect()
    guard()
    vad_config = sherpa.VadModelConfig(silero_vad=sherpa.SileroVadModelConfig(
        model=str(base / "vad/silero/silero_vad.onnx")), sample_rate=16000, num_threads=1, provider="cpu")
    vad = sherpa.VoiceActivityDetector(vad_config, buffer_size_in_seconds=60)
    samples = samples_16k(wav_path)
    window = vad_config.silero_vad.window_size
    for offset in range(0, len(samples), window):
        guard()
        chunk = samples[offset:offset + window]
        if len(chunk) < window:
            chunk = np.pad(chunk, (0, window-len(chunk)))
        vad.accept_waveform(chunk)
    vad.flush()
    segments = 0
    while not vad.empty():
        segments += 1
        vad.pop()
    report["vad_segments"] = segments
    report["timings"] = timings
    report["status"] = "passed" if (report["synthetic_transcript"] and report["publisher_fixture_transcript"]
                         and report["speaker_embedding_valid"] and segments > 0
                         and (not source_wav or report.get("provided_file_transcript"))) else "failed"
    report["limits"] = "File-only smoke test; no microphone, speaker identity enrollment, spoof defense or voice quality benchmark."
    guard()
    (output / "speech-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=Path("H:/JarvisData/models"))
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ".")) / "Jarvis/data")
    parser.add_argument("--input-wav", type=Path, help="Optional explicit PCM16 file; never recorded automatically")
    args = parser.parse_args()
    from jarvis_core.service import CoreService
    try:
        core = CoreService(args.data_dir)
        report = selftest(args.model_root, args.data_dir / "diagnostics/speech", core.assert_running, args.input_wav)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "passed" else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
