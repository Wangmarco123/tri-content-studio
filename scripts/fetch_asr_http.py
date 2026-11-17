"""Build-time pinned HTTP range download, independently verifies each range and whole hash."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
from pathlib import Path
from urllib.request import Request, urlopen

REVISION='0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
SIZE=1617884929
SHA256='e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da'
URL='https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo/resolve/'+REVISION+'/model.bin'

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--try-existing-prefix',action='store_true');a=p.parse_args()
    root=Path(a.project).resolve();parts=root/'runtime/asr/http-parts'/REVISION;parts.mkdir(parents=True,exist_ok=True)
    chunk=16*1024*1024
    def fetch(start):
        end=min(SIZE-1,start+chunk-1);dest=parts/str(start)
        if dest.is_file() and dest.stat().st_size==end-start+1:return end-start+1
        for attempt in range(3):
            try:
                req=Request(URL+'?download=true&part='+str(start),headers={'Range':f'bytes={start}-{end}'})
                with urlopen(req,timeout=60) as response:
                    if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{SIZE}':raise ValueError('Unexpected HTTP range')
                    payload=response.read(end-start+2)
                if len(payload)!=end-start+1:raise ValueError('Incomplete HTTP range')
                temp=dest.with_suffix('.tmp');temp.write_bytes(payload);os.replace(temp,dest)
                return len(payload)
            except Exception:
                if attempt==2:raise
    dest=root/'runtime/asr/models/faster-whisper-large-v3-turbo/model.bin';temp=dest.with_suffix('.verified-download')
    def download(starts):
        completed=0
        with ThreadPoolExecutor(max_workers=6) as pool:
            for f in as_completed([pool.submit(fetch,start) for start in starts]):
                completed+=f.result();print(f'Ranges completed {completed}',flush=True)
    def assemble(prefix=None,boundary=0):
        h=hashlib.sha256()
        with temp.open('wb') as out:
            if prefix:
                remaining=boundary
                with prefix.open('rb') as source:
                    while remaining:
                        data=source.read(min(4*1024*1024,remaining))
                        if not data:raise ValueError('Existing prefix became shorter')
                        out.write(data);h.update(data);remaining-=len(data)
            for start in range(boundary,SIZE,chunk):
                with (parts/str(start)).open('rb') as part:
                    while data:=part.read(4*1024*1024):out.write(data);h.update(data)
        return temp.stat().st_size==SIZE and h.hexdigest()==SHA256
    if a.try_existing_prefix:
        candidates=list((dest.parent/'.cache/huggingface/download').glob('*.incomplete'))
        prefix=max(candidates,key=lambda f:f.stat().st_size) if candidates else None
        boundary=prefix.stat().st_size//chunk*chunk if prefix else 0
        if boundary:
            print(f'Trying existing prefix {boundary} bytes; whole SHA256 is mandatory',flush=True)
            download(range(boundary,SIZE,chunk))
            if assemble(prefix,boundary):
                os.replace(temp,dest);print('SHA256 verified '+SHA256,flush=True);return
            print('Prefix did not match whole hash; fetching all independent ranges',flush=True)
    download(range(0,SIZE,chunk))
    if not assemble():raise ValueError('Complete model SHA256 mismatch')
    os.replace(temp,dest);print('SHA256 verified '+SHA256,flush=True)

if __name__=='__main__':main()
