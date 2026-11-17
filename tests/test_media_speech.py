import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import media


def speech_fixture(count=250):
    segments = [{'start': i * 6 / count, 'end': (i + 1) * 6 / count,
                 'text': f'口播片段{i}', 'avg_logprob': -0.2, 'no_speech_prob': 0.01, 'uncertain': i == count - 1}
                for i in range(count)]
    return {'status': 'complete', 'engine': 'faster-whisper', 'model': 'large-v3-turbo',
            'device': 'cuda', 'compute_type': 'float16', 'language': 'zh', 'language_probability': 0.98,
            'audio_duration': 6.0, 'processed_duration': 6.0, 'complete': True,
            'segments': segments, 'text': ' '.join(s['text'] for s in segments),
            'uncertain_segments': [count - 1], 'warnings': [], 'txt_path': 'PRIVATE/transcript.txt',
            'srt_path': 'PRIVATE/transcript.srt', 'json_path': 'PRIVATE/transcript.json', 'cache_hit': False}


class MediaSpeechTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / 'fixture.mp4'; self.video.write_bytes(b'fixture')
        self.asset = {'id': 'asset-1', 'path': str(self.video)}

    def fake_run(self, command, **kwargs):
        if '-show_entries' in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({'format': {'duration': '6'}, 'streams': [
                {'index': 0, 'codec_type': 'video', 'width': 1280, 'height': 720}]}), '')
        Path(command[-1]).write_bytes(b'\xff\xd8fixture\xff\xd9')
        return subprocess.CompletedProcess(command, 0, '', '')

    def analyze(self, speech):
        with patch.object(media, '_find_tools', return_value=(Path('ffmpeg.exe'), Path('ffprobe.exe'))), \
             patch.object(media.subprocess, 'run', side_effect=self.fake_run):
            return media.analyze_media(self.asset, self.root / 'work', self.root, speech=speech)

    def test_full_asr_over_200_segments_kept_and_external_subtitles_separate(self):
        speech = speech_fixture(); original = copy.deepcopy(speech)
        self.video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n外部字幕不同内容\n', encoding='utf-8')
        result = self.analyze(speech)
        self.assertEqual(result['analysis_scope'], 'sampled_frames_and_full_audio_transcript')
        self.assertEqual(len(result['transcript']), 250)
        self.assertEqual(result['transcript'][-1]['text'], '口播片段249')
        self.assertEqual(result['transcript'][-1]['source'], 'asr')
        self.assertTrue(result['transcript'][-1]['uncertain'])
        self.assertEqual(result['supplied_subtitles'][0]['text'], '外部字幕不同内容')
        self.assertEqual(result['speech'], original); self.assertEqual(speech, original)
        self.assertLessEqual(len(result['frames']), 8)
        self.assertTrue(any(frame['timestamp'] > 5 for frame in result['frames']))
        self.assertFalse(any('未进行语音转写' in warning for warning in result['warnings']))

    def test_no_audio_and_no_speech_are_distinct_image_scopes(self):
        for status, scope in [('no_audio', 'sampled_frames_no_audio'), ('no_speech', 'sampled_frames_no_speech')]:
            speech = speech_fixture()
            speech.update(status=status, segments=[], text='', uncertain_segments=[])
            if status == 'no_audio': speech.update(audio_duration=0, processed_duration=0)
            result = self.analyze(speech)
            self.assertEqual(result['analysis_scope'], scope)
            self.assertEqual(result['transcript'], [])
            self.assertGreater(len(result['frames']), 0)

    def test_incomplete_failed_or_partial_speech_is_not_normal_generation(self):
        variants = []
        s = speech_fixture(); s['complete'] = False; variants.append(s)
        s = speech_fixture(); s['status'] = 'failed'; variants.append(s)
        s = speech_fixture(); s['processed_duration'] = 2; variants.append(s)
        s = speech_fixture(); s['segments'][-1]['end'] = 12; variants.append(s)
        for speech in variants:
            with self.subTest(speech=speech['status']), self.assertRaises(ValueError):
                self.analyze(speech)

    def test_no_speech_does_not_promote_supplied_srt_to_asr(self):
        self.video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n外部字幕\n', encoding='utf-8')
        speech = speech_fixture(); speech.update(status='no_speech', segments=[], text='', uncertain_segments=[])
        result = self.analyze(speech)
        self.assertEqual(result['transcript'], [])
        self.assertEqual(result['supplied_subtitles'][0]['text'], '外部字幕')

    def test_real_local_video_fuses_full_supplied_asr_without_running_asr(self):
        project = Path(__file__).resolve().parents[4]
        video = project / 'outputs' / '测试素材' / '上传功能测试_6秒.mp4'
        if not video.is_file(): self.skipTest('Local six-second fixture unavailable')
        try: media._find_tools(project)
        except ValueError: self.skipTest('Project-local FFmpeg unavailable')
        before = video.stat().st_mtime_ns
        result = media.analyze_media({'id': 'fixture', 'path': str(video)}, self.root / 'real-work',
                                     project, speech=speech_fixture())
        self.assertEqual(len(result['transcript']), 250)
        self.assertLessEqual(len(result['frames']), 8)
        self.assertGreaterEqual(len(result['frames']), 6)
        self.assertEqual(result['analysis_scope'], 'sampled_frames_and_full_audio_transcript')
        self.assertTrue(all(Path(f['path']).is_relative_to(self.root / 'real-work') for f in result['frames']))
        self.assertEqual(video.stat().st_mtime_ns, before)


if __name__ == '__main__': unittest.main()
