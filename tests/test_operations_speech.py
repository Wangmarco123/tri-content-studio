import copy
import json
import unittest
from studio.operations import build_brief, campaign_schema, validate_campaign
from test_media_speech import speech_fixture


def campaign_fixture():
    return {'asset_id': 'asset-1', 'summary': '完整口播与抽样画面的结构演示', 'no_trend_reason': '',
            'opportunities': [{'id': 'o1', 'platform': 'douyin', 'title': '相关表达', 'kind': 'expression',
                'evidence_ids': ['ev1'], 'why_relevant': '与实际口播一致', 'query_time': '2026-11-16T12:00:00+08:00'}],
            'fit_assessments': [{'opportunity_id': 'o1', 'verdict': 'connection', 'reason': '有口播依据',
                'segments': [{'start': 5.95, 'end': 5.99, 'observation': '末尾口播相关', 'evidence_type': 'speech'}],
                'supports_features': ['结构演示'], 'limits': ['机器识别需核对']}],
            'packages': [{'platform': p, 'title': '结构演示', 'title_candidates': ['结构演示', '装配过程'],
                'caption': '真实装配视频', 'tags': ['结构设计'], 'hook': '先看结构', 'visibility': 'draft',
                'evidence_ids': ['ev1'] if p == 'douyin' else [], 'fit_reason': '围绕实际内容', 'tag_checks': [],
                'category_suggestion': '科技' if p == 'bilibili' else '',
                'search_keywords': ['结构设计'] if p == 'xiaohongshu' else []} for p in ('bilibili', 'douyin', 'xiaohongshu')]}


class OperationsSpeechTests(unittest.TestCase):
    def setUp(self):
        self.asset = {'id': 'asset-1', 'path': 'PRIVATE/video.mp4', 'sha256': 'PRIVATE-HASH',
                      'summary': '', 'facts': [], 'audience': '设计师', 'keywords': []}
        self.evidence = [{'id': 'ev1', 'platform': 'douyin', 'title': '相关表达',
            'source_url': 'https://www.douyin.com/hot/1', 'fetched_at': '2026-11-16T12:00:00+08:00'}]
        self.speech = speech_fixture()
        self.media = {'duration': 6, 'width': 1280, 'height': 720,
            'frames': [{'timestamp': .5, 'path': 'PRIVATE/frame.jpg'}],
            'transcript': [], 'speech': self.speech, 'supplied_subtitles': [],
            'analysis_scope': 'sampled_frames_and_full_audio_transcript', 'warnings': []}

    def test_full_transcript_is_sent_once_no_paths_or_duplicated_text(self):
        # Even if a caller accidentally supplied a short transcript view, full ASR segments are authoritative.
        self.media['transcript'] = self.speech['segments'][:3]
        brief = build_brief(self.asset, self.evidence, self.media)
        self.assertEqual(len(brief['media']['transcript']), 250)
        encoded = json.dumps(brief, ensure_ascii=False)
        self.assertNotIn('PRIVATE', encoded)
        self.assertEqual(encoded.count('口播片段249'), 1)
        self.assertNotIn('segments', brief['media']['speech'])
        self.assertNotIn('text', brief['media']['speech'])
        self.assertTrue(brief['media']['transcript'][-1]['uncertain'])
        self.assertIn('机器识别', brief['instructions'])

    def test_speech_schema_and_actual_end_of_track_evidence(self):
        schema = campaign_schema('asset-1')
        enum = schema['properties']['fit_assessments']['items']['properties']['segments']['items']['properties']['evidence_type']['enum']
        self.assertIn('speech', enum)
        result = validate_campaign(campaign_fixture(), self.asset, self.evidence, self.media)
        self.assertEqual(result['fit_assessments'][0]['segments'][0]['evidence_type'], 'speech')

    def test_speech_requires_complete_and_real_overlapping_asr(self):
        for change in [{'complete': False}, {'status': 'no_audio', 'segments': [], 'audio_duration': 0, 'processed_duration': 0},
                       {'segments': [{'start': 0, 'end': 1, 'text': '只有开头'}]}, {'processed_duration': 1}]:
            media = copy.deepcopy(self.media); media['speech'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_campaign(campaign_fixture(), self.asset, self.evidence, media)

    def test_asr_is_not_external_subtitle_but_legacy_subtitles_still_work(self):
        payload = campaign_fixture(); payload['fit_assessments'][0]['segments'][0]['evidence_type'] = 'subtitle'
        self.media['transcript'] = self.speech['segments']
        with self.assertRaises(ValueError): validate_campaign(payload, self.asset, self.evidence, self.media)
        legacy = {k: copy.deepcopy(v) for k, v in self.media.items() if k not in ('speech', 'supplied_subtitles')}
        legacy['analysis_scope'] = 'sampled_frames_and_supplied_subtitles'
        self.assertEqual(validate_campaign(payload, self.asset, self.evidence, legacy)['asset_id'], 'asset-1')
        self.media['supplied_subtitles'] = [{'start': 5.9, 'end': 6, 'text': '真实外部字幕'}]
        self.assertEqual(validate_campaign(payload, self.asset, self.evidence, self.media)['asset_id'], 'asset-1')

    def test_incomplete_media_cannot_pass_brief_without_speech_claim(self):
        self.media['speech']['complete'] = False
        with self.assertRaises(ValueError): build_brief(self.asset, [], self.media)

    def test_no_audio_and_no_speech_briefs_are_truthful_image_fallbacks(self):
        for status in ('no_audio', 'no_speech'):
            media = copy.deepcopy(self.media)
            media['speech'].update(status=status, segments=[], text='', uncertain_segments=[])
            if status == 'no_audio': media['speech'].update(audio_duration=0, processed_duration=0)
            brief = build_brief(self.asset, [], media)
            self.assertEqual(brief['media']['transcript'], [])
            self.assertEqual(brief['media']['speech']['status'], status)
            self.assertNotIn('PRIVATE', json.dumps(brief, ensure_ascii=False))
            self.assertIn('抽样画面', brief['instructions'])


if __name__ == '__main__': unittest.main()
