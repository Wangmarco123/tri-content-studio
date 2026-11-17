"""Real temporary store + campaign threads; all AI/media/network actions isolated."""
import copy
import json
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from studio.campaigns import campaign_prompt, normalize_sources
from studio.service import Service


def result_fixture(asset_id, tags=None):
    return {'asset_id': asset_id, 'summary': '本人素材的结构演示', 'opportunities': [], 'fit_assessments': [],
            'no_trend_reason': '无直接相关热点，仅采用自然内容包装', 'research_sources': [],
            'packages': [{'platform': platform, 'title': '结构演示', 'title_candidates': ['结构演示', '装配过程'],
                          'caption': '视频实际展示装配过程', 'tags': tags or ['结构设计'], 'hook': '先看装配过程',
                          'visibility': 'draft', 'evidence_ids': [], 'fit_reason': '与本人装配演示直接相关',
                          'tag_checks': [], 'category_suggestion': '科技·软件应用' if platform == 'bilibili' else '',
                          'search_keywords': ['结构设计'] if platform == 'xiaohongshu' else []}
                         for platform in ('bilibili', 'douyin', 'xiaohongshu')]}


class CampaignReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='campaign isolated ')
        self.root = Path(self.temp.name)
        self.s = Service(self.root, self.root / 'data', start_worker=False)
        self.video = self.root / 'never-uploaded.mp4'; self.video.write_bytes(b'local synthetic asset')
        self.asset = self.s.add_asset({'path': str(self.video), 'summary': '本人装配演示', 'facts': ['展示壶盖配合']})
        self.media = {'duration': 6, 'width': 1280, 'height': 720, 'frames': [], 'transcript': [],
                      'analysis_scope': 'sampled_frames_and_supplied_subtitles', 'warnings': []}

    def tearDown(self):
        self.s.close(); self.temp.cleanup()

    def isolated(self, generate):
        stack = ExitStack()
        stack.enter_context(patch('studio.campaigns.transcribe_video',return_value={'status':'no_audio','complete':True,'audio_duration':0,'processed_duration':0,'segments':[],'text':''}))
        stack.enter_context(patch('studio.campaigns.analyze_media', return_value=self.media))
        stack.enter_context(patch('studio.campaigns.fetch_trends', return_value={'items': []}))
        stack.enter_context(patch('studio.campaigns.codex_status', return_value={'available': True, 'logged_in': True}))
        stack.enter_context(patch('studio.campaigns.run_codex', side_effect=generate))
        return stack

    def wait(self, cid):
        for _ in range(200):
            record = self.s.get_campaign(cid)
            if record['status'] not in ('queued', 'running'):
                return record
            time.sleep(0.01)
        self.fail('campaign did not terminate')

    def complete(self, result=None):
        with self.isolated(lambda *args, **kwargs: copy.deepcopy(result or result_fixture(self.asset['id']))):
            record = self.s.start_campaign({'asset_id': self.asset['id']})
            return self.wait(record['id'])

    def test_cancel_discards_late_success_without_drafts(self):
        entered, release = threading.Event(), threading.Event()
        def late(*args, **kwargs):
            entered.set(); release.wait(3); return result_fixture(self.asset['id'])
        with self.isolated(late):
            record = self.s.start_campaign({'asset_id': self.asset['id']})
            self.assertTrue(entered.wait(2))
            self.s.cancel_campaign(record['id']); release.set()
            result = self.wait(record['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(result['result']); self.assertEqual(self.s.drafts(), [])

    def test_stop_discards_late_success_without_drafts(self):
        entered, release = threading.Event(), threading.Event(); errors = []
        def late(*args, **kwargs):
            entered.set(); release.wait(3); return result_fixture(self.asset['id'])
        def stop():
            try: self.s.campaign_manager.stop()
            except Exception as exc: errors.append(exc)
        with self.isolated(late):
            record = self.s.start_campaign({'asset_id': self.asset['id']})
            self.assertTrue(entered.wait(2))
            stopper = threading.Thread(target=stop); stopper.start()
            for _ in range(100):
                if self.s.campaign_manager.closing: break
                time.sleep(.01)
            release.set(); stopper.join(3)
            result = self.wait(record['id'])
        self.assertFalse(errors); self.assertFalse(stopper.is_alive())
        self.assertEqual(result['status'], 'cancelled'); self.assertEqual(self.s.drafts(), [])

    def test_cancelled_generation_error_stays_cancelled(self):
        entered, release = threading.Event(), threading.Event()
        def failing_late(*args, **kwargs):
            entered.set(); release.wait(3); raise ValueError('simulated transport failure after cancel')
        with self.isolated(failing_late):
            record = self.s.start_campaign({'asset_id': self.asset['id']})
            self.assertTrue(entered.wait(2))
            self.s.cancel_campaign(record['id']); release.set()
            result = self.wait(record['id'])
        self.assertEqual(result['status'], 'cancelled')

    def test_stop_during_final_write_rolls_back_late_result(self):
        entered, release = threading.Event(), threading.Event(); stop_errors = []
        original = self.s.save_draft
        def slow_write(payload):
            entered.set(); release.wait(3); return original(payload)
        def stop():
            try: self.s.campaign_manager.stop()
            except Exception as exc: stop_errors.append(exc)
        with self.isolated(lambda *args, **kwargs: result_fixture(self.asset['id'])), \
             patch.object(self.s, 'save_draft', side_effect=slow_write):
            record = self.s.start_campaign({'asset_id': self.asset['id']})
            self.assertTrue(entered.wait(2))
            stopper = threading.Thread(target=stop); stopper.start()
            for _ in range(100):
                if self.s.campaign_manager.events[record['id']].is_set(): break
                time.sleep(.01)
            release.set(); stopper.join(3)
            result = self.wait(record['id'])
        self.assertFalse(stop_errors)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.s.drafts(), [])

    def test_selected_titles_update_existing_drafts_and_repeated_save_is_noop(self):
        record = self.complete()
        self.assertEqual(record['status'], 'complete')
        ids = {d['platform']: d['id'] for d in self.s.drafts()}
        first = self.s.save_campaign({'id': record['id'], 'selections': {'bilibili': 1, 'xiaohongshu': 1}})
        versions = len(self.s.store.list('versions'))
        again = self.s.save_campaign({'id': record['id'], 'selections': {'bilibili': 1, 'xiaohongshu': 1}})
        self.assertEqual(first['count'], 3); self.assertEqual(len(self.s.drafts()), 3)
        self.assertEqual(len(self.s.store.list('versions')), versions)
        self.assertEqual({d['platform']: d['id'] for d in again['items']}, ids)
        self.assertEqual(next(d for d in again['items'] if d['platform'] == 'bilibili')['title'], '装配过程')

    def test_hash_prefixed_tags_do_not_break_repeated_queue_idempotency(self):
        record = self.complete(result_fixture(self.asset['id'], tags=['#结构设计']))
        self.assertEqual(record['status'], 'complete')
        with patch('studio.service.now', return_value='2026-11-16T10:00:01+08:00'):
            first = self.s.save_campaign({'id': record['id'], 'queue_drafts': True})
        versions = len(self.s.store.list('versions'))
        with patch('studio.service.now', return_value='2026-11-16T10:00:02+08:00'):
            again = self.s.save_campaign({'id': record['id'], 'queue_drafts': True})
        self.assertEqual({j['id'] for j in first['jobs']}, {j['id'] for j in again['jobs']})
        self.assertEqual(len(self.s.jobs()), 1)
        self.assertEqual(len(self.s.store.list('versions')), versions)

    def test_research_id_collision_cannot_hijack_existing_reference(self):
        known = {'id': 'known-dy', 'platform': 'douyin', 'title': '真实已知来源',
                 'source_url': 'https://www.douyin.com/hot/123', 'verification': 'user_supplied'}
        self.s.import_evidence({'items': [known]})
        before = self.s.store.get('evidence', 'known-dy')
        raw = result_fixture(self.asset['id'])
        raw['packages'][1]['evidence_ids'] = ['known-dy']
        raw['research_sources'] = [{'id': 'known-dy', 'platform': 'douyin', 'title': '其他链接',
                                    'source_url': 'https://www.douyin.com/hot/999'}]
        record = self.complete(raw)
        self.assertEqual(self.s.store.get('evidence', 'known-dy'), before)
        # Collision may be rejected, or existing references must retain their identity.
        if record['status'] == 'complete':
            refs = next(p for p in record['result']['packages'] if p['platform'] == 'douyin')['evidence_ids']
            self.assertEqual(refs, ['known-dy'])
        else:
            self.assertEqual(record['status'], 'failed')

    def test_foreign_domains_and_credentials_rejected_no_network(self):
        for url in ['https://douyin.com.evil.invalid/x', 'https://evil.invalid/douyin.com',
                    'https://user:pass@www.douyin.com/hot/1', 'file:///douyin.com/x']:
            raw = result_fixture(self.asset['id'])
            raw['research_sources'] = [{'id': 'new', 'platform': 'douyin', 'title': 'test', 'source_url': url}]
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_sources(raw, 'review-campaign')

    def test_prompt_does_not_include_original_path_hash_or_account_state(self):
        asset = dict(self.asset, account_cookie='SYNTHETIC_COOKIE', account_profile='SYNTHETIC_PROFILE')
        frame_path = str(self.root / 'frame-private-location.jpg')
        media = dict(self.media, frames=[{'timestamp': 1, 'path': frame_path}])
        prompt = campaign_prompt(asset, [], media, '真实结构演示', True)
        for private in [str(self.video), self.asset['sha256'], frame_path, 'SYNTHETIC_COOKIE', 'SYNTHETIC_PROFILE']:
            self.assertNotIn(private, prompt)
        self.assertIn('本人装配演示', prompt)
        self.assertIn('timestamp', prompt)


if __name__ == '__main__':
    unittest.main()
