"""Small, dependency-free contract shared by the host and isolated TTS worker."""
import base64
import binascii
import io
import wave

MAX_REFERENCE_BYTES = 3_000_000
EMOTIONS = {'neutral': '', 'happy': '请非常开心地说一句话。', 'sad': '请非常伤心地说一句话。',
            'angry': '请非常生气地说一句话。', 'soft': 'Please say a sentence in a very soft voice.',
            'slow': '请用尽可能慢地语速说一句话。', 'fast': '请用尽可能快地语速说一句话。'}


class SpeechError(ValueError):
    pass


def inference_yaml(original):
    """Derive only native inference nodes from the pinned, unmodified upstream YAML."""
    head = original.split('# gan related module\n', 1)[0]
    tokenizer = original.split('get_tokenizer:', 1)[1].split('\ntokenize:', 1)[0]
    features = original.split('feat_extractor:', 1)[1].split('\ncompute_fbank:', 1)[0]
    if len(head) < 3000 or len(tokenizer) < 50 or len(features) < 50:
        raise SpeechError('上游语音配置结构已变化。')
    return head + '\nget_tokenizer:' + tokenizer + '\nfeat_extractor:' + features + '\n'


def reference_info(data, maximum_seconds=15):
    if not isinstance(data, bytes) or not 44 <= len(data) <= MAX_REFERENCE_BYTES:
        raise SpeechError('参考音频需为不超过 3 MB 的 PCM16 WAV。')
    try:
        with wave.open(io.BytesIO(data)) as audio:
            rate, channels, frames = audio.getframerate(), audio.getnchannels(), audio.getnframes()
            if audio.getsampwidth() != 2 or channels not in (1, 2) or not 8000 <= rate <= 48000:
                raise SpeechError('参考音频需为 8–48kHz、单/双声道 PCM16 WAV。')
            if not rate <= frames <= rate * maximum_seconds:
                raise SpeechError('参考音频需为 1–15 秒。')
            if len(audio.readframes(frames)) != frames * channels * 2:
                raise SpeechError('参考音频数据不完整。')
            return {'seconds': frames / rate, 'sample_rate_hz': rate, 'channels': channels}
    except (wave.Error, EOFError) as exc:
        raise SpeechError('参考音频格式无效，请转换为 PCM16 WAV。') from exc


def validate_synthesis(payload):
    keys = {'action', 'text', 'mode', 'emotion', 'reference_audio', 'reference_text'}
    if not isinstance(payload, dict) or set(payload) - keys or payload.get('action') != 'synthesize':
        raise SpeechError('语音合成参数无效。')
    text = payload.get('text', '')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 300 or '\x00' in text:
        raise SpeechError('合成文字需为 1–300 字。')
    mode, emotion = payload.get('mode', 'instruct'), payload.get('emotion', 'neutral')
    if not isinstance(mode, str) or mode not in {'clone', 'instruct', 'cross_lingual'}:
        raise SpeechError('请选择克隆、情绪指令或跨语种模式。')
    if not isinstance(emotion, str) or emotion not in EMOTIONS:
        raise SpeechError('情绪选项无效。')
    if mode != 'instruct' and emotion != 'neutral':
        raise SpeechError('情绪选项需要使用情绪指令模式。')
    transcript = payload.get('reference_text', '')
    if not isinstance(transcript, str) or len(transcript) > 500 or '\x00' in transcript:
        raise SpeechError('参考音频文字过长或无效。')
    encoded = payload.get('reference_audio')
    data = None
    if encoded is not None:
        if not isinstance(encoded, str) or len(encoded) > 4_000_000:
            raise SpeechError('参考音频过大。')
        try: data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc: raise SpeechError('参考音频编码无效。') from exc
        reference_info(data)
        if mode == 'clone' and not transcript.strip(): raise SpeechError('克隆模式需要与参考录音一致的文字。')
    return {'text': text.strip(), 'mode': mode, 'emotion': emotion,
            'reference_text': transcript.strip(), 'reference_data': data}
