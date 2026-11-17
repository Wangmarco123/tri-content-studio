> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R03 完整音轨本地转写

接口：`studio.asr.transcribe_video(asset, work_dir, engine_root, emit=None, cancel=None)`；隔离worker入口为 `worker_main(request_path,events_path,result_path)`；只读准备状态为 `asr_status(engine_root)`。

模型固定为large-v3-turbo，只接受项目内 `runtime/asr/models/faster-whisper-large-v3-turbo` 或发行包 `components/asr/models/faster-whisper-large-v3-turbo`，使用 `local_files_only=True`，不隐式下载。模型bin、config、tokenizer及vocabulary文件必须存在且非空；完整权重的固定revision/哈希验证由安装记录负责，存在检查不等于真实推理已经通过。

## 全音轨处理与真实边界

ffprobe从所选视频中找默认音轨，没有默认标记时取第一音轨；ffmpeg解码该音轨全部内容为16kHz单声道PCM WAV。不加截断参数，不限制前N秒或前N句。WAV实际帧数确定audio_duration。所有解码与转写工作文件均在该任务work_dir。

### 音轨与抽帧时间轴

ffprobe同时保留format.start_time、选定audio.start_time和video.start_time。视频抽帧用FFmpeg输入`-ss`，未启用seek_timestamp，时间零点是容器起点而非音轨首采样或视频流起点。偏移使用`audio.start_time - format.start_time`，不能直接减video.start_time或假定容器总为0。

完整解码音轨先用asetpts归零，再按16kHz采样数adelay补正偏移的前导静音，保留全部音频；ASR返回的时间就是与抽帧一致的容器相对时间，不需后续把音轨0秒的词误标成视频0秒。audio_duration/processed_duration包含对齐静音，不自动扩到视频尾部无音轨时段。audio_alignment元数据记录来源起点和补齐时长，warnings明确说明。

整体容器起点非零或负数仍按差值计算。明显负相对偏移（音轨先于容器零点）明确报时间轴不支持/需先规范化，不裁负时刻口播，也不把负值挤到0；小于一个输出采样的舍入误差按采样精度处理。缺失起点时按FFmpeg默认零点/容器起点处理并保留来源限制警示。当前识别设置已升v4，旧时间轴、纯符号及尾段挤压结果缓存不会再命中。

优先独立CUDA/float16工作进程；GPU失败或崩溃后，最多另起一次独立CPU/int8进程重新处理整个音轨。CPU失败后raise ValueError，不再重试。取消抛既有GenerationCancelled，不回退CPU，不把局部识别当成完整口播。工作进程不会打开平台浏览器或发布内容。

使用beam_size=5，vad_filter=False，迭代完整faster-whisper生成器；不设200段限制。完整解码后先扫描PCM；只有每个采样字节都为零才直接判no_speech，不使用音量阈值抹掉微弱人声。非零音乐、环境声仍可能诱发模型幻觉，未部署独立人声/音乐分类；no_speech通常只代表模型完整跑完未输出文字，不能保证客观没有人声。只有生成器正常耗尽并通过取消检查，才complete:true、processed_duration=audio_duration。生成器中途异常不产生成功结果、不写成功缓存。完整指选定音轨处理结束，不保证每字准确，也不意味着人工听过全部声音。其它语言/品牌/命令/数值须结合画面核对。

无音轨返回no_audio、时长0、空segments；音轨已完整处理但没有输出文字返回no_speech、完整时长和空segments。这些均为正常情况。没有人声的音乐可能被模型误识别，不能把模型输出绝对等同实际人声。

每段保留start/end/text/avg_logprob/no_speech_prob；avg_logprob小于-1、no_speech_prob大于0.6或实际compression_ratio大于2.4时uncertain:true，并记录零基uncertain_segments索引。阈值是提示规则，不是识别准确率；高置信幻觉仍可能漏标。不会静默删除这些段落或把它们改写成摘要。

模型输出如果不含任何Unicode.isalnum字符（如单独`.`、省略号或音符），不作为词汇/口播事实：不放入segments/text/TXT/SRT，而将原始文字、时间和识别分值完整保留在JSON的nonlexical_segments并警示。中文、英文、数字及带标点的真实词汇保留；不使用固定词语黑名单。不含可用词汇时status为no_speech，仍完整处理音轨，不意味着人工证明没有声音。

