> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R03 Windows 打包与隔离验收

此文档用于维护与打包。版本 1.2.0；正式 Inno 入口仍为 `scripts/installer.iss`。R02 发布物保持独立，不覆盖。

## 输入与前置核验

使用项目内 `runtime/python-desktop-r03/venv/Scripts/python.exe`，依赖固定在 `requirements-build.txt`。构建脚本保留仅所选 Python、Windows/System32、Windows 的清洁 PATH，避免其他软件的 ICU/OpenSSL DLL 冲突。ASR CUDA DLL 只由独立语音 worker 使用本组件目录加载，不加入系统 PATH。

模型从 `runtime/asr/models/faster-whisper-large-v3-turbo` 复制到发布物 `components/asr/models/faster-whisper-large-v3-turbo`。模型必须已完成下载，包含 model.bin、配置、预处理配置、分词器、词表、README 和 MODEL-MANIFEST.json；构建前根据 manifest 检查大小及 SHA256，固定仓库 `mobiuslabsgmbh/faster-whisper-large-v3-turbo` 的 revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`。构建不会下载模型。运行时使用本地模型，禁止隐式下载。

CUDA 从 `runtime/asr/cuda` 仅复制 cublas64_12.dll、cublasLt64_12.dll、cudart64_12.dll。不会复制 Hugging Face 下载缓存、账号、模型下载日志或中间文件。发布时生成 `components/asr/ASR-MANIFEST.json`，记录模型/CUDA 的大小和 SHA256、ASR Python 依赖版本；模型原始来源 manifest 一并保留。此散列是文件完整性记录，不是数字签名，也不表示所有 NVIDIA 显卡都可运行。

ASR wheel 内许可证按 RECORD 收集到 `licenses/ASR`。CTranslate2 与 Tokenizers 当前 wheel 没有许可证原文，需在构建前补到源码 `licenses/ASR/ctranslate2`、`licenses/ASR/tokenizers`；模型及 CUDA 授权分别放 `licenses/ASR/model`、`licenses/ASR/CUDA`。缺少这些资料时构建拒绝继续。其他组件原有许可证保留。原包的组件清单与许可证索引只说明原有范围；新增 ASR 组件以 ASR-MANIFEST 与最终全包 SHA256-MANIFEST 为准。

## 构建命令

以下在 R03 `source` 目录执行，输出目录每次使用新名称。脚本拒绝覆盖已有同名 release 目录。先确认模型 manifest 已生成、许可证已补齐，再执行：

```powershell
$project = (Resolve-Path '..\..\..').Path
$python = Join-Path $project 'runtime\python-desktop-r03\venv\Scripts\python.exe'
& $python scripts/build_windows.py --project $project --out "$project\work\desktop_R03\candidate_01" --revision R03
& $python scripts/finalize_release.py --candidate "$project\work\desktop_R03\candidate_01\三平台内容发布助手_R03" --release "$project\outputs\三平台内容发布助手_R03"
```

finalize 会校验 ASR manifest、完整复制候选、刷新文档和许可证、拒绝带私有状态/下载缓存的发布物，生成全文件 SHA256-MANIFEST 和支持 ZIP64 的绿色版 ZIP。ZIP 与最终目录不能使用已有输出名称。

Inno Setup 在固定源目录执行，`ISCC.exe` 使用本机实际安装位置：

```powershell
& 'ISCC.exe' "/DPackageDir=$project\outputs\三平台内容发布助手_R03" "/DInstallerOut=$project\outputs" scripts/installer.iss
```

模型约 1.62GB、CUDA 约 0.57GB，另有主程序/浏览器/FFmpeg，启用 DiskSpanning，单片约 1.566GB。安装器 EXE 和所有同名前缀 `.bin` 必须一起交付并置于同一文件夹；只发送 Setup.exe 无法安装。安装升级不打包或删除用户 state/profile。需预留候选、正式目录、ZIP、安装分片和独立验收副本空间，不能只按模型大小估计剩余磁盘。

## 隔离验收

```powershell
& $python scripts/accept_release.py --release "$project\outputs\三平台内容发布助手_R03" --work "$project\work\desktop_R03\acceptance_01" --video '<本地短测试视频>'
```

默认在新目录复制应用，清洁 PATH/PYTHONPATH，检查所有 ASR 文件散列、本地模型与依赖就绪、浏览器离线页、CLI/HTTP/MCP、无账号 worker、显式发布范围及 GUI。不登录、不上传。`--asr-wav '<本地PCM WAV>'` 可额外用冻结 ContentCtl 独立 CPU worker 做真实模型转写，1800秒超时，不请求 AI 或平台；仅 doctor ready 不能证明模型实际能推理。`--real-ai` 是显式的真实 AI 一键完整链路测试，会查询公开热点并调用已登录 Codex，结果必须包含 speech.complete=true，仍不发布。

需分别记录 CPU 冻结推理、目标电脑 GPU 推理与一次 CPU 回退；存在 CUDA DLL 不等于显卡/驱动可用。完整转写表示音轨处理完成，不等于逐字识别准确。安装分片的编译、安装后搬迁和真实语音推理需由实际执行结果验收，本脚本变更本身不证明打包成功。
