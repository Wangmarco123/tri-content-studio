import json
from PIL import Image
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

class ProviderTests(unittest.TestCase):
    def test_codex_command_has_no_publish_or_shell_capability(self):
        from studio.ai_provider import codex_command
        command=codex_command(Path('codex.exe'),Path('work'),Path('schema.json'),Path('output.json'),[{'path':'a.jpg'}],{})
        self.assertIn('--ephemeral',command);self.assertIn('--ignore-user-config',command)
        self.assertIn('read-only',command);self.assertIn('--search',command)
        self.assertIn('shell_tool',command);self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',command)
        self.assertIn('--image',command);self.assertIn('a.jpg',command)
    def test_missing_codex_is_real_error_not_template(self):
        from studio.ai_provider import run_codex
        with tempfile.TemporaryDirectory() as d,patch('studio.ai_provider.find_codex',return_value=None):
            with self.assertRaises(ValueError):run_codex('prompt',{},[],Path(d))
    def test_cancel_before_generation_makes_no_process(self):
        from studio.ai_provider import run_codex,GenerationCancelled
        with tempfile.TemporaryDirectory() as d,patch('studio.ai_provider.subprocess.Popen') as launch:
            with self.assertRaises(GenerationCancelled):run_codex('prompt',{},[],Path(d),cancel=lambda:True)
            launch.assert_not_called()
    def test_api_request_contains_actual_frames_and_no_file_path(self):
        from studio.ai_provider import run_api
        with tempfile.TemporaryDirectory() as d:
            frame=Path(d)/'a.jpg';Image.new('RGB',(4,4),'white').save(frame)
            config={'api_key':'SYNTHETIC_KEY','base_url':'https://example.com/v1','model':'test'}
            with patch('studio.ai_provider._request_json',return_value={'choices':[{'message':{'content':'{"asset_id":"a"}'}}]}) as request:
                result=run_api('facts',{},[{'path':str(frame),'timestamp':1.2}],config)
            self.assertEqual(result['asset_id'],'a')
            body=request.call_args.kwargs['body'];serialized=json.dumps(body)
            self.assertIn('data:image/jpeg;base64,',serialized);self.assertNotIn(str(frame),serialized)
    def test_invalid_multiline_key_is_rejected_without_logging_it(self):
        from studio.ai_provider import run_api
        with patch('studio.ai_provider._request_json') as request:
            with self.assertRaises(ValueError) as caught:run_api('facts',{},[],{'api_key':'part\nSYNTHETIC_SECRET','model':'m'})
        self.assertNotIn('SYNTHETIC_SECRET',str(caught.exception));request.assert_not_called()

if __name__=='__main__':unittest.main()
