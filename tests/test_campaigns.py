import tempfile
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from studio.service import Service

def fixture(asset_id):
    return {'asset_id':asset_id,'summary':'抽样画面中的功能测试片','opportunities':[],'fit_assessments':[],'no_trend_reason':'测试片不适合借势实时热点','research_sources':[],
      'packages':[{'platform':p,'title':'功能测试','title_candidates':['功能测试','六秒测试'],'caption':'仅功能测试，未承诺流量。','tags':['功能测试'],'hook':'先看功能测试','category_suggestion':'科技·软件应用' if p=='bilibili' else '', 'search_keywords':['功能测试'] if p=='xiaohongshu' else [],'visibility':'draft','evidence_ids':[],'fit_reason':'围绕测试内容本身','tag_checks':[]} for p in ('bilibili','douyin','xiaohongshu')]}

class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Service(self.root,self.root/'data',start_worker=False)
        self.speech_patch=patch('studio.campaigns.transcribe_video',return_value={'status':'no_audio','complete':True,'audio_duration':0,'processed_duration':0,'segments':[],'text':''});self.speech_patch.start();self.addCleanup(self.speech_patch.stop)
        video=self.root/'test.mp4';video.write_bytes(b'fixture');self.asset=self.s.add_asset({'path':str(video)})
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def wait(self,cid):
        for _ in range(100):
            record=self.s.get_campaign(cid)
            if record['status'] not in ('queued','running'):return record
            time.sleep(.02)
        self.fail('campaign never finished')
    def test_one_click_saves_all_five_sections_and_three_local_drafts(self):
        media={'duration':6,'width':1280,'height':720,'frames':[],'transcript':[],'analysis_scope':'sampled_frames_and_supplied_subtitles','warnings':[]}
        with patch('studio.campaigns.analyze_media',return_value=media),patch('studio.campaigns.fetch_trends',return_value={'items':[]}),patch('studio.campaigns.run_codex',return_value=fixture(self.asset['id'])),patch('studio.campaigns.codex_status',return_value={'available':True,'logged_in':True}):
            c=self.s.start_campaign({'asset_id':self.asset['id']});r=self.wait(c['id'])
        self.assertEqual(r['status'],'complete',r)
        self.assertEqual(len(r['result']['packages']),3);self.assertEqual(len(self.s.drafts()),3)
        self.assertEqual(self.s.jobs(),[])
        saved=self.s.save_campaign({'id':r['id'],'selections':{'bilibili':1,'xiaohongshu':1}})
        self.assertEqual(saved['count'],3);self.assertEqual(len(self.s.drafts()),3)
        self.assertEqual(next(x for x in self.s.drafts() if x['platform']=='bilibili')['title'],'六秒测试')
    def test_no_ai_does_not_create_fake_results(self):
        with patch('studio.campaigns.codex_status',return_value={'available':False,'logged_in':False}):
            r=self.wait(self.s.start_campaign({'asset_id':self.asset['id']})['id'])
        self.assertEqual(r['status'],'failed');self.assertIsNone(r['result']);self.assertEqual(self.s.drafts(),[])
    def test_discovered_source_cannot_replace_existing_evidence_or_use_foreign_domain(self):
        from studio.campaigns import normalize_sources
        data=fixture(self.asset['id']);data['research_sources']=[{'id':'existing','platform':'douyin','title':'topic','source_url':'https://evil.invalid/x'}]
        with self.assertRaises(ValueError):normalize_sources(data,'campaign_1')
        data['research_sources'][0]['source_url']='https://www.douyin.com/hot/123'
        result,sources=normalize_sources(data,'campaign_1')
        self.assertNotEqual(sources[0]['id'],'existing');self.assertEqual(sources[0]['verification'],'ai_researched')
        self.assertNotIn('research_sources',result)

if __name__=='__main__':unittest.main()
