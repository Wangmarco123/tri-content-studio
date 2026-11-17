import unittest
from pathlib import Path
from patchright.async_api import async_playwright
from studio.browser_worker import select_visibility,browser_options

class CurrentVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.p=await async_playwright().start();opts=browser_options({'engine_root':str(Path(__file__).resolve().parents[4])});opts['headless']=True
        self.browser=await self.p.chromium.launch(**opts);self.page=await self.browser.new_page()
    async def asyncTearDown(self):await self.browser.close();await self.p.stop()
    async def test_whitespace_label_native_checkbox_reads_selected(self):
        await self.page.set_content('<label data-checked="false"><input type="checkbox" value="0"><span>公开 </span></label>')
        await select_visibility(self.page,'douyin','public',lambda:None)
        self.assertTrue(await self.page.locator('input').is_checked())
    async def test_duplicate_public_labels_never_click(self):
        await self.page.set_content('<label><input type="checkbox">公开 </label><label><input type="checkbox">公开 </label>')
        with self.assertRaises(ValueError):await select_visibility(self.page,'douyin','public',lambda:None)
        self.assertEqual(await self.page.locator('input:checked').count(),0)

if __name__=='__main__':unittest.main()
