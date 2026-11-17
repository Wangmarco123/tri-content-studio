"""Real loopback/CLI/MCP transport tests with a stub AI, no platform worker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from studio.api import ApiServer,openapi_document
from studio.service import Service
from studio import mcp_server
from studio import __version__


class CampaignTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='方案 clients ');self.root=Path(self.tmp.name)
        self.s=Service(self.root,self.root/'data',start_worker=False)
        video=self.root/'测试.mp4';video.write_bytes(b'not uploaded')
        self.asset=self.s.add_asset({'path':str(video),'summary':'工具上传演示'})
        self.started=[]
        self.s.ai_status=lambda:{'codex':{'available':True,'logged_in':True,'message':'stub, no invocation'},'api':{'configured':False},'default_provider':'codex'}
        def start(payload):
            self.started.append(payload)
            packages=[]
            for platform in ('bilibili','douyin','xiaohongshu'):
                packages.append({'platform':platform,'title':'标题一','title_candidates':['标题一','标题二'],'caption':'实际演示',
                    'tags':['工具'],'hook':'先看操作','category_suggestion':'软件','search_keywords':['上传工具'],
                    'visibility':'draft','evidence_ids':[],'fit_reason':'原片内容','tag_checks':[]})
            result={'id':'campaign_fixture','asset_id':self.asset['id'],'status':'complete','stage':'complete','progress':100,
                    'message':'stub AI completed','provider':payload.get('provider','auto'),'result':{'packages':packages},'draft_ids':[]}
            return self.s.store.put('campaigns',result)
        self.s.start_campaign=start
        self.s.cancel_campaign=lambda cid:self.s.store.update('campaigns',cid,{'status':'cancelled','message':'stub cancelled'})
        self.api=ApiServer(self.s,port=0);self.api.start()
        self.prefix=[sys.executable,'-m','studio.cli','--home',str(self.root),'--data-dir',str(self.root/'data'),
                     '--endpoint',self.api.endpoint,'--token-file',str(self.s.paths.token_path)]
        self.cwd=Path(__file__).resolve().parents[1]
    def tearDown(self):self.api.close();self.s.close();self.tmp.cleanup()
    def call(self,path,method='GET',payload=None,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+self.s.paths.token
        request=Request(self.api.endpoint+'/api/v1'+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers,method=method)
        with urlopen(request,timeout=10) as r:return json.load(r)
    def cli(self,*args):
        r=subprocess.run(self.prefix+list(args),cwd=self.cwd,env=dict(os.environ,PYTHONUTF8='1'),capture_output=True,encoding='utf-8',timeout=15)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        return json.loads(r.stdout)
    def mcp(self,messages):
        r=subprocess.run(self.prefix+['mcp'],input=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in messages),cwd=self.cwd,
                         env=dict(os.environ,PYTHONUTF8='1'),capture_output=True,encoding='utf-8',timeout=15)
        self.assertEqual(r.returncode,0,r.stderr)
        return [json.loads(line) for line in r.stdout.splitlines()]

    def test_http_campaign_start_poll_save_and_cancel_never_publish(self):
        self.assertEqual(self.call('/ai/status')['default_provider'],'codex')
        c=self.call('/campaigns','POST',{'asset_id':self.asset['id'],'provider':'auto','goal':'只做运营'})
        self.assertEqual(self.call('/campaigns/'+c['id'])['status'],'complete')
        self.assertEqual(len(self.call('/campaigns')),1)
        saved=self.call('/campaigns/'+c['id']+'/save','POST',{'selections':{'bilibili':1,'xiaohongshu':1},'queue_drafts':True})
        self.assertEqual(saved['count'],3)
        self.assertEqual({j['action'] for j in saved['jobs']},{'draft'})
        self.assertEqual({j['platform'] for j in saved['jobs']},{'douyin'})
        self.assertEqual(next(d['title'] for d in saved['items'] if d['platform']=='bilibili'),'标题二')
        self.assertEqual(self.call('/campaigns/'+c['id']+'/cancel','POST',{})['status'],'cancelled')

    def test_campaign_auth_exact_methods_and_openapi(self):
        with self.assertRaises(HTTPError) as error:self.call('/ai/status',token=False)
        self.assertEqual(error.exception.code,401)
        with self.assertRaises(HTTPError) as error:self.call('/campaigns','PUT',{'asset_id':self.asset['id']})
        self.assertEqual(error.exception.code,405)
        self.assertFalse(self.started)
        doc=openapi_document(self.api.endpoint)
        self.assertIn('/api/v1/campaigns/{id}/save',doc['paths'])
        self.assertIn('Campaign',doc['components']['schemas'])
        self.assertEqual(doc['info']['version'],__version__)
        with self.assertRaises(HTTPError) as error:self.call('/campaigns','POST',{'asset_id':self.asset['id'],'provider':'invalid'})
        self.assertEqual(error.exception.code,400)
        self.assertFalse(self.started)

    def test_cli_plan_commands_utf8_and_default_local_save(self):
        self.assertEqual(self.cli('ai-status')['default_provider'],'codex')
        c=self.cli('plan','--asset-id',self.asset['id'],'--provider','auto','--goal','只研究不发布')
        self.assertEqual(self.started[0]['goal'],'只研究不发布')
        self.assertEqual(self.cli('plan-status',c['id'])['id'],c['id'])
        saved=self.cli('plan-save',c['id'],'--bili-title-index','1','--xhs-title-index','0')
        self.assertEqual(saved['jobs'],[])
        self.assertEqual(self.s.jobs(),[])
        self.assertEqual(self.cli('plan-cancel',c['id'])['status'],'cancelled')

    def test_mcp_has_17_tools_and_campaign_end_to_end(self):
        messages=[{'jsonrpc':'2.0','id':1,'method':'tools/list'},
            {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'start_campaign','arguments':{'asset_id':self.asset['id'],'provider':'auto'}}},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'save_campaign','arguments':{'id':'campaign_fixture','selections':{'bilibili':1},'queue_drafts':False}}},
            {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'get_campaign','arguments':{'id':'campaign_fixture'}}},
            {'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'ai_status','arguments':{}}},
            {'jsonrpc':'2.0','id':6,'method':'tools/call','params':{'name':'list_campaigns','arguments':{}}},
            {'jsonrpc':'2.0','id':7,'method':'tools/call','params':{'name':'cancel_campaign','arguments':{'id':'campaign_fixture'}}},
            {'jsonrpc':'2.0','id':8,'method':'initialize','params':{'protocolVersion':'2024-11-05'}}]
        replies=self.mcp(messages)
        self.assertEqual(len(replies[0]['result']['tools']),21)
        saved=json.loads(replies[2]['result']['content'][0]['text'])
        self.assertEqual(saved['count'],3);self.assertEqual(saved['jobs'],[])
        self.assertEqual(json.loads(replies[6]['result']['content'][0]['text'])['status'],'cancelled')
        self.assertEqual(replies[7]['result']['serverInfo']['version'],__version__)
        self.assertEqual(self.s.jobs(),[])

    def test_mcp_rejects_boolean_index_and_false_string(self):
        tool=next(t for t in mcp_server.TOOLS if t[0]=='save_campaign')
        for args in ({'id':'x','selections':{'bilibili':True}}, {'id':'x','queue_drafts':'false'}, {'id':'x','selections':{'bilibili':-1}}):
            with self.subTest(args=args),self.assertRaises(ValueError):mcp_server.arguments_for(tool,{'arguments':args})

    def test_mcp_invalid_index_returns_protocol_error_and_continues(self):
        replies=self.mcp([
            {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'save_campaign','arguments':{'id':'x','queue_drafts':'false'}}},
            {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'ai_status','arguments':{}}}])
        self.assertEqual(replies[0]['error']['code'],-32602)
        self.assertEqual(replies[0]['id'],1)
        self.assertEqual(json.loads(replies[1]['result']['content'][0]['text'])['default_provider'],'codex')
        self.assertEqual(self.s.jobs(),[])

if __name__=='__main__':unittest.main()
