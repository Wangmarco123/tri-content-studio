import hashlib
import json
import re
import threading
from pathlib import Path
from urllib.parse import urlparse
from .core import Store, Paths, PLATFORMS, file_hash, uid, now, redact, protect_secret, unprotect_secret

class Service:
    def __init__(self,project_root,data_dir=None,start_worker=True):
        self.paths=Paths(project_root,data_dir);self.store=Store(self.paths.data_dir)
        self.lock=threading.RLock();self.closed=False;self.worker=None
        from .campaigns import CampaignManager
        self.campaign_manager=CampaignManager(self)
        for campaign in self.campaigns():
            if campaign['status'] in ('queued','running'):self.store.update('campaigns',campaign['id'],{'status':'failed','message':'上次AI生成已中断，未自动重新消耗AI额度'})
        self.settings_path=self.paths.data_dir/'settings.json'
        for j in self.jobs():
            if j.get('platform')=='xiaohongshu' and j['status']=='queued':
                self.store.update('jobs',j['id'],{'status':'cancelled','message':'小红书已改为人工发布，旧自动任务已取消'})
                continue
            if j['status'] in ('running','awaiting_user','cancel_requested'):
                status='outcome_unknown' if j['action'] in ('publish','update_publication') else 'failed'
                self.store.update('jobs',j['id'],{'status':status,'message':'软件上次退出中断，请核对原页面；不会自动重发'})
        if start_worker:
            from .jobs import JobManager
            self.worker=JobManager(self);self.worker.start()
    def health(self):
        from . import __version__
        return {'ok':True,'name':'三平台内容发布助手','version':__version__,'schema_version':2,'platforms':list(PLATFORMS),'automatic_platforms':['bilibili','douyin'],'manual_platforms':['xiaohongshu']}
    def assets(self): return self.store.list('assets')
    def campaigns(self): return self.store.list('campaigns')
    def get_campaign(self,record_id): return self.store.get('campaigns',record_id)
    def start_campaign(self,payload): return self.campaign_manager.start(payload)
    def cancel_campaign(self,record_id): return self.campaign_manager.cancel(record_id)
    def ai_status(self):
        from .ai_provider import codex_status
        from .asr import asr_status
        local=codex_status();cfg=self._settings_raw().get('llm',{})
        configured=bool(cfg.get('api_key_protected') and cfg.get('base_url') and cfg.get('model'))
        return {'codex':local,'api':{'configured':configured},'default_provider':'codex' if local.get('logged_in') else ('api' if configured else 'none'),'asr':asr_status(self.paths.project_root)}
    def save_campaign(self,payload):
        from .campaigns import canonical_package
        record=self.get_campaign(payload.get('id',''))
        if record['status']!='complete' or not record.get('result'):raise ValueError('请先完成一键生成')
        selections=payload.get('selections',{})
        if not isinstance(selections,dict):raise ValueError('标题选择格式错误')
        if not isinstance(payload.get('queue_drafts',False),bool):raise ValueError('queue_drafts须为布尔值')
        existing={self.store.get('drafts',x)['platform']:self.store.get('drafts',x) for x in record.get('draft_ids',[])}
        records=[]
        with self.lock,self.store.transaction():
            for package in record['result']['packages']:
                p=dict(canonical_package(package),asset_id=record['asset_id'],visibility='draft');platform=p['platform']
                index=selections.get(platform,0);titles=p.get('title_candidates') or [p['title']]
                if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(titles):raise ValueError('标题候选索引无效')
                p['title']=titles[index]
                old=existing.get(platform)
                if old and all(old.get(k)==v for k,v in p.items()):d=old
                else:
                    if old:p['id']=old['id']
                    d=self.save_draft(p)
                records.append(d)
            self.store.update('campaigns',record['id'],{'draft_ids':[d['id'] for d in records]})
        jobs=[]
        if payload.get('queue_drafts'):
            for d in records:
                if d['platform']!='douyin':continue
                identity=json.dumps({k:d.get(k) for k in ('title','caption','tags')},ensure_ascii=False,sort_keys=True)
                key='campaign:'+record['id']+':'+d['platform']+':'+hashlib.sha256(identity.encode()).hexdigest()[:16]
                jobs.append(self.create_job({'action':'draft','platform':d['platform'],'draft_id':d['id'],'idempotency_key':key}))
        return {'items':records,'count':len(records),'jobs':jobs}
    def drafts(self): return self.store.list('drafts')
    def evidence(self): return self.store.list('evidence')
    def jobs(self): return self.store.list('jobs')
    def get_job(self,record_id): return self.store.get('jobs',record_id)
    def events(self,record_id): return [e for e in reversed(self.store.list('events')) if e['job_id']==record_id]
    def add_event(self,job_id,event):
        safe={k:v for k,v in event.items() if k in ('stage','progress','qr_path','requires_user')}
        safe['message']=redact(event.get('message',''))
        safe.update(id=uid('ev'),job_id=job_id,created_at=now())
        self.store.put('events',safe)
        change={'message':safe['message']}
        for key in ('stage','progress','qr_path'):
            if key in safe: change[key]=safe[key]
        if safe.get('requires_user'): change['status']='awaiting_user'
        elif self.get_job(job_id)['status']=='awaiting_user': change['status']='running'
        self.store.update('jobs',job_id,change)
    def add_asset(self,payload):
        path=Path(str(payload.get('path',''))).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in ('.mp4','.mov','.mkv','.avi','.webm','.m4v'):
            raise ValueError('请选择存在的视频文件')
        digest=file_hash(path)
        with self.lock:
            for a in self.assets():
                if a['sha256']==digest and a['path']==str(path): return a
            a={'id':uid('asset'),'path':str(path),'name':path.name,'size':path.stat().st_size,'sha256':digest,'summary':str(payload.get('summary','')),'audience':str(payload.get('audience','')),'facts':payload.get('facts',[]),'keywords':payload.get('keywords',[]),'created_at':now()}
            return self.store.put('assets',a)
    def update_asset(self,record_id,payload):
        updates={k:payload[k] for k in ('summary','audience','facts','keywords') if k in payload}
        for key in ('facts','keywords'):
            if key in updates and (not isinstance(updates[key],list) or not all(isinstance(x,str) for x in updates[key])): raise ValueError(key+'须为文本数组')
        return self.store.update('assets',record_id,updates)
    def save_draft(self,payload):
        a=self.store.get('assets',payload.get('asset_id',''))
        platform=payload.get('platform')
        if platform not in PLATFORMS: raise ValueError('请选择正确平台')
        title=str(payload.get('title','')).strip()
        if not title or len(title)>{'bilibili':80,'douyin':30,'xiaohongshu':20}[platform]: raise ValueError('标题为空或超过当前平台长度策略')
        tags=payload.get('tags',[])
        if not isinstance(tags,list) or not all(isinstance(t,str) for t in tags): raise ValueError('话题须为文本数组')
        visibility=payload.get('visibility','draft')
        if visibility not in ('draft','private','public'): raise ValueError('可见范围不支持')
        known={e['id'] for e in self.evidence()}
        if not set(payload.get('evidence_ids',[]))<=known: raise ValueError('文案引用了不存在的证据')
        d={k:payload[k] for k in ('hook','evidence_ids','fit_reason','tag_checks','warnings','title_candidates','category_suggestion','search_keywords') if k in payload}
        d.update(id=payload.get('id') or uid('draft'),asset_id=a['id'],platform=platform,title=title,caption=str(payload.get('caption','')),tags=list(dict.fromkeys(t.strip().lstrip('#').strip() for t in tags if t.strip().lstrip('#').strip())),visibility=visibility,updated_at=now())
        with self.store.transaction():
            if payload.get('id'):
                old=self.store.get('drafts',d['id'])
                self.store.put('versions',{'id':uid('version'),'draft_id':d['id'],'snapshot':old,'created_at':now()})
            return self.store.put('drafts',d)
    def import_evidence(self,payload):
        items=payload.get('items')
        if not isinstance(items,list) or len(items)>200: raise ValueError('证据须为最多200项的items数组')
        normalized=[]
        for item in items:
            if not isinstance(item,dict) or item.get('platform') not in PLATFORMS: raise ValueError('证据平台不正确')
            if not str(item.get('title','')).strip() or urlparse(str(item.get('source_url',''))).scheme not in ('http','https'): raise ValueError('证据需要标题与http(s)来源链接')
            record={k:item[k] for k in ('title','platform','source_url','source_updated_at','rank','metric','verification','notes') if k in item}
            record.update(id=item.get('id') or uid('evidence'),fetched_at=item.get('fetched_at') or now())
            normalized.append(record)
        with self.lock,self.store.transaction():
            for record in normalized: self.store.put('evidence',record)
        return {'items':normalized,'count':len(normalized)}
    def fetch_trends(self,platform,keyword=''):
        from .operations import fetch_trends
        result=fetch_trends(platform,keyword)
        if result.get('items'):
            result['items']=self.import_evidence({'items':result['items']})['items']
        return result
    def export_brief(self,asset_id):
        from .operations import build_brief
        return build_brief(self.store.get('assets',asset_id),self.evidence())
    def import_packages(self,payload):
        from .operations import validate_packages
        a=self.store.get('assets',payload.get('asset_id',''))
        packages=validate_packages(payload,a,self.evidence())
        # Validation completes for all platforms before any record is changed.
        with self.lock,self.store.transaction():
            records=[self.save_draft(dict(p,asset_id=a['id'])) for p in packages]
        return {'items':records,'count':len(records)}
    def generate(self,payload):
        from .operations import generate_packages
        a=self.store.get('assets',payload.get('asset_id',''))
        cfg=self._settings_raw().get('llm',{}).copy()
        cfg['api_key']=unprotect_secret(cfg.pop('api_key_protected',''))
        cfg.update(payload.get('config',{}))
        packages=generate_packages(a,self.evidence(),cfg)
        return self.import_packages({'asset_id':a['id'],'packages':packages})
    def _settings_raw(self):
        if self.settings_path.exists(): return json.loads(self.settings_path.read_text(encoding='utf-8'))
        return {'llm':{'base_url':'','model':''}}
    def settings(self):
        cfg=self._settings_raw();llm=cfg.get('llm',{})
        return {'llm':{'base_url':llm.get('base_url',''),'model':llm.get('model',''),'has_api_key':bool(llm.get('api_key_protected'))}}
    def save_settings(self,payload):
        with self.lock:
            cfg=self._settings_raw();llm=cfg.setdefault('llm',{})
            inp=payload.get('llm',{})
            for k in ('base_url','model'):
                if k in inp: llm[k]=str(inp[k]).strip()
            if inp.get('api_key'): llm['api_key_protected']=protect_secret(str(inp['api_key']))
            if inp.get('clear_api_key'): llm.pop('api_key_protected',None)
            self.settings_path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
        return self.settings()
    def accounts(self):
        records=[]
        for platform in ('bilibili','douyin'):
            state=self.paths.project_root/'state'/('xiaohongshu-sau' if platform=='xiaohongshu' else platform)
            cookie=state/('cookies.json' if platform=='bilibili' else f'{platform}_creator.json')
            jobs=[j for j in self.jobs() if j['platform']==platform]
            checks=[j for j in jobs if j['action']=='check' and j['status'] in ('complete','failed')]
            records.append({'id':platform+':creator','platform':platform,'account':'creator','has_local_state':cookie.exists(),'status':'有本地记录，待在线检查' if cookie.exists() else '尚未登录','last_check':checks[0].get('result') if checks else None})
        return records
    def create_job(self,payload):
        action=payload.get('action','draft')
        if action not in ('login','check','open_drafts','draft','publish','query_publications','update_publication'): raise ValueError('不支持的任务动作')
        account=payload.get('account','creator')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',str(account)): raise ValueError('账号别名不合法')
        account=str(account).lower()
        snap={};draft_id=payload.get('draft_id');asset_id=payload.get('asset_id')
        platform=payload.get('platform')
        if action in ('draft','publish','update_publication'):
            d=self.store.get('drafts',draft_id or '')
            if platform is not None and platform!=d['platform']: raise ValueError('请求平台与文案平台不一致')
            platform=d['platform'];asset_id=d['asset_id'];a=self.store.get('assets',asset_id)
            if not Path(a['path']).is_file() or file_hash(a['path'])!=a['sha256']: raise ValueError('素材已修改或丢失，请重新导入')
            visibility='draft' if action=='draft' else payload.get('visibility')
            if action in ('publish','update_publication') and visibility not in ('public','private'): raise ValueError('正式发布必须明确选择public或private')
            if action=='draft' and platform=='bilibili': raise ValueError('B站当前适配器不提供草稿；可明确选择仅自己可见投稿')
            snap=dict(d,file=a['path'],sha256=a['sha256'],visibility=visibility,account=account)
            if action=='update_publication':
                old=self.get_job(payload.get('matched_job_id',''))
                if platform!='bilibili' or old['platform']!=platform or old['account']!=account or old['status']!='submitted' or not (old.get('result') or {}).get('evidence',{}).get('creator_readback'):raise ValueError('改稿必须引用已核实的同账号B站原稿件')
                if old['payload'].get('sha256')!=a['sha256']:raise ValueError('原稿件素材与新文案素材不同')
                snap['remote_id']=old['result']['remote_id']
                transport=payload.get('transport','browser')
                if transport not in ('browser','api'):raise ValueError('不支持的改稿方式')
                snap['transport']=transport
                snap['update_protocol']='creator-edit-v2-verified-tags'
        if platform=='xiaohongshu':raise ValueError('小红书已移除自动操作，请导出文案后人工发布')
        if platform not in PLATFORMS: raise ValueError('平台不正确')
        if action=='open_drafts' and platform=='bilibili': raise ValueError('B站请使用创作中心核对稿件')
        fingerprint=hashlib.sha256(json.dumps([platform,account,action,snap],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        key=str(payload.get('idempotency_key') or fingerprint)
        with self.lock:
            for previous in self.jobs():
                if previous.get('idempotency_key')==key:
                    if previous.get('fingerprint')!=fingerprint: raise ValueError('此幂等键已用于不同任务，请使用新的幂等键')
                    return previous
                same_video=previous.get('asset_id')==asset_id or (bool(snap.get('sha256')) and previous.get('payload',{}).get('sha256')==snap.get('sha256'))
                if action in ('draft','publish') and previous.get('action')=='publish' and previous.get('status') in ('queued','running','awaiting_user','cancel_requested','submitted') and same_video and previous.get('platform')==platform and str(previous.get('account','creator')).lower()==account:
                    raise ValueError('同一视频已有执行中或已受理稿件，请查询核对或修改原稿件，不得重复上传')
                if action in ('draft','publish') and previous.get('action')=='publish' and previous.get('status')=='outcome_unknown' and same_video and previous.get('platform')==platform and str(previous.get('account','creator')).lower()==account:
                    raise ValueError('此素材在该平台账号已有待核实提交，请先核对原稿件，不得修改文案或换动作重复上传')
                if previous.get('fingerprint')==fingerprint:
                    if previous['status']=='outcome_unknown': raise ValueError('同一发布结果未确认，请先核对原稿件，禁止重复提交')
                    if previous['status'] in ('queued','running','awaiting_user','cancel_requested','submitted','draft_saved'): return previous
            job={'id':uid('job'),'platform':platform,'account':account,'action':action,'asset_id':asset_id,'draft_id':draft_id,'payload':snap,'status':'queued','stage':'queued','message':'等待执行','progress':0,'created_at':now(),'updated_at':now(),'result':None,'fingerprint':fingerprint,'idempotency_key':key}
            self.store.put('jobs',job)
        if self.worker: self.worker.wake.set()
        return job
    def query_publications(self,payload):
        return self.create_job({'platform':payload.get('platform'),'account':payload.get('account','creator'),'action':'query_publications','idempotency_key':uid('query')})
    def publications(self):
        return [{'query_job_id':j['id'],'platform':j['platform'],'account':j['account'],'checked_at':j.get('finished_at'),'result':j.get('result')} for j in self.jobs() if j['action']=='query_publications']
    def reconcile_publication(self,record_id,payload):
        from datetime import datetime,timezone,timedelta
        old=self.get_job(record_id);query=self.get_job(payload.get('query_job_id',''))
        if old['action'] not in ('publish','update_publication') or old['status'] not in ('outcome_unknown','submitted'):raise ValueError('只核对已提交或待核实发布任务')
        if query['action']!='query_publications' or query['status']!='complete' or query['platform']!=old['platform'] or query['account']!=old['account']:raise ValueError('需要同账号平台的成功只读查询回执')
        remote=payload.get('remote_id');rows=[r for r in (query.get('result') or {}).get('items',[]) if r.get('remote_id')==remote]
        if len(rows)!=1:raise ValueError('查询结果中没有唯一对应作品；未解除防重投')
        row=rows[0];snapshot=old['payload']
        actual_title=row.get('title','');expected_title=snapshot.get('title','')
        if old['platform']=='douyin':
            clean=lambda s:''.join(s.replace('\u200b','').split())
            if clean(expected_title) not in clean(actual_title) or clean(snapshot.get('caption','')) not in clean(actual_title):raise ValueError('抖音作品标题和正文未对应提交快照')
        elif actual_title!=expected_title:raise ValueError('作品标题与原提交快照不一致，需进一步核实')
        when=row.get('created_at_raw');duration=row.get('duration_raw')
        if old['platform']=='xiaohongshu' and isinstance(when,str):
            try:when=datetime.fromisoformat(when).replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
            except ValueError:raise ValueError('小红书作品日期不可解析')
        if old['action']=='update_publication':
            if snapshot.get('remote_id')!=remote:raise ValueError('改稿对应的原稿件编号不同')
        elif not isinstance(when,(int,float)) or abs(when-datetime.fromisoformat(old['created_at']).timestamp())>1800:raise ValueError('作品时间不能对应本次旧投稿')
        if not isinstance(duration,(int,float)):raise ValueError('作品时长缺失，不能自动对应')
        if old['platform']=='douyin':duration/=1000
        from .asr import probe_audio
        expected=float((probe_audio(snapshot['file'],self.paths.project_root) or {}).get('duration') or 0)
        if expected<=0 or abs(duration-expected)>3:raise ValueError('作品时长与原视频不符')
        actual=row.get('visibility','unknown');verified=actual==snapshot.get('visibility')
        result={'status':'submitted' if verified else 'outcome_unknown','message':'作品编号、文案、时间、时长及可见范围已回读' if verified else '作品已对应，但可见范围尚未核实','remote_id':remote,'url':row.get('url'),'visibility':actual,'evidence':{'query_job_id':query['id'],'identity_basis':['exact_title','submission_time','duration'],'creator_readback':True,'visibility_readback':verified,'status_raw':row.get('status_raw')}}
        history=list(old.get('verification_history',[]));history.append({'at':now(),'result':old.get('result')})
        return self.store.update('jobs',record_id,{'status':result['status'],'result':result,'message':result['message'],'verification_history':history})
    def resolve_unsubmitted(self,record_id,payload):
        old=self.get_job(record_id);query=self.get_job(payload.get('query_job_id',''))
        if old['action']!='publish' or old['status']!='outcome_unknown' or old['platform']=='bilibili':raise ValueError('仅核对浏览器旧提交前异常')
        if query['action']!='query_publications' or query['status']!='complete' or query['platform']!=old['platform'] or query['account']!=old['account']:raise ValueError('需要同账号平台成功作品查询')
        events=self.events(record_id);stages=[e.get('stage') for e in events]
        message=(old.get('result') or {}).get('message','')
        if not stages or 'submit_requested' in stages or stages[-1] not in ('uploading','prepared') or not any(x in message for x in ('（ValueError）','（TimeoutError）')):raise ValueError('本地记录不足以证明停在提交前，保持待核实')
        result={'status':'failed','message':'本地工作进程在发布按钮调用前异常结束；已另查作品列表，不以列表缺席证明远端不存在','evidence':{'query_job_id':query['id'],'stages':stages,'submission_attempted':False,'remote_absence_verified':False,'resolution':'local_pre_submit_failure'}}
        return self.store.update('jobs',record_id,{'status':'failed','result':result,'message':result['message']})
    def cancel_job(self,record_id):
        with self.lock:
            j=self.get_job(record_id)
            if j['status']=='queued': return self.store.update('jobs',record_id,{'status':'cancelled','message':'尚未执行，已取消'})
            if j['status'] in ('running','awaiting_user','cancel_requested'):
                marker=self.paths.data_dir/'jobs'/record_id/'cancel'
                marker.parent.mkdir(parents=True,exist_ok=True);marker.touch()
                return self.store.update('jobs',record_id,{'status':'cancel_requested','message':'请求停止本地操作；已提交的远端稿件不会自动撤回'})
            return j
    def close(self):
        if self.closed: return
        self.campaign_manager.stop()
        if self.worker: self.worker.stop()
        self.store.close()
        self.closed=True
