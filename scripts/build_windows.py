"""Reproducible onedir build; the caller supplies the external runtime root."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ASR_PACKAGES=('faster_whisper','ctranslate2','av','onnxruntime','tokenizers','huggingface_hub','numpy')
ASR_DISTRIBUTIONS=('faster-whisper','ctranslate2','av','onnxruntime','tokenizers','huggingface-hub','numpy')
MODEL_FOLDER='faster-whisper-large-v3-turbo'
CUDA_FILES=('cublas64_12.dll','cublasLt64_12.dll','cudart64_12.dll')

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def check_asr(project):
    model=project/'runtime/asr/models'/MODEL_FOLDER;cuda=project/'runtime/asr/cuda'
    for name in ('model.bin','config.json','tokenizer.json','vocabulary.json','preprocessor_config.json','README.md','MODEL-MANIFEST.json'):
        if not (model/name).is_file() or (model/name).stat().st_size==0:raise ValueError('ASR model download incomplete: '+name)
    if (model/'model.bin').stat().st_size<1_000_000_000:raise ValueError('ASR model.bin unexpectedly small; finish and verify download first')
    manifest=json.loads((model/'MODEL-MANIFEST.json').read_text(encoding='utf-8'))
    if manifest.get('revision')!='0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf' or manifest.get('repo')!='mobiuslabsgmbh/faster-whisper-large-v3-turbo':raise ValueError('Unexpected model revision/provenance')
    recorded=set()
    for item in manifest['files']:
        file=model/item['name']
        if not file.resolve().is_relative_to(model.resolve()) or not file.is_file() or file.stat().st_size!=item['bytes'] or digest(file)!=item['sha256']:raise ValueError('Model manifest integrity mismatch: '+item['name'])
        recorded.add(item['name'])
    if not {'model.bin','config.json','tokenizer.json','vocabulary.json'}.issubset(recorded):raise ValueError('Model manifest missing required files')
    for name in CUDA_FILES:
        if not (cuda/name).is_file():raise ValueError('Missing CUDA library: '+name)
    source=Path(__file__).resolve().parents[1]
    for name in ('model','CUDA','ctranslate2','tokenizers'):
        folder=source/'licenses/ASR'/name
        if not folder.is_dir() or not any(p.is_file() for p in folder.rglob('*')):raise ValueError('Supply ASR license text before building: '+name)
    versions={name:importlib.metadata.version(name) for name in ASR_DISTRIBUTIONS}
    if versions['faster-whisper']!='1.2.1' or versions['ctranslate2']!='4.8.1':raise ValueError('ASR package pins do not match R03')
    return model,cuda,versions

def copy_asr(project,release,model,cuda,versions):
    target=release/'components/asr';target.mkdir(parents=True,exist_ok=True)
    shutil.copytree(model,target/'models'/MODEL_FOLDER,ignore=shutil.ignore_patterns('.cache','.git','*.incomplete','*.lock'),dirs_exist_ok=False)
    (target/'cuda').mkdir()
    for name in CUDA_FILES:shutil.copy2(cuda/name,target/'cuda'/name)
    upstream=json.loads((model/'MODEL-MANIFEST.json').read_text(encoding='utf-8'))
    for item in upstream['files']:
        if digest(target/'models'/MODEL_FOLDER/item['name'])!=item['sha256']:raise ValueError('Packaged model copy hash mismatch: '+item['name'])
    for name in CUDA_FILES:
        if digest(cuda/name)!=digest(target/'cuda'/name):raise ValueError('Packaged CUDA copy hash mismatch: '+name)
    license_root=release/'licenses'/'ASR';license_root.mkdir(parents=True,exist_ok=True)
    for name in ASR_DISTRIBUTIONS:
        dist=importlib.metadata.distribution(name);count=0
        for entry in dist.files or []:
            if any(part.lower() in ('licenses','license','copying') or part.lower().startswith(('license.','copying.','notice')) or 'notice' in part.lower() for part in entry.parts):
                origin=Path(dist.locate_file(entry))
                if origin.is_file():
                    destination=license_root/name/Path(*entry.parts);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(origin,destination);count+=1
        if not count and not any((license_root/name).rglob('LICENSE*')):raise ValueError('Missing distribution license files for '+name+'; provide source/licenses/ASR/'+name)
    for name in ('model','CUDA'):
        if not (license_root/name).is_dir() or not any((license_root/name).rglob('*')):raise ValueError('Missing supplied ASR license directory: '+name)
    files={str(f.relative_to(target)).replace('\\','/'):{'bytes':f.stat().st_size,'sha256':digest(f)} for f in sorted(target.rglob('*')) if f.is_file()}
    manifest={'release':'R05','version':'1.4.0','model':MODEL_FOLDER,'local_files_only':True,'packages':versions,'files':files,'provenance':'See included model README and licenses/ASR; hashes record packaged bytes, not an upstream signature.'}
    (target/'ASR-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--revision',default='R05',choices=('R05',))
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]
    project=Path(args.project).resolve();out=Path(args.out).resolve()
    model,cuda,versions=check_asr(project)
    out.mkdir(parents=True,exist_ok=True)
    release_name='三平台内容发布助手_'+args.revision
    if (out/release_name).exists():raise ValueError('Use a new output directory; do not overlay a previous release')
    build=project/'work'/('desktop_'+args.revision)/'build'
    build.mkdir(parents=True,exist_ok=True)
    from PIL import Image,ImageDraw
    icon=source/'assets'/'studio.ico';icon.parent.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGBA',(256,256),'#142c42');draw=ImageDraw.Draw(im)
    for x,y,h in ((56,124,80),(112,76,128),(168,40,164)):
        draw.rounded_rectangle((x,y,x+32,y+h),radius=12,fill='#41b8a2')
    im.save(icon,sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    version=source/'assets'/'version.txt'
    version.write_text("VSVersionInfo(ffi=FixedFileInfo(filevers=(1,4,0,0),prodvers=(1,4,0,0),mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('080404b0',[StringStruct('CompanyName','漫爱设计工作室'),StringStruct('FileDescription','三平台内容发布助手 AI工作台'),StringStruct('FileVersion','1.4.0'),StringStruct('ProductName','三平台内容发布助手'),StringStruct('ProductVersion','1.4.0')])]),VarFileInfo([VarStruct('Translation',[2052,1200])])])",encoding='utf-8')
    spec=build/'TriContentStudio.spec'
    spec.write_text('''from PyInstaller.utils.hooks import collect_all,copy_metadata
pr_datas,pr_bins,pr_hidden=collect_all('patchright')
for package in ('faster_whisper','ctranslate2','av','onnxruntime','tokenizers','huggingface_hub','numpy'):
    datas,bins,hidden=collect_all(package)
    pr_datas+=datas;pr_bins+=bins;pr_hidden+=hidden
for distribution in ('faster-whisper','ctranslate2','av','onnxruntime','tokenizers','huggingface-hub','numpy'):
    pr_datas+=copy_metadata(distribution,recursive=True)
a=Analysis([SOURCE+'/desktop_main.py'],pathex=[SOURCE],binaries=pr_bins,datas=pr_datas,hiddenimports=pr_hidden+['studio.cli','studio.doctor','studio.mcp_server','studio.adapters','studio.browser_worker','studio.asr','segno','greenlet'],excludes=['tkinter','matplotlib','scipy','IPython'],noarchive=False)
b=Analysis([SOURCE+'/contentctl.py'],pathex=[SOURCE],binaries=pr_bins,datas=pr_datas,hiddenimports=pr_hidden+['studio.app','studio.doctor','studio.gui','studio.mcp_server','studio.adapters','studio.browser_worker','studio.asr','segno','greenlet'],excludes=['tkinter','matplotlib','scipy','IPython'],noarchive=False)
pa=PYZ(a.pure);pb=PYZ(b.pure)
gui=EXE(pa,a.scripts,[],exclude_binaries=True,name='TriContentStudio',console=False,icon=ICON,version=VERSION,upx=False)
cli=EXE(pb,b.scripts,[],exclude_binaries=True,name='ContentCtl',console=True,icon=ICON,version=VERSION,upx=False)
coll=COLLECT(gui,cli,a.binaries,a.datas,b.binaries,b.datas,strip=False,upx=False,name=RELEASE_NAME)
'''.replace('SOURCE=', 'SOURCE='),encoding='utf-8')
    body=spec.read_text(encoding='utf-8')
    spec.write_text('SOURCE='+repr(str(source))+'\nICON='+repr(str(icon))+'\nVERSION='+repr(str(version))+'\nRELEASE_NAME='+repr(release_name)+'\n'+body,encoding='utf-8')
    env=os.environ.copy()
    # Build tools on the host may expose incompatible ICU/OpenSSL DLLs on PATH.
    # Resolve only the selected Python and Windows libraries for this release.
    windows=Path(os.environ.get('WINDIR','C:/Windows'))
    env['PATH']=os.pathsep.join(map(str,(Path(sys.executable).parent,windows/'System32',windows)))
    subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm','--distpath',str(out),'--workpath',str(build/'pyinstaller'),str(spec)],cwd=source,env=env,check=True)
    release=out/release_name
    components=release/'components';components.mkdir(exist_ok=True)
    bili=next((project/'runtime'/'biliup').rglob('biliup.exe'))
    (components/'biliup').mkdir(exist_ok=True)
    shutil.copy2(bili,components/'biliup'/'biliup.exe')
    for file in bili.parent.glob('*.txt'):shutil.copy2(file,components/'biliup'/file.name)
    browser=project/'runtime'/'browsers-douyin'/'chromium-1248'
    shutil.copytree(browser,components/'browsers-douyin'/'chromium-1248',dirs_exist_ok=True)
    shutil.copytree(project/'runtime'/'ffmpeg',components/'ffmpeg',dirs_exist_ok=True)
    for name in ('skills','examples','licenses'):
        if (source/name).exists():shutil.copytree(source/name,release/name,dirs_exist_ok=True)
    copy_asr(project,release,model,cuda,versions)
    try:from .refresh_license_index import refresh
    except ImportError:from refresh_license_index import refresh
    license_report=refresh(release)
    if license_report['missing_license_text']:raise ValueError('Missing installed dependency license text: '+','.join(license_report['missing_license_text']))
    (release/'docs').mkdir(exist_ok=True)
    for name in ('gui-guide.md','ai-interface.md','extensions.md','api-schema.md','validation.md','openapi.json','qt-relink.md','operations-r02.md','media-r02.md','asr-r03.md','media-r03.md','r03-contract.md','packaging-r03.md','publications-r04.md','manual-xhs-r05.md'):
        if (source/'docs'/name).is_file():shutil.copy2(source/'docs'/name,release/'docs'/name)
    if (source/'README.md').is_file():shutil.copy2(source/'README.md',release/'使用说明.md')
    print(json.dumps({'release':str(release)},ensure_ascii=False))

if __name__=='__main__':main()
