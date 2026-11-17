import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from studio import adapters
from studio import browser_worker as bw


class AdapterTests(unittest.TestCase):
    def test_publish_requires_explicit_visibility_before_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            for visibility in (None, 'draft', ''):
                job = {'platform':'douyin','action':'publish','account':'creator','payload':{'visibility':visibility}}
                with self.assertRaises(ValueError):
                    adapters.execute(job,{'state_root':tmp,'engine_root':tmp,'cancel_path':str(Path(tmp)/'cancel')},lambda e:None)

    def test_cancel_before_any_platform_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'cancel'; marker.touch()
            result=adapters.execute({'platform':'bilibili','action':'login'}, {'state_root':tmp,'engine_root':tmp,'cancel_path':str(marker)},lambda e:None)
            self.assertEqual(result['status'],'cancelled')

    def test_lock_prevents_second_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            with adapters.AccountLock(Path(tmp)/'account.lock'):
                with self.assertRaises(adapters.AccountBusy):
                    with adapters.AccountLock(Path(tmp)/'account.lock'): pass

    def test_release_components_discovery_without_developer_paths(self):
        with tempfile.TemporaryDirectory(prefix='adapter release ') as tmp:
            root=Path(tmp)
            exe=root/'components/biliup/biliup.exe';exe.parent.mkdir(parents=True);exe.touch()
            chrome=root/'components/browsers-douyin/chromium-1248/chrome-win64/chrome.exe'
            chrome.parent.mkdir(parents=True);chrome.touch()
            self.assertEqual(adapters.find_bili(root),exe)
            options=bw.browser_options({'engine_root':str(root)})
            self.assertEqual(options['executable_path'],str(chrome))
            self.assertFalse(options['headless'])

    def test_cookie_shape_and_scoping(self):
        data=adapters.bili_cookie_document([{'name':'SESSDATA','value':'test-only'},{'name':'DedeUserID','value':'12'}])
        self.assertEqual(data['token_info']['mid'],12)
        self.assertEqual(data['cookie_info']['cookies'][0]['name'],'SESSDATA')
        with self.assertRaises(ValueError): adapters.account_paths(Path('root'),'douyin','../other')

    def test_bili_command_explicit_private_and_one_process(self):
        args=adapters.bili_publish_args(Path('biliup.exe'),Path('account.json'),{'file':'clip.mp4','title':'test','caption':'cap','tags':['相关'],'visibility':'private'})
        self.assertEqual(args[args.index('--is-only-self')+1],'1')
        self.assertEqual(args[args.index('--limit')+1],'1')
        self.assertEqual(args[args.index('--submit')+1],'web')

    def test_bili_unknown_never_relaunches_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'cookies.json';state.write_text('{}')
            job={'action':'publish','payload':{'file':'clip.mp4','title':'test','visibility':'public'}}
            with patch.object(adapters,'find_bili',return_value=Path('biliup.exe')),patch.object(adapters,'_run_engine',return_value=(1,'no verified receipt')) as engine:
                result=adapters._bili(job,{'engine_root':tmp},state,lambda e:None)
            self.assertEqual(result['status'],'outcome_unknown')
            engine.assert_called_once()

    def test_bili_private_mismatch_keeps_acceptance_but_unknown(self):
        result=self._bili_show_result('{"archive":{"bvid":"BV1xx411c7mD","is_only_self":0,"state_desc":"开放浏览"}}')
        self.assertEqual(result['status'],'outcome_unknown')
        self.assertEqual(result['remote_id'],'BV1xx411c7mD')
        self.assertEqual(result['evidence']['visibility_actual'],'public')
        self.assertFalse(result['evidence']['visibility_readback'])
        self.assertTrue(result['evidence']['submission_accepted'])

    def test_bili_missing_visibility_does_not_claim_private_verified(self):
        result=self._bili_show_result('{"archive":{"bvid":"BV1xx411c7mD","state_desc":"审核中"}}')
        self.assertEqual(result['status'],'outcome_unknown')
        self.assertIsNone(result['evidence']['visibility_actual'])
        self.assertFalse(result['evidence']['visibility_readback'])

    def test_bili_matching_private_readback_verified(self):
        result=self._bili_show_result('INFO before JSON\n{"archive":{"bvid":"BV1xx411c7mD","is_only_self":1,"state_desc":"仅自己可见"}}\n')
        self.assertEqual(result['status'],'submitted')
        self.assertEqual(result['evidence']['visibility_actual'],'private')
        self.assertTrue(result['evidence']['visibility_readback'])

    def _bili_show_result(self,show):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'cookies.json';state.write_text('{}')
            job={'action':'publish','payload':{'file':'clip.mp4','title':'test','visibility':'private'}}
            with patch.object(adapters,'find_bili',return_value=Path('biliup.exe')),patch.object(adapters,'_run_engine',side_effect=[(0,'BV1xx411c7mD'),(0,show)]) as engine:
                result=adapters._bili(job,{'engine_root':tmp},state,lambda e:None)
            self.assertEqual(engine.call_count,2)
            self.assertEqual(sum('upload' in call.args[0] for call in engine.call_args_list),1)
            return result

    def test_bili_qr_login_saves_web_cookie_document_only(self):
        from types import SimpleNamespace
        cookie=SimpleNamespace(name='SESSDATA',value='fixture-only',domain='.bilibili.com',path='/',expires=None)
        replies=[{'code':0,'data':{'url':'https://example.invalid/fixture','qrcode_key':'fixture'}}, {'code':0,'data':{'code':0}}]
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'cookies.json';events=[]
            with patch('http.cookiejar.CookieJar',return_value=[cookie]),patch.object(adapters,'_json_http',side_effect=replies):
                result=adapters._bili_login(state,{'cancel_path':str(Path(tmp)/'cancel')},events.append)
            self.assertEqual(result['status'],'complete')
            import json
            saved=json.loads(state.read_text())
            self.assertEqual(saved['platform'],'Web')
            self.assertEqual(saved['token_info']['access_token'],'')
            self.assertTrue(events[0]['qr_path'].endswith('.png'))
            self.assertNotIn('fixture-only',str(events))


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_submit_never_clicks_twice(self):
        page=AsyncMock()
        button=AsyncMock(); button.count.return_value=1; button.is_visible.return_value=True; button.is_enabled.return_value=True
        page.get_by_role=lambda *a,**k:button
        with patch.object(bw,'wait_verification',AsyncMock()),patch.object(bw,'verify_receipt',AsyncMock(return_value=None)):
            result=await bw.submit_once(page,'douyin','public',lambda:None,lambda e:None)
        self.assertEqual(result['status'],'outcome_unknown')
        button.click.assert_awaited_once()

    async def test_xhs_submit_removed_without_click(self):
        page=AsyncMock()
        with self.assertRaisesRegex(ValueError,'人工'):
            await bw.submit_once(page,'xiaohongshu','public',lambda:None,lambda e:None)
        page.get_by_role.assert_not_called()

    async def test_cancel_before_submit_never_clicks(self):
        page=AsyncMock()
        def cancelled(): raise adapters.Cancelled()
        with self.assertRaises(adapters.Cancelled):
            await bw.submit_once(page,'douyin','private',cancelled,lambda e:None)
        page.get_by_role.assert_not_called()

    async def test_visibility_readback_failure_prevents_submit(self):
        page=AsyncMock()
        with patch.object(bw,'prepare_upload',AsyncMock()),patch.object(bw,'wait_verification',AsyncMock()),patch.object(bw,'select_visibility',AsyncMock(side_effect=ValueError('mismatch'))),patch.object(bw,'submit_once',AsyncMock()) as submit:
            with self.assertRaises(ValueError):
                await bw.perform(page,'douyin','publish',{'visibility':'private'},lambda:None,lambda e:None)
            submit.assert_not_awaited()

    async def test_cancel_after_click_is_unknown(self):
        page=AsyncMock();button=AsyncMock();button.count.return_value=1;button.is_visible.return_value=True;button.is_enabled.return_value=True
        page.get_by_role=lambda *a,**k:button
        with patch.object(bw,'wait_verification',AsyncMock()),patch.object(bw,'verify_receipt',AsyncMock(side_effect=adapters.Cancelled())):
            result=await bw.submit_once(page,'douyin','private',lambda:None,lambda e:None)
        self.assertEqual(result['status'],'outcome_unknown')
        button.click.assert_awaited_once()

    async def test_open_drafts_never_uploads(self):
        page=AsyncMock()
        with patch.object(bw,'prepare_upload',AsyncMock()) as upload:
            result=await bw.perform(page,'douyin','open_drafts',{},lambda:None,lambda e:None)
        upload.assert_not_awaited()
        self.assertEqual(result['status'],'complete')

    async def test_ambiguous_draft_zero_clicks(self):
        page=AsyncMock(); buttons=[]
        def get(*a,**kw):
            b=AsyncMock();b.count.return_value=1;b.is_visible.return_value=True;b.is_enabled.return_value=True;buttons.append(b);return b
        page.get_by_role=get
        result=await bw.save_draft(page,'douyin',lambda:None)
        self.assertEqual(result['status'],'failed')
        for b in buttons:b.click.assert_not_awaited()

if __name__=='__main__': unittest.main()
