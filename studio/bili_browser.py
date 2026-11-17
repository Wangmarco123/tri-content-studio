"""Update one authenticated existing archive through the creator's edit form."""
import asyncio,json,re
from pathlib import Path
from .adapters import _json_http,_bili_cookie_header,check_cancel

async def update_existing(state,payload,context,emit):
    from patchright.async_api import async_playwright
    from .browser_worker import browser_options,wait_verification
    cancel=lambda:check_cancel(context);bid=payload['remote_id'];root=Path(context['engine_root'])
    if not re.fullmatch(r'BV[1-9A-HJ-NP-Za-km-z]{10}',bid):raise ValueError('稿件编号无效')
    url='https://member.bilibili.com/x/vupre/web/archive/view?bvid='+bid
    before=_json_http(url,headers={'Cookie':_bili_cookie_header(state)})
    if before.get('code')!=0:raise ValueError('原稿件读取失败，零修改')
    old=before['data']['archive'];assert old['bvid']==bid
    cookie_data=json.loads(state.read_text(encoding='utf-8-sig'))
    folder=Path(context['cancel_path']).parent;folder.mkdir(parents=True,exist_ok=True)
    submitted=False;responses=[]
    async with async_playwright() as p:
        ctx=await p.chromium.launch_persistent_context(str(Path(context['state_root'])/'bilibili/profiles'/payload.get('account','creator')),**browser_options(context))
        try:
            await ctx.add_cookies([{'name':c['name'],'value':c['value'],'domain':'.bilibili.com','path':'/'} for c in cookie_data['cookie_info']['cookies']])
            page=ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto('https://member.bilibili.com/platform/upload/video/frame?type=edit&bvid='+bid,wait_until='domcontentloaded',timeout=60000)
            title=page.get_by_placeholder('请输入稿件标题',exact=True);await title.wait_for(timeout=30000)
            await page.wait_for_function('(expected)=>document.querySelector("input[placeholder=请输入稿件标题]")?.value===expected',arg=old['title'],timeout=20000)
            if await title.count()!=1 or await title.input_value()!=old['title']:raise ValueError('编辑表单不能对应原稿件，零提交')
            await wait_verification(page,cancel,emit)
            more=page.get_by_text('更多设置 （含声明与权益、视频元素、互动管理等）',exact=True)
            private=page.get_by_text('仅自己可见' if payload['visibility']=='private' else '公开可见',exact=True)
            if await more.count()==1 and (await private.count()!=1 or not await private.is_visible()):await more.click()
            if await private.count()!=1:raise ValueError('原稿件可见范围不唯一')
            await private.click()
            if await private.locator('xpath=..').locator('.check-radio-v2-box-checked').count()!=1:raise ValueError('原稿件可见范围没有选中')
            await title.fill(payload['title'])
            editor=page.locator('div.ql-editor').first
            normal=lambda s:''.join(s.split())
            await page.wait_for_function('(expected)=>(document.querySelector("div.ql-editor")?.innerText||"").replace(/\\s/g,"")===expected',arg=normal(old.get('desc','')),timeout=15000)
            if normal(await editor.inner_text())!=normal(old.get('desc','')):raise ValueError('简介表单与原稿件不符')
            caption=payload.get('caption','')
            repo='https://github.com/Wangmarco123/dual-cloud-uploader'
            if repo in old.get('desc','') and repo not in caption:caption+='\n代码与下载：'+repo
            if '授权合成旁白' in old.get('desc','') and '合成旁白' not in caption:caption+='\n本片含原创二次元讲解员与本人授权合成旁白。'
            await editor.fill(caption)
            tags=page.locator('div.label-item-v2-container svg.close');count=await tags.count()
            if count>10:raise ValueError('标签表单存在歧义')
            for _ in range(count):await tags.first.click()
            tag_input=page.get_by_placeholder('按回车键Enter创建标签',exact=True).first
            for index,tag in enumerate(payload.get('tags',[])):
                await tag_input.fill(tag);await tag_input.press('Enter')
                await page.wait_for_function('(expected)=>{const values=Array.from(document.querySelectorAll("div.label-item-v2-container p")).map(e=>e.innerText.trim());return values.length===expected.length&&expected.every((v,i)=>values[i]===v)}',arg=payload['tags'][:index+1],timeout=10000)
            if [s.strip() for s in await page.locator('div.label-item-v2-container p').all_text_contents()]!=payload.get('tags',[]):raise ValueError('原稿件标签回读不一致')
            # Current creator UI offers the primary category directly.
            region=page.get_by_text('游戏 → 电子竞技',exact=True)
            if await region.count()==1:
                await region.click();tech=page.get_by_text('科技数码',exact=True)
                if await tech.count()!=1:raise ValueError('软件相关分区无法唯一选择')
                await tech.click()
            if await title.input_value()!=payload['title'] or normal(await editor.inner_text())!=normal(caption):raise ValueError('改稿文案回读不一致')
            await page.screenshot(path=str(folder/'before-edit-submit.png'))
            button=page.get_by_text('立即投稿',exact=True)
            if await button.count()!=1:raise ValueError('改稿提交按钮不唯一')
            cancel();emit({'stage':'submit_requested','message':'仅提交一次原稿件修改；未选择上传文件'})
            submitted=True;await button.click(timeout=8000)
            await wait_verification(page,cancel,emit)
            for _ in range(20):
                cancel();await asyncio.sleep(1)
                after=_json_http(url,headers={'Cookie':_bili_cookie_header(state)});actual=(after.get('data') or {}).get('archive') or {}
                if actual.get('is_only_self')==(1 if payload['visibility']=='private' else 0) and actual.get('title')==payload['title'] and normal(actual.get('desc',''))==normal(caption) and set(str(actual.get('tag','')).split(','))==set(payload.get('tags',[])):
                    return {'status':'submitted','message':'原稿件文案和可见范围已回读确认','remote_id':bid,'url':'https://www.bilibili.com/video/'+bid,'visibility':payload['visibility'],'evidence':{'updated_existing':True,'readback_verified':True,'new_video_uploaded':False,'category_id':actual.get('human_type2'),'caption':caption,'tags':actual.get('tag')}}
            return {'status':'outcome_unknown','message':'已提交原稿件修改，回读尚未一致；禁止重复提交','remote_id':bid}
        except Exception as exc:
            try:
                (folder/'edit-diagnostic.json').write_text(json.dumps({'error_type':type(exc).__name__,'message':str(exc) if isinstance(exc,ValueError) else '', 'text':(await page.locator('body').inner_text())[:18000]},ensure_ascii=False),encoding='utf-8')
            except Exception:pass
            return {'status':'outcome_unknown' if submitted else 'failed','message':('改稿响应需核对' if submitted else '原稿件表单检查失败，零提交')+'（'+type(exc).__name__+'）'+(str(exc) if isinstance(exc,ValueError) else ''),'remote_id':bid}
        finally:await ctx.close()
