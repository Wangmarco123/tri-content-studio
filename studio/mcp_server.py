import json
import sys
from .cli import request
from . import __version__

TOOLS=[
 ('resolve_unsubmitted','仅以持久提交前异常日志核对，列表缺席不能解除未知结果','POST','/jobs/{id}/resolve-unsubmitted',{'id':{'type':'string'},'query_job_id':{'type':'string'}}),
 ('update_publication','修改已核实同素材B站原稿件文案和明确可见范围，不新上传','POST','/publications/update',{'draft_id':{'type':'string'},'matched_job_id':{'type':'string'},'visibility':{'type':'string','enum':['public','private']},'account':{'type':'string'}}),
 ('query_publications','只读查询本人创作者作品列表，不上传、不发布','POST','/publications/query',{'platform':{'type':'string','enum':['bilibili','douyin']},'account':{'type':'string'}}),
 ('reconcile_publication','用同账号已保存查询匹配待核实稿件，不凭空解除防重投','POST','/jobs/{id}/reconcile',{'id':{'type':'string'},'query_job_id':{'type':'string'},'remote_id':{'type':'string'}}),
 ('studio_status','读取软件状态','GET','/health',{}),
 ('list_assets','列出已登记视频','GET','/assets',{}),
 ('register_asset','登记本机视频与真实摘要','POST','/assets',{'path':{'type':'string'},'summary':{'type':'string'},'audience':{'type':'string'}}),
 ('export_brief','取得供AI运营研究的事实卡与响应schema','GET','/briefs/{id}',{'id':{'type':'string'}}),
 ('fetch_trends','取固定平台公开榜；小红书可提示需要证据源','POST','/trends/fetch',{'platform':{'type':'string','enum':['bilibili','douyin','xiaohongshu']},'keyword':{'type':'string'}}),
 ('import_evidence','导入带链接和时间的真实证据','POST','/evidence/import',{'items':{'type':'array','items':{'type':'object'}}}),
 ('import_packages','导入三平台标题文案和话题，先整批校验','POST','/packages/import',{'asset_id':{'type':'string'},'packages':{'type':'array','items':{'type':'object'}}}),
 ('list_jobs','列出任务和实际状态','GET','/jobs',{}),
 ('queue_task','创建明确平台/账号的草稿或发布任务；正式发布需明确可见范围','POST','/jobs',{'platform':{'type':'string','enum':['bilibili','douyin']},'action':{'type':'string','enum':['login','check','open_drafts','draft','publish','query_publications']},'account':{'type':'string'},'draft_id':{'type':'string'},'visibility':{'type':'string','enum':['private','public']},'idempotency_key':{'type':'string'}}),
 ('get_job','读取单个任务，不把启动当成完成','GET','/jobs/{id}',{'id':{'type':'string'}}),
 ('cancel_job','停止本地动作，不撤回远端已提交稿件','POST','/jobs/{id}/cancel',{'id':{'type':'string'}}),
 ('ai_status','读取本机Codex/API连接与ASR文件就绪状态，不加载模型或回传凭据','GET','/ai/status',{}),
 ('list_campaigns','列出一键运营生成方案','GET','/campaigns',{}),
 ('start_campaign','自动转写完整主音轨并结合抽帧、研究生成五块运营结果，不发布','POST','/campaigns',{'asset_id':{'type':'string','minLength':1},'provider':{'type':'string','enum':['auto','codex','api'],'default':'auto'},'goal':{'type':'string'}}),
 ('get_campaign','轮询运营方案进度与结果','GET','/campaigns/{id}',{'id':{'type':'string','minLength':1}}),
 ('save_campaign','保存选定标题为本地文案；可选只排抖音草稿，小红书人工发布，不公开发布','POST','/campaigns/{id}/save',{'id':{'type':'string','minLength':1},'selections':{'type':'object','properties':{'bilibili':{'type':'integer','minimum':0},'xiaohongshu':{'type':'integer','minimum':0}},'additionalProperties':False},'queue_drafts':{'type':'boolean','default':False}}),
 ('cancel_campaign','取消AI生成，不撤回任何远端稿件','POST','/campaigns/{id}/cancel',{'id':{'type':'string','minLength':1}}),
]

