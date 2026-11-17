import json
import tempfile
import unittest
from pathlib import Path

from studio.service import Service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.video = self.root / '中文 video.mp4'
        self.video.write_bytes(b'functional-test-video')
        self.s = Service(self.root, self.root / 'data', start_worker=False)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def asset(self):
        return self.s.add_asset({'path':str(self.video),'summary':'真实的模型演示','facts':['展示外观']})

    def draft(self):
        a = self.asset()
        return self.s.save_draft({'asset_id':a['id'],'platform':'douyin','title':'模型演示','caption':'展示实际模型','tags':['#模型']})

    def test_asset_hash_deduplicates_and_survives_restart(self):
        a = self.asset()
        self.assertEqual(self.asset()['id'], a['id'])
        self.s.close()
        self.s = Service(self.root,self.root/'data',start_worker=False)
        self.assertEqual(self.s.assets()[0]['sha256'],a['sha256'])

    def test_draft_default_is_not_public(self):
        d = self.draft()
        self.assertEqual(d['visibility'],'draft')
        self.assertEqual(d['tags'],['模型'])

    def test_publish_requires_explicit_visibility(self):
        d = self.draft()
        with self.assertRaises(ValueError):
            self.s.create_job({'action':'publish','draft_id':d['id']})
        self.assertEqual(self.s.jobs(),[])

    def test_idempotent_job_uses_frozen_content(self):
        d = self.draft()
        j = self.s.create_job({'action':'draft','draft_id':d['id'],'idempotency_key':'once'})
        same = self.s.create_job({'action':'draft','draft_id':d['id'],'idempotency_key':'once'})
        self.assertEqual(j['id'],same['id'])
        d['title']='编辑后的标题'
        self.s.save_draft(d)
        self.assertEqual(self.s.get_job(j['id'])['payload']['title'],'模型演示')

    def test_unknown_submission_cannot_be_reissued(self):
        d = self.draft()
        j = self.s.create_job({'action':'publish','draft_id':d['id'],'visibility':'private'})
        self.s.store.update('jobs',j['id'],{'status':'outcome_unknown'})
        with self.assertRaises(ValueError):
            self.s.create_job({'action':'publish','draft_id':d['id'],'visibility':'private','idempotency_key':'another'})

    def test_changed_asset_is_rejected_before_enqueue(self):
        d = self.draft()
        self.video.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.s.create_job({'action':'draft','draft_id':d['id']})

    def test_evidence_import_is_atomic(self):
        with self.assertRaises(ValueError):
            self.s.import_evidence({'items':[{'platform':'douyin','title':'ok','source_url':'https://www.douyin.com/hot/1'},{'platform':'unknown','title':'bad','source_url':'file:///secret'}]})
        self.assertEqual(self.s.evidence(),[])

    def test_cancel_queued_never_runs(self):
        j=self.s.create_job({'action':'login','platform':'douyin'})
        self.assertEqual(self.s.cancel_job(j['id'])['status'],'cancelled')

    def test_account_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            self.s.create_job({'action':'login','platform':'douyin','account':'../outside'})

    def test_settings_never_return_secret(self):
        self.s.save_settings({'llm':{'base_url':'https://example.com/v1','model':'test','api_key':'test-private-key'}})
        self.assertNotIn('test-private-key',json.dumps(self.s.settings()))
        self.assertTrue(self.s.settings()['llm']['has_api_key'])
        disk=''.join(p.read_text(errors='ignore') for p in (self.root/'data').glob('*.json'))
        self.assertNotIn('test-private-key',disk)

    def test_recovery_marks_running_submission_unknown(self):
        d=self.draft()
        j=self.s.create_job({'action':'publish','draft_id':d['id'],'visibility':'private'})
        self.s.store.update('jobs',j['id'],{'status':'running','stage':'submit_requested'})
        self.s.close()
        self.s=Service(self.root,self.root/'data',start_worker=False)
        self.assertEqual(self.s.get_job(j['id'])['status'],'outcome_unknown')

if __name__=='__main__': unittest.main()
