import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from studio.api import ApiServer
from studio.service import Service


class ClientIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='客户端 integration ')
        self.root = Path(self.temp.name)
        self.service = Service(self.root, self.root / 'data', start_worker=False)
        self.api = ApiServer(self.service, port=0)
        self.api.start()
        self.token_file = self.service.paths.token_path
        self.source = Path(__file__).resolve().parents[1]
        self.environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        self.prefix = [sys.executable, '-m', 'studio.cli', '--home', str(self.root),
                       '--data-dir', str(self.root / 'data'), '--endpoint', self.api.endpoint,
                       '--token-file', str(self.token_file)]

    def tearDown(self):
        self.api.close()
        self.service.close()
        self.temp.cleanup()

    def cli(self, *args):
        result = subprocess.run(self.prefix + list(args), cwd=self.source, env=self.environment,
                                capture_output=True, encoding='utf-8', timeout=15)
        return result, json.loads(result.stdout)

    def mcp(self, messages, prefix=None):
        result = subprocess.run((prefix or self.prefix) + ['mcp'], cwd=self.source,
                                env=self.environment, input=''.join(json.dumps(m, ensure_ascii=False) + '\n'
                                                                  for m in messages),
                                capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def asset(self):
        video = self.root / '中文 空格.mp4'
        video.write_bytes(b'local fixture, not uploaded')
        result, asset = self.cli('add', '--file', str(video), '--summary', '本人确认的壶盖装配演示')
        self.assertEqual(result.returncode, 0, result.stderr)
        return asset

    def test_cli_asset_brief_package_import_share_api_state(self):
        asset = self.asset()
        _, listed = self.cli('list', 'assets')
        self.assertEqual(listed[0]['id'], asset['id'])
        brief_file = self.root / '外部AI任务.json'
        result, brief = self.cli('brief', asset['id'], '--out', str(brief_file))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(brief['asset']['summary'], '本人确认的壶盖装配演示')
        self.assertNotIn('path', brief['asset'])
        payload = {'asset_id': asset['id'], 'packages': [{'platform': 'douyin', 'title': '装配过程',
                   'caption': '真实展示壶盖配合', 'tags': ['CAD'], 'evidence_ids': [], 'fit_reason': ''}]}
        package = self.root / '运营成品.json'
        package.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8-sig')
        result, imported = self.cli('import-packages', str(package))
        self.assertEqual(result.returncode, 0, imported)
        self.assertEqual(imported['items'][0]['visibility'], 'draft')
        self.assertEqual(self.service.drafts()[0]['title'], '装配过程')

    def test_cli_queue_default_draft_cancel_no_worker(self):
        asset = self.asset()
        draft = self.service.save_draft({'asset_id': asset['id'], 'platform': 'douyin',
                                        'title': '测试草稿', 'caption': '实际素材', 'tags': []})
        result, job = self.cli('queue', '--draft-id', draft['id'], '--idempotency-key', 'fixture-once')
        self.assertEqual(result.returncode, 0, job)
        self.assertEqual(job['action'], 'draft')
        self.assertEqual(job['payload']['visibility'], 'draft')
        _, same = self.cli('queue', '--draft-id', draft['id'], '--idempotency-key', 'fixture-once')
        self.assertEqual(same['id'], job['id'])
        _, cancelled = self.cli('cancel', job['id'])
        self.assertEqual(cancelled['status'], 'cancelled')
        result, error = self.cli('queue', '--action', 'publish', '--draft-id', draft['id'])
        self.assertEqual(result.returncode, 2)
        self.assertIn('error', error)
        self.assertEqual(len(self.service.jobs()), 1)

    def test_cli_wrong_token_returns_json_error_without_token(self):
        wrong = self.root / 'wrong-token.txt'
        sentinel = 'fake-client-token-not-user-secret'
        wrong.write_text(sentinel, encoding='ascii')
        command = self.prefix.copy()
        command[command.index('--token-file') + 1] = str(wrong)
        result = subprocess.run(command + ['list', 'assets'], cwd=self.source, env=self.environment,
                                capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn('error', json.loads(result.stdout))
        self.assertNotIn(sentinel, result.stdout + result.stderr)

    def test_mcp_initialize_list_and_real_api_calls(self):
        asset = self.asset()
        messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                     'params': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'fixture', 'version': '1'}}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'list_assets', 'arguments': {}}},
                    {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'export_brief', 'arguments': {'id': asset['id']}}}]
        responses = self.mcp(messages)
        self.assertEqual([r['id'] for r in responses], [1, 2, 3, 4])
        tools = {t['name']: t for t in responses[1]['result']['tools']}
        self.assertIn('queue_task', tools)
        self.assertIn('asset_id', tools['import_packages']['inputSchema']['required'])
        self.assertEqual(json.loads(responses[2]['result']['content'][0]['text'])[0]['id'], asset['id'])
        self.assertNotIn('path', json.loads(responses[3]['result']['content'][0]['text'])['asset'])

    def test_mcp_writes_packages_and_invalid_args_keep_request_id(self):
        asset = self.asset()
        payload = {'asset_id': asset['id'], 'packages': [{'platform': 'xiaohongshu', 'title': '壶盖装配',
                   'caption': '本视频真实展示壶盖配合', 'tags': ['CAD'], 'evidence_ids': [], 'fit_reason': ''}]}
        responses = self.mcp([
            {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': 'import_packages', 'arguments': payload}},
            {'jsonrpc': '2.0', 'id': 8, 'method': 'tools/call', 'params': {'name': 'export_brief', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 9, 'method': 'tools/call', 'params': {'name': 'not_a_tool', 'arguments': {}}}])
        self.assertFalse(responses[0]['result'].get('isError', False))
        self.assertEqual(self.service.drafts()[0]['visibility'], 'draft')
        self.assertEqual(responses[1]['id'], 8)
        self.assertEqual(responses[1]['error']['code'], -32602)
        self.assertEqual(responses[2]['id'], 9)

    def test_mcp_wrong_token_is_tool_error_not_process_crash(self):
        wrong = self.root / 'wrong.txt'; wrong.write_text('synthetic-wrong', encoding='ascii')
        prefix = self.prefix.copy(); prefix[prefix.index('--token-file') + 1] = str(wrong)
        response = self.mcp([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                              'params': {'name': 'list_assets', 'arguments': {}}}], prefix=prefix)[0]
        self.assertTrue(response['result']['isError'])
        self.assertNotIn('synthetic-wrong', json.dumps(response))

    def test_cli_unknown_submission_not_requeued_with_new_key(self):
        asset = self.asset()
        draft = self.service.save_draft({'asset_id': asset['id'], 'platform': 'douyin',
                                        'title': '未知结果测试', 'caption': '实际素材', 'tags': []})
        job = self.service.create_job({'action': 'publish', 'draft_id': draft['id'],
                                       'visibility': 'private', 'idempotency_key': 'observed'})
        self.service.store.update('jobs', job['id'], {'status': 'outcome_unknown'})
        result, error = self.cli('queue', '--action', 'publish', '--draft-id', draft['id'],
                                 '--visibility', 'private', '--idempotency-key', 'changed-key')
        self.assertEqual(result.returncode, 2)
        self.assertIn('error', error)
        self.assertEqual(len(self.service.jobs()), 1)

    def test_cli_forces_utf8_even_with_legacy_stream_encoding(self):
        video = self.root / '中文😀.mp4'; video.write_bytes(b'fixture')
        environment = dict(self.environment, PYTHONUTF8='0', PYTHONIOENCODING='cp1252')
        result = subprocess.run(self.prefix + ['add', '--file', str(video), '--summary', '事实😀'],
                                cwd=self.source, env=environment, capture_output=True,
                                encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['summary'], '事实😀')

    def test_cli_rejects_token_bearing_redirects(self):
        captured = []
        class Sink(BaseHTTPRequestHandler):
            def do_GET(self):
                captured.append(self.headers.get('Authorization'))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self, *_): pass
        sink = ThreadingHTTPServer(('127.0.0.1', 0), Sink)
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:%d/api/v1/assets' % sink.server_port)
                self.end_headers()
            def log_message(self, *_): pass
        redirect = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        for server in (sink, redirect):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        prefix = self.prefix.copy(); prefix[prefix.index('--endpoint') + 1] = 'http://127.0.0.1:%d' % redirect.server_port
        result = subprocess.run(prefix + ['list', 'assets'], cwd=self.source, env=self.environment,
                                capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(captured, [])


if __name__ == '__main__':
    unittest.main()