REQUIRED={'resolve_unsubmitted':['id','query_job_id'],'update_publication':['draft_id','matched_job_id','visibility'],'query_publications':['platform'],'reconcile_publication':['id','query_job_id','remote_id'],'register_asset':['path'],'export_brief':['id'],'fetch_trends':['platform'],
          'import_evidence':['items'],'import_packages':['asset_id','packages'],
          'get_job':['id'],'cancel_job':['id'],'start_campaign':['asset_id'],
          'get_campaign':['id'],'save_campaign':['id'],'cancel_campaign':['id']}

def tool_schema(tool):
    name,_,_,_,properties=tool
    return {'type':'object','properties':properties,'required':REQUIRED.get(name,[]),'additionalProperties':False}

def _validate_value(value,rule):
    kind=rule.get('type')
    if kind=='string':
        if not isinstance(value,str) or len(value)<rule.get('minLength',0):raise ValueError('Expected a nonempty string argument')
    elif kind=='boolean':
        if not isinstance(value,bool):raise ValueError('Expected a boolean argument')
    elif kind=='integer':
        if isinstance(value,bool) or not isinstance(value,int) or value<rule.get('minimum',value):raise ValueError('Expected an integer argument within range')
    elif kind=='array':
        if not isinstance(value,list):raise ValueError('Expected an array argument')
        for item in value:_validate_value(item,rule.get('items',{}))
    elif kind=='object':
        if not isinstance(value,dict):raise ValueError('Expected an object argument')
        properties=rule.get('properties',{})
        if rule.get('additionalProperties') is False and set(value)-set(properties):raise ValueError('Unknown nested argument')
        if any(k not in value for k in rule.get('required',[])):raise ValueError('Missing nested argument')
        for key,item in value.items():
            if key in properties:_validate_value(item,properties[key])
    if 'enum' in rule and value not in rule['enum']:raise ValueError('Invalid enum argument')


def arguments_for(tool,params):
    payload=params.get('arguments',{})
    if not isinstance(payload,dict):raise ValueError('arguments must be an object')
    schema=tool_schema(tool)
    if set(payload)-set(schema['properties']):raise ValueError('Unknown tool argument')
    if any(key not in payload for key in schema['required']):raise ValueError('Missing required tool argument')
    for key,value in payload.items():
        rule=schema['properties'][key]
        _validate_value(value,rule)
    return dict(payload)

def serve(args):
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    for line in sys.stdin:
        msg_id=None
        try:
            try:msg=json.loads(line)
            except json.JSONDecodeError:
                print(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}),flush=True);continue
            if not isinstance(msg,dict) or msg.get('jsonrpc')!='2.0':raise ValueError('Invalid JSON-RPC request')
            msg_id=msg.get('id')
            if 'id' not in msg:continue
            method=msg.get('method');params=msg.get('params',{})
            if not isinstance(params,dict):raise ValueError('params must be an object')
            if method=='initialize':result={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'tri-content-studio','version':__version__}}
            elif method=='ping':result={}
            elif method=='tools/list':result={'tools':[{'name':t[0],'description':t[1],'inputSchema':tool_schema(t)} for t in TOOLS]}
            elif method=='tools/call':
                tool=next((t for t in TOOLS if t[0]==params.get('name')),None)
                if not tool:raise ValueError('Unknown tool')
                _,_,verb,path,_=tool;payload=arguments_for(tool,params)
                if '{id}' in path:path=path.replace('{id}',payload.pop('id',''))
                try:
                    value=request(args,verb,'/api/v1'+path,payload if verb!='GET' else None)
                    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
                except Exception as exc:
                    from .core import redact
                    result={'content':[{'type':'text','text':redact(exc)}],'isError':True}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
            print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result},ensure_ascii=False),flush=True)
        except Exception:
            print(json.dumps({'jsonrpc':'2.0','id':msg_id,'error':{'code':-32602,'message':'Invalid request or tool arguments'}}),flush=True)
    return 0
