"""Offline runtime diagnostics; uses a fresh browser without account state."""
import asyncio
import json
from pathlib import Path
import subprocess
import tempfile

async def probe_browser(root,export_notices=None):
    from patchright.async_api import async_playwright
    from .browser_worker import browser_options
    options=browser_options({'engine_root':str(root)})
    options['headless']=True
    async with async_playwright() as p:
        browser=await p.chromium.launch(**options)
        try:
            page=await browser.new_page()
            await page.set_content('<html><head><title>三平台离线诊断</title></head><body>本地浏览器检查</body></html>')
            title=await page.title()
            if export_notices:
                target=Path(export_notices);target.mkdir(parents=True,exist_ok=True)
                for section in ('credits','terms'):
                    await page.goto('chrome://'+section,wait_until='load',timeout=20000)
                    await page.wait_for_timeout(1500)
                    (target/('chrome-'+section+'.html')).write_text(await page.content(),encoding='utf-8')
                    (target/('chrome-'+section+'.txt')).write_text(await page.locator('body').inner_text(),encoding='utf-8')
            return {'ok':title=='三平台离线诊断','version':browser.version,'offline_page_title':title,'account_profile_used':False}
        finally:await browser.close()

def diagnose(root,browser=False,export_notices=None):
    from PySide6 import QtCore
    from .adapters import find_bili
    from .browser_worker import browser_options
    from .media import _find_tools
    from .asr import asr_status
    result={'ok':True,'qt':QtCore.qVersion(),'biliup_found':False,'browser_found':False}
    try:
        exe=find_bili(root)
        p=subprocess.run([str(exe),'--version'],capture_output=True,text=True,encoding='utf-8',timeout=15,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result['biliup_found']=p.returncode==0
        result['biliup_version']=p.stdout.strip()[:200]
        result['browser_found']=Path(browser_options({'engine_root':str(root)})['executable_path']).is_file()
        tools=_find_tools(Path(root));result['media_tools_found']=all(p.is_file() for p in tools)
        result['asr']=asr_status(root)
        if browser:result['browser']=asyncio.run(probe_browser(root,export_notices))
    except Exception as exc:
        result['ok']=False;result['error']=type(exc).__name__
    result['ok']=result['ok'] and result['biliup_found'] and result['browser_found'] and result.get('media_tools_found',False) and result.get('asr',{}).get('ready',False) and result.get('browser',{'ok':True})['ok']
    return result
