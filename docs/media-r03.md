> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R03 媒体与完整口播融合

`analyze_media(asset, work_dir, engine_root, emit=None, speech=None)` 保留旧接口调用方式，不导入或安装 ASR 引擎。生产流程由上层先完整转写所选主音轨，再传入 speech。本模块只读取选定视频、相邻同名字幕，并在传入工作目录生成 JPEG；不联网，不调用 AI，不改动原片。

传入 speech 后，`transcript` 采用全部实际 ASR segments，不受旧外部字幕 200 段上限影响；保留 start/end/text、实际置信度与 uncertain，并标记 source=asr。完整 speech 原对象另存用于本地展示，包含原始全文、转写文件路径和设备信息。相邻 SRT/VTT 放入独立 `supplied_subtitles`，不会代替 ASR。外部字幕仍有 2MiB/200 段读取上限，截断会明确提示。

合法完成状态及范围：

| speech 状态 | analysis_scope | 含义 |
| --- | --- | --- |
| complete | sampled_frames_and_full_audio_transcript | 所选音轨处理完成，有实际口播片段；机器识别不保证逐字准确 |
| no_audio | sampled_frames_no_audio | 没有音轨，继续按抽样画面处理 |
| no_speech | sampled_frames_no_speech | 已处理音轨，未识别出可用人声，不等于证明绝对无声 |
| 无 speech（旧历史） | sampled_frames_and_supplied_subtitles | 仅旧画面/用户外部字幕依据，不能称自动完整转写 |

`complete` 必须严格为 true；失败/未知状态、未覆盖音轨、无效时间、明显超出视频时长或完成状态没有实际口播都会拒绝。处理覆盖与尾端采用 0.25 秒容器/识别舍入容差，标准化片段不超过视频时长；本地原始 speech 保持原样。不要求语音片段覆盖每秒：真实停顿不应被填造为口播。

画面保留六个均匀时间点；有语音时可加全体语音片段四分之一、四分之三位置的中点，共最多八张。附加点只是采样位置，不宣称已经语义识别“精彩片段”。固定项目 FFmpeg 路径、无 shell 子进程和原有有界超时继续生效。

`build_brief` 将完整 speech segments 作为唯一口播全文来源，即使调用方传入了截短 transcript 视图也不会缩短全文。只发送 speech 白名单元数据和一次标准化全文，不发送 speech.text、另一份 speech.segments 或 TXT/SRT/JSON/WAV 路径；抽帧只发送时间点，图片由上层受控通道提供。外部字幕带独立名称进入 brief。品牌、命令、数值与不确定词需结合画面核查，不能编造人工听审结论。

方案 `evidence_type=speech` 只接受完整识别后的真实片段时间重叠；无音轨或无可识别人声时不能引用 speech。`subtitle` 在新记录中只能引用 supplied_subtitles，旧记录继续兼容 transcript。所有适配片段不得越过视频 duration；这些校验仅证明时间与来源存在，不证明 AI 对内容的解释正确。

验证使用隔离 fixture（含 250 段 ASR、末尾口播、外部字幕冲突、失败/局部识别、无音轨、无可识别人声、路径剔除）及项目实际六秒测试片的原有本机抽帧测试，不调用真实 AI 或平台账号。完整语音识别准确度与真实模型执行属于独立 ASR 模块验证范围。

本轮实测：`test_media*.py` 14 项通过（包含实际六秒视频＋250 段注入 ASR 的本机八帧以内融合）；`test_operations*.py` 30 项通过；上层新 `test_speech_campaign.py` 2 项通过。旧 campaign fixture 在新 ASR 前置阶段尚未模拟转写的失败已交由集成负责人更新，不将其表述为全套测试通过。
