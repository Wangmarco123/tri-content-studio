> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# AI控制接口：HTTP、JSON CLI 与 stdio MCP

R03 1.2.0桌面界面、CLI和MCP共用同一本机API、素材库和任务库。外部AI可以登记素材事实、一键启动完整音轨转写、研究与三平台运营方案、导入证据与文案包、创建明确任务及查询回执；没有任意shell命令执行工具。生成文案与执行发布是两个步骤。R02历史及旧控制接口继续兼容。

## R03 一键运营方案

启动桌面软件或serve后，使用真实素材/方案ID调用；全局参数放在子命令之前：

```powershell
.\ContentCtl.exe --home "$PWD" ai-status
.\ContentCtl.exe --home "$PWD" plan --asset-id asset_实际ID --provider auto --goal "准备相关热点与三平台文案"
.\ContentCtl.exe --home "$PWD" plan-status campaign_实际ID
.\ContentCtl.exe --home "$PWD" plan-save campaign_实际ID --bili-title-index 1 --xhs-title-index 0
.\ContentCtl.exe --home "$PWD" plan-save campaign_实际ID --queue-drafts
.\ContentCtl.exe --home "$PWD" plan-cancel campaign_实际ID
```

provider为auto/codex/api，默认auto优先本机已登录Codex，无需摘要、字幕或API Key。plan异步返回Campaign，轮询plan-status看五块结果；阶段为audio/transcribe/media/research/ai/validate，失败不假造结果。生成完成已保存三平台首选标题的本地文案，plan-save可改选候选标题（索引从0开始），默认不创建平台任务。queue-drafts只为抖音创建draft，B站仅保存本地；没有自动公开发布。plan-cancel取消整个方案处理，包括本地转写/AI调用，不撤回稿件，也不自动取消已经另行创建的平台任务。

以下HTTP路由均需Bearer认证：

| 路由 | 方法 | 请求/响应 |
| --- | --- | --- |
| `/api/v1/ai/status` | GET | codex可用/登录状态、api是否配置、default_provider、asr文件就绪信息；无凭据 |
| `/api/v1/campaigns` | GET | Campaign数组 |
| `/api/v1/campaigns` | POST | `{asset_id,provider?,goal?}` → 异步Campaign |
| `/api/v1/campaigns/{id}` | GET | status、stage、progress、result、draft_ids |
| `/api/v1/campaigns/{id}/cancel` | POST | 可无正文 → Campaign |
| `/api/v1/campaigns/{id}/save` | POST | `{selections?:{bilibili?:int,xiaohongshu?:int},queue_drafts?:bool}` → `{items,count:3,jobs}` |

save路径ID为权威值，正文不要重复提供id。标题索引必须为非负整数，不接受bool；queue_drafts必须JSON布尔值，不接受字符串false。当前精确schemas见服务OpenAPI。

MCP增加 `ai_status`、`list_campaigns`、`start_campaign`、`get_campaign`、`save_campaign`、`cancel_campaign`，与旧11个工具合计17个。start_campaign必填asset_id，provider/goal可选；get/save/cancel必填id；save_campaign使用同样的selections对象和queue_drafts布尔值。嵌套参数错误返回invalid-params，未执行任务。API info与MCP serverInfo版本均来自studio.__version__。

方案包含机会来源、逐项适配与timecode、三平台差异化文案：B站/小红书候选标题、B站分区建议、抖音hook、小红书搜索词和实际sources/media。无相关热点允许空机会并解释。旧brief/import-packages/generate/queue继续兼容，不强制旧provider返回campaign；旧R02历史无speech时只保留当时的画面/外部字幕范围。

### 完整口播与数据边界

主链先用本地faster-whisper large-v3-turbo处理完整所选主音轨，CUDA失败时有界回退CPU，最多8帧保留均匀覆盖。模型仅从本地组件目录读取，禁止隐式联网下载；缺模型/依赖报错。`ai-status.asr.ready`表示模型与Python依赖文件检查就绪，`cuda_libraries_present`也只是文件存在；不运行推理，不证明GPU能力、速度或识别准确度。

`result.media.speech`保留status、engine/model、device/compute_type、language、audio_duration/processed_duration、complete、全segments/text、uncertain_segments、warnings、cache_hit及txt_path/srt_path/json_path，路径只供本地用户打开。缓存按素材内容及识别设置识别，不能仅凭同名文件冒充原片转写。complete指完整处理，不等于人工逐字核对；低置信片段、音乐/环境音误识别和品牌数值须复核。

