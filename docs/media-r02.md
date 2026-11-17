> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R02 本地媒体证据提取

接口：`analyze_media(asset: dict, work_dir: Path, engine_root: Path, emit=None) -> dict`，实现位于studio/media.py，无数据库、UI、AI或平台调用依赖。

## 实际行为

- 仅打开传入asset.path所指向的视频，先检查文件存在和支持扩展名（mp4/mov/mkv/avi/webm/m4v），不扫描其他视频。
- 只在engine_root的components/ffmpeg/bin、components/ffmpeg、runtime/ffmpeg/bin、runtime/ffmpeg找成对ffmpeg.exe与ffprobe.exe。不从PATH挑选程序，也不写死本机其他工程的路径。缺工具明确ValueError，不生成模板观察。
- ffprobe读取有效视频流的时长、原始宽高。排除attached_pic内嵌封面，并以实际视频流索引抽帧；拒绝没有视频流、没有有限正时长等结果。
- 在视频总时长的六个等分区间中点，各提取一张JPEG。6秒片对应0.5/1.5/2.5/3.5/4.5/5.5秒。画面按比例缩放到不超过1280×720的展示框，横竖比例保留；返回width/height仍是原视频元信息，抽帧图尺寸可以不同。
- 原文件只读，输出置于work_dir内独立media-随机ID子目录，不覆盖原视频，不清理其他项目文件。
- subprocess使用参数数组、shell=False、stdin禁用，Windows隐藏子进程窗口。每次工具调用最多25秒，单次分析总预算120秒；FFmpeg输入协议白名单为file,pipe，禁用HTTP等输入。
- 失败抽样位置仅记warning，保留真实成功帧；没有任何有效JPEG则明确失败，不补假帧。所有路径均为实际生成文件。

## 字幕边界

只读取与当前视频同目录、同主文件名的.srt/.vtt；同时存在时采用SRT并提示，不合并重复字幕。跳过指向视频目录外的字幕链接。只支持UTF-8/UTF-8 BOM及带BOM的UTF-16，不猜测其他编码；字幕文件上限2MiB。

字幕解析支持SRT毫秒逗号、VTT小数点、VTT cue id与位置设置，去除字幕格式标签并解码HTML实体，忽略NOTE/STYLE/REGION块。保留start/end/text，最多200段；越界结束点裁到视频尾并提示，非法/空段跳过。字幕来自外部文件，未对音轨逐句校验。

**没有相邻字幕时transcript为空，并明确说明未进行语音转写。** 本模块不调用Whisper或联网ASR，不把用户摘要冒充转录文本。

## 返回与可证明范围

```json
{
  "duration": 6.0,
  "width": 1280,
  "height": 720,
  "frames": [{"timestamp": 0.5, "path": "实际工作目录中的JPEG完整路径"}],
  "transcript": [{"start": 0.5, "end": 1.9, "text": "用户提供的字幕正文"}],
  "analysis_scope": "sampled_frames_and_supplied_subtitles",
  "warnings": ["均匀抽样可能漏掉短暂事件；未完整观看或进行ASR"]
}
```

这一步真实提取画面/字幕供后续模型或用户判断，本身不做画面语义识别、OCR或音频理解。不能仅因为抽帧成功就声称“完整看过视频”“识别了全部卖点”“听过所有口播”。root层仍需承担素材指纹和后续模型/证据引用校验。

emit可接收stage=media、progress和message。它只报告本机提取进度，不报告AI已分析或平台已上传。

## 已完成验证

tests/test_media.py先红灯再实现，覆盖以下行为：

- SRT实际分段、六个均匀位置、工作目录内真实JPEG文件及原视频不修改；
- VTT位置参数/NOTE/HTML标签与200段截断；
- 无字幕返回空transcript与明确无ASR提示；
- 缺素材/缺工具/缺有效视频流/非有限时长/超时；
- 所有抽帧失败不返回虚构结果；
- 内嵌封面不被当成主视频；
- 固定项目目录工具发现；
- 使用本项目真实FFmpeg与实际“上传功能测试_6秒.mp4”完成本地解码抽帧，不调用AI或平台。

实测元信息为6.0秒、1280×720，取得6张JPEG，时间点0.5/1.5/2.5/3.5/4.5/5.5秒；该测试片没有相邻字幕，transcript如实为空。一次复核生成的帧保存在项目work/desktop_R02/media_validation中；单元测试自己的临时目录会自动清理。

## 本次实际FFmpeg组件记录

项目内工具已由root放到runtime/ffmpeg/bin，后续打包位置约定为components/ffmpeg/bin。

- 工具版本：`N-126168-gb16b5f2a01-20260815`。
- 编译器：gcc15.2.0，crosstool-NG1.28.0.23_185f348。
- ffmpeg.exe：145811456字节；SHA-256 `4762609c60e0c6acfa478b6421d06fd1d1ebba4f5f033aac51ea316d960b8d1d`。
- ffprobe.exe：145595904字节；SHA-256 `f5df287b27e1e395608a441c08e262bc3675406cd0c86377d04b40476da260e6`。
- ffmpeg -L实际报告 **GNU GPL version3 or later**。不是默认LGPL构建：参数含--enable-gpl、--enable-version3、--enable-libx264和--enable-libx265；本次版本行未见--enable-nonfree，并有--disable-whisper。
- libavutil61.5.100、libavcodec63.8.101、libavformat63.6.100、libavfilter12.3.101、libswscale10.2.100。
- 从既有FFmpeg源工具文件夹核查，未找到LICENSE/COPYING/NOTICE/README现成资料可复制。本说明记录实际二进制自行输出的许可，不伪造原包附带许可文件或完整对应源码归档。
- 上游源码项目为[FFmpeg](https://git.ffmpeg.org/ffmpeg.git)，版本行给出的源码提交缩写为b16b5f2a01。最终随软件分发这些独立可执行工具时，应保留其GPLv3-or-later声明、GPL正文与准确构建/对应源码取得信息；本次没有声称已核实所有静态编译依赖的完整源码包。

媒体提取使用独立FFmpeg子进程，不把上述构建的库静态链接进本应用原创代码；不因此替本应用原创部分指定开源许可证。

