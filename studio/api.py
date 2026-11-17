import hmac
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from . import __version__

# One route/method table drives both documentation and dispatch admission.
# Values are (request schema, response schema). A trailing [] means a JSON array.
ROUTES = {
    '/publications': {'GET':(None,'PublicationQueries')},
    '/publications/update': {'POST':('PublicationUpdate','Job')},
    '/publications/query': {'POST':('PublicationQuery','Job')},
    '/jobs/{id}/resolve-unsubmitted': {'POST':('ResolveUnsubmitted','Job')},
    '/jobs/{id}/reconcile': {'POST':('ReconcilePublication','Job')},
    '/ai/status': {'GET':(None,'AIStatus')},
    '/campaigns': {'GET':(None,'Campaign[]'),'POST':('CampaignStart','Campaign')},
    '/campaigns/{id}': {'GET':(None,'Campaign')},
    '/campaigns/{id}/cancel': {'POST':(None,'Campaign')},
    '/campaigns/{id}/save': {'POST':('CampaignSave','CampaignSaveResult')},
    '/assets': {'GET':(None,'Asset[]'),'POST':('AssetCreate','Asset')},
    '/assets/{id}': {'PUT':('AssetUpdate','Asset')},
    '/drafts': {'GET':(None,'Draft[]'),'POST':('DraftCreate','Draft')},
    '/evidence': {'GET':(None,'Evidence[]')},
    '/evidence/import': {'POST':('EvidenceImport','EvidenceResult')},
    '/trends/fetch': {'POST':('TrendsRequest','TrendsResult')},
    '/briefs/{id}': {'GET':(None,'Brief')},
    '/packages/import': {'POST':('PackagesImport','DraftResult')},
    '/generate': {'POST':('GenerateRequest','DraftResult')},
    '/jobs': {'GET':(None,'Job[]'),'POST':('JobCreate','Job')},
    '/jobs/{id}': {'GET':(None,'Job')},
    '/jobs/{id}/events': {'GET':(None,'Event[]')},
    '/jobs/{id}/cancel': {'POST':(None,'Job')},
    '/jobs/{id}/qrcode': {'GET':(None,'PNG')},
    '/accounts': {'GET':(None,'Account[]')},
    '/settings': {'GET':(None,'Settings'),'POST':('SettingsUpdate','Settings')},
    '/health': {'GET':(None,'Health')},
    '/openapi.json': {'GET':(None,'OpenAPIDocument')},
}


def _ref(name):
    if name.endswith('[]'): return {'type':'array','items':_ref(name[:-2])}
    return {'$ref':'#/components/schemas/'+name}


def _object(properties, required=(), **extra):
    value={'type':'object','properties':properties,**extra}
    if required: value['required']=list(required)
    return value


