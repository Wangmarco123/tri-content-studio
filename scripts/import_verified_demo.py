"""Import the actual frozen acceptance result into the user's local workspace."""
import argparse
import copy
import json
import shutil
from pathlib import Path
from studio.app import InstanceLock
from studio.core import file_hash,now
from studio.service import Service
from studio.operations import validate_campaign
from studio.campaigns import canonical_package

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--receipt',required=True);p.add_argument('--source-video',required=True);p.add_argument('--target-video',required=True);p.add_argument('--source-work');a=p.parse_args()
    root=Path(a.project);data=root/'state'/'desktop'
    assert file_hash(a.source_video)==file_hash(a.target_video),'Video bytes differ; do not relabel AI evidence'
    record=json.loads(Path(a.receipt).read_text(encoding='utf-8-sig'))
    assert record['status']=='complete' and record['provider']=='codex'
    lock=InstanceLock(data/'instance.lock');s=None
    try:
        s=Service(root,data,start_worker=False)
        if any(c['id']==record['id'] for c in s.campaigns()):print('Verified result already present');return
        asset=s.add_asset({'path':a.target_video})
        raw=copy.deepcopy(record['result']);raw['asset_id']=asset['id']
        for package in raw['packages']:package['asset_id']=asset['id']
        sources=raw.get('sources',[]);media=raw['media']
        copied_artifacts=0
        if a.source_work:
            origin=Path(a.source_work).resolve();target=(data/'campaigns'/record['id']).resolve()
            assert origin.is_relative_to(root.resolve()) and target.is_relative_to(data.resolve())
            assert origin.is_dir() and not target.exists(),'Preserve prior artifacts; do not overlay'
            shutil.copytree(origin,target)
            for original in origin.rglob('*'):
                if original.is_file():
                    assert file_hash(original)==file_hash(target/original.relative_to(origin))
                    copied_artifacts+=1
            def rebase(value):
                source=Path(value).resolve()
                assert source.is_relative_to(origin),'Media artifact outside copied work folder'
                return str(target/source.relative_to(origin))
            for frame in media['frames']:frame['path']=rebase(frame['path'])
            spoken=media.get('speech') or {}
            for key in ('txt_path','srt_path','json_path'):
                if spoken.get(key):spoken[key]=rebase(spoken[key])
            if spoken.get('json_path'):Path(spoken['json_path']).write_text(json.dumps(spoken,ensure_ascii=False,indent=2),encoding='utf-8')
        result=validate_campaign(raw,asset,s.evidence()+sources,media)
        result['packages']=[canonical_package(p) for p in result['packages']]
        result['sources']=sources;result['media']=media
        with s.lock,s.store.transaction():
            if sources:s.import_evidence({'items':sources})
            drafts=[s.save_draft(dict(package,asset_id=asset['id'],visibility='draft')) for package in result['packages']]
            record.update(asset_id=asset['id'],result=result,draft_ids=[d['id'] for d in drafts])
            s.store.put('campaigns',record)
        provenance={'imported_at':now(),'source_receipt':str(Path(a.receipt).resolve()),'receipt_sha256':file_hash(a.receipt),'campaign_id':record['id'],'verified_video_sha256':asset['sha256'],'note':'实际冻结版AI生成结果，视频字节一致；只放入本人本地工作区，不进入干净分发包。'}
        provenance['copied_artifact_files']=copied_artifacts
        (root/'work'/'desktop_R03'/'verified-demo-import.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'campaign_id':record['id'],'draft_count':3,'platform_jobs_created':0},ensure_ascii=False))
    finally:
        if s:s.close()
        lock.close()

if __name__=='__main__':main()
