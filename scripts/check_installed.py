"""Read-only session checks using the installed EXE and existing local state."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request,build_opener,ProxyHandler

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--only',choices=('bilibili','douyin','xiaohongshu'));args=p.parse_args()
    root=Path(args.project).resolve();app=root/'应用';(app/'workspace.json').write_text('{"workspace":".."}',encoding='utf-8')
    conn=root/'state'/'desktop'/'connection.json';previous=conn.stat().st_mtime_ns if conn.exists() else 0
    proc=subprocess.Popen([str(app/'ContentCtl.exe'),'serve','--port','0'],cwd=app,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    report={'installed_start':False,'publications_performed':0,'checks':[]}
    try:
        for _ in range(150):
            if conn.exists() and conn.stat().st_mtime_ns!=previous:break
            if proc.poll() is not None:raise RuntimeError('Installed application startup failed')
            time.sleep(.1)
        cfg=json.loads(conn.read_text(encoding='utf-8'));token=Path(cfg['token_path']).read_text(encoding='ascii').strip();opener=build_opener(ProxyHandler({}))
        def call(path,payload=None):
            req=Request(cfg['endpoint']+'/api/v1/'+path,data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with opener.open(req,timeout=20) as r:return json.load(r)
        report['installed_start']=call('health')['ok']
        asset=call('assets',{'path':str(root/'outputs'/'测试素材'/'上传功能测试_6秒.mp4'),'summary':'已授权六秒功能测试片；本轮用于软件素材登记和接口验收','audience':'本人功能测试'})
        if not any(d['asset_id']==asset['id'] for d in call('drafts')):
            call('packages/import',{'asset_id':asset['id'],'packages':[{'platform':platform,'title':'发布助手功能测试','caption':'简短功能测试片，仅准备本地文案。','tags':['功能测试'],'visibility':'draft','evidence_ids':[]} for platform in ('bilibili','douyin','xiaohongshu')]})
        for platform in ([args.only] if args.only else ('bilibili','douyin','xiaohongshu')):
            job=call('jobs',{'platform':platform,'action':'check','idempotency_key':'installed-r01-readonly-'+platform+'-'+str(time.time_ns())})
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                result=call('jobs/'+job['id'])
                if result['status'] not in ('queued','running','awaiting_user','cancel_requested'):break
                time.sleep(.5)
            else:
                call('jobs/'+job['id']+'/cancel',{})
                for _ in range(50):
                    result=call('jobs/'+job['id'])
                    if result['status'] not in ('queued','running','awaiting_user','cancel_requested'):break
                    time.sleep(.5)
            report['checks'].append({'platform':platform,'job_id':job['id'],'status':result['status'],'message':result['message'],'result':result.get('result')})
        report['accounts']=call('accounts')
    finally:
        proc.terminate();proc.wait(timeout=15)
    (root/'work'/'desktop_R01'/('installed-verification-'+args.only+'.json' if args.only else 'installed-verification.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
