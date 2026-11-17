import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--release',required=True)
    a=p.parse_args();source=Path(__file__).resolve().parents[1];candidate=Path(a.candidate).resolve();release=Path(a.release).resolve()
    if release.exists():raise ValueError('Release destination already exists; preserve it before proceeding')
    archive=release.parent/(release.name+'_绿色版.zip')
    if archive.exists():raise ValueError('Archive destination already exists; preserve it before proceeding')
    asr=candidate/'components/asr';asr_manifest=json.loads((asr/'ASR-MANIFEST.json').read_text(encoding='utf-8'))
    assert asr_manifest['version']=='1.4.0' and asr_manifest['local_files_only'] is True
    for name,record in asr_manifest['files'].items():
        file=(asr/name).resolve()
        assert file.is_relative_to(asr.resolve()) and file.is_file() and file.stat().st_size==record['bytes'] and digest(file)==record['sha256'],name
    shutil.copytree(candidate,release)
    for file in candidate.rglob('*'):
        if file.is_file():assert digest(file)==digest(release/file.relative_to(candidate))
    for name in ('gui-guide.md','ai-interface.md','extensions.md','api-schema.md','validation.md','openapi.json','qt-relink.md','operations-r02.md','media-r02.md','asr-r03.md','media-r03.md','r03-contract.md','packaging-r03.md','publications-r04.md','manual-xhs-r05.md'):
        if (source/'docs'/name).is_file():shutil.copy2(source/'docs'/name,release/'docs'/name)
    for name in ('skills','licenses'):shutil.copytree(source/name,release/name,dirs_exist_ok=True)
    try:from .refresh_license_index import refresh
    except ImportError:from refresh_license_index import refresh
    license_report=refresh(release)
    if license_report['missing_license_text']:raise ValueError('Missing installed dependency license text: '+','.join(license_report['missing_license_text']))
    shutil.copy2(source/'README.md',release/'使用说明.md')
    forbidden={'state','profiles','cookies.json','api-token.txt','settings.json','catalog.sqlite3','workspace.json','.git','.cache','hf-cache','xet-cache','connection.json'}
    bad=[str(p.relative_to(release)) for p in release.rglob('*') if p.name.lower() in forbidden]
    assert not bad,bad
    files=[f for f in release.rglob('*') if f.is_file()]
    manifest={str(f.relative_to(release)).replace('\\','/'):digest(f) for f in sorted(files)}
    (release/'SHA256-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=release.parent/(release.name+'_绿色版.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for file in sorted(release.rglob('*')):
            if file.is_file():z.write(file,str(Path(release.name)/file.relative_to(release)))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    print(json.dumps({'release':str(release),'files':len(files)+1,'bytes':sum(f.stat().st_size for f in release.rglob('*') if f.is_file()),'zip':str(archive),'zip_bytes':archive.stat().st_size,'zip_sha256':digest(archive),'private_files':bad},ensure_ascii=False))

if __name__=='__main__':main()
