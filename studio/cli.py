import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler
from urllib.error import HTTPError,URLError

def connection(args):
    from .app import discover_root
    root=discover_root(args.home)
    data=Path(args.data_dir) if args.data_dir else root/'state'/'desktop'
    file=data/'connection.json'
    cfg=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    endpoint=args.endpoint or cfg.get('endpoint','http://127.0.0.1:19266')
    parsed=urlparse(endpoint)
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('','/')): raise ValueError('CLI只允许访问无凭据/查询参数的本机loopback服务根地址')
    parsed.port  # Validate a malformed port before reading a local token.
    token_path=Path(args.token_file or cfg.get('token_path',str(data/'api-token.txt')))
    token=token_path.read_text(encoding='ascii').strip()
    return endpoint.rstrip('/'),token

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def request(args,method,path,payload=None):
    if not path.startswith('/api/v1/') or '..' in path or '?' in path:raise ValueError('只接受/api/v1下的固定路径')
    endpoint,token=connection(args)
    req=Request(endpoint+path,data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
    try:
        # Never send the local bearer through a system proxy or a redirect target.
        with build_opener(ProxyHandler({}),_NoRedirect()).open(req,timeout=120) as response:return json.load(response)
    except HTTPError as exc:
        try: detail=json.loads(exc.read().decode('utf-8'))
        except Exception:detail={'error':{'message':'本机服务返回错误','status':exc.code}}
        exc.close()
        raise ValueError(json.dumps(detail,ensure_ascii=False)) from None
    except URLError:raise ValueError('无法连接本机服务，请先启动桌面软件或serve') from None

def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)

def main(argv=None):
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='三平台内容发布助手 JSON CLI / MCP')
    for option in ('home','data-dir','endpoint','token-file'):p.add_argument('--'+option)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('status');sub.add_parser('mcp')
    sub.add_parser('ai-status')
    s=sub.add_parser('plan');s.add_argument('--asset-id',required=True);s.add_argument('--provider',choices=('auto','codex','api'),default='auto');s.add_argument('--goal',default='')
    s=sub.add_parser('plan-status');s.add_argument('id')
    s=sub.add_parser('plan-save');s.add_argument('id');s.add_argument('--bili-title-index',type=int);s.add_argument('--xhs-title-index',type=int);s.add_argument('--queue-drafts',action='store_true')
    s=sub.add_parser('plan-cancel');s.add_argument('id')
    s=sub.add_parser('doctor');s.add_argument('--browser',action='store_true');s.add_argument('--export-notices')
    s=sub.add_parser('serve');s.add_argument('--port',type=int,default=19266)
    s=sub.add_parser('list');s.add_argument('collection',choices=('assets','drafts','jobs','accounts','evidence'))
    s=sub.add_parser('add');s.add_argument('--file',required=True);s.add_argument('--summary',default='');s.add_argument('--audience',default='')
    s=sub.add_parser('brief');s.add_argument('asset_id');s.add_argument('--out')
    s=sub.add_parser('import-packages');s.add_argument('file')
    s=sub.add_parser('import-evidence');s.add_argument('file')
    s=sub.add_parser('queue');s.add_argument('--platform',choices=('bilibili','douyin'));s.add_argument('--action',choices=('login','check','open_drafts','draft','publish','query_publications'),default='draft');s.add_argument('--account',default='creator');s.add_argument('--draft-id');s.add_argument('--visibility',choices=('private','public'));s.add_argument('--idempotency-key')
    s=sub.add_parser('job');s.add_argument('job_id');s.add_argument('--events',action='store_true')
    s=sub.add_parser('cancel');s.add_argument('job_id')
    s=sub.add_parser('trends');s.add_argument('platform',choices=('bilibili','douyin','xiaohongshu'));s.add_argument('--keyword',default='')
    s=sub.add_parser('request');s.add_argument('method',choices=('GET','POST','PUT'));s.add_argument('path');s.add_argument('--json-file')
    s=sub.add_parser('_worker');s.add_argument('--request',required=True);s.add_argument('--events',required=True);s.add_argument('--result',required=True)
    s=sub.add_parser('_speech_worker');s.add_argument('--request',required=True);s.add_argument('--events',required=True);s.add_argument('--result',required=True)
    args=p.parse_args(argv)
    try:
        if args.command=='_speech_worker':
            from .asr import worker_main
            return worker_main(args.request,args.events,args.result)
        if args.command=='doctor':
            from .doctor import diagnose
            from .app import discover_root
            value=diagnose(discover_root(args.home),args.browser,args.export_notices)
            emit(value);return 0 if value['ok'] else 2
        if args.command=='_worker':
            from .jobs import run_worker
            return run_worker(args.request,args.events,args.result)
        if args.command=='serve':
            from .app import main as app_main
            params=['--headless','--port',str(args.port)]
            if args.home:params+=['--home',args.home]
            if args.data_dir:params+=['--data-dir',args.data_dir]
            return app_main(params)
        if args.command=='mcp':
            from .mcp_server import serve
            return serve(args)
        command=args.command
        if command=='status':value=request(args,'GET','/api/v1/health')
        elif command=='ai-status':value=request(args,'GET','/api/v1/ai/status')
        elif command=='plan':value=request(args,'POST','/api/v1/campaigns',{'asset_id':args.asset_id,'provider':args.provider,'goal':args.goal})
        elif command=='plan-status':value=request(args,'GET','/api/v1/campaigns/'+args.id)
        elif command=='plan-cancel':value=request(args,'POST','/api/v1/campaigns/'+args.id+'/cancel',{})
        elif command=='plan-save':
            selections={k:v for k,v in (('bilibili',args.bili_title_index),('xiaohongshu',args.xhs_title_index)) if v is not None}
            if any(v<0 for v in selections.values()):raise ValueError('标题索引必须为非负整数（从0开始）')
            value=request(args,'POST','/api/v1/campaigns/'+args.id+'/save',{'selections':selections,'queue_drafts':args.queue_drafts})
        elif command=='list':value=request(args,'GET','/api/v1/'+args.collection)
        elif command=='add':value=request(args,'POST','/api/v1/assets',{'path':args.file,'summary':args.summary,'audience':args.audience})
        elif command=='brief':
            value=request(args,'GET','/api/v1/briefs/'+args.asset_id)
            if args.out:Path(args.out).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        elif command.startswith('import-'):
            value=request(args,'POST','/api/v1/'+('packages/import' if command=='import-packages' else 'evidence/import'),json.loads(Path(args.file).read_text(encoding='utf-8-sig')))
        elif command=='queue':value=request(args,'POST','/api/v1/jobs',{k:v for k,v in vars(args).items() if k in ('platform','action','account','draft_id','visibility','idempotency_key') and v is not None})
        elif command=='job':value=request(args,'GET','/api/v1/jobs/'+args.job_id+('/events' if args.events else ''))
        elif command=='cancel':value=request(args,'POST','/api/v1/jobs/'+args.job_id+'/cancel',{})
        elif command=='trends':value=request(args,'POST','/api/v1/trends/fetch',{'platform':args.platform,'keyword':args.keyword})
        elif command=='request':value=request(args,args.method,args.path,json.loads(Path(args.json_file).read_text(encoding='utf-8-sig')) if args.json_file else None)
        emit(value);return 0
    except Exception as exc:
        from .core import redact
        emit({'error':{'message':redact(exc)}});return 2

if __name__=='__main__':raise SystemExit(main())