status=`complete`有口播全文；`no_audio`无音轨；`no_speech`全音轨处理后无可用文字，不证明绝对静音。后两种可继续画面方案；识别失败不进入正常完整生成。media.analysis_scope分别为sampled_frames_and_full_audio_transcript、sampled_frames_no_audio、sampled_frames_no_speech；旧记录仍为sampled_frames_and_supplied_subtitles。

AI brief仅发送白名单语音元数据与一次完整transcript（不限前200段），不重复发送speech.text/segments，不发送TXT/SRT/JSON/WAV本地路径，也不上传原视频/音轨；图片由受控图像附件发送。外部相邻字幕独立为supplied_subtitles，不能冒充自动识别。方案片段evidence_type增加speech，必须与实际完整ASR段重叠；subtitle指外部字幕，sampled_frame指真实抽帧。所有时间不得越过视频时长，时间匹配不证明AI解释必然正确。

## 启动与连接

先运行桌面软件。无界面服务可用源代码入口：

```powershell
python -m studio.cli --home "C:\TriContentStudio" serve --port 19266
```

打包版对应可执行文件为 `ContentCtl.exe`，它与桌面EXE共用服务。使用时将下列路径替换为实际解压目录；源码开发方式要求在source目录运行，并使用已安装依赖的项目Python。

服务只监听 `127.0.0.1`。端点和令牌文件路径写入当前数据目录的 `connection.json`；默认数据目录为项目根下 `state/desktop`。CLI可指定 `--home`、`--data-dir`、`--endpoint`、`--token-file`，这些全局选项必须放在子命令前。默认端点为 `http://127.0.0.1:19266`，实际端口可从连接记录读取。

## 鉴权与访问边界

业务路由使用 `Authorization: Bearer <本机令牌>`。`GET /api/v1/health` 和 `GET /api/v1/openapi.json` 可用于无令牌发现；其余业务路由需要令牌。CLI/MCP自动读取指定令牌文件，配置中只填写文件路径，不填写令牌值。

- 不将令牌、Cookie、短信验证码或模型Key写进AI任务、工单、截图、命令参数或公开仓库。
- 本机令牌授予实际业务控制权，只交给本人信任的AI客户端。MCP客户端的工具批准规则仍应限制真实发布动作。
- CLI仅连接loopback HTTP根地址，不接受远端服务地址、嵌入凭据或查询参数；不跟随重定向、不使用系统HTTP代理，避免将Bearer送往其他地址。
- HTTP服务拒绝带Origin的浏览器请求，没有开放跨域CORS。该接口供本机客户端调用，不应直接嵌入外站网页。
- 不要把API端口映射到公网，也不要共享state目录。

## JSON CLI

CLI成功退出码为0，标准输出为一条UTF-8 JSON；业务/连接错误退出码为2并输出 `{"error":{"message":"..."}}`。参数格式错误由argparse报告到stderr。stdout不能当作人类进度日志解析。典型流程：

```powershell
.\ContentCtl.exe --home "$PWD" status
.\ContentCtl.exe --home "$PWD" add --file "G:\素材\成片.mp4" --summary "本人确认：画面展示壶盖装配" --audience "产品设计师"
.\ContentCtl.exe --home "$PWD" list assets
.\ContentCtl.exe --home "$PWD" brief asset_实际ID --out "G:\项目\外部AI任务.json"
.\ContentCtl.exe --home "$PWD" import-evidence "G:\项目\热点证据.json"
.\ContentCtl.exe --home "$PWD" import-packages "G:\项目\运营成品.json"
.\ContentCtl.exe --home "$PWD" list drafts
```

`brief`输出事实摘要、证据和响应schema，包含“未分析原片”边界，不传输视频文件。外部AI应核对近7天原链接和时效；无法取数时不得编造热点/互动。没有合适热点时允许自然搜索型包装。

证据导入示例（日期/数字只允许填真实观察，以下不含热度）：

```json
{
  "items": [{
    "id": "evidence-actual-1",
    "platform": "xiaohongshu",
    "title": "本人看到的相关笔记标题",
    "source_url": "https://www.xiaohongshu.com/explore/实际笔记ID",
    "fetched_at": "实际观察的ISO8601时间",
    "verification": "user_supplied",
    "notes": "只记录可见事实，缺少互动量时不补数字"
  }]
}
```

