import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
from studio.core import redact
from studio.service import Service
from studio.jobs import JobManager
from studio.adapters import execute

class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.s=Service(self.root,self.root/'data',start_worker=False)
        self.video=self.root/'v.mp4';self.video.write_bytes(b'video')
        self.asset=self.s.add_asset({'path':str(self.video)})
        self.draft=self.s.save_draft({'asset_id':self.asset['id'],'platform':'douyin','title':'test','caption':'facts','tags':[]})
    def tearDown(self):
        self.s.worker=None;self.s.close();self.tmp.cleanup()
    def test_redaction_header_json_and_nested_values(self):
        for text in ('Authorization: Bearer SYNTHETIC_TEST_SECRET','{"api_key":"SYNTHETIC_TEST_SECRET"}','Cookie: SID=SYNTHETIC_TEST_SECRET; other=SYNTHETIC_TEST_SECRET',json.dumps({'nested':{'access_token':'SYNTHETIC_TEST_SECRET'}})):
            self.assertNotIn('SYNTHETIC_TEST_SECRET',redact(text))
    def test_explicit_platform_cannot_be_silently_changed(self):
        with self.assertRaises(ValueError):self.s.create_job({'platform':'bilibili','action':'publish','draft_id':self.draft['id'],'visibility':'private'})
        self.assertEqual(self.s.jobs(),[])
    def test_idempotency_key_conflict_is_rejected(self):
        self.s.create_job({'action':'login','platform':'douyin','idempotency_key':'one'})
        with self.assertRaises(ValueError):self.s.create_job({'action':'login','platform':'xiaohongshu','idempotency_key':'one'})
    def test_unknown_result_blocks_new_copy_or_draft_for_same_asset_account(self):
        j=self.s.create_job({'action':'publish','draft_id':self.draft['id'],'visibility':'private'})
        self.s.store.update('jobs',j['id'],{'status':'outcome_unknown'})
        copy=self.s.save_draft(dict(self.draft,id=None,title='revised'))
        for action in ('publish','draft'):
            with self.assertRaises(ValueError):self.s.create_job({'action':action,'draft_id':copy['id'],'visibility':'private'})
    def test_vendor_exception_during_publish_stays_unknown(self):
        job={'platform':'bilibili','action':'publish','payload':{'file':str(self.video),'title':'test','tags':[],'visibility':'private'}}
        with patch('studio.adapters._bili',side_effect=ValueError('vendor response broke')):
            value=execute(job,{'engine_root':str(self.root),'state_root':str(self.root/'state')},lambda e:None)
        self.assertEqual(value['status'],'outcome_unknown')
    def test_package_database_failure_rolls_back_all_drafts(self):
        payload={'asset_id':self.asset['id'],'packages':[{'platform':'bilibili','title':'Bili','caption':'facts','tags':[]},{'platform':'xiaohongshu','title':'XHS','caption':'facts','tags':[]}]}
        original=self.s.store.put;calls=[]
        def fail_second(table,record):
            if table=='drafts':
                calls.append(1)
                if len(calls)==2:raise OSError('simulated disk failure')
            return original(table,record)
        before=self.s.drafts()
        with patch.object(self.s.store,'put',side_effect=fail_second):
            with self.assertRaises(OSError):self.s.import_packages(payload)
        self.assertEqual(self.s.drafts(),before)
    def test_failed_close_can_be_retried(self):
        worker=Mock();worker.stop.side_effect=[RuntimeError('still stopping'),None];self.s.worker=worker
        with self.assertRaises(RuntimeError):self.s.close()
        self.assertFalse(self.s.closed)
        self.s.close();self.assertEqual(worker.stop.call_count,2);self.assertTrue(self.s.closed)
    def test_worker_failure_after_submit_is_unknown_and_not_requeued(self):
        j=self.s.create_job({'action':'publish','draft_id':self.draft['id'],'visibility':'private'})
        self.s.store.update('jobs',j['id'],{'stage':'submit_requested'})
        manager=JobManager(self.s)
        def fail(job):
            manager.stopping.set()
            raise json.JSONDecodeError('truncated','{',1)
        with patch.object(manager,'run_one',side_effect=fail):manager.loop()
        self.assertEqual(self.s.get_job(j['id'])['status'],'outcome_unknown')
        with self.assertRaises(ValueError):self.s.create_job({'action':'publish','draft_id':self.draft['id'],'visibility':'private','idempotency_key':'new'})

if __name__=='__main__':unittest.main()
