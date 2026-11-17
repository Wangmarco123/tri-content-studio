import json
from pathlib import Path
import tempfile
import sys
import wave
import subprocess
import time
from array import array
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from studio import asr
from studio.ai_provider import GenerationCancelled


class SpeechTests(unittest.TestCase):
    def test_full_iterator_over_200_segments_is_preserved(self):
        class Model:
            def transcribe(self,*args,**kwargs):
                self.kwargs=kwargs
                return (SimpleNamespace(start=i,end=i+1,text=f'第{i}句',avg_logprob=-.2,no_speech_prob=.02) for i in range(251)), SimpleNamespace(language='zh',language_probability=.9)
        model=Model();events=[]
        result=asr.recognize(model,'fixture.wav',251,'cuda','float16',events.append,lambda:False)
        self.assertEqual(len(result['segments']),251)
        self.assertEqual(result['processed_duration'],251)
        self.assertTrue(result['complete'])
        self.assertIn('第250句',result['text'])
        self.assertEqual(events[-1]['progress'],100)
        self.assertTrue(all(e['progress']<100 for e in events[:-1]))

    def test_low_confidence_and_srt_roundtrip_output(self):
        class Model:
            def transcribe(self,*a,**kw):return iter([SimpleNamespace(start=.25,end=1.5,text='待核对品牌',avg_logprob=-1.5,no_speech_prob=.7)]), SimpleNamespace(language='zh',language_probability=.8)
        result=asr.recognize(Model(),'audio.wav',2,'cpu','int8',lambda e:None,lambda:False)
        self.assertEqual(result['uncertain_segments'],[0])
        with tempfile.TemporaryDirectory() as tmp:
            saved=asr.write_outputs(result,Path(tmp),False)
            self.assertIn('00:00:00,250 --> 00:00:01,500',Path(saved['srt_path']).read_text(encoding='utf-8'))
            self.assertEqual(json.loads(Path(saved['json_path']).read_text(encoding='utf-8'))['text'],'待核对品牌')

    def test_lazy_generator_failure_is_not_complete(self):
        def partial():
            yield SimpleNamespace(start=0,end=1,text='开头',avg_logprob=-.2,no_speech_prob=.1)
            raise RuntimeError('fixture failure')
        model=SimpleNamespace(transcribe=lambda *a,**k:(partial(),SimpleNamespace(language='zh',language_probability=.8)))
        with self.assertRaises(RuntimeError):asr.recognize(model,'audio.wav',10,'cuda','float16',lambda e:None,lambda:False)

    def test_cancel_does_not_return_partial_transcript(self):
        model=SimpleNamespace(transcribe=lambda *a,**k:(iter([]),SimpleNamespace(language='zh',language_probability=.8)))
        with self.assertRaises(GenerationCancelled):asr.recognize(model,'audio.wav',10,'cpu','int8',lambda e:None,lambda:True)

    def test_no_speech_is_complete_full_audio(self):
        model=SimpleNamespace(transcribe=lambda *a,**k:(iter([]),SimpleNamespace(language='en',language_probability=.2)))
        result=asr.recognize(model,'audio.wav',100,'cpu','int8',lambda e:None,lambda:False)
        self.assertEqual(result['status'],'no_speech')
        self.assertEqual(result['processed_duration'],100)
        self.assertEqual(result['segments'],[])

    def test_one_gpu_failure_then_one_cpu_attempt_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'fixture.mp4';video.write_bytes(b'whole-video-fixture');work=root/'work'
            model=root/'runtime/asr/models/faster-whisper-large-v3-turbo';model.mkdir(parents=True)
            for file in ('model.bin','config.json','tokenizer.json','vocabulary.json'):(model/file).write_bytes(b'fixture')
            def extracted(*a,**kw):return work/'audio.wav',3
            complete=asr.empty_result('no_speech',3,'cpu','int8')
            with patch.object(asr,'probe_audio',return_value={'index':1}),patch.object(asr,'extract_audio',side_effect=extracted),patch.object(asr,'is_digital_silence',return_value=False),patch.object(asr,'run_worker',side_effect=[ValueError('GPU failed'),complete]) as worker:
                result=asr.transcribe_video({'path':str(video)},work,root)
                self.assertEqual([c.args[3] for c in worker.call_args_list],['cuda','cpu'])
                self.assertEqual(worker.call_count,2)
                self.assertTrue(result['complete'])
            with patch.object(asr,'run_worker',side_effect=AssertionError('cache must avoid worker')):
                cached=asr.transcribe_video({'path':str(video)},root/'other-work',root)
                self.assertTrue(cached['cache_hit'])
                self.assertTrue(Path(cached['txt_path']).is_relative_to(root/'other-work'))

    def test_full_digital_silence_checked_without_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav=Path(tmp)/'audio.wav'
            with wave.open(str(wav),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*64000)
            self.assertTrue(asr.is_digital_silence(wav))
            with wave.open(str(wav),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*63998+b'\x01\0')
            self.assertFalse(asr.is_digital_silence(wav))

    def test_complete_result_rejects_truncated_text_and_bad_time(self):
        result=asr.empty_result('complete',3,'cpu','int8')
        result.update(segments=[{'start':0,'end':1,'text':'完整文字','avg_logprob':-.2,'no_speech_prob':.1,'uncertain':False}],text='被截断',uncertain_segments=[])
        with self.assertRaises(ValueError):asr._valid_complete(result,3)
        result['text']='完整文字';result['segments'][0]['end']=9
        with self.assertRaises(ValueError):asr._valid_complete(result,3)

    def test_cache_checksum_detects_modified_payload(self):
        result=asr.empty_result('no_speech',3,'cpu','int8')
        envelope=asr.cache_document(result,'cache-key','video-hash')
        self.assertEqual(asr.read_cache_document(envelope,'cache-key','video-hash')['audio_duration'],3)
        envelope['result']['text']='伪造缓存'
        with self.assertRaises(ValueError):asr.read_cache_document(envelope,'cache-key','video-hash')

    def test_silent_audio_skips_gpu_even_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'silent.mp4';video.write_bytes(b'fixture');audio=root/'audio.wav'
            with wave.open(str(audio),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*64000)
            with patch.object(asr,'probe_audio',return_value={'index':1}),patch.object(asr,'extract_audio',return_value=(audio,2)),patch.object(asr,'run_worker',side_effect=AssertionError('must not start GPU')):
                result=asr.transcribe_video({'path':str(video)},root/'work',root)
            self.assertEqual(result['status'],'no_speech');self.assertTrue(result['complete'])

    def test_changed_video_during_asr_is_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'video.mp4';video.write_bytes(b'fixture')
            model=root/'runtime/asr/models/faster-whisper-large-v3-turbo';model.mkdir(parents=True)
            for file in ('model.bin','config.json','tokenizer.json','vocabulary.json'):(model/file).write_bytes(b'fixture')
            def changed(*a,**kw):
                video.write_bytes(b'changed-video')
                return asr.empty_result('no_speech',3,'cpu','int8')
            with patch.object(asr,'probe_audio',return_value={'index':1}),patch.object(asr,'extract_audio',return_value=(root/'audio.wav',3)),patch.object(asr,'is_digital_silence',return_value=False),patch.object(asr,'run_worker',side_effect=changed):
                with self.assertRaises(ValueError):asr.transcribe_video({'path':str(video)},root/'work',root)
            self.assertFalse(list((root/'state/asr_cache').glob('*.json')))

    def test_high_compression_ratio_is_flagged(self):
        model=SimpleNamespace(transcribe=lambda *a,**kw:(iter([SimpleNamespace(start=0,end=1,text='重复词',avg_logprob=-.2,no_speech_prob=.01,compression_ratio=3.0)]),SimpleNamespace(language='zh',language_probability=.9)))
        self.assertTrue(asr.recognize(model,'audio.wav',2,'cpu','int8')['segments'][0]['uncertain'])

    def test_punctuation_is_kept_for_review_not_speech_fact(self):
        model=SimpleNamespace(transcribe=lambda *a,**kw:(iter([
            SimpleNamespace(start=0,end=1,text='.',avg_logprob=-.1,no_speech_prob=.01),
            SimpleNamespace(start=1,end=2,text='字幕！',avg_logprob=-.1,no_speech_prob=.01)
        ]),SimpleNamespace(language='zh',language_probability=.9)))
        result=asr.recognize(model,'audio.wav',3,'cpu','int8')
        self.assertEqual(result['text'],'字幕！')
        self.assertEqual(result['nonlexical_segments'][0]['text'],'.')
        self.assertEqual(len(result['segments']),1)
        only=SimpleNamespace(transcribe=lambda *a,**kw:(iter([SimpleNamespace(start=0,end=1,text='...♪',avg_logprob=-.1,no_speech_prob=.01)]),SimpleNamespace(language='zh',language_probability=.9)))
        result=asr.recognize(only,'audio.wav',3,'cpu','int8')
        self.assertEqual(result['status'],'no_speech');self.assertEqual(result['text'],'')
        self.assertTrue(result['warnings'])

    def test_real_tail_overrun_and_zero_intervals_are_rejected_not_clamped(self):
        # Shape observed in real_asr_03: late hallucinated chunks past 105.2667s.
        items=[SimpleNamespace(start=104.22,end=106,text='尾段待核对',avg_logprob=-1.2,no_speech_prob=.1),
            SimpleNamespace(start=106,end=109,text='不在音轨内',avg_logprob=-.1,no_speech_prob=.1),
            SimpleNamespace(start=105.2666875,end=108,text='末帧挤压',avg_logprob=-.1,no_speech_prob=.1),
            SimpleNamespace(start=100,end=100,text='零长度',avg_logprob=-.1,no_speech_prob=.1)]
        kwargs={}
        def transcribe(*args,**kw):
            kwargs.update(kw);return iter(items),SimpleNamespace(language='zh',language_probability=.9)
        result=asr.recognize(SimpleNamespace(transcribe=transcribe),'audio.wav',105.2666875,'cuda','float16')
        self.assertEqual(len(result['segments']),1)
        self.assertEqual(len(result['rejected_segments']),3)
        self.assertTrue(all(s['end']>s['start'] for s in result['segments']))
        self.assertNotIn('不在音轨内',result['text'])
        self.assertEqual(kwargs['temperature'],0.0)
        self.assertFalse(kwargs['condition_on_previous_text'])
        asr._valid_complete(result,105.2666875)

    def test_valid_complete_rejects_zero_length_tail(self):
        result=asr.empty_result('complete',3,'cpu','int8')
        result.update(text='末帧',segments=[{'start':3,'end':3,'text':'末帧','avg_logprob':-.1,'no_speech_prob':.1,'uncertain':False}])
        with self.assertRaises(ValueError):asr._valid_complete(result,3)

    def test_negative_relative_audio_start_fails_without_trimming(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(asr,'_tools',return_value=(Path('ffmpeg.exe'),Path('ffprobe.exe'))),patch.object(asr,'_run_command') as command:
                with self.assertRaises(ValueError):asr.extract_audio(Path('video.mp4'),{'index':1,'audio_start_time':-1,'format_start_time':0},Path(tmp),Path(tmp))
                command.assert_not_called()

    def test_real_ffmpeg_delayed_audio_and_shifted_container_alignment(self):
        root=Path(__file__).resolve().parents[4]
        try:ffmpeg,ffprobe=asr._tools(root)
        except ValueError:self.skipTest('project FFmpeg unavailable')
        parent=root/'work/desktop_R03/asr_timeline_tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            folder=Path(tmp)
            for shift in (0,10):
                video=folder/f'offset-{shift}.mp4';work=folder/f'work-{shift}';work.mkdir()
                args=[str(ffmpeg),'-nostdin','-y','-v','error','-f','lavfi','-i','color=c=black:s=160x90:r=10:d=7',
                    '-itsoffset','5','-f','lavfi','-i','sine=frequency=440:duration=1','-map','0:v','-map','1:a',
                    '-c:v','libx264','-c:a','aac']
                if shift:args+=['-output_ts_offset',str(shift)]
                subprocess.run(args+[str(video)],capture_output=True,check=True,timeout=30)
                track=asr.probe_audio(video,root)
                self.assertIn('audio_start_time',track);self.assertIn('format_start_time',track)
                offset=track['audio_start_time']-track['format_start_time']
                self.assertAlmostEqual(offset,5,delta=.08)
                if shift:self.assertGreater(track['format_start_time'],9)
                audio,duration=asr.extract_audio(video,track,work,root)
                with wave.open(str(audio),'rb') as wav:
                    rate=wav.getframerate();samples=array('h',wav.readframes(wav.getnframes()))
                first=next(i for i,v in enumerate(samples) if abs(v)>128)/rate
                self.assertAlmostEqual(first,offset,delta=.12)
                self.assertGreater(duration,offset+.9)
                self.assertLess(duration,offset+1.2)
                self.assertFalse(any(samples[:int((offset-.1)*rate)]))

    def test_no_audio_and_missing_model_never_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'silent.mp4';video.write_bytes(b'fixture')
            with patch.object(asr,'probe_audio',return_value=None):
                result=asr.transcribe_video({'path':str(video)},root/'work',root)
            self.assertEqual(result['status'],'no_audio');self.assertEqual(result['audio_duration'],0)
            with self.assertRaises(ValueError):asr.model_path(root)
            self.assertFalse(asr.asr_status(root)['ready'])

    def test_real_subprocess_protocol_consumes_result_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);audio=work/'audio.wav';audio.touch();events=[]
            code='''import json,sys
from pathlib import Path
a=sys.argv; result=Path(a[a.index('--result')+1]); events=Path(a[a.index('--events')+1])
events.write_text(json.dumps({'stage':'transcribe','progress':100,'message':'fixture exhausted'})+'\\n')
result.write_text(json.dumps({'status':'no_speech','engine':'faster-whisper','model':'large-v3-turbo','device':'cpu','compute_type':'int8','language':None,'language_probability':None,'complete':True,'audio_duration':3,'processed_duration':3,'segments':[],'text':'','uncertain_segments':[],'warnings':[]}))
'''
            with patch.object(asr,'_worker_command',return_value=[sys.executable,'-c',code]):
                result=asr.run_worker(audio,3,work,'cpu',work,events.append)
            self.assertTrue(result['complete']);self.assertEqual(events[-1]['progress'],100)

    def test_worker_cancel_terminates_owned_subprocess_without_partial_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);audio=work/'audio.wav';audio.touch()
            original=subprocess.Popen;children=[]
            def launch(*args,**kwargs):
                child=original(*args,**kwargs);children.append(child);return child
            cancellation=iter([False,True])
            with patch.object(asr,'_worker_command',return_value=[sys.executable,'-c','import time;time.sleep(30)']),patch.object(asr.subprocess,'Popen',side_effect=launch):
                with self.assertRaises(GenerationCancelled):asr.run_worker(audio,3,work,'cpu',work,cancel=lambda:next(cancellation,True))
            self.assertEqual(len(children),1);self.assertIsNotNone(children[0].poll())

    def test_worker_timeout_terminates_owned_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);audio=work/'audio.wav';audio.touch();original=subprocess.Popen;children=[]
            def launch(*args,**kwargs):
                child=original(*args,**kwargs);children.append(child);return child
            started=time.monotonic()
            with patch.object(asr,'_worker_command',return_value=[sys.executable,'-c','import time;time.sleep(30)']),patch.object(asr,'_worker_timeout',return_value=.05),patch.object(asr.subprocess,'Popen',side_effect=launch):
                with self.assertRaises(ValueError):asr.run_worker(audio,3,work,'cpu',work)
            self.assertLess(time.monotonic()-started,5)
            self.assertEqual(len(children),1);self.assertIsNotNone(children[0].poll())

if __name__=='__main__':unittest.main()
