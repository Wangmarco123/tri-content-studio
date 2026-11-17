"""Bounded platform adapters. Called only in an isolated, account-scoped worker."""
from __future__ import annotations

import asyncio
import http.cookiejar
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.parse
import urllib.request


class Cancelled(Exception):
    pass


class AccountBusy(Exception):
    pass


class AccountLock:
    """OS-released lock; never deletes another process's lock or browser."""
    def __init__(self, path): self.path, self.file = Path(path), None
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        try:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.file.write(b'0'); self.file.flush(); self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file = None
            raise AccountBusy('账号正在被另一个任务使用，请关闭该账号操作后再试') from None
        return self
    def __exit__(self, *args):
        if self.file:
            try:
                self.file.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file, fcntl.LOCK_UN)
            finally: self.file.close()


def account_paths(root, platform, account):
    if platform not in ('douyin', 'xiaohongshu', 'bilibili'):
        raise ValueError('不支持的平台')
    if not isinstance(account, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', account):
        raise ValueError('账号标识仅支持字母、数字、下划线和连字符')
    account=account.lower()
    base = Path(root) / ('xiaohongshu-sau' if platform == 'xiaohongshu' else platform)
    # Preserve the existing creator cookie path; all additional accounts separate.
    state = (base / 'cookies.json' if account == 'creator' else base / 'accounts' / account / 'cookies.json') if platform == 'bilibili' else base / f'{platform}_{account}.json'
    return base / 'profiles' / account, state, base / 'locks' / f'{account}.lock'


def check_cancel(context):
    if context.get('cancel_path') and Path(context['cancel_path']).exists(): raise Cancelled()


def wait_seconds(seconds, context):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        check_cancel(context); time.sleep(min(.2, max(0, end-time.monotonic())))


def _json_http(url, opener=None, headers=None):
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0', **(headers or {})})
    with (opener or urllib.request.build_opener()).open(req, timeout=15) as response:
        return json.loads(response.read(4_000_000))


def bili_cookie_document(cookies):
    values = {c['name']:c['value'] for c in cookies}
    return {'cookie_info':{'cookies':cookies},'sso':[], 'platform':'Web',
            'token_info':{'access_token':'','refresh_token':'','expires_in':0,'mid':int(values.get('DedeUserID','0'))}}


def _write_private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def _bili_cookie_header(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    cookies = data.get('cookie_info', {}).get('cookies', [])
    allowed = {'SESSDATA','bili_jct','DedeUserID','DedeUserID__ckMd5','sid','buvid3','buvid4'}
    return '; '.join(c['name']+'='+c['value'] for c in cookies if c.get('name') in allowed)


def _bili_login(state, context, emit):
    import segno
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    reply = _json_http('https://passport.bilibili.com/x/passport-login/web/qrcode/generate',opener)
    if reply.get('code') != 0: return {'status':'failed','message':'B站二维码获取失败，请稍后手动重试'}
    data = reply['data']; key = data['qrcode_key']
    qr_dir = Path(context['cancel_path']).parent if context.get('cancel_path') else state.parent / 'login-qr'
    qr_dir.mkdir(parents=True, exist_ok=True)
    qr = qr_dir / 'bilibili-login.png'
    segno.make(data['url'], micro=False).save(str(qr), scale=7, border=3)
    emit({'stage':'awaiting_user','message':'请用B站客户端扫码并确认登录（最长180秒）','qr_path':str(qr),'requires_user':True})
    try:
        end = time.monotonic()+180
        while time.monotonic()<end:
            check_cancel(context)
            reply = _json_http('https://passport.bilibili.com/x/passport-login/web/qrcode/poll?'+urllib.parse.urlencode({'qrcode_key':key}),opener)
            result = reply.get('data',{})
            if reply.get('code') != 0: return {'status':'failed','message':'B站登录状态查询失败'}
            code = result.get('code')
            if code == 0:
                cookies = [{'name':c.name,'value':c.value,'domain':c.domain,'path':c.path,'expires':c.expires or 0} for c in jar if c.domain.lstrip('.').endswith('bilibili.com')]
                if not any(c['name']=='SESSDATA' for c in cookies):
                    return {'status':'failed','message':'扫码回执未包含有效会话，未保存凭据'}
                _write_private_json(state,bili_cookie_document(cookies))
                return {'status':'complete','message':'B站扫码登录成功，会话已保存在本账号目录','evidence':{'online_checked':True}}
            if code == 86038: return {'status':'failed','message':'二维码已过期，请重新发起登录'}
            if code not in (86101,86090): return {'status':'failed','message':'B站要求额外登录验证，请在官方客户端处理'}
            wait_seconds(2,context)
        return {'status':'failed','message':'B站扫码等待超时；未自动重复取码'}
    finally:
        qr.unlink(missing_ok=True)


def find_bili(engine_root):
    root = Path(engine_root)
    for folder in (root/'runtime'/'biliup', root/'components'/'biliup', root/'biliup'):
        if folder.is_dir():
            candidates = sorted(folder.rglob('biliup.exe'))
            if candidates:return candidates[0]
    raise ValueError('未找到随软件提供的B站上传组件')


def bili_publish_args(exe, state, payload):
    visibility=payload.get('visibility')
    if visibility not in ('public','private'):raise ValueError('正式发布必须明确 public 或 private')
    return [str(exe),'-u',str(state),'upload',str(payload['file']),'--submit','web','--limit','1',
            '--is-only-self','1' if visibility=='private' else '0','--title',payload['title'],
            '--desc',payload.get('caption',''),'--tag',','.join(payload.get('tags',[]))]


def _run_engine(args, cwd, context, timeout=900):
    # Do not forward vendor stdout: it may contain login cookies or server bodies.
    env = os.environ.copy(); env['RUST_LOG']='error'
    proc=subprocess.Popen(args,cwd=str(cwd),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    end=time.monotonic()+timeout
    try:
        while time.monotonic()<end:
            check_cancel(context)
            try:
                out,err=proc.communicate(timeout=.2)
                return proc.returncode,out.decode('utf-8','replace')[:2_000_000]
            except subprocess.TimeoutExpired:pass
        raise TimeoutError()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)


def bili_show_visibility(output):
    """Read the archive JSON among vendor log lines; never publish raw stdout."""
    decoder=json.JSONDecoder()
    for index,char in enumerate(output):
        if char!='{':continue
        try:data,_=decoder.raw_decode(output,index)
        except (ValueError,TypeError):continue
        if not isinstance(data,dict):continue
        archive=data.get('archive')
        if not isinstance(archive,dict) and isinstance(data.get('data'),dict):
            archive=data['data'].get('archive')
        if not isinstance(archive,dict):continue
        actual=archive.get('is_only_self')
        visibility='private' if actual in (1,'1') else ('public' if actual in (0,'0') else None)
        description=archive.get('state_desc')
        # State descriptions are server status text, not title/cookie/full response.
        description=description[:120] if isinstance(description,str) else None
        return visibility,description
    return None,None


def _bili(job, context, state, emit):
    action=job['action'];payload=job.get('payload',{})
    if action=='query_publications':
        from .publications import query_bilibili
        return query_bilibili(state,context)
    if action=='update_publication':
        if payload.get('transport','browser')=='browser':
            from .bili_browser import update_existing
            return asyncio.run(update_existing(state,payload,context,emit))
        from .publications import update_bilibili
        return update_bilibili(state,payload,context,emit)
    if action=='login':return _bili_login(state,context,emit)
    if action in ('draft','open_drafts'):
        return {'status':'failed','message':'B站当前组件不支持安全草稿入口；未上传、未投稿','evidence':{'supported':False}}
    if not state.is_file():return {'status':'failed','message':'尚无本账号登录记录，请扫码登录','evidence':{'online_checked':False}}
    if action=='check':
        reply=_json_http('https://api.bilibili.com/x/web-interface/nav',headers={'Cookie':_bili_cookie_header(state)})
        valid=reply.get('code')==0 and reply.get('data',{}).get('isLogin') is True
        return {'status':'complete' if valid else 'failed','message':'B站在线会话有效' if valid else 'B站在线会话无效，请重新登录','evidence':{'online_checked':True,'logged_in':valid}}
    if action!='publish':raise ValueError('不支持的B站动作')
    exe=find_bili(context['engine_root'])
    emit({'stage':'uploading','message':'B站单次上传并提交；不会自动再次投稿','progress':15})
    args=bili_publish_args(exe,state,payload)
    check_cancel(context)
    emit({'stage':'submit_requested','message':'B站上传组件开始执行，后续取消仅停止本地处理'})
    try:
        code,output=_run_engine(args,state.parent,context)
        if code!=0:return {'status':'outcome_unknown','message':'B站组件非零退出，不能确认投稿结果；请核对创作中心，未自动重投'}
        # Only extract a remote identifier. Never expose raw engine output.
        match=re.search(r'\bBV[1-9A-HJ-NP-Za-km-z]{10}\b',output)
        if not match:return {'status':'outcome_unknown','message':'B站组件已执行，未取得可核实稿件编号；禁止自动重投'}
        remote=match.group()
        check_cancel(context)
        show_code,show=_run_engine([str(exe),'-u',str(state),'show',remote],state.parent,context,60)
        if show_code!=0 or remote not in show:
            return {'status':'outcome_unknown','message':'已取得稿件编号但回读未确认，请到创作中心核对','remote_id':remote}
        actual,state_desc=bili_show_visibility(show)
        evidence={'remote_id_readback':True,'submission_accepted':True,
                  'visibility_requested':payload['visibility'],'visibility_actual':actual,
                  'visibility_readback':actual==payload['visibility'],'state_desc':state_desc}
        if actual!=payload['visibility']:
            return {'status':'outcome_unknown','message':'稿件已受理，但可见范围回读不匹配或缺失；请立即在B站创作中心人工核对，未再次提交',
                    'remote_id':remote,'url':'https://www.bilibili.com/video/'+remote,
                    'visibility':actual,'evidence':evidence}
        return {'status':'submitted','message':'B站稿件已提交并回读；审核/公开状态需在创作中心确认','remote_id':remote,'url':'https://www.bilibili.com/video/'+remote,'visibility':payload['visibility'],
                'evidence':evidence}
    except (TimeoutError,Cancelled):
        return {'status':'outcome_unknown','message':'B站上传/提交阶段停止，远端是否受理未知；不要直接重投'}


def execute(job:dict, context:dict, emit)->dict:
    platform=job.get('platform');action=job.get('action');payload=job.get('payload',{})
    account=job.get('account') or payload.get('account') or 'creator'
    if platform=='xiaohongshu':return {'status':'failed','message':'小红书自动操作已删除，请人工发布','evidence':{'manual_only':True,'browser_launched':False}}
    profile,state,lock=account_paths(context['state_root'],platform,account)
    if action not in ('login','check','draft','publish','open_drafts','query_publications','update_publication'):raise ValueError('不支持的动作')
    if action=='publish' and payload.get('visibility') not in ('public','private'):
        raise ValueError('正式发布必须明确可见范围 public/private，禁止默认公开')
    if action in ('draft','publish'):
        if not payload.get('file') or not Path(payload['file']).is_file():raise ValueError('视频素材不存在')
        if not isinstance(payload.get('title'),str) or not payload['title'].strip():raise ValueError('标题不能为空')
        if not isinstance(payload.get('tags',[]),list) or any(not isinstance(t,str) for t in payload.get('tags',[])):raise ValueError('话题必须是字符串列表')
    try:
        check_cancel(context)
        with AccountLock(lock):
            if platform=='bilibili':return _bili(job,context,state,emit)
            from .browser_worker import run
            return asyncio.run(run(job,context,profile,state,emit))
    except Cancelled:return {'status':'cancelled','message':'已停止本地操作；不会声称撤回远端内容'}
    except AccountBusy as exc:return {'status':'failed','message':str(exc)}
    except Exception as exc:
        # Vendor errors may embed request headers. Only expose error class.
        return {'status':'outcome_unknown' if action in ('publish','update_publication') else 'failed','message':'平台操作停止（'+type(exc).__name__+'），请检查账号页面；未自动重试'}
