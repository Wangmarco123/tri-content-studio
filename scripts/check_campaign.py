import argparse
import json
from pathlib import Path
import time
from studio.service import Service

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--video',required=True);p.add_argument('--data-dir',required=True);a=p.parse_args()
    root=Path(a.project);data=Path(a.data_dir);s=Service(root,data,start_worker=False)
    try:
        asset=s.add_asset({'path':a.video})
        campaign=s.start_campaign({'asset_id':asset['id'],'provider':'codex','goal':'验证一键生成用户要求的五块完整结果；测试片没有合适热点就明确说明，禁止硬蹭。'})
        stage=None
        for _ in range(900):
            c=s.get_campaign(campaign['id'])
            if c['stage']!=stage:print(json.dumps({k:c[k] for k in ('id','status','stage','progress','message')},ensure_ascii=False),flush=True);stage=c['stage']
            if c['status'] not in ('queued','running'):break
            time.sleep(1)
        (data/'real-campaign-receipt.json').write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':c['status'],'message':c['message'],'drafts':len(s.drafts()),'opportunities':len((c.get('result') or {}).get('opportunities',[]))},ensure_ascii=False),flush=True)
        return 0 if c['status']=='complete' else 2
    finally:s.close()

if __name__=='__main__':raise SystemExit(main())
