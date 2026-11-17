import unittest,tempfile
import json,io
from unittest.mock import patch
from pathlib import Path
from studio.service import Service
from studio.publications import extract_records

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Service(self.root,self.root/'data',start_worker=False)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def test_records_whitelist_excludes_tokens(self):
        rows=extract_records({'data':{'notes':[{'id':'abc','display_title':'作品','xsec_token':'SECRET','time':'2026-11-16 01:00'}]}},'xiaohongshu')
        self.assertEqual(rows[0]['remote_id'],'abc');self.assertNotIn('SECRET',str(rows))
    def test_same_bytes_different_asset_path_block_unknown(self):
        ids=[]
        for name in ('a.mp4','b.mp4'):
            p=self.root/name;p.write_bytes(b'same video');ids.append(self.s.add_asset({'path':str(p)})['id'])
        old=self.s.save_draft({'asset_id':ids[0],'platform':'douyin','title':'旧稿','caption':'说明','tags':[]})
        job=self.s.create_job({'action':'publish','draft_id':old['id'],'visibility':'public'})
        self.s.store.update('jobs',job['id'],{'status':'outcome_unknown'})
        new=self.s.save_draft({'asset_id':ids[1],'platform':'douyin','title':'新稿','caption':'说明','tags':[]})
        with self.assertRaises(ValueError):self.s.create_job({'action':'publish','draft_id':new['id'],'visibility':'public'})
    def test_query_action_is_read_only_empty_snapshot(self):
        job=self.s.query_publications({'platform':'douyin'});self.assertEqual(job['action'],'query_publications');self.assertEqual(job['payload'],{})
    def test_absent_remote_cannot_reconcile(self):
        self.s.store.put('jobs',{'id':'old','action':'publish','status':'outcome_unknown','platform':'douyin','account':'creator','payload':{}})
        self.s.store.put('jobs',{'id':'q','action':'query_publications','status':'complete','platform':'douyin','account':'creator','result':{'items':[]}})
        with self.assertRaises(ValueError):self.s.reconcile_publication('old',{'query_job_id':'q','remote_id':'missing'})
        self.assertEqual(self.s.get_job('old')['status'],'outcome_unknown')
    def test_submit_marker_prevents_clearing_unknown(self):
        self.s.store.put('jobs',{'id':'old','action':'publish','status':'outcome_unknown','platform':'douyin','account':'creator','payload':{},'result':{'message':'平台操作停止（ValueError）'}})
        self.s.store.put('jobs',{'id':'q','action':'query_publications','status':'complete','platform':'douyin','account':'creator','result':{'items':[]}})
        self.s.add_event('old',{'stage':'submit_requested','message':'提交一次'})
        with self.assertRaises(ValueError):self.s.resolve_unsubmitted('old',{'query_job_id':'q'})
    def test_pre_submit_failure_requires_same_account_query(self):
        self.s.store.put('jobs',{'id':'old','action':'publish','status':'outcome_unknown','platform':'douyin','account':'creator','payload':{},'result':{'message':'平台操作停止（ValueError）'}})
        self.s.add_event('old',{'stage':'prepared','message':'尚未发布'})
        self.s.store.put('jobs',{'id':'q','action':'query_publications','status':'complete','platform':'douyin','account':'other','result':{'items':[]}})
        with self.assertRaises(ValueError):self.s.resolve_unsubmitted('old',{'query_job_id':'q'})
        self.s.store.update('jobs','q',{'account':'creator'})
        self.assertFalse(self.s.resolve_unsubmitted('old',{'query_job_id':'q'})['result']['evidence']['submission_attempted'])
    def test_cannot_update_unmatched_archive(self):
        p=self.root/'a.mp4';p.write_bytes(b'video');a=self.s.add_asset({'path':str(p)})
        d=self.s.save_draft({'asset_id':a['id'],'platform':'bilibili','title':'作品','caption':'文案','tags':[]})
        with self.assertRaises(ValueError):self.s.create_job({'action':'update_publication','draft_id':d['id'],'visibility':'private','matched_job_id':'missing'})
    def test_bili_updates_one_existing_archive_and_reads_private(self):
        from studio.publications import update_bilibili
        state=self.root/'cookies.json';state.write_text(json.dumps({'cookie_info':{'cookies':[{'name':'bili_jct','value':'test-only'}]}}))
        before={'code':0,'data':{'archive':{'bvid':'BV1example0001','aid':123,'title':'old','desc':'old','is_only_self':0,'copyright':1,'tid':1},'videos':[{'filename':'existing-file','title':'part'}]}}
        after={'code':0,'data':{'archive':{'bvid':'BV1example0001','title':'new','desc':'caption','is_only_self':1}}}
        class Opener:
            def __init__(self):self.calls=[]
            def open(self,request,timeout):self.calls.append(request);return io.BytesIO(b'{"code":0}')
        opener=Opener()
        with patch('studio.adapters._json_http',side_effect=[before,after]),patch('urllib.request.build_opener',return_value=opener):
            result=update_bilibili(state,{'remote_id':'BV1example0001','title':'new','caption':'caption','tags':['tag'],'visibility':'private'},{},lambda e:None)
        self.assertEqual(len(opener.calls),1);body=json.loads(opener.calls[0].data);self.assertEqual(body['aid'],123);self.assertEqual(body['videos'][0]['filename'],'existing-file');self.assertEqual(body['is_only_self'],1)
        self.assertEqual(result['status'],'submitted');self.assertTrue(result['evidence']['readback_verified']);self.assertFalse(result['evidence']['new_video_uploaded'])

if __name__=='__main__':unittest.main()
