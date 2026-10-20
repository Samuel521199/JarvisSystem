"""Fixed local ASR entry point. Read PCM via pipe, emit text, then exit."""
import base64
import hashlib
import json
from pathlib import Path
import sys


def main():
    packet = json.loads(sys.stdin.buffer.read(900001))
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root/'runtime/node-host'))
    from jarvis_core import policy
    manifest = json.loads((root/'config/model-profiles/local-candidates.json').read_text(encoding='utf-8'))
    base = Path(packet['model_root'] or manifest['default_root'])
    paths = {}
    for item in manifest['files']:
        if not ((item['component'] == 'sensevoice-int8' and item['path'].endswith(('model.int8.onnx', 'tokens.txt')))
                or item['component'] == 'silero-vad' and item['path'].endswith('silero_vad.onnx')):
            continue
        path = policy.safe_path(base/item['path'], directory=False)
        if path.stat().st_size != item['size_bytes'] or path.stat().st_nlink != 1:
            raise ValueError('Model size mismatch')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                raise ValueError('Model digest mismatch')
        paths[path.name] = str(path)
    import numpy as np
    import sherpa_onnx
    if sherpa_onnx.__version__ != '1.13.8':
        raise ValueError('Unverified speech runtime')
    pcm = base64.b64decode(packet['pcm'], validate=True)
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
    # Energy detects candidate segments in the browser, not human speech.
    # Run the small neural gate before loading ASR; never infer from silence/noise alone.
    text, speech_seconds = '', 0.
    if float(np.sqrt(np.mean(samples**2))) >= .002:
        config = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(model=paths['silero_vad.onnx']),
            sample_rate=16000, num_threads=1, provider='cpu')
        vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=21)
        window = config.silero_vad.window_size
        for offset in range(0, len(samples), window):
            block = samples[offset:offset+window]
            vad.accept_waveform(np.pad(block, (0, window-len(block))))
        vad.flush()
        while not vad.empty():
            speech_seconds += len(vad.front.samples)/16000
            vad.pop()
        del vad
    if speech_seconds >= .18:
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=paths['model.int8.onnx'], tokens=paths['tokens.txt'],
            language=packet['language'], use_itn=True, num_threads=2, provider='cpu')
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        text = stream.result.text.strip()
    print(json.dumps(dict(text=text, backend='sensevoice-int8', vad='silero',
                          speech_seconds=round(speech_seconds, 3)), ensure_ascii=False))


if __name__ == '__main__':
    main()
