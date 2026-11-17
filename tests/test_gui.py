import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
from studio.gui import StudioWindow


class FakeService:
    def __init__(self, root):
        self.paths = SimpleNamespace(data_dir=Path(root), project_root=Path(root), token_path=Path(root)/'token')
        self.created = []
        self.closed = False
        self.campaign_records=[];self.campaign_requests=[];self.campaign_saves=[]
    def assets(self): return [{'id':'asset1','name':'演示视频.mp4','path':'test.mp4','size':100,'summary':'真实演示','audience':'设计师','facts':['展示模型'],'keywords':['设计']}]
    def drafts(self): return [{'id':'draft1','asset_id':'asset1','platform':'bilibili','title':'真实模型展示','caption':'展示内容','tags':['设计'],'visibility':'draft','evidence_ids':[],'fit_reason':''}]
    def evidence(self): return []
    def jobs(self): return []
    def accounts(self): return []
    def settings(self): return {}
    def events(self, job_id): return []
    def close(self): self.closed = True
    def create_job(self, payload): self.created.append(payload); return {'id':'newjob'}
    def ai_status(self):return {'codex':{'available':False,'logged_in':False,'message':'离线测试未运行登录检测'},'api':{'configured':False},'default_provider':'codex'}
    def campaigns(self):return self.campaign_records
    def get_campaign(self,record_id):return next(c for c in self.campaign_records if c['id']==record_id)
    def start_campaign(self,payload):
        self.campaign_requests.append(payload)
        record={'id':'campaign1','asset_id':payload['asset_id'],'status':'queued','stage':'media','progress':0,'message':'等待抽帧','provider':'codex','created_at':'2026-11-16','result':None,'draft_ids':[]}
        self.campaign_records.append(record);return record
    def save_campaign(self,payload):self.campaign_saves.append(payload);return {'items':[],'count':3,'jobs':[]}
    def cancel_campaign(self,record_id):
        record=self.get_campaign(record_id);record.update(status='cancelled',message='已取消');return record


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.service = FakeService(self.temp.name)
        self.window = StudioWindow(self.service, {'endpoint':'http://127.0.0.1:32100','token_path':str(self.service.paths.token_path),'openapi_url':'http://127.0.0.1:32100/openapi.json','version':'test'})
    def tearDown(self):
        self.window.shutdown()
        self.temp.cleanup()
    def test_xhs_manual_export_hides_remote_controls(self):
        self.window.draft_platform.setCurrentIndex(self.window.draft_platform.findData('xiaohongshu'))
        self.window.update_publish_controls()
        self.assertTrue(self.window.publish_button.isHidden())
        self.assertTrue(self.window.draft_button.isHidden())
        self.assertFalse(self.window.manual_export.isHidden())
        self.assertEqual(self.window.account_platform.findData('xiaohongshu'),-1)
        target=Path(self.temp.name)/'人工发布.txt'
        self.window.title_edit.setText('手动发布标题');self.window.caption_edit.setPlainText('真实视频说明')
        self.window.tags_edit.setText('文件管理，办公效率')
        with patch('studio.gui.QFileDialog.getSaveFileName',return_value=(str(target),'文本 (*.txt)')):
            self.window.export_manual_copy()
        text=target.read_text(encoding='utf-8-sig')
        self.assertIn('手动发布标题',text);self.assertIn('#文件管理 #办公效率',text)
        self.assertEqual(self.service.created,[])

    def test_publish_requires_explicit_confirmation(self):
        self.window.draft_choice.setCurrentIndex(0)
        self.window.visibility.setCurrentIndex(self.window.visibility.findData('public'))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            self.window.enqueue_selected('publish')
        self.assertEqual(self.service.created, [])
    def test_default_visibility_is_draft_and_save_action_is_separate(self):
        self.assertEqual(self.window.visibility.currentData(), 'draft')
        self.assertIn('草稿', self.window.draft_button.text())
    def test_empty_token_is_not_shown_or_read_on_initialization(self):
        self.assertFalse(self.service.paths.token_path.exists())
        self.assertNotIn('test-token', self.window.endpoint.text())
    def test_shutdown_closes_service(self):
        self.window.shutdown()
        self.assertTrue(self.service.closed)
    def test_unsaved_copy_cannot_queue_old_snapshot(self):
        self.window.title_edit.setText('未保存的新标题')
        with patch.object(self.window, 'error') as error:
            self.window.enqueue_selected('draft')
        self.assertTrue(error.called)
        self.assertEqual(self.service.created, [])

    def test_real_service_import_selects_new_video_in_all_workspaces(self):
        from studio.service import Service
        root=Path(self.temp.name)/'import-selection';root.mkdir()
        service=Service(root,root/'data',start_worker=False)
        old_file=root/'旧视频.mp4';old_file.write_bytes(b'old-video-fixture')
        new_file=root/'新视频.mp4';new_file.write_bytes(b'new-video-fixture')
        old=service.add_asset({'path':str(old_file)})
        service.save_draft({'asset_id':old['id'],'platform':'bilibili','title':'旧素材文案','caption':'旧文案','tags':[]})
        service.store.put('campaigns',{'id':'old-campaign','asset_id':old['id'],'status':'complete','stage':'complete','progress':100,'message':'已保存','created_at':'2026-11-16T01:00:00+08:00','updated_at':'2026-11-16T01:00:00+08:00','result':self.campaign_result(),'draft_ids':[]})
        window=StudioWindow(service,{'endpoint':'http://127.0.0.1:0'})
        try:
            self.assertEqual(window.campaign_asset.currentData(),old['id'])
            self.assertEqual(window.ops_asset.currentData(),old['id'])
            self.assertEqual(window._campaign_id,'old-campaign')
            self.assertIsNotNone(window._campaign_result)
            with patch('studio.gui.QFileDialog.getOpenFileName',return_value=(str(new_file),'视频')),patch.object(service,'ai_status',return_value=self.service.ai_status()):
                window.import_asset()
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    self.app.processEvents()
                    if window.campaign_asset.currentData()!=old['id'] and not window._workers:break
                    time.sleep(.005)
            new=next(asset for asset in service.assets() if asset['path']==str(new_file))
            self.assertEqual(window.campaign_asset.currentData(),new['id'])
            self.assertEqual(window.ops_asset.currentData(),new['id'])
            self.assertEqual(window.selected_asset()['id'],new['id'])
            self.assertIsNone(window._campaign_id)
            self.assertIsNone(window._campaign_result)
            self.assertEqual(window.campaign_history.currentIndex(),-1)
            self.assertEqual(window.campaign_fields['bilibili']['title'].count(),0)
            self.assertFalse(window.campaign_queue.isEnabled())
            self.assertEqual(service.jobs(),[])
            self.assertEqual(len(service.campaigns()),1)
        finally:window.shutdown()

    def test_restart_restores_latest_current_asset_campaign_not_other_video(self):
        from studio.service import Service
        root=Path(self.temp.name)/'restore-history';root.mkdir()
        service=Service(root,root/'data',start_worker=False)
        other_file=root/'其他视频.mp4';other_file.write_bytes(b'other')
        other=service.add_asset({'path':str(other_file)})
        current_file=root/'当前视频.mp4';current_file.write_bytes(b'current')
        current=service.add_asset({'path':str(current_file)})
        for cid,asset_id,date in [('current-old',current['id'],'2026-11-14'),('current-latest',current['id'],'2026-11-15'),('other-newest',other['id'],'2026-11-16')]:
            service.store.put('campaigns',{'id':cid,'asset_id':asset_id,'status':'complete','stage':'complete','progress':100,'message':'历史完成','created_at':date+'T01:00:00+08:00','updated_at':date+'T01:00:00+08:00','result':self.campaign_result(),'draft_ids':[]})
        service.close()
        service=Service(root,root/'data',start_worker=False)
        window=StudioWindow(service,{'endpoint':'http://127.0.0.1:0'})
        try:
            self.assertEqual(window.campaign_asset.currentData(),current['id'])
            self.assertEqual(window._campaign_id,'current-latest')
            self.assertEqual(window.campaign_history.currentData(),'current-latest')
            self.assertEqual(window.campaign_history.count(),3)
            self.assertEqual(window.campaign_fields['bilibili']['title'].count(),2)
            self.assertIn('模型展示',window.campaign_scope.text())
            # Choosing a historical plan switches its owning video, not only the result pane.
            window.campaign_history.setCurrentIndex(window.campaign_history.findData('other-newest'))
            self.assertEqual(window.campaign_asset.currentData(),other['id'])
            self.assertEqual(window._campaign_id,'other-newest')
            self.assertEqual(window.campaign_history.count(),3)
            # Manually changing the video returns to only that video's newest eligible plan.
            window.campaign_asset.setCurrentIndex(window.campaign_asset.findData(current['id']))
            self.assertEqual(window._campaign_id,'current-latest')
            self.assertEqual(window.campaign_history.currentData(),'current-latest')
        finally:window.shutdown()
    def test_app_main_uses_gui_entry_and_closes_cleanly(self):
        from studio.app import main
        root=Path(self.temp.name)/'entry-smoke'; root.mkdir()
        original_show=StudioWindow.show
        def show_then_exit(window):
            original_show(window)
            QTimer.singleShot(50,window.shutdown)
        from studio.service import Service
        with patch.object(StudioWindow,'show',show_then_exit),patch.object(Service,'ai_status',return_value=self.service.ai_status(),create=True):
            result=main(['--home',str(root),'--data-dir',str(root/'data'),'--port','0'])
        self.assertEqual(result,0)
        self.assertTrue((root/'data'/'connection.json').is_file())
    def test_failed_shutdown_keeps_window_open(self):
        with patch.object(self.service,'close',side_effect=RuntimeError('still stopping')), patch.object(self.window,'error'):
            self.assertFalse(self.window.shutdown())
        self.assertFalse(self.window._closing)
    def test_background_operation_delivers_callback_on_gui_thread(self):
        main_thread=threading.get_ident(); completed=[]
        self.window.busy(lambda:threading.get_ident(),lambda worker:completed.append((worker,threading.get_ident())))
        deadline=time.monotonic()+2
        while not completed and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(0.005)
        self.assertEqual(len(completed),1)
        self.assertNotEqual(completed[0][0],main_thread)
        self.assertEqual(completed[0][1],main_thread)
    def test_real_service_draft_snapshot_shared_with_gui(self):
        from studio.service import Service
        root=Path(self.temp.name)/'isolated'
        root.mkdir()
        video=root/'本地测试.mp4'; video.write_bytes(b'gui-local-registration-fixture')
        service=Service(root,root/'appdata',start_worker=False)
        asset=service.add_asset({'path':str(video),'summary':'测试事实'})
        record=service.save_draft({'asset_id':asset['id'],'platform':'douyin','title':'真实内容测试','caption':'只做本地队列验证','tags':['设计']})
        window=StudioWindow(service,{'endpoint':'http://127.0.0.1:0'})
        try:
            with patch.object(window,'busy',side_effect=lambda operation,success=None,message='': operation()):
                window.enqueue_selected('draft')
            job=service.jobs()[0]
            self.assertEqual(job['draft_id'],record['id'])
            self.assertEqual(job['status'],'queued')
            self.assertEqual(job['payload']['visibility'],'draft')
            self.assertEqual(job['payload']['title'],'真实内容测试')
        finally: window.shutdown()

    def campaign_result(self):
        packages=[]
        for platform in ('bilibili','douyin','xiaohongshu'):
            packages.append({'platform':platform,'title':'第一标题','title_candidates':['第一标题','第二标题'],'caption':'真实成片内容','tags':['设计'],'hook':'首句钩子','category_suggestion':'科技 / 工业设计（建议）','search_keywords':['三维建模'],'fit_reason':'对应模型展示','evidence_ids':['ev1']})
        return {'summary':'模型展示','opportunities':[{'id':'op1','platform':'bilibili','title':'测试研究方向','why_relevant':'与模型功能有关','query_time':'2026-11-16T10:00:00+08:00','evidence_ids':['ev1']}],'fit_assessments':[{'opportunity_id':'op1','verdict':'connection','reason':'素材展示模型','segments':[{'start':1,'end':3,'observation':'展示功能','evidence_type':'sampled_frame'}],'supports_features':['功能演示'],'limits':['仅抽帧']}],'packages':packages,'sources':[{'id':'ev1','title':'测试来源','source_url':'https://www.bilibili.com/video/BV1xx411c7mD','fetched_at':'2026-11-16T10:00:00+08:00'}],'media':{'analysis_scope':'sampled_frames_and_supplied_subtitles','warnings':['没有字幕，不声称听过音频']}}

    def test_r02_primary_action_uses_auto_provider_without_api_key_or_json(self):
        self.assertEqual(self.window.navigation.currentRow(),0)
        self.assertEqual(self.window.campaign_provider.currentData(),'auto')
        with patch.object(self.window,'busy',side_effect=lambda operation,success=None,message='',**kwargs:success(operation()) if success else operation()):
            self.window.start_campaign()
        self.assertEqual(self.service.campaign_requests[0]['provider'],'auto')
        self.assertEqual(self.service.campaign_requests[0]['asset_id'],'asset1')
        self.assertEqual(self.service.created,[])

    def test_five_blocks_show_sources_segments_and_separate_platform_fields(self):
        record={'id':'campaign1','status':'complete','stage':'complete','progress':100,'message':'完成','result':self.campaign_result()}
        self.window._campaign_id='campaign1';self.window.render_campaign(record)
        self.assertEqual(self.window.campaign_tabs.count(),5)
        self.assertIn('https://www.bilibili.com/video/',self.window.opportunities_view.toHtml())
        self.assertIn('2026-11-16',self.window.opportunities_view.toPlainText())
        self.assertIn('1–3 秒',self.window.fit_view.toPlainText())
        self.assertIn('工业设计',self.window.campaign_fields['bilibili']['category'].text())
        self.assertEqual(self.window.campaign_fields['xiaohongshu']['search'].text(),'三维建模')
        self.assertEqual(self.window.campaign_fields['douyin']['hook'].text(),'首句钩子')

    def test_selected_titles_save_and_queue_only_via_campaign_contract(self):
        self.window._campaign_id='campaign1';self.window.render_campaign({'id':'campaign1','status':'complete','stage':'complete','progress':100,'result':self.campaign_result()})
        self.window.campaign_fields['bilibili']['title'].setCurrentIndex(1)
        self.window.campaign_fields['xiaohongshu']['title'].setCurrentIndex(1)
        with patch.object(self.window,'busy',side_effect=lambda operation,success=None,message='',**kwargs:success(operation()) if success else operation()):self.window.save_campaign_selection(True)
        self.assertEqual(self.service.campaign_saves[-1],{'id':'campaign1','selections':{'bilibili':1,'xiaohongshu':1},'queue_drafts':True})
        self.assertEqual(self.service.created,[],'Campaign UI must not directly create publication jobs')

    def test_polling_same_complete_campaign_preserves_selected_title(self):
        record={'id':'campaign1','status':'complete','stage':'complete','progress':100,'result':self.campaign_result()}
        self.window._campaign_id='campaign1';self.window.render_campaign(record)
        self.window.campaign_fields['bilibili']['title'].setCurrentIndex(1)
        self.window.render_campaign(record)
        self.assertEqual(self.window.campaign_fields['bilibili']['title'].currentIndex(),1)

    def test_campaign_progress_and_failure_are_real_service_state(self):
        self.window.render_campaign({'id':'campaign1','status':'running','stage':'ai','progress':35,'message':'正在匹配真实来源','result':None})
        self.assertEqual(self.window.campaign_progress.value(),35)
        self.assertFalse(self.window.campaign_generate.isEnabled())
        self.assertFalse(self.window.campaign_queue.isEnabled())
        self.window.render_campaign({'id':'campaign1','status':'failed','stage':'ai','progress':35,'message':'本机 Codex 尚未登录','result':None})
        self.assertTrue(self.window.campaign_generate.isEnabled())
        self.assertIn('本机 Codex 尚未登录',self.window.campaign_scope.text())
        self.assertFalse(self.window.campaign_queue.isEnabled())

    def test_no_trend_result_keeps_video_basis_and_stable_search_direction(self):
        result=self.campaign_result();result['opportunities']=[];result['fit_assessments']=[];result['no_trend_reason']='没有与本片直接相关的热点'
        result['media']['frames']=[{'timestamp':1.5,'path':'unused-frame.png'}]
        self.window.render_campaign({'id':'empty-trend','status':'complete','stage':'complete','progress':100,'result':result})
        self.assertIn('采用稳定搜索方向',self.window.opportunities_view.toPlainText())
        self.assertIn('没有与本片直接相关的热点',self.window.opportunities_view.toPlainText())
        text=self.window.fit_view.toPlainText()
        for expected in ('模型展示','B站适配理由','抖音适配理由','小红书适配理由','1.5 秒','未提供字幕'):
            self.assertIn(expected,text)

    def test_ai_searched_source_is_marked_pending_independent_review(self):
        result=self.campaign_result();result['sources'][0]['verification']='ai_researched'
        self.window.render_campaign({'id':'ai-source','status':'complete','stage':'complete','progress':100,'result':result})
        self.assertIn('AI 搜索来源，待独立复核',self.window.opportunities_view.toPlainText())

    def speech_result(self):
        result=self.campaign_result()
        segments=[{'start':i*2,'end':i*2+1.9,'text':f'第{i+1}句真实口播','avg_logprob':-.2,'no_speech_prob':.01,'uncertain':i==249} for i in range(250)]
        result['media'].update(analysis_scope='sampled_frames_and_full_audio_transcript',speech={'status':'complete','complete':True,'audio_duration':500,'processed_duration':500,'model':'large-v3-turbo','device':'cuda','cache_hit':True,'segments':segments,'text':'\n'.join(s['text'] for s in segments),'uncertain_segments':[249],'warnings':['品牌与数值需复核']})
        return result

    def test_full_speech_retains_250_segments_and_explicit_copy(self):
        result=self.speech_result()
        self.window.render_campaign({'id':'speech','status':'complete','stage':'complete','progress':100,'result':result},False)
        self.window.show_speech()
        self.assertEqual(self.window.campaign_tabs.count(),5)
        self.assertIn('第250句真实口播',self.window.speech_views['text'].toPlainText())
        self.assertIn('00:08:18.000',self.window.speech_views['timed'].toPlainText())
        self.assertIn('第250句真实口播',self.window.speech_views['uncertain'].toPlainText())
        for expected in ('500 / 500','large-v3-turbo','cuda','命中','不保证逐字准确','需复核片段：1'):
            self.assertIn(expected,self.window.speech_coverage.text())
        self.window.copy_speech(True)
        self.assertIn('第250句真实口播',self.app.clipboard().text())
        self.assertIn('不将机器评分当准确率',self.window.speech_views['uncertain'].toPlainText())
        output=os.environ.get('GUI_CAMPAIGN_SCREENSHOT_DIR')
        if output:
            directory=Path(output);directory.mkdir(parents=True,exist_ok=True)
            self.app.processEvents();self.window.speech_dialog.grab().save(str(directory/'gui_r03_full_speech.png'))

    def test_hidden_ui_check_captures_full_speech_without_clipboard_or_file_actions(self):
        import json
        from studio.gui import run
        result=self.speech_result()
        self.service.campaign_records=[{'id':'saved-speech','asset_id':'asset1','status':'complete','stage':'complete','progress':100,'created_at':'2026-11-16','result':result}]
        output=Path(self.temp.name)/'hidden-ui'
        self.app.clipboard().setText('验收不得修改剪贴板')
        with patch.object(StudioWindow,'copy_speech',side_effect=AssertionError('no automatic copy')),patch.object(StudioWindow,'open_speech_file',side_effect=AssertionError('no automatic open')):
            self.assertEqual(run(self.service,{'_ui_check_out':str(output)}),0)
        data=json.loads((output/'ui-fields.json').read_text(encoding='utf-8'))
        self.assertEqual(data['speech'],{'status':'complete','complete':True,'segments':250,'text_length':len(result['media']['speech']['text']),'last_text':'第250句真实口播','processed_duration':500,'audio_duration':500,'copy_plain_enabled':True})
        self.assertTrue((output/'speech_full.png').is_file())
        self.assertEqual(len(list(output.glob('page_*.png'))),6)
        self.assertEqual(len(list(output.glob('plan_*.png'))),5)
        self.assertEqual(self.app.clipboard().text(),'验收不得修改剪贴板')

    def test_legacy_no_audio_no_speech_and_asset_clear_are_honest(self):
        self.window.render_campaign({'id':'legacy','status':'complete','result':self.campaign_result()},False)
        self.window.show_speech()
        self.assertIn('旧方案',self.window.speech_status.text())
        self.assertFalse(self.window.speech_copy_plain.isEnabled())
        self.assertIn('旧分析',self.window.campaign_scope.text())
        for status,label in [('no_audio','无音轨'),('no_speech','未识别出可用人声')]:
            result=self.speech_result();result['media']['speech'].update(status=status,segments=[],text='',uncertain_segments=[])
            self.window.render_campaign({'id':status,'status':'complete','result':result},False)
            self.assertIn(label,self.window.speech_status.text())
            self.assertFalse(self.window.speech_copy_plain.isEnabled())
        self.window.clear_campaign_result()
        self.assertFalse(self.window.speech_button.isEnabled())
        self.assertNotIn('第250句',self.window.speech_views['text'].toPlainText())

    def test_audio_transcribe_progress_uses_real_values_and_speech_evidence_label(self):
        for stage,value,label in [('audio',7,'提取音轨'),('transcribe',23,'完整语音转写'),('media',34,'画面与完整口播')]:
            self.window.render_campaign({'id':'progress','status':'running','stage':stage,'progress':value,'result':None},False)
            self.assertEqual(self.window.campaign_progress.value(),value)
            self.assertIn(label,self.window.campaign_stage.text())
        result=self.speech_result();result['fit_assessments'][0]['segments'][0]['evidence_type']='speech'
        self.window.render_campaign({'id':'speech-fit','status':'complete','result':result},False)
        self.assertIn('全音轨机器转写',self.window.fit_view.toPlainText())

    def test_incomplete_speech_cannot_claim_complete_or_copy_as_full(self):
        result=self.speech_result();result['media']['speech'].update(complete=False,processed_duration=200)
        self.window.render_campaign({'id':'incomplete','status':'complete','result':result},False)
        self.window.show_speech()
        self.assertIn('尚未完整',self.window.speech_status.text())
        self.assertFalse(self.window.speech_copy_plain.isEnabled())
        self.app.clipboard().setText('保留原剪贴板')
        self.window.copy_speech()
        self.assertEqual(self.app.clipboard().text(),'保留原剪贴板')

    def test_platform_forms_scroll_and_long_fit_caption_remain_fully_readable(self):
        from PySide6.QtWidgets import QScrollArea, QTextEdit
        from PySide6.QtGui import QTextCursor
        result=self.campaign_result();long_fit='适配依据与真实功能。'*40+'适配说明最后一句';long_caption='这是完整视频简介。'*60+'简介最后一句'
        for package in result['packages']:package.update(fit_reason=long_fit,caption=long_caption)
        self.window.render_campaign({'id':'long-text','status':'complete','result':result},False)
        self.window.resize(1120,720);self.window.show()
        for index,platform in enumerate(('bilibili','douyin','xiaohongshu'),2):
            self.window.campaign_tabs.setCurrentIndex(index);self.app.processEvents()
            scroll=self.window.campaign_tabs.widget(index);self.assertIsInstance(scroll,QScrollArea);self.assertTrue(scroll.widgetResizable())
            fields=self.window.campaign_fields[platform];fit=fields['fit'];caption=fields['caption']
            self.assertIsInstance(fit,QTextEdit);self.assertTrue(fit.isReadOnly());self.assertGreaterEqual(fit.height(),80);self.assertGreaterEqual(caption.height(),90)
            fit.moveCursor(QTextCursor.MoveOperation.End);fit.ensureCursorVisible();self.app.processEvents()
            self.assertGreater(fit.verticalScrollBar().maximum(),0)
            fit.verticalScrollBar().setValue(fit.verticalScrollBar().maximum())
            self.assertEqual(fit.verticalScrollBar().value(),fit.verticalScrollBar().maximum())
            self.assertIn('适配说明最后一句',fit.toPlainText())
            caption.selectAll();self.assertEqual(caption.textCursor().selectedText(),long_caption)
            self.assertEqual(fit.toPlainText(),long_fit)

    def test_speech_files_open_only_existing_local_transcription_types(self):
        local=Path(self.temp.name)/'speech.txt';local.write_text('离线转写',encoding='utf-8')
        self.window._speech_media={'speech':{'txt_path':str(local)}}
        with patch('studio.gui.QDesktopServices.openUrl',return_value=True) as opened:
            self.window.open_speech_file('txt')
            self.assertTrue(opened.call_args.args[0].isLocalFile())
            opened.reset_mock()
            self.window._speech_media['speech']['txt_path']=str(Path(self.temp.name)/'outside.exe')
            with patch.object(self.window,'error') as error:self.window.open_speech_file('txt')
            opened.assert_not_called();error.assert_called_once()

    def test_real_service_async_campaign_poll_and_five_result_views(self):
        from studio.service import Service
        from studio.core import now
        from PySide6.QtGui import QPixmap, QColor
        root=Path(self.temp.name)/'campaign-ui';root.mkdir()
        service=Service(root,root/'data',start_worker=False)
        video=root/'离线界面测试.mp4';video.write_bytes(b'isolated gui async fixture')
        asset=service.add_asset({'path':str(video),'summary':'离线UI测试素材事实'})
        source=service.import_evidence({'items':[{'id':'ev1','platform':'bilibili','title':'离线界面集成测试来源（非当前热榜）','source_url':'https://www.bilibili.com/video/BV1xx411c7mD','fetched_at':now(),'verification':'unverified'}]})['items'][0]
        frame=root/'frame.png';pix=QPixmap(16,16);pix.fill(QColor('#187a72'));pix.save(str(frame))
        speech={'status':'no_audio','complete':True,'segments':[],'text':'','audio_duration':0,'processed_duration':0,'model':'offline-fixture','device':None,'warnings':[]}
        media={'duration':6,'width':1280,'height':720,'frames':[{'timestamp':1,'path':str(frame)}],'transcript':[],'speech':speech,'analysis_scope':'sampled_frames_no_audio','warnings':['离线测试替身，未请求实际AI或网络']}
        raw=self.campaign_result();raw['asset_id']=asset['id'];raw['research_sources']=[];raw['no_trend_reason']='';raw['opportunities'][0]['kind']='evergreen';raw['opportunities'][0]['query_time']=now()
        raw['fit_assessments'][0]['segments'][0].update(start=1,end=1)
        for package in raw['packages']:
            package['visibility']='draft';package['evidence_ids']=['ev1'] if package['platform']=='bilibili' else []
        def provider(*args,**kwargs):
            time.sleep(1.2)  # Real campaign worker stays active for the 1s UI poll.
            return raw
        window=None
        try:
            status={'available':True,'logged_in':True,'message':'离线状态替身'}
            with patch('studio.campaigns.transcribe_video',return_value=speech,create=True),patch('studio.campaigns.analyze_media',return_value=media),patch('studio.campaigns.fetch_trends',return_value={'items':[]}),patch('studio.campaigns.run_codex',side_effect=provider),patch('studio.campaigns.codex_status',return_value=status),patch('studio.ai_provider.codex_status',return_value=status):
                window=StudioWindow(service,{'endpoint':'http://127.0.0.1:0','version':'R02-qa'});window.show();window.start_campaign()
                deadline=time.monotonic()+8;observed=set()
                while window._campaign_result is None and time.monotonic()<deadline:
                    self.app.processEvents();observed.add(window.campaign_progress.value());time.sleep(.01)
                self.assertIsNotNone(window._campaign_result,window.campaign_scope.text())
                self.assertTrue({45,50}.intersection(observed),'The real 1s GUI timer must observe the asynchronous AI stage')
                self.assertEqual(service.get_campaign(window._campaign_id)['status'],'complete')
                self.assertEqual(len(service.drafts()),3);self.assertEqual(service.jobs(),[])
                self.assertIn(source['title'],window.opportunities_view.toPlainText())
                window.campaign_fields['bilibili']['title'].setCurrentIndex(1);window.campaign_fields['xiaohongshu']['title'].setCurrentIndex(1)
                window.save_campaign_selection(True)
                deadline=time.monotonic()+3
                while len(service.jobs())<2 and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
                self.app.processEvents()
                self.assertEqual({j['platform'] for j in service.jobs()},{'douyin'})
                self.assertTrue(all(j['action']=='draft' and j['status']=='queued' for j in service.jobs()))
                self.assertEqual(next(d for d in service.drafts() if d['platform']=='bilibili')['title'],'第二标题')
                output=os.environ.get('GUI_CAMPAIGN_SCREENSHOT_DIR')
                if output:
                    directory=Path(output);directory.mkdir(parents=True,exist_ok=True)
                    window.banner.setText('离线 GUI 集成验收 · 媒体与 AI 返回使用测试夹具，非真实热点')
                    for index in range(5):
                        window.campaign_tabs.setCurrentIndex(index);self.app.processEvents();window.grab().save(str(directory/f'gui_r03_service_async_{index}.png'))
        finally:
            if window:window.shutdown()
            else:service.close()


if __name__ == '__main__': unittest.main()
