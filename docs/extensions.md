> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R03 1.2.0扩展接口（保留R01/R02兼容）

所有控制入口最终调用`studio.service.Service`，数据结构包含schema_version；HTTP使用`/api/v1`。扩展新客户端优先调用API，不直接改SQLite或账号目录。`connection.json`提供端点和token文件位置；CLI与MCP会读取它，不需要把token写进命令行参数。

## 平台适配器

当前统一入口为`studio.adapters.execute(job, context, emit) -> result`。job包含id/platform/account/action/payload；payload是素材路径、SHA256、标题、正文、标签及明确可见范围的冻结快照。context包含engine_root、state_root、cancel_path。emit报告stage/progress/message/qr_path/requires_user。result包含status/message以及实际可核验的remote_id、requested/actual visibility、readback等证据。

适配器不能自行重排或重试提交；外层队列串行执行、子进程隔离。扩展前维持：明确范围后才能点提交、只提交一次、等待有界、验证码交本人、锁定专用账号profile、未知回执返回outcome_unknown。新增action应同时更新Service校验、API schema、CLI/MCP枚举和UI能力限制。

发布状态不等于审核结果。没有观察到明确回执时不返回submitted或draft_saved；浏览器本地草稿的存储范围须说明。平台更新后先做只读登录检查和已授权测试素材草稿，再尝试真实内容。

## 热点与模型

`studio.operations.fetch_trends(platform, keyword='', timeout=15)` 返回items/status/message/source_url/fetched_at。keyword只过滤当前快照，不是全站搜索。新增provider要保留平台、来源原链接、采集时间、来源更新时间、rank和指标原语义；失败与合法空结果分开。不能继承账号Cookie或偷偷调用付费服务。小红书当前明确返回needs_source。

外部只读搜索可将结果通过`POST /api/v1/evidence/import`注入。不要允许任意联网URL变成内网请求代理。模型接口为`generate_packages(asset,evidence,config)`，只发送摘要和证据，返回值必须经过`validate_packages`。新增模型/数据provider应单独实现传输边界，不将视频路径、Cookie、API令牌或账号资料发给模型。

`build_brief`带response_schema与asset_id，供用户自己的AI使用。运营包由平台标题、caption、tags、hook、fit_reason、evidence_ids、tag_checks和visibility组成。批量校验和数据库写入是原子的。

## 当前未提供

当前没有公开远端服务、远程任意命令、定时刷量、多账号批发、队列重排、自动远端对账和未知结果解除接口。未来需要远程AI时应由本机受控客户端桥接，不直接把当前loopback服务暴露到公网。版本演进应新增明确接口和证据，避免绕过任务状态机。

## R02一键AI扩展

`Service.start_campaign`异步完成媒体、研究、AI、校验和本地保存；get_campaign读状态，save_campaign保存候选标题并可显式加入DY/XHS草稿。HTTP、CLI和MCP入口见ai-interface.md，均共用campaigns表和同一套校验，不要直接改数据库终态。

AI传输新增studio.ai_provider：本机Codex使用现有登录的非交互接口，附真实JPEG、原生搜索与严格campaign_schema；普通兼容API附JPEG但不声称原生搜索。原generate_packages只发摘要的旧入口仍保留给兼容客户端，不是首页主链路。媒体模块的固定项目FFmpeg路径、时长和字幕范围见media-r02.md。新增来源按平台域名检查并赋全新ID，拒绝覆盖已有证据归因；AI来源仍标记待独立复核。

## R03完整主音轨与媒体融合

主链阶段为audio/transcribe/media/research/ai/validate。`studio.asr.transcribe_video(asset,work_dir,engine_root,emit=None,cancel=None)`先完整解码所选主音轨并使用本地faster-whisper large-v3-turbo识别，CUDA失败有界回退CPU。模型仅使用runtime/asr/models/faster-whisper-large-v3-turbo或components对应本地目录，local_files_only，缺失明确失败，不隐式下载。`asr_status`仅文件/依赖就绪检查并由ai-status的asr返回，ready不能当作GPU可用、速度或效果测试。

speech返回status、模型/设备/语言、音轨与处理时长、complete、全部segments/text、uncertain_segments、warnings、TXT/SRT/JSON路径及cache_hit。缓存按原片内容与识别设置关联；独立worker、取消与有界GPU→CPU回退不能改成无限重试。complete表示音轨迭代结束，不保证逐字正确；no_audio和no_speech是正常画面回退状态，失败raise不能交局部口播。no_speech不等于证明音轨绝对无声。

`analyze_media(...,speech=None)`向后兼容，生产链传完整speech；transcript采用完整ASR，不受外部字幕200段上限影响；speech完整对象留本地UI，supplied_subtitles独立保留。最多8帧保留均匀覆盖。新scope分别为sampled_frames_and_full_audio_transcript、sampled_frames_no_audio、sampled_frames_no_speech；R02历史沿用旧scope，不能冒称全音轨已识别。详细范围见media-r03.md。

`build_brief`只发送白名单语音元信息＋一次完整transcript，不重复text/segments，不发送转写文件路径、原视频/音轨、账号或凭据；真实JPEG经provider附件边界输入。campaign_schema新增evidence_type=speech，必须是完整ASR及实际时间重叠；subtitle在新记录只指supplied_subtitles，旧无speech记录兼容原transcript。时间依据验证不等于内容准确性证明，品牌/数字/命令/低置信词仍需核对。

默认auto优先已登录Codex，无需摘要、字幕或Key；可选兼容API保持独立配置与数据边界。R03不新增控制工具数量，HTTP/CLI与17工具MCP共用同一Service，保留旧generate/brief/import及R02历史。生成后仍只写本地文案；草稿须显式请求，未知提交仍禁止自动重传。
