"""Native desktop workspace. All platform actions go through the shared service."""
from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
import sys
import uuid
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRunnable, QThreadPool, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QPushButton, QListWidget, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox, QLineEdit, QTextEdit,
    QComboBox, QSplitter, QFormLayout, QGroupBox, QSystemTrayIcon, QMenu, QCheckBox,
    QScrollArea, QTabWidget, QTextBrowser, QProgressBar, QDialog,
)

PLATFORMS = {'bilibili': 'B站', 'douyin': '抖音', 'xiaohongshu': '小红书'}
ACTIONS = {'login':'登录授权','check':'在线检查','open_drafts':'核对草稿','draft':'保存草稿','publish':'提交发布','query_publications':'查询作品','update_publication':'修改原稿件'}
STATES = {'queued':'等待执行','running':'执行中','awaiting_user':'待本人操作','cancel_requested':'正在停止本地操作','draft_saved':'草稿已保存','submitted':'已提交受理','outcome_unknown':'结果待核实','failed':'失败','cancelled':'已取消','complete':'已完成'}
STYLE = '''
QWidget {font-family:"Microsoft YaHei UI";font-size:13px;color:#23374c;background:#f3f6f8;}
QMainWindow {background:#f3f6f8;}
QListWidget#navigation {background:#142c42;color:#b9ccd9;border:0;padding:12px 8px;font-size:15px;outline:0;}
QListWidget#navigation::item {padding:17px 14px;margin:3px 0;border-radius:7px;}
QListWidget#navigation::item:selected {background:#235064;color:#f5ffff;}
QLabel#brand {background:#142c42;color:white;font-size:21px;font-weight:600;padding:25px 20px 5px;}
QLabel#brandSub {background:#142c42;color:#88a9bd;padding:0 20px 25px;font-size:11px;}
QLabel#pageTitle {font-size:26px;font-weight:600;color:#142c42;background:transparent;}
QLabel#muted {color:#6a7e8e;background:transparent;}
QLabel#status {background:#e5f2ee;color:#21634f;padding:9px 16px;border-radius:6px;}
QPushButton {background:white;border:1px solid #cdd8df;border-radius:6px;padding:9px 16px;min-height:17px;}
QPushButton:hover {border-color:#428d88;background:#edf6f4;}
QPushButton:disabled {color:#9aaab4;background:#e9eef1;}
QPushButton#primary {background:#187a72;color:white;border:1px solid #187a72;font-weight:600;}
QPushButton#primary:disabled {background:#e4ecef;color:#97a9b4;border-color:#d3dee4;}
QPushButton#danger {color:#a24a41;border-color:#dfc5c0;}
QLineEdit,QTextEdit,QComboBox {background:white;border:1px solid #ccd8e0;border-radius:5px;padding:8px;selection-background-color:#d1e9e3;}
QLineEdit:focus,QTextEdit:focus {border-color:#187a72;}
QGroupBox {background:white;border:1px solid #dce4e9;border-radius:8px;margin-top:16px;padding:18px 13px 13px;font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:15px;padding:0 6px;background:#f3f6f8;}
QGroupBox QLabel {background:transparent;}
QTableWidget {background:white;alternate-background-color:#f8fafb;border:1px solid #dde5eb;border-radius:5px;gridline-color:#edf1f4;}
QHeaderView::section {background:#eaf0f4;border:0;padding:11px;color:#4e6577;font-weight:600;}
QTableWidget::item {padding:8px;border-bottom:1px solid #edf1f4;}
QTableWidget::item:selected {background:#dceee9;color:#143b39;}
QSplitter::handle {background:#e2e9ed;width:7px;}
QScrollArea {border:0;} QCheckBox {spacing:8px;}
QTabWidget::pane {border:1px solid #d4e0e5;background:white;border-radius:5px;}
QTabBar::tab {background:#e8eef1;color:#536b7b;padding:10px 15px;border:1px solid #d4e0e5;border-bottom:0;}
QTabBar::tab:selected {background:white;color:#176e65;border-top:3px solid #187a72;}
QProgressBar {border:1px solid #ccd8df;border-radius:5px;text-align:center;background:#eef3f5;min-height:20px;}
QProgressBar::chunk {background:#8bc8ba;border-radius:4px;}
'''


class WorkSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Work(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = WorkSignals()
    def run(self):
        try: self.signals.done.emit(self.operation())
        except Exception as exc: self.signals.failed.emit(str(exc))


def icon():
    pix = QPixmap(64, 64)
    pix.fill(QColor('#142c42'))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#41b8a2'))
    for x, y, h in ((14,31,20),(28,19,32),(42,10,41)):
        painter.drawRoundedRect(x,y,8,h,3,3)
    painter.end()
    return QIcon(pix)


def button(text, slot, primary=False):
    widget = QPushButton(text)
    if primary: widget.setObjectName('primary')
    widget.clicked.connect(slot)
    return widget


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(43)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setAlternatingRowColors(True)
    return widget


class StudioWindow(QMainWindow):
    def __init__(self, service, api_info):
        if os.name == 'nt':
            # Offscreen Qt does not enumerate installed system fonts on Windows.
            font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'msyh.ttc'
            if font_path.is_file(): QFontDatabase.addApplicationFont(str(font_path))
        super().__init__()
        self.service, self.api_info = service, api_info
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self._workers = set()
        self._closing = False
        self._asset_rows, self._draft_rows, self._job_rows = [], [], []
        self._draft_id = None
        self.setWindowTitle('三平台内容发布助手')
        self.setWindowIcon(icon())
        self.resize(1320, 880)
        self.setMinimumSize(1120, 760)
        self.setStyleSheet(STYLE)
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        sidebar = QWidget()
        sidebar.setStyleSheet('background:#142c42;')
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0,0,0,0)
        brand = QLabel('内容发布助手'); brand.setObjectName('brand')
        sub = QLabel('B站 · 抖音 · 小红书'); sub.setObjectName('brandSub')
        side.addWidget(brand); side.addWidget(sub)
        self.navigation = QListWidget(); self.navigation.setObjectName('navigation')
        self.navigation.addItems(['AI 一键方案','素材库','文案与证据','账号与授权','任务队列','AI 接入与设置'])
        side.addWidget(self.navigation)
        foot = QLabel('本机工作空间  /  R05'); foot.setObjectName('brandSub'); side.addWidget(foot)
        outer.addWidget(sidebar)
        body = QWidget(); main = QVBoxLayout(body); main.setContentsMargins(28,24,28,20); main.setSpacing(16)
        self.banner = QLabel('就绪 · 选择视频，一键研究借势方向并生成三平台方案。'); self.banner.setObjectName('status')
        self.stack = QStackedWidget()
        main.addWidget(self.banner); main.addWidget(self.stack,1)
        outer.addWidget(body,1); self.setCentralWidget(central)
        self._campaign_id=None; self._rendered_campaign_id=None; self._campaign_result=None
        self._speech_media={};self.speech_dialog=None
        self.build_campaign(); self.build_assets(); self.build_operations(); self.build_accounts(); self.build_jobs(); self.build_ai()
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('三平台内容发布助手')
        menu = QMenu(); menu.addAction('显示主窗口', self.show_window); menu.addAction('退出并停止本地任务', self.shutdown)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable(): self.tray.show()
        self.refresh_workspace()
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_jobs); self.timer.start(2000)
        self.campaign_timer=QTimer(self); self.campaign_timer.timeout.connect(self.poll_campaign); self.campaign_timer.start(1000)
        QTimer.singleShot(50,self.refresh_ai_status)

    def build_campaign(self):
        layout=self.page('一键生成三平台方案','选择视频，自动提取音轨、完整转写并结合画面生成五项方案。不必先准备摘要或字幕；生成不等于发布。')
        controls=QHBoxLayout()
        self.campaign_asset=QComboBox(); self.campaign_asset.setPlaceholderText('导入或选择视频');self.campaign_asset.currentIndexChanged.connect(self.campaign_asset_changed); controls.addWidget(self.campaign_asset,1)
        controls.addWidget(button('＋ 导入视频',self.import_asset))
        self.campaign_provider=QComboBox()
        for label,value in [('自动 · 优先本机 Codex','auto'),('本机 Codex 登录态','codex'),('可选 API 模型','api')]: self.campaign_provider.addItem(label,value)
        controls.addWidget(self.campaign_provider); layout.addLayout(controls)
        self.campaign_goal=QLineEdit(); self.campaign_goal.setPlaceholderText('可选：本次想强调的功能、结果或目标观众'); layout.addWidget(self.campaign_goal)
        bar=QHBoxLayout(); self.campaign_generate=button('一键生成三平台方案',self.start_campaign,True); self.campaign_generate.setMinimumHeight(34); self.campaign_generate.setStyleSheet('font-size:16px;font-weight:600;')
        bar.addWidget(self.campaign_generate,2); self.campaign_cancel=button('取消本次生成',self.cancel_campaign); self.campaign_cancel.setEnabled(False); bar.addWidget(self.campaign_cancel)
        self.campaign_history=QComboBox(); self.campaign_history.setPlaceholderText('查看已生成的方案'); self.campaign_history.currentIndexChanged.connect(self.select_campaign); bar.addWidget(self.campaign_history,1); layout.addLayout(bar)
        self.ai_availability=QLabel('正在检查本机 Codex；API 模型为可选项。'); self.ai_availability.setWordWrap(True);self.ai_availability.setObjectName('muted'); layout.addWidget(self.ai_availability)
        progressrow=QHBoxLayout(); self.campaign_stage=QLabel('等待生成'); self.campaign_stage.setMinimumWidth(180);self.campaign_stage.setMaximumWidth(620);self.campaign_stage.setWordWrap(True); self.campaign_progress=QProgressBar(); self.campaign_progress.setRange(0,100); self.campaign_progress.setValue(0); progressrow.addWidget(self.campaign_stage); progressrow.addWidget(self.campaign_progress,1); layout.addLayout(progressrow)
        scope_row=QHBoxLayout();self.campaign_scope=QLabel('自动完成音轨转写与画面分析；只展示真实查询和分析范围。'); self.campaign_scope.setWordWrap(True); self.campaign_scope.setObjectName('muted');scope_row.addWidget(self.campaign_scope,1)
        self.speech_button=button('查看完整口播…',self.show_speech);self.speech_button.setEnabled(False);scope_row.addWidget(self.speech_button);layout.addLayout(scope_row)
        self.campaign_tabs=QTabWidget()
        self.opportunities_view=QTextBrowser(); self.opportunities_view.setOpenExternalLinks(False); self.opportunities_view.anchorClicked.connect(lambda url:QDesktopServices.openUrl(url) if url.scheme() in ('https','http') else None)
        self.opportunities_view.setPlainText('生成后显示借势方向、真实来源链接和查询时间。'); self.campaign_tabs.addTab(self.opportunities_view,'1  借势方向与来源')
        self.fit_view=QTextEdit(); self.fit_view.setReadOnly(True); self.fit_view.setPlaceholderText('生成后显示对应视频片段、功能或结果，以及适配理由与限制。'); self.campaign_tabs.addTab(self.fit_view,'2  素材适配理由')
        self.campaign_fields={}
        for platform,label in [('bilibili','3  B站方案'),('douyin','4  抖音方案'),('xiaohongshu','5  小红书方案')]:
            page=QWidget(); form=QFormLayout(page); form.setContentsMargins(16,18,16,16);form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            title=QComboBox(); title.setPlaceholderText('生成后选择标题候选'); caption=QTextEdit(); caption.setReadOnly(True);caption.setMinimumHeight(90);caption.setMaximumHeight(160);caption.setPlaceholderText('生成后的简介或短配文')
            tags=QLineEdit(); tags.setReadOnly(True); tags.setPlaceholderText('候选话题 / TAG，核验状态与生成结果一并保留')
            fields={'title':title,'caption':caption,'tags':tags}
            form.addRow('候选标题' if platform!='douyin' else '作品标题',title)
            if platform=='douyin':
                hook=QLineEdit();hook.setReadOnly(True);hook.setPlaceholderText('首句钩子');fields['hook']=hook;form.addRow('首句钩子',hook)
            form.addRow('视频简介' if platform=='bilibili' else '短配文',caption)
            form.addRow('投稿 TAG' if platform=='bilibili' else '# 话题',tags)
            if platform=='bilibili':
                category=QLineEdit();category.setReadOnly(True);category.setPlaceholderText('文字分区建议，发布前核对；不自动推断分区 ID');fields['category']=category;form.addRow('分区建议',category)
            if platform=='xiaohongshu':
                search=QLineEdit();search.setReadOnly(True);search.setPlaceholderText('用于搜索识别的关键词，独立于话题标签');fields['search']=search;form.addRow('搜索关键词',search)
            fit=QTextEdit();fit.setReadOnly(True);fit.setMinimumHeight(80);fit.setMaximumHeight(120);fields['fit']=fit;form.addRow('适配说明',fit)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page)
            self.campaign_fields[platform]=fields; self.campaign_tabs.addTab(scroll,label)
        layout.addWidget(self.campaign_tabs,1)
        footer=QHBoxLayout(); self.campaign_save=button('保存所选标题到三平台文案',lambda:self.save_campaign_selection(False)); self.campaign_save.setEnabled(False)
        self.campaign_queue=button('保存并加入抖音草稿',lambda:self.save_campaign_selection(True),True); self.campaign_queue.setEnabled(False)
        footer.addWidget(self.campaign_save); footer.addWidget(self.campaign_queue); layout.addLayout(footer)
        note=QLabel('生成完成会自动保存三个平台的第一候选为本地文案。B站仅保存本地；小红书仅生成文案，由本人手动发布。更多修改请到「文案与证据」。'); note.setWordWrap(True);note.setObjectName('muted');layout.addWidget(note)

    @staticmethod
    def speech_timestamp(value):
        try:seconds=max(0,float(value))
        except (TypeError,ValueError):return '时间未知'
        millis=round(seconds*1000);hours,rest=divmod(millis,3600000);minutes,rest=divmod(rest,60000);secs,ms=divmod(rest,1000)
        return f'{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}'

    def speech_texts(self):
        media=self._speech_media or {};speech=media.get('speech')
        if not isinstance(speech,dict):
            return {'status':'旧方案：没有自动全音轨转写记录','coverage':'此记录仅保留原来的画面 / 字幕范围，不能视为完整口播分析。','text':'','timed':'','uncertain':'没有可用的完整 ASR 置信信息。','warnings':'\n'.join(str(x) for x in media.get('warnings',[])),'speech':None}
        segments=speech.get('segments') or [];uncertain_indexes=set(speech.get('uncertain_segments') or [])
        full=speech.get('text') or '\n'.join(str(segment.get('text','')) for segment in segments)
        timed=[];uncertain=[]
        for index,segment in enumerate(segments):
            stamp=f"[{self.speech_timestamp(segment.get('start'))} → {self.speech_timestamp(segment.get('end'))}]"
            line=stamp+' '+str(segment.get('text',''));timed.append(line)
            if segment.get('uncertain') or index in uncertain_indexes:
                scores=[]
                if segment.get('avg_logprob') is not None:scores.append('识别评分 avg_logprob='+str(segment['avg_logprob']))
                if segment.get('no_speech_prob') is not None:scores.append('无人声概率 no_speech_prob='+str(segment['no_speech_prob']))
                uncertain.append(line+('\n'+'；'.join(scores) if scores else '')+'\n请结合音频 / 画面复核品牌、命令和数值，不将机器评分当准确率。')
        status=speech.get('status')
        if speech.get('complete') is not True:label='转写尚未完整 · 不能视为完整口播'
        elif status=='no_audio':label='视频无音轨 · 按画面准备方案';full='该视频没有音轨，无需补写空口播。';timed=[]
        elif status=='no_speech':label='全音轨已检查 · 未识别出可用人声';full='本次没有识别出可用人声，方案应按实际画面与已有事实生成。';timed=[]
        elif speech.get('complete') is True:label='全音轨处理完成 · 机器转写需复核'
        else:label='转写尚未完整 · 不能视为完整口播'
        duration=speech.get('audio_duration',0);processed=speech.get('processed_duration',0)
        coverage=f"处理覆盖：{processed} / {duration} 秒。模型：{speech.get('model','未提供')}；设备：{speech.get('device') or '未提供'}；缓存：{'命中' if speech.get('cache_hit') else '本次处理'}。\ncomplete 只表示整段音轨处理完，不保证逐字准确。需复核片段：{len(uncertain)}。"
        warnings=list(dict.fromkeys(str(x) for x in list(media.get('warnings',[]))+list(speech.get('warnings',[]))))
        return {'status':label,'coverage':coverage,'text':str(full),'timed':'\n\n'.join(timed),'uncertain':'\n\n'.join(uncertain) or '没有被引擎标记的低置信片段；这不代表逐字人工核验。','warnings':'\n'.join(warnings),'speech':speech}

    def show_speech(self):
        if self.speech_dialog is None:
            dialog=QDialog(self);dialog.setWindowTitle('完整口播 · 转写与复核');dialog.resize(1000,750);dialog.setMinimumSize(760,580)
            layout=QVBoxLayout(dialog);self.speech_status=QLabel();self.speech_status.setObjectName('pageTitle');self.speech_status.setWordWrap(True);layout.addWidget(self.speech_status)
            self.speech_coverage=QLabel();self.speech_coverage.setWordWrap(True);layout.addWidget(self.speech_coverage)
            controls=QHBoxLayout();self.speech_query=QLineEdit();self.speech_query.setPlaceholderText('在当前转写页搜索文字');controls.addWidget(self.speech_query,1);controls.addWidget(button('查找下一处',self.find_speech));layout.addLayout(controls)
            self.speech_tabs=QTabWidget();self.speech_views={}
            for key,label in [('text','转写全文'),('timed','带时间戳全文'),('uncertain','低置信片段'),('warnings','处理说明与限制')]:
                view=QTextEdit();view.setReadOnly(True);self.speech_tabs.addTab(view,label);self.speech_views[key]=view
            layout.addWidget(self.speech_tabs,1)
            actions=QHBoxLayout();self.speech_copy_plain=button('复制全文',lambda:self.copy_speech(False));self.speech_copy_timed=button('复制带时间戳全文',lambda:self.copy_speech(True));actions.addWidget(self.speech_copy_plain);actions.addWidget(self.speech_copy_timed)
            self.speech_file_buttons={}
            for kind in ('txt','srt','json'):
                control=button('打开 '+kind.upper(),lambda checked=False,k=kind:self.open_speech_file(k));actions.addWidget(control);self.speech_file_buttons[kind]=control
            layout.addLayout(actions);self.speech_dialog=dialog
        self.update_speech_dialog();self.speech_dialog.show();self.speech_dialog.raise_();self.speech_dialog.activateWindow()

    def update_speech_dialog(self):
        if self.speech_dialog is None:return
        data=self.speech_texts();self.speech_status.setText(data['status']);self.speech_coverage.setText(data['coverage'])
        for key,view in self.speech_views.items():view.setPlainText(data[key] or ('没有完整口播记录。' if key in ('text','timed') else '无额外说明。'))
        available=isinstance(data['speech'],dict) and data['speech'].get('status')=='complete' and data['speech'].get('complete') is True
        self.speech_copy_plain.setEnabled(available and bool(data['text']));self.speech_copy_timed.setEnabled(available and bool(data['timed']))
        for kind,control in self.speech_file_buttons.items():control.setEnabled(bool((data['speech'] or {}).get(kind+'_path')))

    def copy_speech(self,timestamps=False):
        data=self.speech_texts()
        if not isinstance(data['speech'],dict) or data['speech'].get('status')!='complete' or data['speech'].get('complete') is not True:return
        text=data['timed'] if timestamps else data['text']
        if text:QApplication.clipboard().setText(text)

    def find_speech(self):
        query=self.speech_query.text()
        if not query:return
        view=self.speech_tabs.currentWidget()
        if not view.find(query):
            cursor=view.textCursor();cursor.setPosition(0);view.setTextCursor(cursor);view.find(query)

    def open_speech_file(self,kind):
        speech=self.speech_texts()['speech'] or {};value=speech.get(kind+'_path')
        if not value:return
        path=Path(value).resolve();allowed=(self.service.paths.data_dir.resolve(),(self.service.paths.project_root/'state'/'asr_cache').resolve())
        if path.suffix.lower()!='.'+kind or not path.is_file() or not any(path.is_relative_to(root) for root in allowed):return self.error('转写文件不存在或不在本方案的数据目录内。')
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def refresh_ai_status(self):
        if self._closing:return
        def done(status):
            codex=status.get('codex',{}); api=status.get('api',{})
            self.ai_availability.setText('本机 Codex：'+('已登录，可直接生成' if codex.get('available') and codex.get('logged_in') else str(codex.get('message','尚未就绪，请先在本机 Codex 完成登录')))+'；API 模型：'+('已配置' if api.get('configured') else '未配置（可选，不影响已登录 Codex）'))
            self.ai_settings_status.setText(self.ai_availability.text())
        self.busy(self.service.ai_status,done,'正在检查本机 AI 可用性…')

    def start_campaign(self):
        asset_id=self.campaign_asset.currentData()
        if not asset_id:return self.error('请先导入或选择视频。')
        payload={'asset_id':asset_id,'provider':self.campaign_provider.currentData(),'goal':self.campaign_goal.text().strip()}
        self.campaign_generate.setEnabled(False)
        def started(record):
            if record.get('asset_id')!=self.campaign_asset.currentData():
                self.campaign_generate.setEnabled(True);self.refresh_workspace();return
            self._campaign_id=record['id'];self._rendered_campaign_id=None;self.render_campaign(record)
        self.busy(lambda:self.service.start_campaign(payload),started,'正在创建一键 AI 方案…',on_error=lambda:self.campaign_generate.setEnabled(True))

    def cancel_campaign(self):
        if self._campaign_id:self.busy(lambda:self.service.cancel_campaign(self._campaign_id),self.render_campaign,'正在取消 AI 生成，不涉及平台发布…')

    def select_campaign(self):
        record_id=self.campaign_history.currentData()
        if record_id:
            try:
                record=self.service.get_campaign(record_id)
                asset_index=self.campaign_asset.findData(record.get('asset_id'))
                if asset_index<0:
                    self.clear_campaign_result();return self.error('该历史方案的素材未注册，不能作为当前视频方案使用。')
                self.campaign_asset.blockSignals(True);self.campaign_asset.setCurrentIndex(asset_index);self.campaign_asset.blockSignals(False)
                self._campaign_id=record_id;self._rendered_campaign_id=None;self.render_campaign(record)
            except Exception as exc:self.error('读取历史方案失败：'+str(exc))

    def clear_campaign_result(self):
        self._campaign_id=None;self._rendered_campaign_id=None;self._campaign_result=None
        self._speech_media={};self.speech_button.setEnabled(False);self.update_speech_dialog()
        self.campaign_progress.setValue(0);self.campaign_stage.setText('等待生成')
        self.campaign_scope.setText('当前视频尚无已选方案，请一键生成；不会套用其他视频的结果。')
        self.opportunities_view.setPlainText('生成后显示当前视频的借势方向、真实来源链接和查询时间。');self.fit_view.clear()
        for fields in self.campaign_fields.values():
            for control in fields.values():control.clear()
        self.campaign_save.setEnabled(False);self.campaign_queue.setEnabled(False);self.campaign_cancel.setEnabled(False);self.campaign_generate.setEnabled(True)

    def sync_campaign_history(self,records):
        asset_id=self.campaign_asset.currentData()
        current=next((c for c in records if c['id']==self._campaign_id),None)
        if current and current.get('asset_id')!=asset_id:self.clear_campaign_result()
        matching=sorted((c for c in records if c.get('asset_id')==asset_id),key=lambda c:(str(c.get('created_at','')),str(c.get('updated_at',''))),reverse=True)
        if not self._campaign_id:
            latest=next((c for c in matching if c.get('status') in ('queued','running','complete')),None)
            if latest:self._campaign_id=latest['id']
        self.campaign_history.blockSignals(True);self.campaign_history.clear()
        names={a['id']:a['name'] for a in self._asset_rows}
        for record in sorted(records,key=lambda c:(str(c.get('created_at','')),str(c.get('updated_at',''))),reverse=True):
            label=names.get(record.get('asset_id'),'未注册素材')+' · '+{'complete':'已完成','running':'生成中','queued':'等待中','failed':'失败','cancelled':'已取消'}.get(record.get('status'),str(record.get('status','')))+' · '+str(record.get('created_at',''))[:19]
            self.campaign_history.addItem(label,record['id'])
            self.campaign_history.setItemData(self.campaign_history.count()-1,label,Qt.ItemDataRole.ToolTipRole)
        self.campaign_history.setCurrentIndex(self.campaign_history.findData(self._campaign_id));self.campaign_history.blockSignals(False)
        return next((c for c in matching if c['id']==self._campaign_id),None)

    def campaign_asset_changed(self):
        if not hasattr(self,'campaign_history'):return
        self.clear_campaign_result()
        try:
            record=self.sync_campaign_history(self.service.campaigns())
            if record:self.render_campaign(record,refresh_workspace=False)
        except Exception as exc:self.campaign_scope.setText('方案记录读取失败：'+str(exc))

    def poll_campaign(self):
        if self._closing or not self._campaign_id:return
        try:self.render_campaign(self.service.get_campaign(self._campaign_id))
        except Exception as exc:self.campaign_stage.setText('方案读取失败：'+str(exc)[:100])

    def render_campaign(self,record,refresh_workspace=True):
        stage={'audio':'提取音轨','transcribe':'完整语音转写','media':'结合画面与完整口播分析','research':'查询公开热点','ai':'AI 搜索与匹配生成','validate':'校验并保存文案','complete':'方案已完成'}.get(record.get('stage'),record.get('stage','等待执行'))
        status=record.get('status','queued'); running=status in ('queued','running')
        self.campaign_stage.setText(stage+' · '+str(record.get('message',''))[:85]);self.campaign_progress.setValue(max(0,min(100,int(record.get('progress',0)))))
        self.campaign_generate.setEnabled(not running);self.campaign_cancel.setEnabled(running)
        result=record.get('result'); ready=status=='complete' and isinstance(result,dict)
        self.campaign_save.setEnabled(ready);self.campaign_queue.setEnabled(ready)
        if not ready:
            if status in ('failed','cancelled'):
                self.campaign_scope.setText(('生成失败：' if status=='failed' else '生成已取消：')+str(record.get('message','')))
            if self._rendered_campaign_id!=record['id']:
                self._speech_media={};self.speech_button.setEnabled(False);self.update_speech_dialog()
                self._campaign_result=None;self.opportunities_view.setPlainText('正在生成；结果只在真实返回后展示。');self.fit_view.clear()
                for fields in self.campaign_fields.values():
                    for key,control in fields.items():
                        if key=='title':control.clear()
                        else:control.clear()
            return
        if self._rendered_campaign_id==record['id']:return
        self._rendered_campaign_id=record['id'];self._campaign_result=result
        media=result.get('media') or {};scope=str(media.get('analysis_scope','未返回媒体分析范围'))
        self._speech_media=media;self.speech_button.setEnabled(True);self.update_speech_dialog()
        scope={'sampled_frames_and_full_audio_transcript':'抽样画面＋全音轨机器转写；转写需复核','sampled_frames_no_audio':'抽样画面；视频无音轨','sampled_frames_no_speech':'抽样画面；全音轨检查未识别出可用人声','sampled_frames_and_supplied_subtitles':'旧分析：抽样画面与提供的字幕；未完成自动全音轨转写'}.get(scope,scope)
        if isinstance(media.get('speech'),dict) and media['speech'].get('complete') is not True:scope='转写尚未完整；该记录不能视为全音轨分析，请检查生成错误'
        if not isinstance(media.get('speech'),dict) and not scope.startswith('旧分析'):scope='旧分析：'+scope+'；没有自动全音轨转写记录'
        self.campaign_scope.setText('分析范围：'+scope+'。'+str(result.get('summary',''))[:240])
        self.campaign_scope.setToolTip('；'.join(str(x) for x in media.get('warnings',[])))
        sources={str(e['id']):e for e in result.get('sources',[]) if isinstance(e,dict) and e.get('id')}
        parts=[]
        for opportunity in result.get('opportunities',[]):
            parts.append('<h3>'+escape(PLATFORMS.get(opportunity.get('platform'),str(opportunity.get('platform','')))+' · '+str(opportunity.get('title','')))+'</h3>')
            parts.append('<p>'+escape(str(opportunity.get('why_relevant','')))+'</p><p>查询时间：'+escape(str(opportunity.get('query_time','未提供')))+'</p>')
            for evidence_id in opportunity.get('evidence_ids',[]):
                source=sources.get(str(evidence_id),{});url=str(source.get('source_url',''))
                if QUrl(url).scheme() in ('https','http'):
                    verification='AI 搜索来源，待独立复核原页面' if source.get('verification')=='ai_researched' else '公开来源记录，请核对原链接与查询时间'
                    parts.append('<p><a href="'+escape(url,quote=True)+'">'+escape(str(source.get('title',url)))+'</a><br/>来源查询 / 抓取时间：'+escape(str(source.get('fetched_at',source.get('queried_at','未提供'))))+'<br/>'+escape(verification)+'</p>')
        if not parts:
            parts=['<h3>本次不借势实时热点</h3><p>'+escape(str(result.get('no_trend_reason','未找到足够相关、可追溯的热点。')))+'</p><p>采用稳定搜索方向：围绕视频本身的功能、结果和自然关键词准备文案，不套无关热榜。</p>']
            search_terms=list(dict.fromkeys(term for package in result.get('packages',[]) for term in package.get('search_keywords',[])))
            if search_terms:parts.append('<p>搜索关键词：'+escape('、'.join(search_terms))+'</p>')
        self.opportunities_view.setHtml(''.join(parts))
        fits=[];verdicts={'direct':'直接相关','connection':'有真实连接点','not_fit':'不适合借势','needs_extra':'需要补拍 / 补充证据'}
        opportunity_names={o.get('id'):o.get('title','素材适配') for o in result.get('opportunities',[])}
        for fit in result.get('fit_assessments',[]):
            fits+=['【'+str(opportunity_names.get(fit.get('opportunity_id'),'素材适配'))+'】'+verdicts.get(fit.get('verdict'),str(fit.get('verdict',''))),str(fit.get('reason',''))]
            for segment in fit.get('segments',[]):
                basis={'sampled_frame':'抽样画面','speech':'全音轨机器转写','subtitle':'提供的字幕','user_fact':'用户事实'}.get(segment.get('evidence_type'),str(segment.get('evidence_type','')))
                fits.append(f"片段 {segment.get('start',0)}–{segment.get('end',0)} 秒 [{basis}]：{segment.get('observation','')}")
            if fit.get('supports_features'):fits.append('对应功能 / 结果：'+'；'.join(fit['supports_features']))
            if fit.get('limits'):fits.append('限制：'+'；'.join(fit['limits']))
            fits.append('')
        if not fits:
            fits=['本次采用视频自身的稳定内容方向，不硬借无关热点。','视频内容摘要：'+str(result.get('summary','未提供')),'']
            for package in result.get('packages',[]):fits+=[PLATFORMS.get(package.get('platform'),str(package.get('platform','')))+'适配理由：'+str(package.get('fit_reason','未提供'))]
            fits+=['','实际媒体依据']
            timestamps=[str(frame['timestamp'])+' 秒' for frame in media.get('frames',[]) if isinstance(frame,dict) and 'timestamp' in frame]
            fits.append('实际抽样画面时间：'+('、'.join(timestamps) if timestamps else '没有可用抽帧记录，不能声称已看见未提供画面。'))
            transcript=media.get('transcript') or []
            if isinstance(media.get('speech'),dict):
                speech_data=self.speech_texts();fits+=[speech_data['status'],speech_data['coverage'],'全文与全部时间戳请点击「查看完整口播」，此处不截取口播冒充全文。']
            else:fits.append('旧记录提供的字幕区间（非完整 ASR）：'+('；'.join(str(line.get('start',''))+'–'+str(line.get('end',''))+' 秒：'+str(line.get('text','')) for line in transcript[:12]) if transcript else '未提供字幕；不声称听过声音或完成语音识别。'))
            fits.append('分析范围：'+scope)
            fits+=['限制：'+str(warning) for warning in media.get('warnings',[])]
        self.fit_view.setPlainText('\n'.join(fits))
        for package in result.get('packages',[]):
            fields=self.campaign_fields.get(package.get('platform'))
            if fields is None:continue
            titles=([package.get('title','')] if package['platform']=='douyin' else package.get('title_candidates') or [package.get('title','')])
            fields['title'].clear();fields['title'].addItems(titles);fields['title'].setCurrentIndex(max(0,fields['title'].findText(package.get('title',''))))
            fields['caption'].setPlainText(package.get('caption',''));fields['tags'].setText(('，' if package['platform']=='bilibili' else ' ').join(('#'+tag if package['platform']!='bilibili' else tag) for tag in package.get('tags',[])));fields['fit'].setPlainText(package.get('fit_reason',''))
            if 'hook' in fields:fields['hook'].setText(package.get('hook',''))
            if 'category' in fields:fields['category'].setText(package.get('category_suggestion',''))
            if 'search' in fields:fields['search'].setText('，'.join(package.get('search_keywords',[])))
        if refresh_workspace:self.refresh_workspace()

    def save_campaign_selection(self,queue_drafts=False):
        if not self._campaign_id or not self._campaign_result:return self.error('请先完成一键方案生成。')
        payload={'id':self._campaign_id,'selections':{key:self.campaign_fields[key]['title'].currentIndex() for key in ('bilibili','xiaohongshu')},'queue_drafts':queue_drafts}
        def saved(result):
            self.refresh_workspace();self.banner.setText(f"已保存 {result.get('count',0)} 个平台文案；创建 {len(result.get('jobs',[]))} 个草稿任务。B站仅本地保存，未公开发布。")
        self.busy(lambda:self.service.save_campaign(payload),saved,'正在保存所选标题及草稿任务…')

    def page(self, title, subtitle):
        widget = QWidget(); layout = QVBoxLayout(widget); layout.setContentsMargins(0,0,0,0); layout.setSpacing(14)
        heading = QLabel(title); heading.setObjectName('pageTitle'); layout.addWidget(heading)
        hint = QLabel(subtitle); hint.setWordWrap(True); hint.setObjectName('muted'); layout.addWidget(hint)
        self.stack.addWidget(widget)
        return layout

    def busy(self, operation, success=None, message='正在处理…', on_error=None):
        if self._closing: return
        self.banner.setText(message)
        worker = Work(operation); self._workers.add(worker)
        def done(result):
            self._workers.discard(worker)
            if self._closing: return
            self.banner.setText('操作完成 · 请查看记录与平台返回状态。')
            if success:
                try: success(result)
                except Exception as exc: self.error(str(exc))
        def failed(error):
            self._workers.discard(worker)
            if not self._closing:
                if on_error:on_error()
                self.error(error)
        worker.signals.done.connect(done); worker.signals.failed.connect(failed)
        self.pool.start(worker)

    def error(self, message):
        self.banner.setText('操作未完成 · '+message[:160])
        QMessageBox.warning(self, '操作未完成', message)

    def fill_table(self, widget, rows, columns):
        selected = widget.currentRow(); widget.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, column in enumerate(columns): widget.setItem(r,c,QTableWidgetItem(str(column(row))))
        if rows: widget.selectRow(min(max(selected,0),len(rows)-1))

    def build_assets(self):
        layout = self.page('素材库', '注册视频后即可一键分析画面与完整口播；摘要、事实与人群均为可选补充，原文件保留原位。')
        bar = QHBoxLayout(); bar.addWidget(button('＋ 导入视频',self.import_asset,True)); bar.addWidget(button('刷新素材',self.refresh_workspace)); bar.addStretch(); layout.addLayout(bar)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.asset_table = table(['素材','大小','内容摘要'])
        self.asset_table.itemSelectionChanged.connect(self.load_asset)
        split.addWidget(self.asset_table)
        editor = QGroupBox('素材事实'); form = QFormLayout(editor)
        self.asset_name = QLabel('先导入或选择一条视频'); self.asset_name.setWordWrap(True); self.asset_name.setMaximumHeight(55)
        self.summary = QTextEdit(); self.summary.setMaximumHeight(100)
        self.facts = QTextEdit(); self.facts.setPlaceholderText('每行一项：画面或口播能够证明的事实'); self.facts.setMaximumHeight(135)
        self.keywords = QLineEdit(); self.keywords.setPlaceholderText('逗号分隔，例如：三维建模，工业设计')
        self.audience = QLineEdit(); self.audience.setPlaceholderText('这条视频适合谁看')
        form.addRow(self.asset_name); form.addRow('摘要', self.summary); form.addRow('事实',self.facts); form.addRow('关键词',self.keywords); form.addRow('目标人群',self.audience)
        form.addRow(button('保存素材资料',self.save_asset,True)); split.addWidget(editor); split.setSizes([650,400]); layout.addWidget(split,1)

    def selected_asset(self):
        i = self.asset_table.currentRow()
        return self._asset_rows[i] if 0 <= i < len(self._asset_rows) else None

    def import_asset(self):
        path, _ = QFileDialog.getOpenFileName(self,'导入视频','','视频 (*.mp4 *.mov *.mkv *.webm *.avi *.flv);;所有文件 (*)')
        if path:
            def imported(asset):
                self.refresh_workspace()
                self.campaign_asset.setCurrentIndex(self.campaign_asset.findData(asset['id']))
                self.ops_asset.setCurrentIndex(self.ops_asset.findData(asset['id']))
                for row,record in enumerate(self._asset_rows):
                    if record['id']==asset['id']:
                        self.asset_table.selectRow(row)
                        self.load_asset()
                        break
            self.busy(lambda:self.service.add_asset({'path':path}),imported,'正在计算素材摘要并注册…')

    def load_asset(self):
        asset = self.selected_asset()
        if not asset: return
        self.asset_name.setText(asset['name']); self.summary.setPlainText(asset.get('summary','')); self.facts.setPlainText('\n'.join(asset.get('facts',[])))
        self.keywords.setText('，'.join(asset.get('keywords',[]))); self.audience.setText(asset.get('audience',''))

    def save_asset(self):
        asset = self.selected_asset()
        if not asset: return self.error('请先导入或选择视频。')
        payload={'summary':self.summary.toPlainText(),'facts':self.facts.toPlainText().splitlines(),'keywords':self.split_tags(self.keywords.text()),'audience':self.audience.text()}
        self.busy(lambda:self.service.update_asset(asset['id'],payload),lambda _:self.refresh_workspace())

    @staticmethod
    def split_tags(text): return [s.strip().strip('#') for s in text.replace('，',',').split(',') if s.strip().strip('#')]

    def build_operations(self):
        layout = self.page('内容运营', '查真实热点、核对素材关联，再编辑标题、简介与标签。没有相关热点时，使用视频本身的关键词。')
        bar=QHBoxLayout(); self.ops_asset=QComboBox(); self.ops_asset.setPlaceholderText('先从素材库导入视频'); bar.addWidget(QLabel('素材')); bar.addWidget(self.ops_asset,1)
        self.trend_platform=QComboBox()
        for key,name in PLATFORMS.items(): self.trend_platform.addItem(name,key)
        bar.addWidget(self.trend_platform); self.trend_keyword=QLineEdit(); self.trend_keyword.setPlaceholderText('筛选热点关键词'); bar.addWidget(self.trend_keyword)
        bar.addWidget(button('获取热榜',self.fetch_trends,True)); layout.addLayout(bar)
        tools=QHBoxLayout()
        for label,slot in [('导入证据 JSON',self.import_evidence),('导出 AI 文案任务',self.export_brief),('导入文案 JSON',self.import_packages),('使用已配置模型生成',self.generate)]: tools.addWidget(button(label,slot))
        tools.addStretch(); layout.addLayout(tools)
        split=QSplitter(Qt.Orientation.Vertical)
        self.evidence_table=table(['平台','证据标题','来源与抓取时间']); split.addWidget(self.evidence_table)
        group=QGroupBox('三平台文案编辑'); form=QGridLayout(group)
        form.setColumnStretch(0,0); form.setColumnStretch(1,4); form.setColumnStretch(2,1); form.setColumnMinimumWidth(0,88)
        self.draft_choice=QComboBox(); self.draft_choice.setPlaceholderText('暂无文案：可手工编辑后保存，或导入 AI 文案 JSON'); self.draft_choice.currentIndexChanged.connect(self.load_draft)
        self.draft_platform=QComboBox()
        for key,name in PLATFORMS.items(): self.draft_platform.addItem(name,key)
        self.draft_platform.currentIndexChanged.connect(lambda _:setattr(self,'_draft_id',None))
        self.draft_platform.currentIndexChanged.connect(lambda _:self.update_publish_controls())
        self.title_edit=QLineEdit(); self.caption_edit=QTextEdit(); self.caption_edit.setMaximumHeight(110)
        self.tags_edit=QLineEdit(); self.tags_edit.setPlaceholderText('逗号分隔；投稿标签与动态话题分开核对')
        self.fit_edit=QLineEdit(); self.fit_edit.setPlaceholderText('说明视频中哪一处支持相关热点；无关不借势')
        form.addWidget(QLabel('已有文案'),0,0); form.addWidget(self.draft_choice,0,1); form.addWidget(self.draft_platform,0,2)
        form.addWidget(QLabel('标题'),1,0); form.addWidget(self.title_edit,1,1,1,2)
        form.addWidget(QLabel('简介 / 正文'),2,0); form.addWidget(self.caption_edit,2,1,1,2)
        form.addWidget(QLabel('候选标签'),3,0); form.addWidget(self.tags_edit,3,1,1,2)
        form.addWidget(QLabel('相关性说明'),4,0); form.addWidget(self.fit_edit,4,1,1,2)
        actions=QHBoxLayout(); actions.addWidget(button('保存文案版本',self.save_draft,True)); self.visibility=QComboBox()
        for label,value in [('草稿（默认）','draft'),('仅自己可见','private'),('公开发布','public')]: self.visibility.addItem(label,value)
        actions.addWidget(self.visibility); self.publish_account=QLineEdit('creator'); self.publish_account.setMaximumWidth(115); self.publish_account.setToolTip('执行此文案的本地账号名称'); actions.addWidget(self.publish_account)
        self.draft_button=button('加入草稿任务',lambda:self.enqueue_selected('draft')); actions.addWidget(self.draft_button)
        publish=button('按选定范围发布…',lambda:self.enqueue_selected('publish')); publish.setObjectName('danger'); actions.addWidget(publish); self.publish_button=publish
        self.manual_export=button('导出小红书人工发布文案',self.export_manual_copy); actions.addWidget(self.manual_export)
        self.manual_note=QLabel('小红书仅提供文案，请在官方App或网页手动上传发布。'); actions.addWidget(self.manual_note)
        self.update_publish_controls()
        form.addLayout(actions,5,0,1,3); split.addWidget(group); split.setSizes([150,430]); layout.addWidget(split,1)

    def fetch_trends(self):
        platform=self.trend_platform.currentData(); keyword=self.trend_keyword.text()
        self.busy(lambda:self.service.fetch_trends(platform,keyword),lambda result:(self.refresh_workspace(),self.banner.setText(str(result.get('message','热榜已更新；请核对来源时间。')))),'正在查询公开热榜…')

    def read_json(self, caption):
        path,_=QFileDialog.getOpenFileName(self,caption,'','JSON (*.json)')
        if not path: return None
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(data,dict): raise ValueError('顶层必须是JSON对象，请按导出任务中的schema组织字段')
            return data
        except Exception as exc: self.error('JSON文件无法读取：'+str(exc)); return None

    def import_evidence(self):
        data=self.read_json('导入公开证据 JSON')
        if data is not None: self.busy(lambda:self.service.import_evidence(data),lambda _:self.refresh_workspace())

    def export_brief(self):
        asset_id=self.ops_asset.currentData()
        if not asset_id: return self.error('请先注册素材。')
        path,_=QFileDialog.getSaveFileName(self,'导出供外部 AI 使用的文案任务','内容运营任务.json','JSON (*.json)')
        if path:
            def write(result): Path(path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); self.banner.setText('已导出素材事实与公开证据；没有导出视频或账号凭据。')
            self.busy(lambda:self.service.export_brief(asset_id),write)

    def import_packages(self):
        data=self.read_json('导入 AI 文案成品 JSON')
        if data is not None:
            if not data.get('asset_id'): data['asset_id']=self.ops_asset.currentData()
            self.busy(lambda:self.service.import_packages(data),lambda _:self.refresh_workspace())

    def generate(self):
        asset_id=self.ops_asset.currentData()
        if not asset_id: return self.error('请先选择素材。事实摘要是可选补充。')
        self.busy(lambda:self.service.generate({'asset_id':asset_id}),lambda _:self.refresh_workspace(),'正在基于素材事实与公开证据生成文案…')

    def load_draft(self):
        record=self.draft_choice.currentData()
        if not record: return
        self.draft_platform.blockSignals(True); self.draft_platform.setCurrentIndex(max(0,self.draft_platform.findData(record['platform']))); self.draft_platform.blockSignals(False)
        self._draft_id=record['id']; self.title_edit.setText(record.get('title','')); self.caption_edit.setPlainText(record.get('caption','')); self.tags_edit.setText('，'.join(record.get('tags',[]))); self.fit_edit.setText(record.get('fit_reason',''))
        idx=self.ops_asset.findData(record.get('asset_id')); self.ops_asset.setCurrentIndex(idx)
        is_bili=record['platform']=='bilibili'
        self.update_publish_controls()

    def update_publish_controls(self):
        if not hasattr(self,'manual_export'):return
        platform=self.draft_platform.currentData();manual=platform=='xiaohongshu'
        for control in (self.draft_button,self.publish_button,self.visibility,self.publish_account):control.setVisible(not manual)
        self.draft_button.setEnabled(platform=='douyin')
        self.manual_export.setVisible(manual);self.manual_note.setVisible(manual)

    def export_manual_copy(self):
        title=self.title_edit.text().strip();caption=self.caption_edit.toPlainText().strip()
        if not title:return self.error('请先选择或填写小红书标题。')
        tags=self.split_tags(self.tags_edit.text())
        text=title+'\n\n'+caption+'\n\n'+' '.join('#'+t.lstrip('#') for t in tags)
        record=self.draft_choice.currentData() or {}
        if record.get('search_keywords'):text+='\n\n搜索关键词：'+'、'.join(record['search_keywords'])
        path,_=QFileDialog.getSaveFileName(self,'导出小红书人工发布文案','小红书_人工发布文案.txt','文本 (*.txt)')
        if path:
            Path(path).write_text(text,encoding='utf-8-sig')
            self.banner.setText('已导出文案，请本人在小红书官方App或网页选择视频并发布。')

    def save_draft(self):
        asset_id=self.ops_asset.currentData()
        if not asset_id: return self.error('请先选择素材。')
        old=self.draft_choice.currentData() or {}
        payload={'asset_id':asset_id,'platform':self.draft_platform.currentData(),'title':self.title_edit.text(),'caption':self.caption_edit.toPlainText(),'tags':self.split_tags(self.tags_edit.text()),'fit_reason':self.fit_edit.text(),'visibility':'draft','evidence_ids':old.get('evidence_ids',[]) if old.get('asset_id')==asset_id else []}
        def saved(result):
            self._draft_id=result['id']; self.refresh_workspace()
        self.busy(lambda:self.service.save_draft(payload),saved)

    def enqueue_selected(self, action):
        if self.draft_platform.currentData()=='xiaohongshu':return self.error('小红书已改为人工发布，请导出文案。')
        record=self.draft_choice.currentData()
        if not record or not self._draft_id: return self.error('先保存并选择要执行的文案版本。编辑后的内容请先保存。')
        if record.get('asset_id')!=self.ops_asset.currentData(): return self.error('所选素材与文案版本不一致，请先保存该素材的文案版本。')
        if (self.title_edit.text()!=record.get('title','') or self.caption_edit.toPlainText()!=record.get('caption','') or self.split_tags(self.tags_edit.text())!=record.get('tags',[]) or self.fit_edit.text()!=record.get('fit_reason','')):
            return self.error('文案有未保存修改。请先保存文案版本，再创建任务。')
        account=self.publish_account.text().strip() or 'creator'
        visibility='draft' if action=='draft' else self.visibility.currentData()
        if action=='publish':
            if visibility=='draft':
                QMessageBox.information(self,'请选择可见范围','发布前请选择“仅自己可见”或“公开发布”。当前默认是草稿。'); return
            answer=QMessageBox.question(self,'确认提交发布',f"平台：{PLATFORMS[record['platform']]}\n账号：{account}\n标题：{record.get('title','')}\n可见范围：{'公开' if visibility=='public' else '仅自己可见'}\n\n将提交一次。提交受理不等于审核通过；结果未知时不能自动重发。",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes: return
        payload={'platform':record['platform'],'account':account,'action':action,'asset_id':record['asset_id'],'draft_id':record['id'],'visibility':visibility,'idempotency_key':uuid.uuid4().hex}
        self.busy(lambda:self.service.create_job(payload),lambda _:(self.refresh_jobs(),self.navigation.setCurrentRow(4)),'正在建立任务快照…')

    def build_accounts(self):
        layout=self.page('账号与授权','扫码或验证码由本人完成。专用浏览器保留各平台登录状态，不读取其他浏览器账号。')
        group=QGroupBox('当前账号'); row=QHBoxLayout(group)
        self.account_platform=QComboBox()
        for key in ('bilibili','douyin'): self.account_platform.addItem(PLATFORMS[key],key)
        self.account_name=QLineEdit('creator'); self.account_name.setPlaceholderText('本地账号名称')
        row.addWidget(self.account_platform); row.addWidget(self.account_name)
        for label,action in [('扫码登录','login'),('在线检查','check'),('查询作品','query_publications'),('打开草稿核对','open_drafts')]:
            control=button(label,lambda checked=False,a=action:self.account_action(a),action=='login')
            if action=='open_drafts': self.open_drafts_button=control
            row.addWidget(control)
        def capabilities():
            supported=self.account_platform.currentData()!='bilibili'
            self.open_drafts_button.setEnabled(supported)
            self.open_drafts_button.setToolTip('B站请在创作中心核对稿件；此适配器没有安全草稿入口' if not supported else '在专用浏览器中核对草稿；不上传新文件')
        self.account_platform.currentIndexChanged.connect(capabilities); capabilities()
        layout.addWidget(group); self.account_table=table(['平台','账号','本地状态 / 检查结果']); layout.addWidget(self.account_table,1)
        hint=QLabel('登录会进入任务队列。出现“待本人操作”时，在任务详情查看二维码或专用浏览器；取消仅停止本地操作。'); hint.setWordWrap(True); hint.setObjectName('muted'); layout.addWidget(hint)

    def account_action(self, action):
        payload={'platform':self.account_platform.currentData(),'account':self.account_name.text().strip() or 'creator','action':action,'idempotency_key':uuid.uuid4().hex}
        self.busy(lambda:self.service.create_job(payload),lambda _:(self.refresh_jobs(),self.navigation.setCurrentRow(4)))

    def build_jobs(self):
        layout=self.page('任务队列','跟踪每次操作的证据。草稿、平台提交受理、审核与公开展示是不同状态；未知结果先人工核对。')
        bar=QHBoxLayout(); bar.addWidget(button('刷新任务',self.refresh_jobs)); bar.addWidget(button('取消所选本地任务',self.cancel_selected)); bar.addStretch(); layout.addLayout(bar)
        split=QSplitter(Qt.Orientation.Vertical); self.jobs_table=table(['平台 / 动作','账号','状态','进度','平台消息'])
        self.jobs_table.itemSelectionChanged.connect(self.load_events); split.addWidget(self.jobs_table)
        detail=QWidget(); row=QHBoxLayout(detail); row.setContentsMargins(0,0,0,0)
        self.events_view=QTextEdit(); self.events_view.setReadOnly(True); self.events_view.setPlaceholderText('选择任务查看阶段、状态与平台回执。')
        self.qr_image=QLabel('等待登录任务时\n这里显示本地二维码'); self.qr_image.setAlignment(Qt.AlignmentFlag.AlignCenter); self.qr_image.setMinimumSize(235,220); self.qr_image.setMaximumWidth(280)
        row.addWidget(self.events_view,1); row.addWidget(self.qr_image); split.addWidget(detail); split.setSizes([330,220]); layout.addWidget(split,1)

    def refresh_jobs(self):
        if self._closing: return
        try:
            self._job_rows=self.service.jobs()
            self.fill_table(self.jobs_table,self._job_rows,[lambda j:PLATFORMS.get(j.get('platform'),j.get('platform',''))+' / '+ACTIONS.get(j.get('action'),j.get('action','')),lambda j:j.get('account',''),lambda j:STATES.get(j.get('status'),j.get('status','')),lambda j:str(j.get('progress',0))+'%',lambda j:j.get('message','')])
            self.load_events()
        except Exception as exc: self.banner.setText('刷新任务失败：'+str(exc))

    def load_events(self):
        i=self.jobs_table.currentRow()
        if not 0<=i<len(self._job_rows): return
        job=self._job_rows[i]
        try:
            events=self.service.events(job['id'])
            details=[f"任务：{job['id']}",str(job.get('message',''))]+[str(e.get('message',e)) for e in events]
            if job.get('result'): details+=['\n平台回执',json.dumps(job['result'],ensure_ascii=False,indent=2)]
            self.events_view.setPlainText('\n'.join(details))
            qr_path=None
            for event in reversed(events):
                data=event.get('data',event.get('payload',event))
                if isinstance(data,dict) and data.get('qr_path'): qr_path=data['qr_path']; break
            if qr_path and Path(qr_path).is_file():
                pix=QPixmap(str(qr_path))
                if not pix.isNull(): self.qr_image.setPixmap(pix.scaled(230,230,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)); return
            self.qr_image.clear(); self.qr_image.setText('请在专用浏览器完成验证' if job.get('status')=='awaiting_user' else '选择登录任务查看二维码')
        except Exception as exc: self.events_view.setPlainText(str(exc))

    def cancel_selected(self):
        i=self.jobs_table.currentRow()
        if 0<=i<len(self._job_rows):
            job_id=self._job_rows[i]['id']; self.busy(lambda:self.service.cancel_job(job_id),lambda _:self.refresh_jobs())

    def build_ai(self):
        layout=self.page('AI 接入与设置','AI 与桌面共用任务、素材和文案服务。接口仅在本机监听，密钥不会进入任务日志。')
        codex_group=QGroupBox('默认生成方式 · 本机 Codex / ChatGPT 登录态');codex_layout=QVBoxLayout(codex_group)
        self.ai_settings_status=QLabel('使用本机已登录的 Codex 生成，无需先填写 API Key。');self.ai_settings_status.setWordWrap(True);codex_layout.addWidget(self.ai_settings_status)
        codex_layout.addWidget(button('重新检测本机 AI',self.refresh_ai_status));layout.addWidget(codex_group)
        group=QGroupBox('本机 AI 控制接口'); form=QFormLayout(group)
        self.endpoint=QLineEdit(str(self.api_info.get('endpoint',''))); self.endpoint.setReadOnly(True); form.addRow('HTTP 地址',self.endpoint)
        actions=QHBoxLayout(); actions.addWidget(button('复制地址',lambda:QApplication.clipboard().setText(self.endpoint.text()))); actions.addWidget(button('复制访问令牌',self.copy_token)); actions.addWidget(button('打开 OpenAPI',self.open_api)); actions.addStretch(); form.addRow(actions)
        hint=QLabel('访问令牌仅在你主动点击时读取并复制到本机剪贴板。请勿粘贴到公开聊天、日志或客户文件。'); hint.setWordWrap(True); hint.setObjectName('muted'); form.addRow(hint); layout.addWidget(group)
        model=QGroupBox('可选文案模型 · OpenAI 兼容接口'); form=QFormLayout(model)
        self.llm_url=QLineEdit(); self.llm_url.setPlaceholderText('https://服务地址/v1 或明确的本地 HTTP 服务')
        self.llm_model=QLineEdit(); self.llm_model.setPlaceholderText('模型名称')
        self.llm_key=QLineEdit(); self.llm_key.setEchoMode(QLineEdit.EchoMode.Password); self.llm_key.setPlaceholderText('留空保留已有 Key')
        self.clear_key=QCheckBox('清除已保存的模型 Key')
        form.addRow('Base URL',self.llm_url); form.addRow('模型',self.llm_model); form.addRow('API Key',self.llm_key); form.addRow(self.clear_key); form.addRow(button('保存模型设置',self.save_settings,True)); layout.addWidget(model)
        note=QLabel('默认从首页一键使用本机 Codex 登录态。API 模型为可选连接；JSON 导入导出属于高级备用工具。生成只使用明确的素材分析、事实与公开证据，不会直接发布视频。'); note.setWordWrap(True); note.setObjectName('muted'); layout.addWidget(note); layout.addStretch()
        try:
            config=self.service.settings().get('llm',{}); self.llm_url.setText(config.get('base_url','')); self.llm_model.setText(config.get('model',''))
            if config.get('has_api_key'): self.llm_key.setPlaceholderText('已保存 Key；留空保留，内容不回显')
        except Exception: pass

    def copy_token(self):
        try:
            token_path=Path(self.api_info.get('token_path') or self.service.paths.token_path)
            QApplication.clipboard().setText(token_path.read_text(encoding='utf-8').strip())
            self.banner.setText('令牌已复制到本机剪贴板；请勿公开。')
        except Exception as exc: self.error('无法读取本机令牌：'+str(exc))

    def open_api(self):
        url=self.api_info.get('openapi_url')
        if url: QDesktopServices.openUrl(QUrl(str(url)))
        else: self.error('HTTP服务尚未提供OpenAPI地址。')

    def save_settings(self):
        payload={'llm':{'base_url':self.llm_url.text().strip(),'model':self.llm_model.text().strip(),'api_key':self.llm_key.text(),'clear_api_key':self.clear_key.isChecked()}}
        def done(_): self.llm_key.clear(); self.clear_key.setChecked(False); self.banner.setText('模型设置已保存；Key不回显。')
        self.busy(lambda:self.service.save_settings(payload),done)

    def refresh_workspace(self):
        try:
            self._asset_rows=self.service.assets(); self.fill_table(self.asset_table,self._asset_rows,[lambda a:a.get('name',''),lambda a:f"{a.get('size',0)/1024/1024:.1f} MB",lambda a:a.get('summary','') or '可选补充；可直接一键分析'])
            selected_campaign_asset=self.campaign_asset.currentData();self.campaign_asset.blockSignals(True);self.campaign_asset.clear()
            for asset in self._asset_rows:self.campaign_asset.addItem(asset['name'],asset['id'])
            if selected_campaign_asset:self.campaign_asset.setCurrentIndex(max(0,self.campaign_asset.findData(selected_campaign_asset)))
            elif self.campaign_asset.count():self.campaign_asset.setCurrentIndex(0)
            self.campaign_asset.blockSignals(False)
            restore_record=None
            if hasattr(self.service,'campaigns'):
                restore_record=self.sync_campaign_history(self.service.campaigns())
            old=self.ops_asset.currentData(); self.ops_asset.clear()
            for asset in self._asset_rows: self.ops_asset.addItem(asset['name'],asset['id'])
            if old: self.ops_asset.setCurrentIndex(max(0,self.ops_asset.findData(old)))
            self._draft_rows=self.service.drafts(); old_id=self._draft_id; self.draft_choice.blockSignals(True); self.draft_choice.clear()
            for d in self._draft_rows: self.draft_choice.addItem(PLATFORMS.get(d['platform'],d['platform'])+' · '+d.get('title','未命名'),d)
            index=next((i for i,d in enumerate(self._draft_rows) if d['id']==old_id),len(self._draft_rows)-1)
            self.draft_choice.setCurrentIndex(index); self.draft_choice.blockSignals(False); self.load_draft()
            evidence=self.service.evidence(); self.fill_table(self.evidence_table,evidence,[lambda e:PLATFORMS.get(e.get('platform'),e.get('platform','')),lambda e:e.get('title',''),lambda e:e.get('source_url','')+'\n'+e.get('fetched_at','')])
            accounts=self.service.accounts(); self.fill_table(self.account_table,accounts,[lambda a:PLATFORMS.get(a.get('platform'),a.get('platform','')),lambda a:a.get('account','creator'),lambda a:a.get('message',a.get('status','本地记录；未在线验证'))+(' | 最近检查：'+str(a['last_check'].get('message',a['last_check'].get('status',''))) if isinstance(a.get('last_check'),dict) else '')])
            self.refresh_jobs()
            if restore_record and self._rendered_campaign_id!=restore_record['id']:self.render_campaign(restore_record,refresh_workspace=False)
        except Exception as exc: self.banner.setText('工作空间读取失败：'+str(exc))

    def show_window(self): self.showNormal(); self.raise_(); self.activateWindow()

    def shutdown(self):
        if self._closing: return True
        self._closing=True
        if hasattr(self,'timer'): self.timer.stop()
        if hasattr(self,'campaign_timer'):self.campaign_timer.stop()
        # Finish finite workspace writes before closing their database.
        if not self.pool.waitForDone(45000):
            self._closing=False; self.timer.start()
            self.error('后台文案或素材处理尚未结束，请稍后再退出。')
            return False
        try: self.service.close()
        except Exception as exc:
            self._closing=False; self.timer.start(); self.show_window()
            self.error('后台任务尚未安全停止：'+str(exc))
            return False
        self.tray.hide()
        if self.speech_dialog is not None:self.speech_dialog.hide()
        self.hide()
        QApplication.instance().quit()
        return True

    def closeEvent(self,event):
        if self._closing: event.accept(); return
        if self.tray.isVisible():
            choice=QMessageBox(self); choice.setWindowTitle('关闭窗口'); choice.setText('保留到系统托盘，或退出并停止本地任务。')
            tray=choice.addButton('保留到托盘',QMessageBox.ButtonRole.AcceptRole); quit_button=choice.addButton('退出软件',QMessageBox.ButtonRole.DestructiveRole); choice.addButton('取消',QMessageBox.ButtonRole.RejectRole); choice.exec()
            if choice.clickedButton()==tray: self.hide(); event.ignore(); return
            if choice.clickedButton()!=quit_button: event.ignore(); return
        if self.shutdown(): event.accept()
        else: event.ignore()


def run(service, api_info:dict)->int:
    app=QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('三平台内容发布助手')
    app.setQuitOnLastWindowClosed(False)
    window=StudioWindow(service,api_info)
    window.show()
    app.aboutToQuit.connect(window.shutdown)
    if api_info.get('_ui_check_out'):
        def check_ui():
            target=Path(api_info['_ui_check_out']);target.mkdir(parents=True,exist_ok=True)
            for index in range(window.stack.count()):
                window.navigation.setCurrentRow(index);app.processEvents()
                window.grab().save(str(target/f'page_{index}.png'))
            window.navigation.setCurrentRow(0)
            for index in range(window.campaign_tabs.count()):
                window.campaign_tabs.setCurrentIndex(index);app.processEvents()
                window.grab().save(str(target/f'plan_{index}.png'))
            verification={'campaign_id':window._campaign_id,'rendered_campaign_id':window._rendered_campaign_id,'platforms':{p:{'title_count':f['title'].count(),'caption':f['caption'].toPlainText(),'category':f['category'].text() if 'category' in f else '', 'search':f['search'].text() if 'search' in f else '', 'hook':f['hook'].text() if 'hook' in f else ''} for p,f in window.campaign_fields.items()}}
            speech=(window._speech_media or {}).get('speech')
            if isinstance(speech,dict):
                window.show_speech();app.processEvents()
                window.speech_dialog.grab().save(str(target/'speech_full.png'))
                segments=speech.get('segments') or []
                verification['speech']={'status':speech.get('status'),'complete':speech.get('complete'),'segments':len(segments),'text_length':len(str(speech.get('text') or '')),'last_text':str(segments[-1].get('text','')) if segments else '', 'processed_duration':speech.get('processed_duration'),'audio_duration':speech.get('audio_duration'),'copy_plain_enabled':window.speech_copy_plain.isEnabled()}
                window.speech_dialog.hide()
            (target/'ui-fields.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
            window.shutdown()
        QTimer.singleShot(500,check_ui)
    return app.exec()
