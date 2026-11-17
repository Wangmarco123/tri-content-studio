"""AI transports for the one-click workbench; never performs platform actions."""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from PIL import Image
from .core import redact
from .jobs import stop_owned_process
from .operations import _request_json,_llm_url

class GenerationCancelled(Exception):pass

def find_codex():
    value=shutil.which('codex.exe') or shutil.which('codex')
    if value:return Path(value)
    base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'OpenAI'/'Codex'/'bin'
    matches=list(base.glob('*/codex.exe')) if base.is_dir() else []
    return max(matches,key=lambda p:p.stat().st_mtime) if matches else None

def codex_status():
    executable=find_codex()
    if not executable:return {'available':False,'logged_in':False,'message':'未找到本机Codex，可安装登录Codex或连接兼容模型'}
    try:
        result=subprocess.run([str(executable),'login','status'],capture_output=True,encoding='utf-8',timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        logged=result.returncode==0
        return {'available':True,'logged_in':logged,'message':'本机Codex已登录，可直接生成' if logged else '本机Codex需要本人登录'}
    except (OSError,subprocess.TimeoutExpired):return {'available':True,'logged_in':False,'message':'暂时无法检查本机Codex，请重试连接检查'}

def codex_command(executable,work,schema,output,frames,config):
    args=[str(executable),'--no-daemon','--search','-a','never']
    for feature in ('apps','shell_tool','unified_exec','computer_use','browser_use','in_app_browser','hooks','multi_agent','goals'):
        args+=['--disable',feature]
    args+=['exec','-','--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','read-only','--json','--output-schema',str(schema),'--output-last-message',str(output),'-C',str(work)]
    if config.get('codex_model'):args+=['--model',str(config['codex_model'])]
    for frame in frames:args+=['--image',str(frame['path'])]
    return args

def _cancelled(cancel):return bool(cancel and cancel())

def validate_frames(frames):
    if not isinstance(frames,list) or len(frames)>8:raise ValueError('最多允许8张实际抽帧JPEG')
    for frame in frames:
        path=Path(frame['path'])
        if path.suffix.lower() not in ('.jpg','.jpeg') or not path.is_file() or path.stat().st_size>2*1024*1024:raise ValueError('抽帧文件须为不超过2MiB的JPEG')
        try:
            with Image.open(path) as img:
                if img.format!='JPEG':raise ValueError('抽帧文件必须是实际JPEG')
                img.verify()
        except (OSError,Image.DecompressionBombError) as exc:raise ValueError('抽帧JPEG无效') from exc

def run_codex(prompt,schema,frames,work_dir,config=None,cancel=None,emit=None):
    if _cancelled(cancel):raise GenerationCancelled()
    validate_frames(frames)
    executable=find_codex()
    if not executable:raise ValueError('未找到本机Codex；请安装并登录Codex，或选择已配置的兼容模型')
    work=Path(work_dir);work.mkdir(parents=True,exist_ok=True)
    schema_file=work/'response-schema.json';output=work/'ai-result.json';events=work/'ai-events.jsonl'
    if output.exists():output.replace(work/('ai-result-previous-'+uuid.uuid4().hex[:12]+'.json'))
    schema_file.write_text(json.dumps(schema,ensure_ascii=False),encoding='utf-8')
    prompt_file=work/'ai-prompt.txt';prompt_file.write_text(prompt,encoding='utf-8')
    if prompt_file.stat().st_size>8*1024*1024:raise ValueError('AI输入过大，请缩减证据')
    env=os.environ.copy()
    for key in ('CODEX_THREAD_ID','CODEX_TURN_ID','CODEX_API_KEY','OPENAI_API_KEY'):env.pop(key,None)
    env['PYTHONUTF8']='1'
    started=time.monotonic();proc=None
    with events.open('wb') as log,prompt_file.open('rb') as prompt_input:
        try:
            proc=subprocess.Popen(codex_command(executable,work,schema_file,output,frames,config or {}),stdin=prompt_input,stdout=log,stderr=subprocess.STDOUT,cwd=work,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while proc.poll() is None:
                if _cancelled(cancel):raise GenerationCancelled()
                if time.monotonic()-started>420:raise ValueError('AI生成超过7分钟，已停止本次任务；不会自动重试')
                if events.stat().st_size>12*1024*1024:raise ValueError('AI输出过大，已停止本次任务')
                time.sleep(.2)
            if events.stat().st_size>12*1024*1024:raise ValueError('AI输出过大，已停止本次任务')
            if output.is_file() and output.stat().st_size>4*1024*1024:raise ValueError('AI结果过大，已停止本次任务')
            if proc.returncode!=0 or not output.is_file():
                message='本机Codex生成未完成，请检查登录状态、网络或额度'
                for line in events.read_text(encoding='utf-8',errors='replace').splitlines()[-12:]:
                    try:
                        item=json.loads(line)
                        if item.get('type') in ('error','turn.failed'):
                            error=item.get('error',{});message+='：'+redact(error.get('message','') if isinstance(error,dict) else str(error))[:220];break
                    except ValueError:pass
                raise ValueError(message)
            if _cancelled(cancel):raise GenerationCancelled()
            return json.loads(output.read_text(encoding='utf-8-sig'))
        finally:
            if proc is not None:
                if proc.poll() is None:stop_owned_process(proc)
                proc.wait(timeout=5)

def run_api(prompt,schema,frames,config,cancel=None):
    if _cancelled(cancel):raise GenerationCancelled()
    validate_frames(frames)
    key=str(config.get('api_key','')).strip();model=str(config.get('model','')).strip()
    if not key or not model:raise ValueError('兼容模型未配置完整，请使用本机Codex或先连接模型')
    if '\r' in key or '\n' in key:raise ValueError('API Key格式无效，请重新粘贴单行密钥')
    content=[{'type':'text','text':prompt+'\n输出JSON Schema：'+json.dumps(schema,ensure_ascii=False)}]
    for frame in frames:
        image=Path(frame['path']).read_bytes()
        if len(image)>2*1024*1024:raise ValueError('抽帧图像过大，已停止发送')
        content+=[{'type':'text','text':f"抽样画面时间：{frame['timestamp']}秒"},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(image).decode('ascii')}}]
    result=_request_json(_llm_url(config.get('base_url')),timeout=60,body={'model':model,'messages':[{'role':'user','content':content}],'response_format':{'type':'json_object'}},headers={'Authorization':'Bearer '+key})
    if _cancelled(cancel):raise GenerationCancelled()
    try:
        raw=result['choices'][0]['message']['content'].strip()
        if raw.startswith('```'):raw=raw.split('\n',1)[1].rsplit('```',1)[0]
        return json.loads(raw)
    except (KeyError,IndexError,AttributeError,ValueError):raise ValueError('模型未返回有效的五块方案JSON，请重试生成') from None
