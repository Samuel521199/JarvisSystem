"""A voice transport may narrow chat authority, never add capabilities."""


def validate(value):
    if value is not None and value != 'conversation':
        raise ValueError('invalid voice mode')
    return value == 'conversation'


def effect_response():
    return {'status': 'SUCCEEDED', 'provider': 'builtin', 'model': 'voice-conversation-v1',
            'text': '这句话涉及个人资料指令。连续语音只用于交流；请检查转写后用文字发送，或在记忆与交流设置中修改。',
            'voice_mode': 'conversation', 'outcome_uncertain': False}
