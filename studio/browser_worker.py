"""Visible persistent browser actions; no dependency on SAU publish loops."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import re
import time

from .adapters import Cancelled, check_cancel

URLS = {
    'douyin':'https://creator.douyin.com/creator-micro/content/upload',
}
TITLES = {'douyin':'input[placeholder*="填写作品标题"]'}
INPUTS = {'douyin':'input.upload-btn-input, div[class^="container"] input[type="file"]'}


async def bounded(awaitable, cancel, timeout):
    task=asyncio.ensure_future(awaitable)
    end=time.monotonic()+timeout
    try:
        while not task.done():
            cancel()
            if time.monotonic()>end:raise TimeoutError()
            await asyncio.sleep(.15)
        cancel()
        return await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)


async def unique_visible(locator):
    return await locator.count()==1 and await locator.is_visible()


async def wait_condition(probe, cancel, timeout):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        cancel()
        if await probe():return True
        await asyncio.sleep(.4)
    return False


async def is_logged_in(page,platform):
    if 'creator.' not in page.url:return False
    # Check visible authenticated controls AND absence of login forms.
    for name in ('扫码登录','手机号登录','短信登录'):
        loc=page.get_by_text(name,exact=True)
        if await loc.count() and await loc.first.is_visible():return False
    input_loc=page.locator(INPUTS[platform])
    if await input_loc.count():return True
    for text in ('发布视频','发布笔记','创作首页','内容管理','笔记管理'):
        loc=page.get_by_text(text,exact=True)
        if await loc.count() and await loc.first.is_visible():return True
    return False


async def seed(context,state):
    data=json.loads(state.read_text(encoding='utf-8-sig'))
    cookies=data.get('cookies',[])
    if cookies:await context.add_cookies(cookies)
    # Scope localStorage seeding to each recorded origin; no user-code injection.
    origins=data.get('origins',[])
    # The caller supplies only its own account file. Still restrict origin families
    # so an accidentally mixed state file cannot seed a different platform.
    if state.name.startswith('douyin_'):
        allowed={'https://creator.douyin.com','https://www.douyin.com'}
    else:
        raise ValueError('仅支持抖音会话，已移除小红书自动操作')
    origins=[o for o in origins if o.get('origin') in allowed]
    await context.add_init_script(script='(() => {const list='+json.dumps(origins,ensure_ascii=True)+'; const o=list.find(x=>x.origin===location.origin);if(o)for(const i of(o.localStorage||[])){if(localStorage.getItem(i.name)===null)localStorage.setItem(i.name,i.value);}})();')


async def login(page,context,state,platform,cancel,emit,qr_dir):
    if platform!='douyin':raise ValueError('小红书已删除自动操作，请人工发布')
    await bounded(page.goto(URLS[platform],wait_until='domcontentloaded',timeout=90000),cancel,95)
    if await is_logged_in(page,platform):
        await context.storage_state(path=str(state))
        return {'status':'complete','message':'在线会话已有效，无需重复扫码','evidence':{'online_checked':True,'logged_in':True}}
    tab=page.get_by_text('扫码登录',exact=True)
    if await unique_visible(tab):await tab.click(timeout=3000)
    qr_dir.mkdir(parents=True,exist_ok=True)
    qr=qr_dir/(platform+'-login.png')
    selectors=('div#animate_qrcode_container img','div[class*="qrcode"] img','img[aria-label="二维码"]','canvas')
    qr_sent=False
    end=time.monotonic()+180
    try:
        while time.monotonic()<end:
            cancel()
            if await is_logged_in(page,platform):
                await context.storage_state(path=str(state))
                return {'status':'complete','message':'扫码登录成功，会话已保存','evidence':{'online_checked':True,'logged_in':True}}
            if not qr_sent:
                for selector in selectors:
                    loc=page.locator(selector)
                    if await unique_visible(loc):
                        await loc.screenshot(path=str(qr),timeout=5000)
                        emit({'stage':'awaiting_user','message':'请本人扫码，或在专用浏览器完成登录验证（最长180秒）','qr_path':str(qr),'requires_user':True})
                        qr_sent=True;break
                if not qr_sent:
                    emit({'stage':'awaiting_user','message':'请在可见浏览器中完成登录；二维码未定位，不自动输入或破解验证','requires_user':True})
                    qr_sent=True
            await asyncio.sleep(.5)
        return {'status':'failed','message':'登录等待超时，未自动重复登录'}
    finally:qr.unlink(missing_ok=True)


async def wait_verification(page,cancel,emit):
    selector='input[placeholder*="验证码"], div[class*="captcha"], iframe[src*="captcha"]'
    async def visible():
        loc=page.locator(selector)
        for i in range(min(await loc.count(),10)):
            if await loc.nth(i).is_visible():return True
        return False
    if await visible():
        emit({'stage':'awaiting_user','message':'平台要求验证码，请本人在浏览器处理（最长180秒）','requires_user':True})
        if not await wait_condition(lambda: _not(visible),cancel,180):raise TimeoutError('verification')


async def _not(fn):return not await fn()


async def prepare_upload(page,platform,payload,cancel,emit):
    if platform!='douyin':raise ValueError('小红书已删除自动操作，请人工发布')
    await bounded(page.goto(URLS[platform],wait_until='domcontentloaded',timeout=90000),cancel,95)
    await wait_verification(page,cancel,emit)
    inp=page.locator(INPUTS[platform])
    # File selector must be unique. Never use a generic login input fallback.
    await bounded(inp.wait_for(state='attached',timeout=30000),cancel,32)
    if await inp.count()!=1:raise ValueError('上传框不唯一')
    cancel()
    await inp.set_input_files(payload['file'],timeout=15000)
    emit({'stage':'uploading','message':'已选择一次视频，等待平台处理','progress':35})
    ready=page.locator('[class^="long-card"] div:has-text("重新上传")').first
    await bounded(ready.wait_for(state='visible',timeout=180000),cancel,185)
    await wait_verification(page,cancel,emit)
    title=page.locator(TITLES[platform])
    await bounded(title.wait_for(state='visible',timeout=30000),cancel,32)
    if await title.count()!=1:raise ValueError('标题框不唯一')
    await title.fill(payload['title'],timeout=5000)
    caption=payload.get('caption','')
    tags=payload.get('tags',[])
    text=caption+(' ' if caption and tags else '')+' '.join('#'+t.lstrip('#') for t in tags)
    if text:
        editor=page.locator('div.zone-container[contenteditable="true"]' if platform=='douyin' else 'div.tiptap[contenteditable="true"], div[contenteditable="true"][role="textbox"]')
        if not await unique_visible(editor):raise ValueError('正文框缺失或不唯一，未继续提交')
        await editor.fill(text,timeout=5000)
        await editor.press('Tab')
    emit({'stage':'prepared','message':'视频与标题、正文、话题已填写；尚未发布','progress':70})


async def save_draft(page,platform,cancel):
    cancel();candidates=[]
    for name in ('保存草稿','暂存草稿','暂存离开'):
        button=page.get_by_role('button',name=name,exact=True)
        n=await button.count()
        if n>1:return {'status':'failed','message':'草稿按钮存在歧义，零点击'}
        if n==1 and await button.is_visible() and await button.is_enabled():candidates.append(button)
    if len(candidates)!=1:return {'status':'failed','message':'未找到唯一草稿按钮，零点击；请人工检查页面'}
    cancel();await candidates[0].click(timeout=5000)
    try:
        await bounded(page.wait_for_url('**/creator-micro/content/upload**',timeout=7000),cancel,8)
        loc=page.get_by_text('你还有上次未发布的视频，是否继续编辑？',exact=True)
        await bounded(loc.wait_for(state='visible',timeout=5000),cancel,6)
        return {'status':'draft_saved','message':'已观察到抖音上次未发布视频继续编辑回执','evidence':{'draft_scope':'browser_local','receipt':'previous_unpublished_video'}}
    except Cancelled:raise
    except Exception:pass
    return {'status':'complete','message':'已请求暂存，未取得保存完成回执；未点击发布','evidence':{'draft_click_requested':True,'draft_confirmed':False}}


async def select_visibility(page,platform,visibility,cancel):
    if platform!='douyin':raise ValueError('小红书已删除自动操作，请人工发布')
    if visibility not in ('private','public'):raise ValueError('必须明确可见范围')
    names=('仅自己可见','私密','仅自己') if visibility=='private' else ('公开可见','公开','所有人可见')
    cancel()
    # Prefer semantic radios. Never assume public because it is the default.
    radios=[]
    for name in names:
        radio=page.get_by_role('radio',name=name,exact=True)
        if await unique_visible(radio):radios.append(radio)
    if len(radios)==1:
        await radios[0].check(timeout=5000)
        if not await radios[0].is_checked():raise ValueError('可见范围没有选中')
        return
    # Douyin's custom radio labels contain a native input in current layouts.
    labels=[]
    for name in names:
        loc=page.locator('label').filter(has_text=re.compile(r'^\s*'+re.escape(name)+r'\s*$'))
        if await unique_visible(loc):labels.append(loc)
    if len(labels)!=1:raise ValueError('抖音可见范围未找到可验证的唯一选项，拒绝发布')
    await labels[0].click(timeout=5000)
    radio=labels[0].locator('input[type="radio"],input[type="checkbox"]')
    if await radio.count()==1:
        if not await radio.is_checked():raise ValueError('抖音可见范围回读失败，拒绝发布')
    else:
        selected=labels[0].locator('[class*="checked"],[class*="selected"],[data-state="checked"],[aria-checked="true"]')
        if await selected.count()==0 and await labels[0].get_attribute('data-checked')!='true':raise ValueError('抖音自定义可见范围没有选中标记，拒绝发布')


async def verify_receipt(page,platform,cancel):
    async def probe():
        for name in ('发布成功','笔记发布成功','发布审核中'):
            loc=page.get_by_text(name,exact=True)
            if await loc.count() and await loc.first.is_visible():return True
        return platform=='douyin' and '/creator-micro/content/manage' in page.url
    if await wait_condition(probe,cancel,30):
        return {'status':'submitted','message':'已观察到提交回执，仍需平台审核；不代表已公开','evidence':{'receipt':'platform_submit_ack'}}
    return None


async def submit_once(page,platform,visibility,cancel,emit):
    if platform!='douyin':raise ValueError('小红书已删除自动操作，请人工发布')
    cancel()
    button=page.get_by_role('button',name='发布',exact=True)
    if platform=='xiaohongshu' and not await unique_visible(button):
        fallback=page.get_by_text('发布',exact=True)
        if await unique_visible(fallback):button=fallback
    async def submit_ready():
        return await unique_visible(button) and await button.is_enabled()
    if not await submit_ready():
        return {'status':'failed','message':'发布按钮缺失、禁用或有歧义；零提交'}
    cancel()
    emit({'stage':'submit_requested','message':'仅提交一次；响应未知时不会重复点击','progress':85})
    try:
        # From this point even a click timeout may mean the request was accepted.
        await button.click(timeout=8000)
        await wait_verification(page,cancel,emit)
        result=await verify_receipt(page,platform,cancel)
        if result:return {**result,'visibility':visibility}
    except Exception:pass
    return {'status':'outcome_unknown','message':'已尝试提交一次，回执未知或操作已取消；请核对创作中心，禁止自动重发','visibility':visibility}


async def perform(page,platform,action,payload,cancel,emit):
    if platform!='douyin':raise ValueError('小红书已删除自动操作，请人工发布')
    if action=='query_publications':
        from .publications import query_browser
        return await query_browser(page,platform,cancel,emit)
    if action=='open_drafts':
        await bounded(page.goto(URLS[platform],wait_until='domcontentloaded',timeout=90000),cancel,95)
        return {'status':'complete','message':'只打开既有草稿页面；未选择文件、未上传、未点击按钮'}
    if action=='check':
        await bounded(page.goto(URLS[platform],wait_until='domcontentloaded',timeout=90000),cancel,95)
        await asyncio.sleep(2);cancel()
        valid=await is_logged_in(page,platform)
        return {'status':'complete' if valid else 'failed','message':'在线会话有效' if valid else '在线会话未确认，请登录；本地文件存在不等于在线有效','evidence':{'online_checked':True,'logged_in':valid}}
    await prepare_upload(page,platform,payload,cancel,emit)
    if action=='draft':return await save_draft(page,platform,cancel)
    if action!='publish':raise ValueError('不支持的浏览器动作')
    await wait_verification(page,cancel,emit)
    await select_visibility(page,platform,payload['visibility'],cancel)
    return await submit_once(page,platform,payload['visibility'],cancel,emit)


def browser_options(context):
    root=Path(context['engine_root'])
    if context.get('browser_path'):
        path=Path(context['browser_path'])
        if path.is_file():return {'executable_path':str(path),'headless':False}
        browser_dir=path
    else:
        browser_dir=next((p for p in (root/'runtime'/'browsers-douyin',root/'components'/'browsers-douyin',root/'browsers-douyin') if p.is_dir()),None)
    if browser_dir is None:raise ValueError('缺少随软件浏览器组件')
    candidates=sorted(browser_dir.glob('chromium-*/chrome-win64/chrome.exe'))
    if not candidates:candidates=sorted(browser_dir.glob('chromium-*/chrome-win/chrome.exe'))
    if not candidates:raise ValueError('未找到本项目 Chromium 可执行文件')
    return {'executable_path':str(candidates[-1]),'headless':False}


async def run(job,worker_context,profile,state,emit):
    from patchright.async_api import async_playwright
    if job.get('platform')=='xiaohongshu':return {'status':'failed','message':'小红书已改为人工发布','evidence':{'manual_only':True,'browser_launched':False}}
    cancel=lambda:check_cancel(worker_context)
    platform=job['platform'];action=job['action'];payload=job.get('payload',{})
    has_profile=profile.is_dir() and any(profile.iterdir())
    if action!='login' and not has_profile and not state.is_file():
        return {'status':'failed','message':'本账号没有登录记录，请先扫码登录','evidence':{'online_checked':False}}
    profile.mkdir(parents=True,exist_ok=True);state.parent.mkdir(parents=True,exist_ok=True)
    qr_dir=Path(worker_context['cancel_path']).parent if worker_context.get('cancel_path') else state.parent/'login-qr'
    async with async_playwright() as p:
        ctx=await bounded(p.chromium.launch_persistent_context(str(profile),**browser_options(worker_context)),cancel,45)
        try:
            if not has_profile and state.is_file():await seed(ctx,state)
            page=ctx.pages[0] if ctx.pages else await ctx.new_page()
            if action=='login':return await login(page,ctx,state,platform,cancel,emit,qr_dir)
            last_stage={'value':None,'submitted':False}
            def observed_emit(event):
                last_stage['value']=event.get('stage')
                if event.get('stage')=='submit_requested':last_stage['submitted']=True
                emit(event)
            try:
                result=await perform(page,platform,action,payload,cancel,observed_emit)
                if action=='publish' and result.get('status')=='failed' and not last_stage['submitted']:raise ValueError(result.get('message','发布前检查失败'))
            except Exception as exc:
                if action!='publish':raise
                attempted=last_stage['submitted']
                diagnostic=qr_dir/'publish-diagnostic.json'
                try:
                    details={'url':page.url,'text':(await page.locator('body').inner_text(timeout=5000))[:16000],
                        'radios':await page.locator('[role=radio],input[type=radio],label').evaluate_all('(els)=>els.map(e=>({tag:e.tagName,role:e.getAttribute("role"),text:e.innerText,aria:e.getAttribute("aria-label"),checked:e.checked,cls:e.className,html:e.outerHTML})).slice(0,120)')}
                    details['buttons']=await page.locator('button,[role=button],[class*=publish-button],[class*=publishBtn],[class*=submit]').evaluate_all('(els)=>els.map(e=>({tag:e.tagName,text:e.innerText,aria:e.getAttribute("aria-label"),cls:e.className,disabled:e.disabled,html:e.outerHTML.slice(0,1800)})).slice(0,100)')
                    diagnostic.write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
                except Exception:pass
                result={'status':'outcome_unknown' if attempted else 'failed','message':('已请求提交，结果需核对' if attempted else '发布前表单检查未通过，零提交')+'（'+type(exc).__name__+'）'+(str(exc) if isinstance(exc,ValueError) else ''),'evidence':{'submission_attempted':attempted,'last_stage':last_stage['value'],'diagnostic_path':str(diagnostic)}}
            try:
                await ctx.storage_state(path=str(state))
            except Exception:
                # Saving a local session must not erase an observed remote receipt.
                result.setdefault('evidence',{})['session_saved']=False
            if action=='open_drafts':
                emit({'stage':'awaiting_user','message':'请检查可见浏览器；关闭页面、取消任务或180秒后结束本地窗口','requires_user':True})
                end=time.monotonic()+180
                while not page.is_closed() and time.monotonic()<end:
                    cancel();await asyncio.sleep(.3)
            return result
        finally:
            # Close only our context. Never kill other account/browser processes.
            try:await ctx.close()
            except Exception:pass