运营包必须使用已有素材ID，证据ID必须先导入。三个平台名为 `bilibili`、`douyin`、`xiaohongshu`；tags为字符串数组，B站是投稿TAG，小红书/抖音是相关话题候选。正文中的#不自动证明平台话题已存在或正热门。

```json
{
  "asset_id": "asset_实际ID",
  "packages": [{
    "platform": "xiaohongshu",
    "title": "壶盖装配过程",
    "caption": "这段视频展示实际壶盖配合，供关心产品结构的朋友参考。尺寸和制造结果仍需按自己的工艺核对。",
    "tags": ["产品设计", "结构设计"],
    "hook": "先看配合，再解释结构",
    "visibility": "draft",
    "evidence_ids": [],
    "fit_reason": "围绕视频本身的装配内容，不硬蹭热点",
    "tag_checks": [{"name": "产品设计", "verification": "unverified", "evidence_ids": [], "reason": "相关候选，未核实平台话题入口"}]
  }]
}
```

本轮客户端标题策略为B站80字、抖音30字、小红书20字；这是当前软件规则，平台表单变化时需同步调整。整批运营包先验证；一个包错误时不能将其当成全批成功。

## 任务、默认草稿与可见范围

```powershell
.\ContentCtl.exe --home "$PWD" queue --draft-id draft_实际ID --idempotency-key 本次唯一请求键
.\ContentCtl.exe --home "$PWD" job job_实际ID
.\ContentCtl.exe --home "$PWD" job job_实际ID --events
.\ContentCtl.exe --home "$PWD" cancel job_实际ID
```

省略action默认为draft。B站当前适配器不支持草稿，应由本人明确选择仅自己可见投稿；软件不会自动把B站草稿改成公开或私有投稿。正式发布必须明确 `--action publish` 及 `--visibility private` 或 `public`，并核对账号、素材与平台。不要让AI根据“文案已确认”推导出公开发布授权。

任务状态需要分别理解：`queued/running/awaiting_user`不是提交成功；`draft_saved`不是已公开；`submitted`仅表示提交受理，不等于审核通过；`outcome_unknown`必须先核对平台原稿件，不能换幂等键重复提交。重启不能使未知提交自动重发。取消只停止本地动作，不撤回远端已提交稿件。

## stdio MCP

MCP入口是同一CLI的 `mcp` 子命令，通过UTF-8逐行JSON-RPC通信；不另起发布服务、不绕过HTTP鉴权。先启动桌面软件或serve，再让AI客户端连接。支持initialize、ping、tools/list、tools/call；通知不返回消息。

打包版配置示例：

```json
{
  "mcpServers": {
    "tri-content-studio": {
      "command": "G:\\实际解压目录\\ContentCtl.exe",
      "args": ["--home", "G:\\实际解压目录", "mcp"]
    }
  }
}
```

源码测试配置则将command改为项目Python的完整路径，args使用 `-m studio.cli --home <项目根> mcp`，并将客户端工作目录设为source目录或配置对应PYTHONPATH。使用独立数据目录时增加 `--data-dir`；必要时显式指定 `--endpoint` 与 `--token-file`，均放在mcp子命令前。

旧工具继续可用：`studio_status`、`list_assets`、`register_asset`、`export_brief`、`fetch_trends`、`import_evidence`、`import_packages`、`list_jobs`、`queue_task`、`get_job`、`cancel_job`，加上R02六个方案工具共17个。请以tools/list返回的inputSchema为准；必填参数缺失和未知参数会返回带原请求ID的invalid-params错误。平台API/业务失败通过工具结果isError报告，客户端进程继续接受后续请求。

`queue_task`可以创建实际动作，不是模拟工具。默认草稿和正式发布显式可见范围同CLI；平台登录/验证码需要本人在专用浏览器完成。没有自动验证码破解工具。

## 真实验证范围

tests/test_clients.py使用临时独立Service/SQLite、真实loopback HTTP与独立CLI/MCP子进程，验证中文素材登记、brief导出、JSON运营包导入、共享状态、默认草稿队列/取消、鉴权错误、MCP协议与参数、未知结果不重发，以及Bearer重定向阻断。测试关闭平台worker，不启动账号浏览器、不登录、不投稿、不调用付费模型。
