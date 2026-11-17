"""Black-box test of a frozen release in an independently copied workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import wave
from urllib.request import Request,build_opener,ProxyHandler

def main():
    p=argparse.ArgumentParser();p.add_argument('--release',required=True);p.add_argument('--work',required=True);p.add_argument('--video',required=True);p.add_argument('--real-ai',action='store_true');p.add_argument('--asr-wav',help='Optional local PCM WAV: run the frozen ASR CPU worker without AI or platform requests')
    args=p.parse_args();work=Path(args.work).resolve();work.mkdir(parents=True,exist_ok=True)
    clone=work/'应用 副本'
    if clone.exists():raise ValueError('Use a new acceptance directory to preserve prior evidence')
    shutil.copytree(args.release,clone)
    assert not (clone/'state').exists(),'Distribution unexpectedly contains private state'
    asr=clone/'components/asr';manifest=json.loads((asr/'ASR-MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['version']=='1.4.0' and manifest['local_files_only'] is True
    for name,record in manifest['files'].items():
        path=(asr/name).resolve();assert path.is_relative_to(asr.resolve()) and path.is_file(),name
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        assert actual==record['sha256'] and path.stat().st_size==record['bytes'],name
    media=work/'输入素材';media.mkdir();video=media/'视频素材.mp4';shutil.copy2(args.video,video)
    env=os.environ.copy();env.pop('PYTHONPATH',None);env.pop('TRIPUBLISH_HOME',None)
    windows=Path(os.environ.get('WINDIR','C:/Windows'));env['PATH']=os.pathsep.join(map(str,(windows/'System32',windows)))
    env['PYTHONUTF8']='1';env['QT_QPA_PLATFORM']='offscreen'
    cli=clone/'ContentCtl.exe';gui=clone/'TriContentStudio.exe';data=work/'隔离数据'
    base=[str(cli),'--home',str(clone),'--data-dir',str(data)]
    def run(arguments,check=True,timeout=60):
        r=subprocess.run(arguments,cwd=work,env=env,capture_output=True,encoding='utf-8',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if check and r.returncode:raise RuntimeError(r.stdout+'\n'+r.stderr)
        return r
    report={'ok':False,'platform_uploads_performed':0,'network_account_requests':0}
    report['doctor']=json.loads(run([str(cli),'doctor','--browser']).stdout)
    assert report['doctor']['ok']
    assert report['doctor']['asr']['ready'] and report['doctor']['asr']['cuda_libraries_present']
    report['asr_package_integrity']={'files':len(manifest['files']),'packages':manifest['packages'],'local_files_only':True}
    if args.asr_wav:
        asr_work=work/'隔离口播验收';asr_work.mkdir();wav=asr_work/'input.wav';shutil.copy2(args.asr_wav,wav)
        with wave.open(str(wav),'rb') as reader:duration=reader.getnframes()/reader.getframerate()
        request=asr_work/'request.json';events=asr_work/'events.jsonl';result_file=asr_work/'result.json'
        request.write_text(json.dumps({'engine_root':str(clone),'work_dir':str(asr_work),'audio_path':str(wav),'audio_duration':duration,'device':'cpu','cancel_path':str(asr_work/'cancel')}),encoding='utf-8')
        run([str(cli),'_speech_worker','--request',str(request),'--events',str(events),'--result',str(result_file)],timeout=1800)
        speech=json.loads(result_file.read_text(encoding='utf-8'))
        assert speech.get('complete') is True and speech['status'] in ('complete','no_speech'),speech.get('error')
        assert abs(speech['processed_duration']-duration)<1 and speech['device']=='cpu'
        report['frozen_asr_cpu']={'status':speech['status'],'audio_duration':duration,'processed_duration':speech['processed_duration'],'segments':len(speech['segments']),'device':speech['device']}
    proc=subprocess.Popen(base+['serve','--port','0'],cwd=work,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for _ in range(120):
            if (data/'connection.json').exists():break
            if proc.poll() is not None:raise RuntimeError('Frozen service exited at startup')
            time.sleep(.1)
        cfg=json.loads((data/'connection.json').read_text(encoding='utf-8'))
        assert json.loads(run(base+['status']).stdout)['ok']
        asset=json.loads(run(base+['add','--file',str(video)]).stdout)
        brief=json.loads(run(base+['brief',asset['id']]).stdout)
        assert brief['asset']['id']==asset['id'] if 'asset' in brief else asset['id'] in json.dumps(brief)
        packages={'asset_id':asset['id'],'packages':[{'platform':platform,'title':'六秒功能测试','caption':'功能测试素材，默认草稿，不作为公开视频。','tags':['功能测试'],'visibility':'draft','evidence_ids':[]} for platform in ('bilibili','douyin','xiaohongshu')]}
        package_file=work/'三平台文案.json';package_file.write_text(json.dumps(packages,ensure_ascii=False),encoding='utf-8-sig')
        assert json.loads(run(base+['import-packages',str(package_file)]).stdout)['count']==3
        drafts=json.loads(run(base+['list','drafts']).stdout)
        assert len(drafts)==3 and all(d['visibility']=='draft' for d in drafts)
        checks=[]
        for platform in ('bilibili','douyin'):
            job=json.loads(run(base+['queue','--action','check','--platform',platform,'--idempotency-key','offline-check-'+platform]).stdout)
            for _ in range(200):
                result=json.loads(run(base+['job',job['id']]).stdout)
                if result['status'] not in ('queued','running','awaiting_user'):break
                time.sleep(.1)
            assert result['status']=='failed' and result['result']['evidence']['online_checked'] is False,result
            checks.append({'platform':platform,'status':result['status'],'message':result['message']})
        report['frozen_workers_no_account']=checks
        bad=run(base+['queue','--action','publish','--draft-id',drafts[0]['id']],check=False)
        assert bad.returncode==2 and json.loads(bad.stdout)['error']
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'list_assets','arguments':{}}}]
        mcp=subprocess.run(base+['mcp'],input='\n'.join(map(json.dumps,messages))+'\n',cwd=work,env=env,capture_output=True,encoding='utf-8',timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        responses=[json.loads(line) for line in mcp.stdout.splitlines()]
        assert len(responses)==3 and len(responses[1]['result']['tools'])==21
        assert asset['id'] in responses[2]['result']['content'][0]['text']
        report['mcp_tools']=21
        opener=build_opener(ProxyHandler({}))
        token=Path(cfg['token_path']).read_text(encoding='ascii').strip()
        req=Request(cfg['endpoint']+'/api/v1/jobs',headers={'Authorization':'Bearer '+token})
        with opener.open(req,timeout=5) as r:assert len(json.load(r))==2
        report['shared_asset_id']=asset['id'];report['draft_count']=3
        if args.real_ai:
            ai_status=json.loads(run(base+['ai-status']).stdout)
            assert ai_status['codex']['logged_in'],ai_status
            campaign=json.loads(run(base+['plan','--asset-id',asset['id'],'--provider','codex','--goal','按视频真实画面与完整机器口播生成五块方案；没有相关热点请说明，不硬蹭。']).stdout)
            stage=None
            for _ in range(440):
                campaign=json.loads(run(base+['plan-status',campaign['id']]).stdout)
                if campaign['stage']!=stage:
                    print(json.dumps({'stage':campaign['stage'],'message':campaign['message']},ensure_ascii=False),flush=True);stage=campaign['stage']
                if campaign['status'] not in ('queued','running'):break
                time.sleep(1)
            assert campaign['status']=='complete',campaign['message']
            speech=campaign['result']['media']['speech'];assert speech['complete'] is True and speech['status'] in ('complete','no_audio','no_speech')
            result=campaign['result'];assert len(result['packages'])==3 and 6<=len(result['media']['frames'])<=8
            saved=json.loads(run(base+['plan-save',campaign['id']]).stdout)
            assert saved['count']==3 and saved['jobs']==[]
            report['real_ai_campaign']={'id':campaign['id'],'status':campaign['status'],'provider':campaign['provider'],'frames':len(result['media']['frames']),'platforms':[p['platform'] for p in result['packages']],'opportunities':len(result['opportunities'])}
            report['real_ai_campaign']['speech']={k:speech.get(k) for k in ('status','complete','audio_duration','processed_duration','model','device','cache_hit')}
            (work/'真实AI结果.json').write_text(json.dumps(campaign,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        proc.terminate();proc.wait(timeout=15)
    result=run([str(gui),'--home',str(clone),'--data-dir',str(data),'--port','0','--ui-check-out',str(work/'窗口截图')],timeout=45)
    assert len(list((work/'窗口截图').glob('page_*.png')))==6
    assert len(list((work/'窗口截图').glob('plan_*.png')))==5
    if args.real_ai:
        displayed=json.loads((work/'窗口截图'/'ui-fields.json').read_text(encoding='utf-8'))
        assert displayed['rendered_campaign_id']==report['real_ai_campaign']['id']
        assert displayed['platforms']['bilibili']['title_count']>=2 and displayed['platforms']['bilibili']['category']
        assert displayed['platforms']['xiaohongshu']['title_count']>=2 and displayed['platforms']['xiaohongshu']['search']
        assert displayed['platforms']['douyin']['hook'] and all(v['caption'] for v in displayed['platforms'].values())
    report['frozen_gui_pages']=6;report['five_plan_views']=5;report['ok']=True
    (work/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
