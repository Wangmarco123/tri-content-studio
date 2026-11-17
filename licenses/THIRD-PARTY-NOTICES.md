# 第三方软件声明 / Third-party notices

## R03 1.2.0 ASR补充（原R01声明保留）

R03构建环境固定faster-whisper 1.2.1（MIT）、CTranslate2 4.8.1（MIT）、PyAV 16.1.0（BSD-3-Clause，保留其轮子附加声明）、onnxruntime 1.32.0（MIT及ThirdPartyNotices）、tokenizers 0.23.3（Apache-2.0）、huggingface-hub 2.4.0（Apache-2.0）、NumPy 2.5.5（BSD-3-Clause及轮子所列0BSD/MIT/Zlib/CC0-1.0等）。PyAV实际固定16.1.0；19.0.2与当前faster-whisper使用的metadata_errors接口不兼容，不把较新版本当作本次携带版本。对应安装METADATA与RECORD所列许可由刷新脚本归集到python-packages-r03；安装包未携带的CTranslate2/tokenizers原文另保留在ASR，来源见ASR/SOURCE-URLS.json。缺少正文的其他包仅记录missing，不据元数据短字段声称许可材料完整。

源码入口：[faster-whisper v1.2.1](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1)、[CTranslate2 v4.8.1](https://github.com/OpenNMT/CTranslate2/tree/v4.8.1)、[PyAV v16.1.0](https://github.com/PyAV-Org/PyAV/tree/v16.1.0)、[ONNX Runtime v1.32.0](https://github.com/microsoft/onnxruntime/tree/v1.32.0)、[tokenizers v0.23.3](https://github.com/huggingface/tokenizers/tree/v0.23.3)、[huggingface_hub v2.4.0](https://github.com/huggingface/huggingface_hub/tree/v2.4.0)、[NumPy v2.5.5](https://github.com/numpy/numpy/tree/v2.5.5)。这些对应版本入口与实际分发METADATA共同用于定位源码，不表示本目录携带了完整依赖源码或穷尽全部静态依赖义务。

本地模型为mobiuslabsgmbh/faster-whisper-large-v3-turbo，固定revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`；[固定模型文件及模型卡](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo/tree/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf)。模型卡标MIT并说明转换自OpenAI Whisper large-v3-turbo，原卡及Whisper MIT文本保留于ASR/model；运行时仅加载本地文件，不隐式下载。CUDA 12.4系列独立DLL为cublas64_12.dll、cublasLt64_12.dll、cudart64_12.dll，适用原NVIDIA条款而非MIT；保留[CUDA 12.4.1 EULA及可再分发组件条款](https://docs.nvidia.com/cuda/archive/12.4.1/eula/index.html)原HTML于ASR/CUDA，[CUDA 12.4归档来源](https://developer.nvidia.com/cuda-12-4-0-download-archive)供核查。不得将CUDA主版本号或本次文件收集当作所有后续分发均获授权的保证。

components/asr/ASR-MANIFEST.json记录打包模型、CUDA DLL及实际包版本/字节哈希；licenses/LICENSE-FILE-HASHES.json覆盖许可资料；最终SHA256-MANIFEST.json覆盖整个发行包。三者都是字节完整性核对材料，不是上游签名、代码签名或精确SBOM。python-packages-r03/ENVIRONMENT-INVENTORY.json会包含当前构建Python全环境的直接/传递依赖及构建工具，明确是环境清单，不能宣称每项都进入最终可执行程序。

本目录保留三平台内容发布助手 R01 所用第三方组件的原始许可证与声明，核查日期为2026-11-16。第三方著作权属于各自权利人。该文档不为本应用的原创代码指定许可证，不将本应用擅自声明为MIT，也不代表所有组件的分发核验已经完成。

## 版本与来源

以下版本来自本次实际安装的分发元数据、运行时文件或既有安装记录。包完整元数据在python-packages子目录；其许可证文本保持原样。构建工具清单包含于此，并不表示所有构建工具都随最终应用运行。

| 组件 | 实际版本/识别 | 许可证依据及源代码入口 |
|---|---|---|
| CPython | 3.12.14 | 原运行时LICENSE.txt已复制至Python-3.12.14；Python历史许可/PSF条款见原文。[CPython对应版本源码](https://github.com/python/cpython/tree/v3.12.14)，[Python官方源代码入口](https://www.python.org/downloads/source/)；实际独立运行时为uv管理的python-build-standalone构建，[构建项目](https://github.com/astral-sh/python-build-standalone)。 |
| PySide6 Essentials / Qt | 6.12.0；Qt6Core.dll产品版本6.12.0.0 | 已安装METADATA写LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only。原商业授权引用保持原样；已从官方v6.12.0补齐完整LGPL/GPL、补充条款与第三方声明，见Qt-6.12.0。未修改轮子动态库，240个DLL/PYD均符合原RECORD。固定源码链接及库替换说明见随附docs/qt-relink.md。 |
| shiboken6 | 6.12.0 | 与本次PySide6元数据同一许可表达式；完整开源文本在Qt-6.12.0/pyside-setup/LICENSES，原商业引用也保留。 |
| Patchright Python | 1.64.4 | Apache-2.0，实际wheel许可证已复制。[源代码](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python)，[对应版本包](https://pypi.org/project/patchright/1.64.4/)。已安装元数据另明确底层Playwright Python源码v1.64.1和patchright-core 1.64.3，不将这几个版本混为一个。 |
| Patchright驱动及Node | patchright-core 1.64.3（driver package）；Node文件产品版本24.22.1 | Node主许可和其完整附加声明在Patchright-driver/Node-LICENSE；打包JS的独立许可证在Patchright-driver/lib/。保留ThirdPartyNotices.txt。[Patchright core](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)，[Playwright Python v1.64.1](https://github.com/microsoft/playwright-python/tree/v1.64.1)，[Node对应源码](https://github.com/nodejs/node/tree/v24.22.1) |
| Segno | 1.6.6 | 实际LICENSE为BSD-3-Clause文本，位于python-packages/segno-1.6.6.dist-info/licenses/LICENSE。[源码](https://github.com/heuer/segno)，[对应分发包](https://pypi.org/project/segno/1.6.6/) |
| Pillow | 13.0.0 | MIT-CMU；其完整LICENSE还附带wheel打包的Brotli等库许可证，不能只保留主库短声明。已完整复制。[源码](https://github.com/python-pillow/Pillow/tree/13.0.0)，[对应分发包](https://pypi.org/project/Pillow/13.0.0/) |
| PyInstaller | 6.22.3 | GPLv2-or-later with bootloader/special exception，实际COPYING.txt已复制。例外允许按其条款分发非自由/商业应用，不等于把第三方库义务一并豁免。[对应源码](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3)，[对应包](https://pypi.org/project/pyinstaller/6.22.3/) |
| biliup Windows CLI | 1.3.5 | 主包未附主LICENSE，已从官方v1.3.5 tag只读取得MIT原文；源Git blob c9a98b9d5127920785c0b34f93a65194108136f8。另保留安装包THIRD-PARTY-NOTICES.txt（DanmakuFactory派生算法声明）。[准确tag源码与主LICENSE](https://github.com/biliup/biliup/tree/v1.3.5)。**同tag README另有“禁止商业用途”陈述，与MIT文字存在范围冲突，尚未解决，不作已获商用许可结论。** |
| 浏览器 | Patchright revision1248，156.0.8078.4 | browsers.json标识Chrome for Testing；ABOUT实际写Google Chrome及Google版权。已保存该二进制chrome://credits的HTML与完整许可证文本（489个组件/许可块），以及chrome://terms的中文附加服务条款，修改日期2025-09-30。见chrome-for-testing目录。不是可以简单整包声明BSD的纯Chromium发行版。[Chrome for Testing官方项目](https://github.com/GoogleChromeLabs/chrome-for-testing)，[Chromium源码对应版本](https://chromium.googlesource.com/chromium/src/+/refs/tags/156.0.8078.4/)，[Chromium官方说明](https://www.chromium.org/getting-involved/download-chromium/) |

## 其他实际安装依赖

| 组件 | 版本 | 实际元数据/许可证 |
|---|---|---|
| greenlet | 3.5.6 | MIT AND PSF-2.0；LICENSE及LICENSE.PSF均保留 |
| pyee | 14.0.0 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause，三个原始许可文件保留 |
| altgraph | 0.17.5 | MIT，主要用于构建 |
| pefile | 2024.8.26 | MIT，主要用于构建 |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause，主要用于构建 |
| pyinstaller-hooks-contrib | 2026.10 | 完整原LICENSE已保留，按其中hook/运行时例外条款处理 |
| setuptools | 84.2.1 | MIT主许可，主要用于构建 |

更多源代码链接见INSTALLED-COMPONENTS.json的Project-URL以及各分发包METADATA。获取对应版本时，应选择与上表版本一致的tag/源码分发包并保留原版权与修改说明；仅链接最新main分支不能代替对应版本源码。

## Qt动态链接、替换与源码获取

本应用采用PyInstaller onedir布局，Qt/PySide/Shiboken以独立DLL/PYD及插件动态装载，不对第三方库作重命名加密或完整性锁定。使用开放许可路径时，不能限制用户为调试库修改而进行必要的逆向工程或重新链接。替换与本程序兼容、ABI匹配的Qt/PySide/Shiboken库后仍应能够运行；仅有动态链接形式不能自动证明履行全部LGPL义务。

替换说明：先关闭应用并备份，保留原目录布局，将发行目录内部的PySide6、shiboken6相关DLL/PYD和Qt插件用同架构兼容构建替换。构建时应保留独立共享库，而不是把Qt静态绑定进不可替换的自有二进制。真正发行位置与替换步骤必须在打包产物形成后核对，并实际验证可加载替换库；本次尚未做替换试验。

对应源码获取入口：
- [Qt for Python / pyside-setup v6.12.0](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.12.0)含PySide与Shiboken源码及其许可目录；
- [Qt 6官方源码分发](https://download.qt.io/official_releases/qt/)和[Qt各模块源码](https://code.qt.io/cgit/qt/)：获取与实际携带库版本一致的6.12.0以及其依赖/构建信息；
- [Qt关于LGPL的官方义务说明](https://www.qt.io/development/open-source-lgpl-obligations)与[Qt for Python LGPL原文入口](https://doc.qt.io/qtforpython-6/overviews/qtdoc-lgpl.html)。

这些是可定位源码的公开入口；精确tag/commit和源码归档地址另见Qt-6.12.0/CORRESPONDING-SOURCE-URLS.json。本地已补齐四个对应Qt/PySide官方源项目v6.12.0的190份许可/第三方声明；未把许可证文本收集冒充下载了完整Qt源码归档。用户可从所列固定源码树和归档地址获取对应源码。实际共享库替换步骤和本机使用边界见docs/qt-relink.md；将来另行分发或修改库时应据实际分发方式保留源码与修改信息。

## 资料状态与核验边界

1. Qt缺少许可正文的问题已补齐：LGPL3/GPL3/GPL2及Qt相关第三方材料均来自官方v6.12.0；190份原文的来源和摘要可复核。
2. 已核对onedir的独立共享库布局，提供准确源码获取入口及替换说明；未用人为修改的Qt库做完整兼容替换测试，不声称任意修改构建均已验证运行。
3. Chrome for Testing版权导出已补齐并离线核查：原chrome-credits.txt仅含可见组件索引，不能当成完整许可正文；保存的HTML含489个隐藏许可证块，另提取为chrome-credits-full.txt。chrome-terms.html/txt为真实中文Chrome/ChromeOS附加服务条款，正文一致，含2025-09-30日期与AVC段落，不是网络错误页。该附加条款通过链接引入Google一般服务条款；本目录不冒充已经包含被引用网站的所有条款全文。未将Chrome-for-Testing工具仓库的Apache-2.0误用作浏览器整包许可证。
4. biliup官方tag的MIT与README“禁止商业用途”范围冲突仍在；本说明保留原文、不消除冲突。其Rust静态依赖完整许可清单也未由现有converter notices穷尽。
5. 以上为构建环境材料归集，不是最终EXE逐文件SBOM。最终打包后应确认实际携带哪些DLL、字体、图像库、浏览器及构建运行时，再保留相应声明。
6. 首轮提取已有文件，续轮按任务授权补充官方Qt/PySide源tag的许可证文本与元数据；没有运行浏览器、安装新依赖或擅自赋予本应用原创代码任何开源许可。安装环境和最终发行文件可能不同，不把资料准备宣称为对一切后续分发的合规保证。

