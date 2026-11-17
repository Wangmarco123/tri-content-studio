"""Real local ASR acceptance; no AI or account calls, no source video edits."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from studio.asr import transcribe_video
from studio.core import file_hash
from studio.media import analyze_media,validated_speech

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--video',required=True);p.add_argument('--work',required=True);a=p.parse_args()
    root=Path(a.project).resolve();work=Path(a.work).resolve();work.mkdir(parents=True,exist_ok=False)
    asset={'path':str(Path(a.video).resolve()),'sha256':file_hash(a.video)}
    def emit(e):print(json.dumps(e,ensure_ascii=False),flush=True)
    started=time.monotonic();speech=transcribe_video(asset,work/'real-video',root,emit=emit)
    seconds=time.monotonic()-started
    assert speech['complete'] and speech['status']=='complete' and speech['segments']
    assert speech['processed_duration']==speech['audio_duration']
    validated_speech(speech,speech['audio_duration'])
    media=analyze_media(asset,work/'media',root,speech=speech)
    assert media['transcript'][-1]['text']==speech['segments'][-1]['text']
    assert 6<=len(media['frames'])<=8
    assert asset['sha256']==file_hash(a.video)
    started=time.monotonic();cached=transcribe_video(asset,work/'cache-repeat',root,emit=emit)
    cache_seconds=time.monotonic()-started
    assert cached['cache_hit'] and cached['text']==speech['text']
    report={'ok':False,'platform_requests':0,'ai_requests':0,'video_sha256':asset['sha256'],'real_video':{k:speech.get(k) for k in ('status','model','device','compute_type','language','audio_duration','processed_duration','complete','uncertain_segments','warnings','cache_hit')},'segments':len(speech['segments']),'characters':len(speech['text']),'seconds':seconds,'cache_seconds':cache_seconds,'media_scope':media['analysis_scope'],'frames':len(media['frames']),'fixtures':{}}
    ffmpeg=root/'runtime/ffmpeg/bin/ffmpeg.exe'
    for name,source in [('silence','anullsrc=r=16000:cl=mono'),('music_tone','sine=frequency=440:sample_rate=16000')]:
        video=work/(name+'.mkv')
        subprocess.run([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=black:s=320x180:r=10:d=8','-f','lavfi','-i',source,'-t','8','-c:v','libx264','-c:a','pcm_s16le',str(video)],check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result=transcribe_video({'path':str(video),'sha256':file_hash(video)},work/name,root,emit=emit)
        assert result['complete'] and result['processed_duration']==result['audio_duration']
        if name=='silence':assert result['status']=='no_speech' and result['segments']==[]
        report['fixtures'][name]={k:result.get(k) for k in ('status','device','complete','text','uncertain_segments','warnings','audio_duration','processed_duration')}
    quiet=work/'quiet_speech.mkv'
    subprocess.run([str(ffmpeg),'-v','error','-y','-i',a.video,'-t','12','-map','0:v:0','-map','0:a:0','-vf','scale=320:-2','-af','volume=0.02','-c:v','libx264','-c:a','pcm_s16le',str(quiet)],check=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    result=transcribe_video({'path':str(quiet),'sha256':file_hash(quiet)},work/'quiet_speech',root,emit=emit)
    assert result['complete'] and result['status']=='complete' and result['segments']
    report['fixtures']['quiet_speech']={k:result.get(k) for k in ('status','device','complete','text','uncertain_segments','audio_duration','processed_duration')}
    report['ok']=True
    (work/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');emit(report)

if __name__=='__main__':main()