def api_schemas():
    text={'type':'string'};strings={'type':'array','items':text}
    stamp={'type':'string','format':'date-time'}
    platform={'type':'string','enum':['bilibili','douyin','xiaohongshu']}
    account={'type':'string','pattern':'^[A-Za-z0-9_-]{1,40}$','default':'creator'}
    visibility={'type':'string','enum':['draft','private','public'],'default':'draft'}
    asset_edit={'summary':text,'audience':text,'facts':strings,'keywords':strings}
    draft_fields={'asset_id':text,'platform':platform,'title':dict(text,minLength=1,description='B站最多80、抖音30、小红书20字符；服务端校验平台策略。'),'title_candidates':{'type':'array','maxItems':5,'items':text},'category_suggestion':text,'search_keywords':strings,'caption':text,'tags':strings,'hook':text,'visibility':visibility,'evidence_ids':strings,'fit_reason':text,'tag_checks':{'type':'array','items':_ref('TagCheck')},'warnings':strings}
    evidence={'id':text,'platform':platform,'title':text,'source_url':{'type':'string','format':'uri'},'fetched_at':stamp,'source_updated_at':stamp,'rank':{'type':'integer'},'metric':_ref('Metric'),'verification':text,'notes':text}
    automatic_platform={'type':'string','enum':['bilibili','douyin']}
    command={'platform':automatic_platform,'account':account,'action':{'type':'string','enum':['login','check','open_drafts','query_publications']},'idempotency_key':text}
    draft_job={'platform':automatic_platform,'account':account,'action':{'type':'string','enum':['draft']},'asset_id':text,'draft_id':text,'idempotency_key':text}
    publish_job={**draft_job,'action':{'type':'string','enum':['publish']},'visibility':{'type':'string','enum':['private','public']}}
    llm={'base_url':{'type':'string','description':'HTTPS，或明确的本机HTTP服务；只发送素材事实与公开证据。'},'model':text,'api_key':dict(text,writeOnly=True),'clear_api_key':{'type':'boolean','default':False}}
    schemas={
        'PublicationQueries':{'type':'array','items':{'type':'object','additionalProperties':True}},
        'PublicationUpdate':_object({'draft_id':text,'matched_job_id':text,'visibility':{'type':'string','enum':['public','private']},'account':account,'transport':{'type':'string','enum':['browser','api'],'default':'browser'}},('draft_id','matched_job_id','visibility'),additionalProperties=False),
        'PublicationQuery':_object({'platform':automatic_platform,'account':account},('platform',),additionalProperties=False),
        'ResolveUnsubmitted':_object({'query_job_id':text},('query_job_id',),additionalProperties=False),
        'ReconcilePublication':_object({'query_job_id':text,'remote_id':text},('query_job_id','remote_id'),additionalProperties=False),
        'ASRStatus':_object({'ready':{'type':'boolean'},'model':text,'engine':text,'model_path':dict(text,nullable=True),'dependency_available':{'type':'boolean'},'cuda_libraries_present':{'type':'boolean'},'device_capability':dict(text,nullable=True),'message':text},('ready','model','engine','dependency_available','cuda_libraries_present','message'),description='Local files/dependency readiness only; no model loading or GPU inference in this check.'),
        'SpeechSegment':_object({'start':{'type':'number','minimum':0},'end':{'type':'number','minimum':0},'text':text,'avg_logprob':{'type':'number'},'no_speech_prob':{'type':'number'},'compression_ratio':{'type':'number'},'uncertain':{'type':'boolean'}},('start','end','text')),
        'Speech':_object({'status':{'type':'string','enum':['complete','no_audio','no_speech']},'complete':{'type':'boolean'},'engine':text,'model':text,'device':{'type':'string','enum':['cuda','cpu'],'nullable':True},'compute_type':text,'language':dict(text,nullable=True),'language_probability':{'type':'number','nullable':True},'audio_duration':{'type':'number','minimum':0},'processed_duration':{'type':'number','minimum':0},'segments':{'type':'array','items':_ref('SpeechSegment')},'text':text,'uncertain_segments':{'type':'array','items':{'type':'integer','minimum':0}},'warnings':strings,'cache_hit':{'type':'boolean'},'txt_path':text,'srt_path':text,'json_path':text},('status','complete','audio_duration','processed_duration','segments','text'),description='Whole selected audio processed, not word-for-word accuracy certification. No 200-segment truncation. Local transcript paths do not imply permission to publish.'),
        'AIStatus':_object({'codex':_object({'available':{'type':'boolean'},'logged_in':{'type':'boolean'},'message':text},('available','logged_in','message')),'api':_object({'configured':{'type':'boolean'}},('configured',)),'default_provider':{'type':'string','enum':['codex','api','none']},'asr':_ref('ASRStatus')},('codex','api','default_provider','asr')),
        'CampaignStart':_object({'asset_id':dict(text,minLength=1),'provider':{'type':'string','enum':['auto','codex','api'],'default':'auto'},'goal':text},('asset_id',),additionalProperties=False),
        'TitleSelections':_object({'bilibili':{'type':'integer','minimum':0},'xiaohongshu':{'type':'integer','minimum':0}},additionalProperties=False),
        'CampaignSave':_object({'selections':_ref('TitleSelections'),'queue_drafts':{'type':'boolean','default':False}},additionalProperties=False),
        'CampaignSaveResult':_object({'items':{'type':'array','items':_ref('Draft')},'count':{'type':'integer','enum':[3]},'jobs':{'type':'array','items':_ref('Job')}},('items','count','jobs'),description='默认仅保存本地文案；queue_drafts只为抖音创建draft任务；小红书人工发布，不公开发布。'),
        'Campaign':_object({'id':text,'asset_id':text,'status':{'type':'string','enum':['queued','running','complete','failed','cancelled']},'stage':text,'progress':{'type':'number'},'message':text,'provider':{'type':'string','enum':['auto','codex','api']},'created_at':stamp,'updated_at':stamp,'draft_ids':strings,'result':{'allOf':[_ref('CampaignResult')],'nullable':True}},('id','asset_id','status','stage','message','result','draft_ids')),
        'Error':_object({'error':_object({'code':text,'message':text},('code','message'))},('error',)),
        'Health':_object({'ok':{'type':'boolean'},'name':text,'version':text,'schema_version':{'type':'integer'},'platforms':{'type':'array','items':platform}},('ok','version')),
        'AssetCreate':_object({'path':dict(text,minLength=1,description='本机可访问的视频绝对路径；不接收视频字节。'),**asset_edit},('path',)),
        'AssetUpdate':_object(asset_edit),
        'Asset':_object({'id':text,'path':text,'name':text,'size':{'type':'integer','minimum':0},'sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},**asset_edit,'created_at':stamp},('id','path','name','size','sha256')),
        'TagCheck':_object({'name':text,'verification':{'type':'string','enum':['verified','unverified']},'evidence_ids':strings,'reason':text},('name','verification','evidence_ids')),
        'DraftCreate':_object({'id':dict(text,description='省略时创建新文案；提供已有id时保存历史版本。'),**draft_fields},('asset_id','platform','title')),
        'Draft':_object({'id':text,**draft_fields,'updated_at':stamp},('id','asset_id','platform','title','tags','visibility')),
        'Metric':_object({'name':text,'value':{'oneOf':[{'type':'number'},text]},'unit':text},description='公开来源的原始指标；额外字段由provider定义，不同来源不保证可比较。',additionalProperties=True),
        'Evidence':_object(evidence,('id','platform','title','source_url','fetched_at')),
        'EvidenceInput':_object(evidence,('platform','title','source_url')),
        'EvidenceImport':_object({'items':{'type':'array','maxItems':200,'items':_ref('EvidenceInput')}},('items',)),
        'EvidenceResult':_object({'items':{'type':'array','items':_ref('Evidence')},'count':{'type':'integer'}},('items','count')),
        'TrendsRequest':_object({'platform':platform,'keyword':text},('platform',)),
        'TrendsResult':_object({'items':{'type':'array','items':_ref('Evidence')},'status':text,'message':text,'source_url':text,'fetched_at':stamp},('items','status','message')),
        'PackagesImport':_object({'asset_id':text,'packages':{'type':'array','minItems':1,'maxItems':30,'items':_ref('Package')}},('asset_id','packages')),
        'Package':_object({k:v for k,v in draft_fields.items() if k!='asset_id'},('platform','title','caption','tags','evidence_ids','fit_reason')),
        'DraftResult':_object({'items':{'type':'array','items':_ref('Draft')},'count':{'type':'integer'}},('items','count')),
        'GenerateRequest':_object({'asset_id':text,'config':_ref('LLMConfig')},('asset_id',)),
        'LLMConfig':_object(llm),
        'BriefAsset':_object({'id':text,'name':text,**asset_edit},('id',)),
        'Brief':_object({'schema_version':{'type':'integer'},'asset':_ref('BriefAsset'),'evidence':{'type':'array','items':_ref('Evidence')},'instructions':text,'response_schema':_ref('JSONSchema')},('schema_version','asset','evidence','instructions','response_schema')),
        'JSONSchema':_object({'type':text,'properties':{'type':'object','additionalProperties':True},'required':strings},description='嵌入的JSON Schema文档，允许标准schema关键字。',additionalProperties=True),
        'JobCreate':{'oneOf':[_ref('AccountJobCreate'),_ref('DraftJobCreate'),_ref('PublishJobCreate')],'description':'账号命令不接收任意shell；草稿引用已保存文案；发布必须明确可见范围。'},
        'AccountJobCreate':_object(command,('platform','action')),
        'DraftJobCreate':_object(draft_job,('action','draft_id')),
        'PublishJobCreate':_object(publish_job,('action','draft_id','visibility')),
        'JobSnapshot':_object({**draft_fields,'id':text,'file':text,'sha256':text,'account':account},description='服务根据本地素材与文案冻结的快照；客户端不提交file替代该快照。'),
        'JobResult':_object({'status':text,'message':text,'remote_id':text,'url':text,'visibility':visibility,'evidence':{'type':'object','additionalProperties':True}},description='平台适配器回执；submitted不等于审核通过。',additionalProperties=True),
        'Job':_object({'id':text,'platform':platform,'account':account,'action':{'type':'string','enum':['login','check','open_drafts','query_publications','draft','publish','update_publication']},'asset_id':dict(text,nullable=True),'draft_id':dict(text,nullable=True),'payload':_ref('JobSnapshot'),'status':{'type':'string','enum':['queued','running','awaiting_user','cancel_requested','draft_saved','submitted','outcome_unknown','failed','cancelled','complete']},'message':text,'stage':text,'progress':{'type':'number'},'created_at':stamp,'updated_at':stamp,'finished_at':stamp,'idempotency_key':text,'fingerprint':text,'result':{'allOf':[_ref('JobResult')],'nullable':True}},('id','platform','account','action','payload','status')),
        'Event':_object({'id':text,'job_id':text,'created_at':stamp,'stage':text,'message':text,'progress':{'type':'number'},'qr_path':text,'requires_user':{'type':'boolean'}},('id','job_id','message')),
        'Account':_object({'id':text,'platform':platform,'account':account,'has_local_state':{'type':'boolean'},'status':text,'last_check':{'allOf':[_ref('JobResult')],'nullable':True}},('id','platform','account','has_local_state','status')),
        'Settings':_object({'llm':_object({'base_url':text,'model':text,'has_api_key':{'type':'boolean'}},('base_url','model','has_api_key'))},('llm',)),
        'SettingsUpdate':_object({'llm':_ref('LLMConfig')},('llm',)),
        'OpenAPIDocument':_object({'openapi':text,'info':{'type':'object','additionalProperties':True},'servers':{'type':'array','items':{'type':'object','additionalProperties':True}},'paths':{'type':'object','additionalProperties':True},'components':{'type':'object','additionalProperties':True}},('openapi','info','paths')),
    }
    from .operations import campaign_schema
    result_schema=campaign_schema('')
    result_schema['properties']['asset_id'].pop('const',None)
    result_schema['properties'].pop('research_sources',None)
    result_schema['required'].remove('research_sources')
    result_schema['properties']['sources']={'type':'array','items':_ref('Evidence')}
    result_schema['properties']['media']=_object({'duration':{'type':'number'},'width':{'type':'integer'},'height':{'type':'integer'},'analysis_scope':text,'warnings':strings,'frames':{'type':'array','items':_object({'timestamp':{'type':'number'},'path':text},('timestamp','path'))},'transcript':{'type':'array','items':_ref('SpeechSegment')},'supplied_subtitles':{'type':'array','items':_ref('SpeechSegment')},'speech':_ref('Speech')},description='speech is optional for R02 history. R03 campaign generation adds complete local speech results before AI generation.')
    schemas['CampaignResult']=result_schema
    return schemas


def openapi_document(endpoint):
    paths={}
    for route,methods in ROUTES.items():
        item={}
        for method,(request,response) in methods.items():
            content={'image/png':{'schema':{'type':'string','format':'binary'}}} if response=='PNG' else {'application/json':{'schema':_ref(response)}}
            errors={str(code):{'description':desc,'content':{'application/json':{'schema':_ref('Error')}}} for code,desc in [(400,'Validation error'),(401,'Invalid local token'),(403,'Origin or host rejected'),(404,'Unknown route'),(405,'Method not allowed'),(413,'Body too large'),(500,'Internal error')]}
            errors['405']['headers']={'Allow':{'description':'Supported methods for this exact path','schema':{'type':'string'}}}
            op={'operationId':method.lower()+route.replace('/','_').replace('{','').replace('}','').replace('.','_'),'summary':method+' '+route,'security':[] if route in ('/health','/openapi.json') else [{'localToken':[]}],'responses':{'200':{'description':'PNG QR image' if response=='PNG' else 'JSON result','content':content},**errors}}
            if '{id}' in route: op['parameters']=[{'name':'id','in':'path','required':True,'schema':{'type':'string','minLength':1}}]
            if request: op['requestBody']={'required':True,'content':{'application/json':{'schema':_ref(request)}}}
            if route.endswith('/cancel'): op['description']='No request body required. Stops this local job or AI generation; does not withdraw remote content.'
            item[method.lower()]=op
        paths['/api/v1'+route]=item
    paths['/health']={'get':dict(paths['/api/v1/health']['get'],operationId='get_health_alias',summary='Unversioned health alias')}
    return {'openapi':'3.0.3','info':{'title':'三平台内容发布助手 Local API','version':__version__,'description':'Local-only bearer API. Exact versioned routes and methods. Draft is default; publishing requires explicit visibility. No arbitrary shell or URL fetching.'},'servers':[{'url':endpoint}],'components':{'securitySchemes':{'localToken':{'type':'http','scheme':'bearer'}},'schemas':api_schemas()},'paths':paths}


def resolve_route(path):
    if not path.startswith('/api/v1/'): return None
    short=path[len('/api/v1'):]
    for route,methods in ROUTES.items():
        pattern=re.escape(route).replace(r'\{id\}',r'([^/]+)')
        match=re.fullmatch(pattern,short)
        if match: return route,methods,match.group(1) if match.groups() else None
    return None

class ApiServer:
    def __init__(self,service,port=19266):
        self.service=service
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self): self.handle_request('GET')
            def do_POST(self): self.handle_request('POST')
            def do_PUT(self): self.handle_request('PUT')
            def do_DELETE(self): self.handle_request('DELETE')
            def do_PATCH(self): self.handle_request('PATCH')
            def do_HEAD(self): self.handle_request('HEAD')
            def do_OPTIONS(self): self.handle_request('OPTIONS')
            def reply(self,status,value,content_type='application/json; charset=utf-8',allow=None):
                body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode('utf-8')
                self.send_response(status);self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(body)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
                if allow: self.send_header('Allow',allow)
                self.end_headers()
                if self.command!='HEAD': self.wfile.write(body)
            def handle_request(self,method):
                path=urlparse(self.path).path
                # Consume a bounded body before an early 401/404/405 reply.
                # On Windows closing a socket with unread bytes can reset it,
                # hiding the JSON error from otherwise well-formed clients.
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if size<0 or size>2*1024*1024:
                        self.reply(413,{'error':{'code':'too_large','message':'JSON body exceeds 2 MiB'}});return
                    self.connection.settimeout(10)
                    raw=self.rfile.read(size) if size else b''
                    if len(raw)!=size:raise ValueError('Incomplete request body')
                except (ValueError,OSError):
                    self.reply(400,{'error':{'code':'invalid_request','message':'Invalid or incomplete request body'}});return
                if self.headers.get('Origin'): self.reply(403,{'error':{'code':'origin_rejected','message':'Browser cross-origin requests are not accepted'}});return
                host=self.headers.get('Host','').split(':')[0]
                if host not in ('127.0.0.1','localhost'): self.reply(403,{'error':{'code':'host_rejected','message':'Loopback host required'}});return
                if method=='GET' and path in ('/health','/api/v1/health'): self.reply(200,service.health());return
                if method=='GET' and path=='/api/v1/openapi.json': self.reply(200,openapi_document(outer.endpoint));return
                if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+service.paths.token): self.reply(401,{'error':{'code':'unauthorized','message':'本机访问令牌不正确'}});return
                resolved=resolve_route(path)
                if path=='/health': resolved=('/health',ROUTES['/health'],None)
                if resolved is None:
                    self.reply(404,{'error':{'code':'not_found','message':'Unknown route'}});return
                route,allowed,record_id=resolved
                if method not in allowed:
                    self.reply(405,{'error':{'code':'method_not_allowed','message':'Unsupported method for this exact route'}},allow=', '.join(allowed));return
                try:
                    payload={}
                    if method in ('POST','PUT'):
                        if size:
                            if 'application/json' not in self.headers.get('Content-Type',''): raise ValueError('Content-Type must be application/json')
                            payload=json.loads(raw.decode('utf-8-sig'))
                            if not isinstance(payload,dict): raise ValueError('JSON body must be an object')
                    if method=='GET':
                        getters={'/publications':service.publications,'/assets':service.assets,'/drafts':service.drafts,'/evidence':service.evidence,'/jobs':service.jobs,'/accounts':service.accounts,'/settings':service.settings,'/ai/status':service.ai_status,'/campaigns':service.campaigns}
                        if route in getters: result=getters[route]()
                        elif route=='/campaigns/{id}': result=service.get_campaign(record_id)
                        elif route=='/briefs/{id}': result=service.export_brief(record_id)
                        elif route in ('/jobs/{id}','/jobs/{id}/events','/jobs/{id}/qrcode'):
                            job=service.get_job(record_id)
                            if route=='/jobs/{id}': result=job
                            elif route=='/jobs/{id}/events': result=service.events(record_id)
                            elif route=='/jobs/{id}/qrcode':
                                from pathlib import Path
                                image=Path(job.get('qr_path','')).resolve();allowed=(service.paths.project_root/'state').resolve()
                                if not image.is_relative_to(allowed) or image.suffix.lower()!='.png' or not image.is_file(): raise ValueError('当前没有有效二维码')
                                self.reply(200,image.read_bytes(),'image/png');return
                            else: self.reply(404,{'error':{'code':'not_found','message':'Unknown route'}});return
                        else: self.reply(404,{'error':{'code':'not_found','message':'Unknown route'}});return
                    else:
                        setters={'/publications/update':lambda p:service.create_job(dict(p,action='update_publication')),'/publications/query':service.query_publications,'/assets':service.add_asset,'/drafts':service.save_draft,'/evidence/import':service.import_evidence,'/packages/import':service.import_packages,'/generate':service.generate,'/jobs':service.create_job,'/settings':service.save_settings}
                        if method=='POST' and route=='/campaigns':
                            if set(payload)-{'asset_id','provider','goal'}:raise ValueError('Unknown campaign argument')
                            if not isinstance(payload.get('asset_id'),str) or not payload['asset_id']:raise ValueError('asset_id is required')
                            if payload.get('provider','auto') not in ('auto','codex','api'):raise ValueError('Invalid AI provider')
                            if not isinstance(payload.get('goal',''),str):raise ValueError('goal must be string')
                            result=service.start_campaign(payload)
                        elif method=='POST' and route=='/campaigns/{id}/save':
                            if set(payload)-{'selections','queue_drafts'}:raise ValueError('Unknown campaign save argument')
                            selections=payload.get('selections',{})
                            if not isinstance(selections,dict) or set(selections)-{'bilibili','xiaohongshu'}:raise ValueError('Invalid title selections')
                            if any(isinstance(v,bool) or not isinstance(v,int) or v<0 for v in selections.values()):raise ValueError('Title index must be nonnegative integer')
                            if not isinstance(payload.get('queue_drafts',False),bool):raise ValueError('queue_drafts must be boolean')
                            result=service.save_campaign({**payload,'id':record_id})
                        elif method=='POST' and route=='/jobs/{id}/resolve-unsubmitted':result=service.resolve_unsubmitted(record_id,payload)
                        elif method=='POST' and route=='/jobs/{id}/reconcile':result=service.reconcile_publication(record_id,payload)
                        elif method=='POST' and route=='/campaigns/{id}/cancel':result=service.cancel_campaign(record_id)
                        elif method=='POST' and route in setters: result=setters[route](payload)
                        elif route=='/trends/fetch' and method=='POST': result=service.fetch_trends(payload.get('platform',''),payload.get('keyword',''))
                        elif route=='/assets/{id}' and method=='PUT': result=service.update_asset(record_id,payload)
                        elif route=='/jobs/{id}/cancel' and method=='POST': result=service.cancel_job(record_id)
                        else: self.reply(404,{'error':{'code':'not_found','message':'Unknown route'}});return
                    self.reply(200,result)
                except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
                    from .core import redact
                    self.reply(400,{'error':{'code':'invalid_request','message':redact(exc)}})
                except Exception:
                    self.reply(500,{'error':{'code':'internal_error','message':'操作失败，请在本机界面检查状态'}})
        self.http=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.http.daemon_threads=True
        self.endpoint='http://127.0.0.1:'+str(self.http.server_port)
        self.thread=threading.Thread(target=self.http.serve_forever,name='local-api',daemon=True)
    def start(self): self.thread.start()
    def close(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=3)
