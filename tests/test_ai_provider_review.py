"""Isolated regressions: no Codex generation, paid model, or platform request."""
import base64
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import ai_provider as provider


class ProviderReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='provider review ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def finished(self, command, **kwargs):
        class Process:
            stdin = io.BytesIO()
            returncode = 0
            def poll(self): return 0
            def wait(self, **kwargs): return 0
        return Process()

    def test_command_is_read_only_no_shell_and_attaches_selected_images(self):
        command = provider.codex_command(Path('codex.exe'), self.root, self.root / 'schema',
            self.root / 'output', [{'path': str(self.root / 'selected.jpg')}], {})
        self.assertIn('--ignore-user-config', command)
        self.assertIn('--ephemeral', command)
        self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
        self.assertEqual(command[command.index('-a') + 1], 'never')
        for flag in ('shell_tool', 'unified_exec', 'apps', 'hooks', 'multi_agent'):
            self.assertIn(flag, command)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', command)

    def test_existing_output_cannot_be_returned_as_current_generation(self):
        (self.root / 'ai-result.json').write_text('{"old":true}', encoding='utf-8')
        with patch.object(provider, 'find_codex', return_value=Path('fake-codex.exe')), \
             patch.object(provider.subprocess, 'Popen', side_effect=self.finished):
            with self.assertRaises(ValueError):
                provider.run_codex('new request', {}, [], self.root)

    def test_api_rejects_non_image_video_bytes_before_any_request(self):
        video = self.root / 'selected.mp4'; video.write_bytes(b'fixture raw private video')
        response = {'choices': [{'message': {'content': '{"fixture":true}'}}]}
        with patch.object(provider, '_request_json', return_value=response) as request:
            with self.assertRaises(ValueError):
                provider.run_api('facts only', {}, [{'path': str(video), 'timestamp': 0.5}],
                                 {'api_key': 'synthetic', 'model': 'fixture', 'base_url': 'https://example.com/v1'})
            request.assert_not_called()

    def test_api_cancellation_before_start_reads_no_frames(self):
        with patch.object(provider, '_request_json') as request:
            with self.assertRaises(provider.GenerationCancelled):
                provider.run_api('fixture', {}, [{'path': 'not-a-file', 'timestamp': 0}], {}, cancel=lambda: True)
            request.assert_not_called()

    def test_post_exit_event_limit_still_enforced(self):
        def finished_with_big_log(command, **kwargs):
            kwargs['stdout'].write(b'x' * (12 * 1024 * 1024 + 1)); kwargs['stdout'].flush()
            output = Path(command[command.index('--output-last-message') + 1])
            output.write_text('{"fixture":true}', encoding='utf-8')
            return self.finished(command, **kwargs)
        with patch.object(provider, 'find_codex', return_value=Path('fake-codex.exe')), \
             patch.object(provider.subprocess, 'Popen', side_effect=finished_with_big_log):
            with self.assertRaises(ValueError):
                provider.run_codex('fixture', {}, [], self.root)

    def test_cancellation_can_interrupt_stdin_backpressure(self):
        entered = threading.Event(); release = threading.Event(); cancelled = threading.Event()
        class BlockedStdin:
            def write(self, data): entered.set(); release.wait(5); return len(data)
            def close(self): pass
        class Process:
            stdin = BlockedStdin()
            returncode = None
            alive = True
            def poll(self): return None if self.alive else -1
            def wait(self, **kwargs): return -1
        proc = Process()
        errors = []
        def stop_owned(process): process.alive = False
        def generate():
            try: provider.run_codex('x' * (1024 * 1024), {}, [], self.root, cancel=cancelled.is_set)
            except Exception as exc: errors.append(exc)
        with patch.object(provider, 'find_codex', return_value=Path('fake-codex.exe')), \
             patch.object(provider.subprocess, 'Popen', side_effect=lambda *a,**k:(entered.set() or proc)), \
             patch.object(provider, 'stop_owned_process', side_effect=stop_owned):
            thread = threading.Thread(target=generate, daemon=True)
            thread.start()
            self.assertTrue(entered.wait(2))
            cancelled.set()
            thread.join(timeout=0.8)
            still_blocked = thread.is_alive()
            release.set(); thread.join(timeout=2)
        self.assertFalse(still_blocked, 'Cancelled generation remained blocked writing stdin before the timeout loop')
        self.assertTrue(any(isinstance(error, provider.GenerationCancelled) for error in errors))


if __name__ == '__main__':
    unittest.main()
