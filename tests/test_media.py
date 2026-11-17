import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import media


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='媒体证据 test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / '中文 成片.mp4'
        self.video.write_bytes(b'fixture-not-real-video')
        self.asset = {'id': 'asset-1', 'path': str(self.video)}
        self.work = self.root / 'work'

    def fake_run(self, command, **kwargs):
        self.assertFalse(kwargs.get('shell', False))
        self.assertLessEqual(kwargs['timeout'], 25)
        self.assertEqual(command[command.index('-protocol_whitelist') + 1], 'file,pipe')
        if '-show_entries' in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({
                'streams': [{'index': 0, 'codec_type': 'video', 'width': 1280, 'height': 720}],
                'format': {'duration': '6.0'}}), '')
        output = Path(command[-1])
        self.assertTrue(output.resolve().is_relative_to(self.work.resolve()))
        output.write_bytes(b'\xff\xd8fixture\xff\xd9')
        return subprocess.CompletedProcess(command, 0, '', '')

    def fixture_tools(self):
        return patch.object(media, '_find_tools', return_value=(Path('ffmpeg.exe'), Path('ffprobe.exe')))

    def test_srt_and_frames_are_real_artifacts_with_bounded_sampling(self):
        self.video.with_suffix('.srt').write_text(
            '1\n00:00:00,500 --> 00:00:01,900\n真实字幕\n第二行\n\n'
            '2\n00:00:02,000 --> 00:00:03,200\n<b>壶盖装配</b>\n', encoding='utf-8-sig')
        with self.fixture_tools(), patch.object(media.subprocess, 'run', side_effect=self.fake_run):
            result = media.analyze_media(self.asset, self.work, self.root)
        self.assertEqual(result['duration'], 6)
        self.assertEqual((result['width'], result['height']), (1280, 720))
        self.assertEqual(len(result['frames']), 6)
        self.assertEqual([x['timestamp'] for x in result['frames']], [0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
        self.assertEqual(result['transcript'][0], {'start': 0.5, 'end': 1.9, 'text': '真实字幕\n第二行'})
        self.assertEqual(result['transcript'][1]['text'], '壶盖装配')
        self.assertEqual(self.video.read_bytes(), b'fixture-not-real-video')

    def test_no_subtitles_does_not_claim_transcription(self):
        with self.fixture_tools(), patch.object(media.subprocess, 'run', side_effect=self.fake_run):
            result = media.analyze_media(self.asset, self.work, self.root)
        self.assertEqual(result['analysis_scope'], 'sampled_frames_and_supplied_subtitles')
        self.assertEqual(result['transcript'], [])
        self.assertTrue(any('未进行语音转写' in x for x in result['warnings']))

    def test_vtt_settings_notes_html_and_200_segment_limit(self):
        text = 'WEBVTT\n\nNOTE private note not a subtitle\nignore this\n\n'
        text += '\n\n'.join(f'cue-{i}\n00:00.000 --> 00:01.000 align:start\n<v narrator>字幕{i}&amp;事实</v>'
                              for i in range(205))
        self.video.with_suffix('.vtt').write_text(text, encoding='utf-8')
        with self.fixture_tools(), patch.object(media.subprocess, 'run', side_effect=self.fake_run):
            result = media.analyze_media(self.asset, self.work, self.root)
        self.assertEqual(len(result['transcript']), 200)
        self.assertEqual(result['transcript'][0]['text'], '字幕0&事实')
        self.assertTrue(any('200' in x for x in result['warnings']))

    def test_missing_file_tools_and_invalid_probe_fail_explicitly(self):
        with self.assertRaises(ValueError):
            media.analyze_media({'path': str(self.root / 'missing.mp4')}, self.work, self.root)
        with self.assertRaises(ValueError):
            media.analyze_media(self.asset, self.work, self.root)
        bad = subprocess.CompletedProcess([], 0, '{"streams":[],"format":{"duration":"6"}}', '')
        with self.fixture_tools(), patch.object(media.subprocess, 'run', return_value=bad):
            with self.assertRaises(ValueError):
                media.analyze_media(self.asset, self.work, self.root)

    def test_probe_timeout_and_nonfinite_duration_rejected(self):
        with self.fixture_tools(), patch.object(media.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 1)):
            with self.assertRaises(ValueError):
                media.analyze_media(self.asset, self.work, self.root)
        bad = subprocess.CompletedProcess([], 0, '{"streams":[{"codec_type":"video","width":640,"height":480}],"format":{"duration":"NaN"}}', '')
        with self.fixture_tools(), patch.object(media.subprocess, 'run', return_value=bad):
            with self.assertRaises(ValueError):
                media.analyze_media(self.asset, self.work, self.root)

    def test_all_frame_failures_do_not_return_fabricated_frames(self):
        def run(command, **kwargs):
            if '-show_entries' in command:
                return self.fake_run(command, **kwargs)
            return subprocess.CompletedProcess(command, 1, '', 'fixture decode failed')
        with self.fixture_tools(), patch.object(media.subprocess, 'run', side_effect=run):
            with self.assertRaises(ValueError):
                media.analyze_media(self.asset, self.work, self.root)

    def test_embedded_cover_not_mistaken_for_main_video(self):
        def run(command, **kwargs):
            if '-show_entries' in command:
                return subprocess.CompletedProcess(command, 0, json.dumps({'format': {'duration': '6'}, 'streams': [
                    {'index': 0, 'codec_type': 'video', 'width': 100, 'height': 100, 'disposition': {'attached_pic': 1}},
                    {'index': 2, 'codec_type': 'video', 'width': 640, 'height': 480, 'disposition': {'attached_pic': 0}}]}), '')
            self.assertEqual(command[command.index('-map') + 1], '0:2')
            return self.fake_run(command, **kwargs)
        with self.fixture_tools(), patch.object(media.subprocess, 'run', side_effect=run):
            result = media.analyze_media(self.asset, self.work, self.root)
        self.assertEqual(result['width'], 640)

    def test_tool_discovery_only_uses_project_directories(self):
        tools = self.root / 'components' / 'ffmpeg' / 'bin'
        tools.mkdir(parents=True)
        (tools / 'ffmpeg.exe').touch(); (tools / 'ffprobe.exe').touch()
        self.assertEqual(media._find_tools(self.root), (tools / 'ffmpeg.exe', tools / 'ffprobe.exe'))

    def test_real_six_second_video_local_only(self):
        project = Path(__file__).resolve().parents[4]
        video = project / 'outputs' / '测试素材' / '上传功能测试_6秒.mp4'
        legacy_tools = Path('G:/MiniMax-H3/ComfyUI/ffmpeg/bin')
        try:
            ffmpeg, ffprobe = media._find_tools(project)
        except ValueError:
            ffmpeg, ffprobe = legacy_tools / 'ffmpeg.exe', legacy_tools / 'ffprobe.exe'
        if not (video.is_file() and ffmpeg.is_file() and ffprobe.is_file()):
            self.skipTest('Actual six-second fixture or explicitly supplied local FFmpeg is unavailable')
        before = video.stat().st_mtime_ns
        with patch.object(media, '_find_tools', return_value=(ffmpeg, ffprobe)):
            result = media.analyze_media({'id': 'fixture-6s', 'path': str(video)}, self.work, project)
        self.assertAlmostEqual(result['duration'], 6, delta=0.3)
        self.assertGreater(result['width'], 0); self.assertGreater(result['height'], 0)
        self.assertEqual(len(result['frames']), 6)
        for frame in result['frames']:
            path = Path(frame['path'])
            self.assertTrue(path.is_relative_to(self.work))
            self.assertTrue(path.read_bytes().startswith(b'\xff\xd8'))
            self.assertGreater(path.stat().st_size, 100)
        self.assertEqual(video.stat().st_mtime_ns, before)


if __name__ == '__main__':
    unittest.main()
