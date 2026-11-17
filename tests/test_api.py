import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from studio.service import Service
from studio.api import ApiServer

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.s=Service(self.root,self.root/'data',start_worker=False);self.api=ApiServer(self.s,port=0);self.api.start()
    def tearDown(self): self.api.close();self.s.close();self.tmp.cleanup()
    def call(self,path,method='GET',data=None,token=True,headers=None):
        h={'Content-Type':'application/json'}
        if token: h['Authorization']='Bearer '+self.s.paths.token
        h.update(headers or {})
        req=Request(self.api.endpoint+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
        with urlopen(req,timeout=5) as r:return json.load(r)
    def test_private_routes_require_token(self):
        with self.assertRaises(HTTPError) as cm:self.call('/api/v1/assets',token=False)
        self.assertEqual(cm.exception.code,401)
        self.assertNotIn(self.s.paths.token,cm.exception.read().decode())
    def test_website_cannot_drive_loopback_api(self):
        with self.assertRaises(HTTPError) as cm:self.call('/api/v1/assets',headers={'Origin':'https://evil.example'})
        self.assertEqual(cm.exception.code,403)
    def test_ai_can_add_asset_edit_and_read_same_state(self):
        p=self.root/'a.mp4';p.write_bytes(b'video')
        a=self.call('/api/v1/assets','POST',{'path':str(p)})
        self.call('/api/v1/assets/'+a['id'],'PUT',{'summary':'真实摘要'})
        self.assertEqual(self.s.assets()[0]['summary'],'真实摘要')
        self.assertEqual(self.call('/api/v1/assets')[0]['id'],a['id'])
    def test_unknown_action_and_invalid_json_do_not_create_jobs(self):
        with self.assertRaises(HTTPError):self.call('/api/v1/jobs','POST',{'action':'shell','platform':'douyin','command':'bad'})
        self.assertEqual(self.s.jobs(),[])
    def test_openapi_has_real_job_and_operation_routes(self):
        doc=self.call('/api/v1/openapi.json',token=False)
        self.assertIn('/api/v1/packages/import',doc['paths'])
        self.assertIn('/api/v1/jobs/{id}/cancel',doc['paths'])
    def test_wrong_methods_cannot_mutate(self):
        p=self.root/'a.mp4';p.write_bytes(b'video')
        for route,body in [('/assets',{'path':str(p)}),('/jobs',{'platform':'douyin','action':'login'}),('/settings',{'llm':{'model':'unexpected'}}),('/evidence/import',{'items':[]})]:
            with self.subTest(route=route):
                with self.assertRaises(HTTPError) as cm:self.call('/api/v1'+route,'PUT',body)
                self.assertEqual(cm.exception.code,405)
                self.assertIn('POST',cm.exception.headers['Allow'])
        self.assertEqual(self.s.assets(),[]);self.assertEqual(self.s.jobs(),[])
        self.assertEqual(self.s.settings()['llm']['model'],'')
    def test_routes_match_whole_path_and_require_version(self):
        p=self.root/'a.mp4';p.write_bytes(b'video')
        a=self.call('/api/v1/assets','POST',{'path':str(p)})
        for route in ('/assets','/api/v1/assets/'+a['id']+'/extra'):
            with self.assertRaises(HTTPError) as cm:self.call(route,'PUT',{'summary':'bad'})
            self.assertEqual(cm.exception.code,404)
        self.assertEqual(self.s.assets()[0]['summary'],'')
    def test_schema_refs_are_complete_and_request_response_shapes_are_typed(self):
        doc=self.call('/api/v1/openapi.json',token=False);schemas=doc['components']['schemas']
        for expected in ('Asset','AssetCreate','AssetUpdate','Draft','DraftCreate','Evidence','Job','JobCreate','Settings','SettingsUpdate','Brief','Error','Event','Account'):
            self.assertIn(expected,schemas)
        def walk(value):
            if isinstance(value,dict):
                if '$ref' in value:self.assertIn(value['$ref'].removeprefix('#/components/schemas/'),schemas)
                for child in value.values():walk(child)
            elif isinstance(value,list):
                for child in value:walk(child)
        walk(doc)
        for route,item in doc['paths'].items():
            for method,operation in item.items():
                self.assertIn('content',operation['responses']['200'])
                if method in ('post','put') and not route.endswith('/cancel'):
                    self.assertIn('$ref',operation['requestBody']['content']['application/json']['schema'])
        qrcode=doc['paths']['/api/v1/jobs/{id}/qrcode']['get']['responses']['200']['content']
        self.assertEqual(qrcode['image/png']['schema']['format'],'binary')
    def test_post_cancel_and_put_asset_still_work(self):
        p=self.root/'a.mp4';p.write_bytes(b'video')
        asset=self.call('/api/v1/assets','POST',{'path':str(p)})
        self.call('/api/v1/assets/'+asset['id'],'PUT',{'summary':'okay'})
        job=self.call('/api/v1/jobs','POST',{'platform':'douyin','action':'login'})
        with self.assertRaises(HTTPError) as cm:self.call('/api/v1/jobs/'+job['id']+'/cancel','PUT',{})
        self.assertEqual(cm.exception.code,405)
        self.assertEqual(self.call('/api/v1/jobs/'+job['id']+'/cancel','POST',{})['status'],'cancelled')
        self.assertEqual(self.call('/api/v1/jobs/'+job['id'])['status'],'cancelled')
        self.assertIsInstance(self.call('/api/v1/jobs/'+job['id']+'/events'),list)
        self.assertEqual(self.call('/api/v1/assets')[0]['summary'],'okay')
    def test_supported_content_workflow_and_settings_still_work(self):
        p=self.root/'a.mp4';p.write_bytes(b'video')
        asset=self.call('/api/v1/assets','POST',{'path':str(p),'summary':'模型外观演示'})
        evidence=self.call('/api/v1/evidence/import','POST',{'items':[{'platform':'bilibili','title':'公开研究样本','source_url':'https://example.com/research','verification':'unverified'}]})['items'][0]
        brief=self.call('/api/v1/briefs/'+asset['id'])
        self.assertEqual(brief['asset']['id'],asset['id']);self.assertIn('response_schema',brief)
        package={'platform':'bilibili','title':'模型外观演示','caption':'本片展示模型外观。','tags':['模型'],'evidence_ids':[evidence['id']],'fit_reason':'与视频模型主题有关；不作实时热度推断'}
        result=self.call('/api/v1/packages/import','POST',{'asset_id':asset['id'],'packages':[package]})
        self.assertEqual(result['count'],1);self.assertEqual(self.call('/api/v1/drafts')[0]['title'],package['title'])
        settings=self.call('/api/v1/settings','POST',{'llm':{'model':'local-test'}})
        self.assertEqual(settings['llm']['model'],'local-test');self.assertNotIn('api_key',settings['llm'])
        self.assertEqual(len(self.call('/api/v1/accounts')),2)
        self.assertTrue(self.call('/health',token=False)['ok'])
    def test_other_wrong_methods_are_json_405_and_do_not_write(self):
        for method in ('PATCH','DELETE','OPTIONS'):
            with self.assertRaises(HTTPError) as cm:self.call('/api/v1/settings',method,{'llm':{'model':'bad'}})
            self.assertEqual(cm.exception.code,405)
            self.assertEqual(json.load(cm.exception)['error']['code'],'method_not_allowed')
        self.assertEqual(self.s.settings()['llm']['model'],'')

if __name__=='__main__':unittest.main()
