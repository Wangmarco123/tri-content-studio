"""Read-only creator inventory. Unknown coverage never proves non-publication."""
from urllib.parse import urlsplit
import time

def update_bilibili(state,payload,context,emit):
    import json
    from urllib.request import Request,build_opener,ProxyHandler
    from .adapters import _json_http,_bili_cookie_header,check_cancel
    bid=payload['remote_id']
    cookie=_bili_cookie_header(state)
    url='https://member.bilibili.com/x/vupre/web/archive/view?bvid='+bid
    before=_json_http(url,headers={'Cookie':cookie})
    if before.get('code')!=0:raise ValueError('无法读取原稿件，零修改')
    data=before['data'];archive=data['archive']
    if archive.get('bvid')!=bid:raise ValueError('原稿件编号不一致，零修改')
    keys=('aid','tid','copyright','cover','cover43','title','tag','desc','desc_v2','desc_format_id','dynamic','dynamic_v2','source','no_reprint','recreate','interactive','mission_id','topic_id','lossless_music','is_dolby','neutral_mark','creation_statement','human_type2')
    body={k:archive[k] for k in keys if k in archive}
    body['videos']=[{k:v[k] for k in ('filename','title','desc','cid') if k in v} for v in data['videos']]
    if not body['videos'] or any(not v.get('filename') for v in body['videos']):raise ValueError('缺少原视频标识，拒绝改稿')
    body.update(title=payload['title'],desc=payload.get('caption',''),tag=','.join(payload.get('tags',[])),is_only_self=1 if payload['visibility']=='private' else 0)
    cookies=json.loads(state.read_text(encoding='utf-8-sig'))['cookie_info']['cookies']
    csrf=next(c['value'] for c in cookies if c['name']=='bili_jct')
    body['csrf']=csrf;body['subtitle']=data.get('subtitle') or {'open':0,'lan':''}
    check_cancel(context);emit({'stage':'submit_requested','message':'仅修改已核实原稿件一次，不上传新视频'})
    request=Request('https://member.bilibili.com/x/vu/web/edit?csrf='+csrf,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Cookie':cookie,'Content-Type':'application/json','Referer':'https://member.bilibili.com/'},method='POST')
    try:
        with build_opener(ProxyHandler({})).open(request,timeout=60) as response:reply=json.load(response)
        if reply.get('code')!=0:return {'status':'outcome_unknown','message':'原稿件修改未获成功回执，请查询核对，未重试','remote_id':bid}
        after=_json_http(url,headers={'Cookie':cookie})
        actual=(after.get('data') or {}).get('archive') or {}
        verified=actual.get('bvid')==bid and actual.get('is_only_self')==body['is_only_self'] and actual.get('title')==body['title'] and actual.get('desc')==body['desc']
        return {'status':'submitted' if verified else 'outcome_unknown','message':'原稿件文案与可见范围回读一致' if verified else '改稿已受理但回读尚未一致，请查询，未重试','remote_id':bid,'url':'https://www.bilibili.com/video/'+bid,'visibility':'private' if actual.get('is_only_self')==1 else 'public','evidence':{'updated_existing':True,'readback_verified':verified,'new_video_uploaded':False}}
    except Exception:
        return {'status':'outcome_unknown','message':'原稿件修改响应不确定，请只读核对，不得重复提交','remote_id':bid}

MANAGE={'douyin':'https://creator.douyin.com/creator-micro/content/manage'}

def extract_records(data,platform):
    found={}
    def walk(value):
        if isinstance(value,list):
            for child in value:walk(child)
        elif isinstance(value,dict):
            remote=value.get('aweme_id') if platform=='douyin' else (value.get('note_id') or value.get('noteId') or value.get('id'))
            if remote:
                title=value.get('title') or value.get('display_title') or value.get('desc')
                if isinstance(title,str):
                    key=str(remote)
                    status=value.get('status');visibility='unknown'
                    if platform=='douyin' and isinstance(status,dict):
                        if status.get('is_private') is True or status.get('self_see') is True:visibility='private'
                        elif status.get('is_private') is False and status.get('self_see') is False and status.get('private_status')==0:visibility='public'
                    permission=value.get('permission_msg')
                    if platform=='xiaohongshu':
                        if permission in ('公开','公开可见','所有人可见'):visibility='public'
                        elif permission in ('仅自己可见','私密','仅自己'):visibility='private'
                    found[key]={'remote_id':key,'title':title[:2000],
                        'url':('https://www.douyin.com/video/' if platform=='douyin' else 'https://www.xiaohongshu.com/explore/')+key,
                        'created_at_raw':value.get('create_time') or value.get('time'),
                        'status_raw':({k:status[k] for k in ('in_reviewing','is_delete','is_private','is_prohibited','private_status','reviewed','self_see') if k in status} if isinstance(status,dict) else status),'visibility':visibility,'permission_description':permission,
                        'duration_raw':(value.get('video') or value.get('video_info') or {}).get('duration') if isinstance(value.get('video') or value.get('video_info'),dict) else None,
                        'verification':'creator_response_observed'}
            for child in value.values():
                if isinstance(child,(dict,list)):walk(child)
    walk(data);return list(found.values())

async def query_browser(page,platform,cancel,emit):
    if platform!='douyin':raise ValueError('小红书已改为人工发布，不提供账号自动查询')
    import asyncio
    from .browser_worker import bounded,wait_verification,is_logged_in
    rows={};pending=set();errors=[];shapes=[]
    async def capture(response):
        host=urlsplit(response.url).hostname or ''
        allowed='douyin.com' if platform=='douyin' else 'xiaohongshu.com'
        if not (host==allowed or host.endswith('.'+allowed)):return
        if 'json' not in response.headers.get('content-type',''):return
        try:
            length=int(response.headers.get('content-length','0'))
            if length>8*1024*1024:return
            data=await asyncio.wait_for(response.json(),8)
            if '/note/user/posted' in response.url:
                def schema(v,depth=0):
                    if depth>4:return type(v).__name__
                    if isinstance(v,dict):return {k:schema(x,depth+1) for k,x in list(v.items())[:30]}
                    if isinstance(v,list):return [schema(v[0],depth+1)] if v else []
                    return type(v).__name__
                shapes.append({'posted_schema':schema(data)})
            if len(shapes)<40:shapes.append({'path':urlsplit(response.url).path,'keys':list(data)[:20] if isinstance(data,dict) else []})
            for row in extract_records(data,platform):
                row['source_endpoint']=urlsplit(response.url).path
                rows[row['remote_id']]=row
        except Exception:errors.append('response_unreadable')
    def observe(response):
        task=asyncio.create_task(capture(response));pending.add(task);task.add_done_callback(pending.discard)
    page.on('response',observe)
    try:
        await bounded(page.goto(MANAGE[platform],wait_until='domcontentloaded',timeout=60000),cancel,65)
        await wait_verification(page,cancel,emit)
        for _ in range(16):cancel();await asyncio.sleep(.5)
        text=await page.locator('body').inner_text(timeout=10000)
        if any(x in text for x in ('扫码登录','手机号登录','短信登录')):
            return {'status':'failed','message':'作品查询需要本人登录，请执行登录任务','evidence':{'requires_login':True,'read_only':True}}
        links=await page.locator('a[href]').evaluate_all('(els)=>els.map(e=>({text:e.innerText,href:e.href})).filter(x=>x.text).slice(0,300)')
        return {'status':'complete','message':'已读取创作者作品页面；列表覆盖不代表全部作品','items':list(rows.values()),
            'page':{'url':page.url,'text':text[:24000],'links':[x for x in links if urlsplit(x['href']).hostname and (urlsplit(x['href']).hostname or '').endswith('douyin.com' if platform=='douyin' else 'xiaohongshu.com')]},
            'evidence':{'read_only':True,'coverage':'current_page_only','absence_proves_not_published':False,'response_errors':len(errors),'response_shapes':shapes}}
    finally:
        page.remove_listener('response',observe)
        if pending:
            await asyncio.gather(*pending,return_exceptions=True)

def query_bilibili(state,context):
    from .adapters import _json_http,_bili_cookie_header,check_cancel
    rows=[];pages=0;complete=False
    for pn in range(1,6):
        check_cancel(context)
        reply=_json_http('https://member.bilibili.com/x/web/archives?status=is_pubing,pubed,not_pubed&pn='+str(pn)+'&ps=20',headers={'Cookie':_bili_cookie_header(state)})
        if reply.get('code')!=0:return {'status':'failed','message':'B站作品查询未成功，未推断旧稿件不存在','evidence':{'read_only':True,'requires_login':reply.get('code') in (-101,-111)}}
        data=reply.get('data') or {};items=data.get('arc_audits')
        if not isinstance(items,list):return {'status':'failed','message':'B站作品响应结构变化，未认定空列表'}
        pages+=1
        for item in items:
            a=item.get('Archive') or item.get('archive') or {};bid=a.get('bvid')
            if bid:rows.append({'remote_id':bid,'title':a.get('title',''),'url':'https://www.bilibili.com/video/'+bid,'visibility':'private' if a.get('is_only_self')==1 else ('public' if a.get('is_only_self')==0 else 'unknown'),'status_raw':a.get('state'),'created_at_raw':a.get('ctime'),'duration_raw':a.get('duration'),'verification':'creator_response_observed'})
        total=(data.get('page') or {}).get('count')
        if isinstance(total,int) and pn*20>=total:complete=True;break
        if len(items)<20:complete=True;break
    return {'status':'complete','message':'B站作品列表已读取','items':rows,'evidence':{'read_only':True,'pages':pages,'coverage_complete':complete,'absence_proves_not_published':False}}
