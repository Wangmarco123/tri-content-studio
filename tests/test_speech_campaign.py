import tempfile,time
from pathlib import Path
import unittest
from unittest.mock import patch
from studio.service import Service
from test_campaigns import fixture

def speech(complete=True):
    rows=[{'start':i,'end':i+.5,'text':'完整口播第'+str(i)+'段','avg_logprob':-.1,'no_speech_prob':.01,'uncertain':False} for i in range(250)]
    return {'status':'complete','complete':complete,'audio_duration':250,'processed_duration':250 if complete else 100,'segments':rows,'text':'\n'.join(r['text'] for r in rows),'model':'large-v3-turbo','device':'cpu','language':'zh','warnings':[],'cache_hit':False}

class SpeechCampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Service(self.root,self.root/'data',start_worker=False)
        video=self.root/'fixture.mp4';video.write_bytes(b'fake');self.asset=self.s.add_asset({'path':str(video)})
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def wait(self,cid):
        for _ in range(150):
            record=self.s.get_campaign(cid)
            if record['status'] not in ('queued','running'):return record
            time.sleep(.01)
        self.fail('campaign did not finish')
    def run_case(self,spoken,provider):
        media={'duration':250,'width':1280,'height':720,'frames':[],'transcript':spoken['segments'],'speech':spoken,'analysis_scope':'sampled_frames_and_full_audio_transcript','warnings':[]}
        with patch('studio.campaigns.transcribe_video',return_value=spoken,create=True) as transcribe,patch('studio.campaigns.analyze_media',return_value=media) as analyze,patch('studio.campaigns.fetch_trends',return_value={'items':[]}),patch('studio.campaigns.codex_status',return_value={'logged_in':True}),patch('studio.campaigns.run_codex',side_effect=provider):
            record=self.wait(self.s.start_campaign({'asset_id':self.asset['id']})['id'])
        return record,transcribe,analyze
    def test_whole_transcript_reaches_ai_after_automatic_asr(self):
        prompts=[]
        def provider(prompt,*a,**k):prompts.append(prompt);return fixture(self.asset['id'])
        record,transcribe,analyze=self.run_case(speech(),provider)
        self.assertEqual(record['status'],'complete',record)
        transcribe.assert_called_once();self.assertIn('speech',analyze.call_args.kwargs)
        self.assertIn('完整口播第249段',prompts[0]);self.assertNotIn('没有听过音频',prompts[0])
    def test_partial_asr_does_not_generate_or_save_complete_scheme(self):
        provider=unittest.mock.Mock(return_value=fixture(self.asset['id']))
        record,_,_=self.run_case(speech(False),provider)
        self.assertEqual(record['status'],'failed');provider.assert_not_called();self.assertEqual(self.s.drafts(),[])
    def test_video_changed_during_frame_extraction_stops_before_ai(self):
        provider=unittest.mock.Mock(return_value=fixture(self.asset['id']))
        def changed(*args,**kwargs):
            Path(self.asset['path']).write_bytes(b'replaced after ASR')
            return {'duration':250,'frames':[],'speech':speech(),'transcript':speech()['segments']}
        with patch('studio.campaigns.transcribe_video',return_value=speech()),patch('studio.campaigns.analyze_media',side_effect=changed),patch('studio.campaigns.codex_status',return_value={'logged_in':True}),patch('studio.campaigns.run_codex',provider):
            record=self.wait(self.s.start_campaign({'asset_id':self.asset['id']})['id'])
        self.assertEqual(record['status'],'failed',record);provider.assert_not_called();self.assertEqual(self.s.drafts(),[])
    def test_video_changed_during_ai_stops_before_draft_commit(self):
        def changed(*args,**kwargs):
            Path(self.asset['path']).write_bytes(b'replaced during AI')
            return fixture(self.asset['id'])
        record,_,_=self.run_case(speech(),changed)
        self.assertEqual(record['status'],'failed',record);self.assertEqual(self.s.drafts(),[])

if __name__=='__main__':unittest.main()
