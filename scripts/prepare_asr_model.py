import hashlib
import json
import os
from pathlib import Path
import argparse

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--verify-only',action='store_true');a=p.parse_args();root=Path(a.project).resolve()
    base=root/'runtime'/'asr';base.mkdir(parents=True,exist_ok=True)
    os.environ.update(HF_HOME=str(base/'hf-cache'),HF_XET_CACHE=str(base/'xet-cache'),HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_XET='1',HF_HUB_DOWNLOAD_TIMEOUT='120')
    from huggingface_hub import HfApi,snapshot_download
    repo='mobiuslabsgmbh/faster-whisper-large-v3-turbo'
    info=HfApi().model_info(repo,revision='0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf',files_metadata=True,token=False)
    selected=['config.json','model.bin','preprocessor_config.json','tokenizer.json','vocabulary.json','vocabulary.txt','README.md']
    available={f.rfilename:f for f in info.siblings if f.rfilename in selected}
    target=base/'models'/'faster-whisper-large-v3-turbo'
    print(json.dumps({'repo':repo,'revision':info.sha,'files':{k:v.size for k,v in available.items()}},ensure_ascii=False),flush=True)
    if not a.verify_only:
        snapshot_download(repo,revision=info.sha,local_dir=str(target),allow_patterns=list(available),token=False,max_workers=4)
    records=[]
    for name,metadata in available.items():
        path=target/name
        with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        expected=getattr(metadata.lfs,'sha256',None) if metadata.lfs else None
        if expected and digest!=expected:raise ValueError('Model SHA256 mismatch: '+name)
        if metadata.size is not None and path.stat().st_size!=metadata.size:raise ValueError('Model size mismatch: '+name)
        records.append({'name':name,'bytes':path.stat().st_size,'sha256':digest,'upstream_lfs_sha256':expected})
    record={'repo':repo,'revision':info.sha,'source_url':'https://huggingface.co/'+repo+'/tree/'+info.sha,'files':records,'local_files_only_runtime':True}
    (target/'MODEL-MANIFEST.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'verified':True,'target':str(target),'bytes':sum(x['bytes'] for x in records)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
