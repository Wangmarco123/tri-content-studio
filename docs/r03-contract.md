> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R03：完整音轨自动转写＋画面一键五项

用户已明确授权：选择视频后自动完成语音转写、结合画面与完整口播生成既定五项，尽量不手补资料。保留R02。源码完整复制893文件校验一致。使用本地faster-whisper large-v3-turbo，CUDA可用则加速、失败在独立子进程中回退CPU；不需要语音API Key。

## speech（asr.py，engine agent负责）

`transcribe_video(asset, work_dir:Path, engine_root:Path, emit=None, cancel=None)->dict`：cancel可调用返回bool，取消抛`GenerationCancelled`（可从ai_provider导入，避免再建异常类型）。整个所选主音轨都处理完才complete；不静默裁前200句。无音轨/无可识别人声是正常结果，失败raise ValueError，不用局部口播冒充完整。

返回：
```
{status:'complete'|'no_audio'|'no_speech', engine:'faster-whisper',model:'large-v3-turbo',
 device:'cuda'|'cpu'|null,compute_type:string,language:string|null,
 language_probability:number|null,audio_duration:number,processed_duration:number,
 complete:true,segments:[{start:number,end:number,text:string,avg_logprob:number,
 no_speech_prob:number,uncertain:boolean}],text:string,
 uncertain_segments:[integer],warnings:[string],txt_path:string,srt_path:string,
 json_path:string,cache_hit:boolean}
```

complete指全音轨处理完，不保证逐字准确。no_audio时duration0、segments空；no_speech时全音轨检查但没识出人声。所有音轨/转写工作文件放work_dir内，缓存可用engine_root/state/asr_cache（按原视频SHA256+模型/识别设置版本，不按文件名）。模型只从`runtime/asr/models/faster-whisper-large-v3-turbo`或`components/asr/models/faster-whisper-large-v3-turbo`读取，`local_files_only=True`；不隐式联网下载。CUDA DLL目录`runtime/asr/cuda`或components/asr/cuda，不改系统PATH。

优先独立worker隔离CUDA崩溃；源码worker命令`sys.executable -m studio.cli _speech_worker --request PATH --events PATH --result PATH`，冻结版同级ContentCtl.exe同参数。root在cli增加该命令，入口调用`asr.worker_main(request_path,events_path,result_path)`。request包含asset/work_dir/engine_root/device（auto/cuda/cpu可内部确定）和cancel_path；agent可设计内部字段但入口签名固定。worker全部处理后result JSON；父进程有界监管、取消、唯一一次GPU失败CPU回退，不能无限重试。

emit `{stage:'audio'|'transcribe',progress:0..100,message}`，progress仅真实处理位置，最终迭代耗尽才100。SRT/TXT/JSON原始转写都保留；低avg_logprob/no_speech_prob等据实际值标uncertain，不编准确率。转写不擅自改成摘要或营销文案。

## media.py / operations.py（media agent负责）

`analyze_media(asset,work_dir,engine_root,emit=None,speech=None)`向后兼容旧无speech调用。生产链root先转写，再将speech传入。提供speech时media.transcript采用**完整**ASR segments（增加source:'asr'可选），相邻字幕另存supplied_subtitles，不替代ASR。media增加speech完整对象供UI；发AI的build_brief仅白名单语音元数据+全transcript文本，去掉WAV/TXT/SRT/JSON路径，不重复发整段text和segments两份。

analysis_scope：有完整转写`sampled_frames_and_full_audio_transcript`；无音轨`sampled_frames_no_audio`；无可识别人声`sampled_frames_no_speech`；旧历史保留旧scope不冒充新ASR。speech.complete不为true不得进入正常生成。

画面最多8张（provider已有max8）；可结合语音段选关键时间，并保留均匀覆盖，不只截开头。speech超过200句不能截断；源SRT原限制只针对旧路径，不影响新完整口播。

campaign_schema/validator增加segments.evidence_type='speech'，只有media.speech完整、时间与实际ASR段重叠才允许，`subtitle`仍指外部字幕。所有时间不超过视频duration。build_brief/instructions对全音轨转写与抽样画面作真实声明，机器识别不是逐字人工核对；品牌/命令/数值结合画面核对，不依据低置信词作承诺。

## root orchestrator / GUI

Campaign stages新增audio/transcribe，root将ASR emit映射到全任务约5..30%，media约30..40%，research40%，ai50%，validate90%。生成前自动转写，无摘要/字幕也可运行；无声片自动按画面生成并说明，不用用户补空口播。

result.media.speech为GUI依据；五块结果保留，另提供「完整口播」面板：全文、时间戳、处理覆盖、缓存/设备/模型、低置信提示，可复制/打开本地转写文件。不得把本地路径发给模型。首屏默认一键，展示ASR真实进度，不强制用户配置Key或先准备字幕。新界面应能查看R02历史无speech的记录。

## 附加用户请求

用户提供`G:/ai工作输出/抖音自动化/_release/douyin-channels-autopilot`供学习。已读README/SKILL/publish.py；实际发布层包装social-auto-upload而非新上传引擎。root归档整包和核查报告，吸收前置校验/封面/真实回执经验，保留本工具提交一次/未知结果不重发的保护；不擅自增加视频号或真实公开发布。
