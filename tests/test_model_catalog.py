"""Model upgrades must change parameters without changing credentials or endpoints."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/models/provider-native'), str(ROOT / 'runtime/node-host')]
from jarvis_models.catalog import public_models, resolve_settings, select_model, validate_catalog
from jarvis_models.gateway import build_request, read_config
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService


class CatalogTests(unittest.TestCase):
    def test_reasoning_options_match_model_and_native_wire_parameters(self):
        cases = [('openai', 'gpt-6-astra', 'medium', 'reasoning_effort', 'medium'),
                 ('openai', 'gpt-6-luna', 'high', 'reasoning_effort', 'high'),
                 ('vertex', 'gemini-4-argon', 'high', 'thinking_level', 'HIGH'),
                 ('vertex', 'gemini-3.1-flash-lite', 'minimal', 'thinking_level', 'MINIMAL'),
                 ('bailian', 'qwen3.8-max', 'on', 'enable_thinking', True),
                 ('xai', 'grok-4.7', 'xhigh', 'reasoning_effort', 'xhigh')]
        original = deepcopy(self.config)
        for provider, model, level, parameter, value in cases:
            with self.subTest(model=model):
                selected = select_model(self.config, provider, model, level)
                settings = resolve_settings(selected, provider)
                self.assertEqual(settings[parameter], value)
                with patch('jarvis_models.gateway.vertex_auth', return_value=('fake-token', 'test-project')):
                    _, _, body = build_request(provider, settings, 'test', 200, {**self.creds, 'vertex': {'service_account': {}}})
                wire = body['reasoning']['effort'] if provider == 'openai' else body['generationConfig']['thinkingConfig']['thinkingLevel'] if provider == 'vertex' else body[parameter]
                self.assertEqual(wire, value)
        self.assertEqual(self.config, original)

    def test_invalid_per_model_reasoning_never_calls_gateway(self):
        cases = [('openai', 'gpt-6-astra', 'none'), ('vertex', 'gemini-4-argon', 'minimal'), ('vertex', 'gemini-3.1-pro-preview', 'minimal'),
                 ('bailian', 'qwen3.8-max', 'high'), ('local', 'qwen3-0.6b', 'on'),
                 ('xai', 'grok-4-1-fast-non-reasoning', 'low'), ('auto', None, 'high')]
        with tempfile.TemporaryDirectory() as temporary:
            core = CoreService(Path(temporary) / 'data'); core.initialize()
            with patch('jarvis_core.chat.gateway.probe') as probe:
                for provider, model, reasoning in cases:
                    result = ChatService(core).reply('test', provider=provider, model=model, reasoning=reasoning)
                    self.assertEqual(result['error_category'], 'invalid_request')
                probe.assert_not_called()

    def test_concurrent_reasoning_does_not_leak_between_requests(self):
        original = deepcopy(self.config)
        def choose(level):
            return resolve_settings(select_model(self.config, 'openai', 'gpt-6-astra', level), 'openai')['reasoning_effort']
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(choose, ['low', 'high', 'max'] * 5)), ['low', 'high', 'max'] * 5)
        self.assertEqual(self.config, original)

    def test_reasoning_metadata_is_safe_and_default_is_in_supported_levels(self):
        for item in public_models(self.config):
            if item['reasoning_levels']:
                self.assertIn(item['reasoning_default'], item['reasoning_levels'])
        for levels in (['on'], ['low', 'low'], ['ultra'], ['none'], 'high', [False], [{}]):
            candidate = deepcopy(self.config)
            candidate['providers']['openai']['models']['gpt-6-astra']['reasoning_levels'] = levels
            with self.assertRaises(ValueError):
                validate_catalog(candidate)

    def test_chat_returns_effective_reasoning_without_changing_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = CoreService(Path(temporary) / 'data'); core.initialize()
            levels = []
            def success(config, provider, *args, **kwargs):
                levels.append(resolve_settings(config, provider)['enable_thinking'])
                return {'status': 'SUCCEEDED', 'text': 'ok'}
            chat = ChatService(core)
            with patch('jarvis_core.chat.gateway.probe', side_effect=success):
                self.assertEqual(chat.reply('test', provider='bailian', model='qwen3.8-max', reasoning='on')['reasoning'], 'on')
                self.assertEqual(chat.reply('test', provider='bailian', model='qwen3.8-max')['reasoning'], 'off')
            self.assertEqual(levels, [True, False])

    def setUp(self):
        self.config = read_config(ROOT / 'config/model-profiles/providers.json')
        self.creds = {p: {'api_key': 'mock-only'} for p in ('openai', 'bailian', 'xai')}

    def test_modern_openai_models_use_compatible_effort_and_responses(self):
        for model, effort in [('gpt-6-astra', 'low'), ('gpt-6.1-sol', 'low'), ('gpt-6-sol', 'none'), ('gpt-6-luna', 'none')]:
            with self.subTest(model=model):
                settings = resolve_settings(self.config, 'openai', model)
                url, _, body = build_request('openai', settings, 'test', 20, self.creds)
                self.assertEqual(url, 'https://api.openai.com/v1/responses')
                self.assertEqual(body['model'], model)
                self.assertEqual(body['reasoning']['effort'], effort)
                self.assertFalse(body['store'])
                self.assertNotIn('temperature', body)
                self.assertNotIn('tools', body)

    def test_new_gemini_omits_removed_parameters(self):
        creds = {'vertex': {'service_account': {}}}
        for model, level in [('gemini-3.8-flash', 'LOW'), ('gemini-4-argon', 'LOW'), ('gemini-3.1-flash-lite', 'MINIMAL'), ('gemini-3.1-pro-preview', 'LOW'), ('gemini-3.5-flash-lite', 'MINIMAL')]:
            with self.subTest(model=model), patch('jarvis_models.gateway.vertex_auth', return_value=('fake-token', 'test-project')):
                _, _, body = build_request('vertex', resolve_settings(self.config, 'vertex', model), 'test', 20, creds)
                generation = body['generationConfig']
                self.assertEqual(generation['thinkingConfig']['thinkingLevel'], level)
                self.assertNotIn('candidateCount', generation)
                self.assertNotIn('temperature', generation)

    def test_xai_and_qwen_parameter_profiles(self):
        _, _, grok = build_request('xai', resolve_settings(self.config, 'xai', 'grok-4.7'), 'test', 20, self.creds)
        self.assertEqual(grok['reasoning_effort'], 'low')
        _, _, old = build_request('xai', resolve_settings(self.config, 'xai', 'grok-4-1-fast-non-reasoning'), 'test', 20, self.creds)
        self.assertNotIn('reasoning_effort', old)
        _, _, qwen = build_request('bailian', resolve_settings(self.config, 'bailian', 'qwen3.8-max'), 'test', 20, self.creds)
        self.assertFalse(qwen['enable_thinking'])

    def test_selection_is_request_local_even_concurrently(self):
        original = deepcopy(self.config)
        def select(model):
            return resolve_settings(select_model(self.config, 'openai', model), 'openai')['model']
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(list(pool.map(select, ['gpt-6-astra', 'gpt-6-luna'])), ['gpt-6-astra', 'gpt-6-luna'])
        self.assertEqual(self.config, original)

    def test_unknown_or_other_provider_model_cannot_be_selected(self):
        for model in ('qwen3.8-max', 'https://example.com', 'gpt-invented', ['gpt-6-astra']):
            with self.subTest(model=model), self.assertRaises(ValueError):
                select_model(self.config, 'openai', model)

    def test_profile_cannot_override_transport_or_credentials(self):
        for field in ('endpoint', 'api_key', 'headers', 'tools'):
            candidate = deepcopy(self.config)
            candidate['providers']['openai']['models']['gpt-6-luna']['parameters'][field] = 'forbidden'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_catalog(candidate)

    def test_bad_limits_and_missing_default_rejected(self):
        for change in (lambda c: c['providers']['local']['models']['qwen3-0.6b']['parameters'].update(max_output_tokens=1000),
                       lambda c: c['providers']['openai']['models'].pop('gpt-6-luna')):
            candidate = deepcopy(self.config); change(candidate)
            with self.assertRaises(ValueError):
                validate_catalog(candidate)

    def test_old_single_model_configs_still_resolve(self):
        for settings in self.config['providers'].values():
            settings.pop('models')
        validate_catalog(self.config)
        self.assertEqual(len(public_models(self.config)), 5)
        self.assertEqual(resolve_settings(self.config, 'local')['endpoint'], 'http://127.0.0.1:18180/v1/chat/completions')

    def test_chat_rejects_unknown_model_before_any_provider_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = CoreService(Path(temporary) / 'data'); core.initialize()
            chat = ChatService(core)
            with patch('jarvis_core.chat.gateway.probe') as probe:
                for provider, model in [('auto', 'gpt-6-astra'), ('openai', 'not-registered')]:
                    result = chat.reply('test', provider=provider, model=model)
                    self.assertEqual(result['error_category'], 'invalid_request')
                probe.assert_not_called()

    def test_selected_model_is_passed_and_does_not_change_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = CoreService(Path(temporary) / 'data'); core.initialize()
            chat = ChatService(core)
            def success(config, provider, *args, **kwargs):
                return {'status': 'SUCCEEDED', 'provider': provider, 'model': config['providers'][provider]['model'], 'text': 'ok'}
            with patch('jarvis_core.chat.gateway.probe', side_effect=success):
                self.assertEqual(chat.reply('test', provider='openai', model='gpt-6-astra')['model'], 'gpt-6-astra')
                self.assertEqual(chat.reply('test', provider='openai')['model'], 'gpt-6-luna')
                self.assertEqual(len(chat.models()['models']), 17)


if __name__ == '__main__':
    unittest.main()
