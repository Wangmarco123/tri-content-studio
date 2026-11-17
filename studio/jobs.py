import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from .core import now, redact, file_hash

def worker_command():
    if getattr(sys,'frozen',False):
        cli=Path(sys.executable).parent/'ContentCtl.exe'
        if not cli.is_file():raise ValueError('缺少同级 ContentCtl.exe，请恢复完整软件目录')
        return [str(cli),'_worker']
    return [sys.executable,'-m','studio.cli','_worker']

def stop_owned_process(proc):
    """Only stop the still-live process handle this supervisor created."""
    if proc.poll() is not None:return
    if os.name=='nt' and getattr(proc,'pid',None):
        try:
            # Keep helper browsers/engine children scoped to this live owned PID.
            subprocess.run([str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32'/'taskkill.exe'),'/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError,subprocess.TimeoutExpired):pass
    if proc.poll() is None:proc.terminate()
    try:proc.wait(timeout=3)
    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)

class JobManager:
    def __init__(self,service):
        self.service=service;self.wake=threading.Event();self.stopping=threading.Event();self.active=None
        self.thread=threading.Thread(target=self.loop,name='publish-queue',daemon=True)
    def start(self): self.thread.start()
    def stop(self):
        self.stopping.set()
        if self.active:
            marker=self.service.paths.data_dir/'jobs'/self.active/'cancel'
            marker.parent.mkdir(parents=True,exist_ok=True);marker.touch()
        self.wake.set();self.thread.join(timeout=25)
        if self.thread.is_alive(): raise RuntimeError('后台任务尚未结束，请稍后再退出')
    def loop(self):
        while not self.stopping.is_set():
            pending=[j for j in reversed(self.service.jobs()) if j['status']=='queued']
            if pending:
                self.active=pending[0]['id']
                try: self.run_one(pending[0])
                except Exception as exc:
                    status='outcome_unknown' if pending[0]['action'] in ('publish','update_publication') else 'failed'
                    message=('本地执行或结果读取中断，请核对原稿件，禁止自动重发。' if status=='outcome_unknown' else '')+redact(exc)
                    self.service.store.update('jobs',self.active,{'status':status,'message':message,'result':{'status':status,'message':message},'finished_at':now()})
                finally: self.active=None
            else:
                self.wake.wait(0.5);self.wake.clear()
    def run_one(self,job):
        s=self.service
        if s.get_job(job['id'])['status']!='queued': return
        payload=job.get('payload',{})
        if payload.get('file') and (not Path(payload['file']).is_file() or file_hash(payload['file'])!=payload.get('sha256')):
            s.store.update('jobs',job['id'],{'status':'failed','message':'源视频已变化，未执行上传'});return
        folder=s.paths.data_dir/'jobs'/job['id'];folder.mkdir(parents=True,exist_ok=True)
        request=folder/'request.json';events=folder/'events.jsonl';result=folder/'result.json';cancel=folder/'cancel'
        context={'engine_root':str(s.paths.project_root),'state_root':str(s.paths.project_root/'state'),'cancel_path':str(cancel)}
        request.write_text(json.dumps({'job':job,'context':context},ensure_ascii=False),encoding='utf-8')
        command=worker_command()+['--request',str(request),'--events',str(events),'--result',str(result)]
        env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
        with s.lock:
            # A queued cancellation during hashing/preparation wins this claim.
            if s.get_job(job['id'])['status']!='queued':return
            s.store.update('jobs',job['id'],{'status':'running','stage':'starting','message':'正在启动平台工作进程'})
        kwargs={'cwd':str(Path(__file__).resolve().parent.parent),'env':env,'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL}
        if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
        proc=subprocess.Popen(command,**kwargs)
        offset=0;cancel_since=None;started=time.monotonic()
        try:
            while proc.poll() is None:
                offset=self.read_events(job['id'],events,offset)
                if self.stopping.is_set(): cancel.touch(exist_ok=True)
                if cancel.exists():
                    cancel_since=cancel_since or time.monotonic()
                    if time.monotonic()-cancel_since>12:break
                budget=360 if job['action'] in ('login','check') else 1800
                if time.monotonic()-started>budget:
                    cancel.touch(exist_ok=True);cancel_since=cancel_since or time.monotonic()
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                cancel.touch(exist_ok=True)
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:pass
                if proc.poll() is None:stop_owned_process(proc)
            proc.wait(timeout=3)
        self.read_events(job['id'],events,offset)
        current=s.get_job(job['id']);stage=current.get('stage','')
        if result.exists():
            value=json.loads(result.read_text(encoding='utf-8'))
            value['message']=redact(value.get('message',''))
            status=value.get('status','failed')
            if status not in ('complete','failed','cancelled','draft_saved','submitted','outcome_unknown','awaiting_user'):
                status='outcome_unknown' if job['action'] in ('publish','update_publication') else 'failed'
        else:
            status='outcome_unknown' if job['action'] in ('publish','update_publication') else ('cancelled' if cancel.exists() else 'failed')
            value={'status':status,'message':'本地观察已停止；请核对原页面，未自动重发'}
        if job['action'] in ('publish','update_publication') and stage in ('submit_requested','submitted','verifying') and status in ('cancelled','failed'):
            status='outcome_unknown';value['message']='已请求提交，本地停止或错误不等于撤回，请核对稿件'
        value['status']=status
        s.store.update('jobs',job['id'],{'status':status,'message':value.get('message',''),'progress':100 if status in ('complete','draft_saved','submitted') else current.get('progress',0),'result':value,'finished_at':now()})
    def read_events(self,job_id,path,offset):
        if not path.exists(): return offset
        with path.open('r',encoding='utf-8') as f:
            f.seek(offset)
            while True:
                before=f.tell();line=f.readline()
                if not line or not line.endswith('\n'): return before
                try: self.service.add_event(job_id,json.loads(line))
                except (ValueError,json.JSONDecodeError): pass

def run_worker(request_path,events_path,result_path):
    from .adapters import execute
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    def emit(event):
        event=dict(event);event['message']=redact(event.get('message',''))
        with Path(events_path).open('a',encoding='utf-8') as f: f.write(json.dumps(event,ensure_ascii=False)+'\n')
    try: result=execute(request['job'],request['context'],emit)
    except Exception as exc: result={'status':'outcome_unknown' if request['job']['action'] in ('publish','update_publication') else 'failed','message':redact(str(exc))}
    result['message']=redact(result.get('message',''))
    Path(result_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result.get('status') in ('complete','draft_saved','submitted') else 2
