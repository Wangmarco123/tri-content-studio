"""Supervision safety with real isolated storage and fake owned processes only."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from studio.service import Service
from studio.jobs import JobManager


class WorkerCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.service=Service(self.root,self.root/'data',start_worker=False)
        video=self.root/'fixture.mp4';video.write_bytes(b'local-supervision-fixture')
        asset=self.service.add_asset({'path':str(video)})
        draft=self.service.save_draft({'asset_id':asset['id'],'platform':'douyin','title':'isolated','tags':[]})
        self.payload={'platform':'douyin','action':'publish','draft_id':draft['id'],'visibility':'private','idempotency_key':'initial'}
        self.job=self.service.create_job(self.payload)
        self.manager=JobManager(self.service)
    def tearDown(self):self.service.close();self.temp.cleanup()

    def test_event_reader_failure_stops_and_reaps_owned_process(self):
        class LiveProcess:
            terminated=False
            reaped=False
            def poll(self):return None if not self.terminated else -15
            def terminate(self):self.terminated=True
            def kill(self):self.terminated=True
            def wait(self,timeout=None):self.reaped=True;return -15
        proc=LiveProcess()
        with patch('studio.jobs.subprocess.Popen',return_value=proc),patch.object(self.manager,'read_events',side_effect=OSError('injected event read failure')):
            try:self.manager.run_one(self.job)
            except OSError:pass
        self.assertTrue(proc.terminated,'A supervision exception must not leave its platform worker running')
        self.assertTrue(proc.reaped,'Owned platform worker must be waited/reaped after stop')

    def test_invalid_result_after_submit_is_unknown_and_blocks_republish(self):
        service=self.service;job=self.job
        class FinishedProcess:
            def __init__(self,*args,**kwargs):
                folder=service.paths.data_dir/'jobs'/job['id']
                (folder/'events.jsonl').write_text(json.dumps({'stage':'submit_requested','message':'submission attempted'})+'\n',encoding='utf-8')
                (folder/'result.json').write_text(json.dumps({'status':'invalid_protocol_status','message':'untrusted terminal result'}),encoding='utf-8')
            def poll(self):return 0
            def wait(self,timeout=None):return 0
        with patch('studio.jobs.subprocess.Popen',FinishedProcess):self.manager.run_one(self.job)
        self.assertEqual(self.service.get_job(self.job['id'])['status'],'outcome_unknown')
        with self.assertRaises(ValueError):self.service.create_job(dict(self.payload,idempotency_key='different-key'))

    def test_cancel_during_hash_never_launches_worker(self):
        def cancelled_hash(path):
            self.service.cancel_job(self.job['id'])
            return self.job['payload']['sha256']
        with patch('studio.jobs.file_hash',side_effect=cancelled_hash),patch('studio.jobs.subprocess.Popen') as launch:
            self.manager.run_one(self.job)
        launch.assert_not_called()
        self.assertEqual(self.service.get_job(self.job['id'])['status'],'cancelled')

    def test_windows_case_alias_cannot_bypass_unknown_submission(self):
        self.service.store.update('jobs',self.job['id'],{'status':'outcome_unknown'})
        with self.assertRaises(ValueError):
            self.service.create_job(dict(self.payload,account='Creator',idempotency_key='case-alias'))

    def test_legacy_case_alias_unknown_submission_also_blocks(self):
        snapshot=dict(self.job['payload'],account='CREATOR')
        fingerprint=hashlib.sha256(json.dumps(['douyin','CREATOR','publish',snapshot],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        self.service.store.update('jobs',self.job['id'],{'status':'outcome_unknown','account':'CREATOR','payload':snapshot,'fingerprint':fingerprint})
        with self.assertRaises(ValueError):
            self.service.create_job(dict(self.payload,account='creator',idempotency_key='legacy-case'))


if __name__=='__main__':unittest.main()