原始模型start已经大于等于音轨时长、end不大于start、区间完全在音轨外或时间非有限数值时，将原文字、原有效时间值、分值及拒绝原因保存在rejected_segments；不能clamp成音轨末帧的零长度speech事实。有效但跨边界的区间仅保留真实重叠范围并警示，边界文字仍需核对。成功speech片段严格end>start且start<audio_duration，与media校验一致。

为减少随机温度回退与跨窗口文字反馈的影响，v4固定temperature=0.0并关闭condition_on_previous_text，保留beam_size=5与VAD OFF。这是可复现性/错误传播控制，不是准确率提高承诺；真实中文、尾段和低音量回归仍需检查。

## 进程、事件与输出

源码父进程用当前sys.executable运行 `-m studio.cli _speech_worker --request ... --events ... --result ...`。冻结版用同级ContentCtl.exe；缺失明确报错，不回退启动GUI。root CLI须提供该固定入口。

request记录audio_path、audio_duration、work_dir、engine_root、device和cancel_path。每次尝试使用独立worker目录。worker限制音轨位于任务工作目录，JSON结果原子落盘。父进程读取完整JSONL事件，透传stage/progress/message；不解析stdout，也不把底层原始输出送给模型。

FFprobe上限30秒；解码上限由时长计算并封顶1小时；每次推理上限为max(300秒,min(4小时,时长×30+180秒))。父进程约每0.2秒检查取消，终止仅属于本次的worker；CUDA崩溃的设备内存随进程退出释放。实际模型初始化/单段推理期间无需等待引擎主动响应，父进程可终止该隔离进程。

事件stage为audio/transcribe；转写进度来自已实际产出片段的时间位置，未耗尽前最多99。无语音时可能长时间没有片段进度；不按墙钟伪造推进。只有完整迭代耗尽或确认无音轨/缓存完整时才100。

任务最终保留完整 `transcript.txt`、带时间戳 `transcript.srt`、`transcript.json`。返回txt_path/srt_path/json_path供GUI本地查看，不应传给外部模型。重跑不会把营销润色覆盖原始转写。

## 缓存与运行环境

缓存位于engine_root/state/asr_cache，以实际视频SHA256、固定模型名、识别设置版本、faster-whisper/CT2版本、模型文件名称/大小/mtime签名生成key，不按视频文件名。缓存v2带内部来源键、视频hash和结果SHA256；命中时检查这些字段、结果checksum、全部段落的时序范围、全文与全部segments逐行一致性、状态/低置信索引，不采纳损坏或截断结果。旧v1缓存不迁移，忽略后重算。只缓存成功的完整结果；缓存JSON去除任务路径，命中后重新在当前work_dir输出完整TXT/SRT/JSON。安装模型更新会使key变化。模型文件签名用于缓存失效，不能代替权重SHA256完整性验证；cache checksum也不是防本机恶意篡改的认证签名。

开始/结束时核对源视频size/mtime，已有asset.sha256须与实际内容一致；识别期间文件变化时拒绝成功结果与缓存。FFmpeg使用-xerror，解码报错明确失败，不把可解码的局部片段冒充完整音轨。取消/超时会关闭FFmpeg的PIPE并终止本次子进程；不触碰其它进程。

CUDA目录为runtime/asr/cuda或components/asr/cuda。worker通过os.add_dll_directory以及精确绝对路径预加载本项目cudart64_12/cublasLt64_12/cublas64_12，不改系统或进程PATH。CPU回退不预加载CUDA库。不要混入其它应用的cuDNN或CUDA13目录。faster-whisper与CT2导入放在worker内部，GUI/主进程不占显存。

asr_status只做模型/包/CUDA文件存在检查，返回ready、model、engine、model_path、dependency_available、cuda_libraries_present、device_capability:null、message，不加载模型、不分配显存、不查账号或网络。ready不等于GPU实测完成。

## 验证范围

fixtures覆盖251段完整保留、lazy后半段失败、取消不返回局部、no_audio/no_speech、全零扫描及末尾极弱非零不被抹掉、低置信/高压缩率提示、毫秒SRT、GPU一次失败仅一次CPU回退、缓存checksum及正文截断拒绝、识别时源文件变动拒绝缓存、实际隔离子进程JSONL/result协议与取消清理。未将fixtures当真实ASR准确度测试。固定模型完成下载后，仍需用授权的真实105秒宣传片检查whole-audio时长、全文、设备与中文词汇；完成情况以实际回执记录，不能从模型/依赖存在推断。
