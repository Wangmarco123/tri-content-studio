> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# Qt / PySide6：许可证、对应源码与共享库替换

本程序使用 Qt for Python（PySide6 Essentials、Shiboken6）6.12.0。Qt6Core.dll的产品版本为6.12.0.0。当前运行库来自已安装的PyPI分发轮子；本项目未修改这些库。对安装目录内的240个DLL/PYD进行了静态SHA-256检查，全部符合各轮子随附RECORD，详见 `licenses/Qt-6.12.0/WHEEL-BINARY-INTEGRITY.json`。该检查证明与本机轮子记录一致，不冒充独立的上游签名认证。

本程序以PyInstaller onedir方式分发，Qt共享库位于 `_internal/PySide6/`，Shiboken位于 `_internal/shiboken6/` 或其实际打包位置；Qt插件保留在PySide6子目录。它们是独立DLL/PYD，不要求用户修改或重新签名本程序才可替换；应用不对这些Qt库实施自定义签名/哈希锁定。系统级代码签名、架构和ABI规则仍然适用。

## 许可与调试权利

适用许可证完整原文已保留在 `licenses/Qt-6.12.0/pyside-setup/LICENSES/` 与各Qt模块LICENSES目录中，包括 LGPL-3.0-only.txt、GPL-3.0-only.txt及相应补充条款。安装轮子的商业授权引用文本同时保持原样，不表示本用户购买过商业授权。

本程序不限制LGPL所允许的、为调试用户对库所作修改而进行的必要逆向工程、共享库替换或重新链接。没有通过本说明向本程序全部原创代码另授MIT或其他开源许可；第三方库的使用和修改权利按它们各自许可证执行。

## 替换兼容共享库

1. 关闭本程序及其内容控制客户端，备份整个应用目录。无需删除本人素材、账号或任务数据。
2. 准备Windows x64、与Python3.12稳定ABI及PySide6/Shiboken6 6.12系列兼容的Qt构建。优先以本次6.12.0对应源码和构建说明重建，保留与原轮子匹配的编译器/运行库、构建配置和插件ABI。不要把不同架构或不兼容主版本DLL混在一起。
3. 在 `_internal/PySide6/` 中替换相应 `Qt6*.dll`、PySide6绑定PYD与需要同步的Qt插件；修改涉及Shiboken时，配套替换对应的Shiboken库。QtGui、QtWidgets、QtNetwork、QtSvg和图像插件之间有依赖，不能任意只拷一个不同版本的DLL。
4. 保持既有相对目录布局和DLL文件名；不要替换Windows系统目录中的库。替换后运行应用的本地自检，核对Qt版本，再检查窗口、图像和网络功能。因ABI不兼容失败时恢复备份。
5. 若需要调整装载规则，可使用本程序提供的构建脚本按同一onedir布局重新打包；本程序没有以静态链接或库哈希校验阻止替换。文件替换支持与“任意修改后的库已测试兼容”不是同一结论。

当前已核对最终发行目录中Qt6Core/Gui/Network/Svg/Widgets为独立DLL，并保留独立平台、图像、样式等插件。尚未用人为修改后的Qt构建做完整替换运行验收，不能声称任意替换都已验证。

## 准确对应源码

完整固定版本入口和commit在 `licenses/Qt-6.12.0/CORRESPONDING-SOURCE-URLS.json`；可查看源码树或下载同commit的源码归档，无需安装新软件即可查看文本。

| 组件 | 对应源码与下载 |
|---|---|
| PySide6 / Shiboken6 | [pyside-setup 6.12.0源码](https://github.com/pyside/pyside-setup/tree/f50facb83fc3dc5f3240c854668c7a6dd93871b2) · [源码归档](https://github.com/pyside/pyside-setup/archive/f50facb83fc3dc5f3240c854668c7a6dd93871b2.tar.gz) |
| QtCore / QtGui / QtWidgets / QtNetwork及基础插件 | [qtbase 6.12.0源码](https://github.com/qt/qtbase/tree/025bdad181de241e81bf853c8a2d7bf3d19261a9) · [源码归档](https://github.com/qt/qtbase/archive/025bdad181de241e81bf853c8a2d7bf3d19261a9.tar.gz) |
| QtSvg及SVG插件 | [qtsvg 6.12.0源码](https://github.com/qt/qtsvg/tree/883a58532078d003cefef0a549bfe9f885ce41f5) · [源码归档](https://github.com/qt/qtsvg/archive/883a58532078d003cefef0a549bfe9f885ce41f5.tar.gz) |
| 扩展图像格式插件 | [qtimageformats 6.12.0源码](https://github.com/qt/qtimageformats/tree/dc13f2fbff1d579cfb2eb2d9092e3563b4d05b8e) · [源码归档](https://github.com/qt/qtimageformats/archive/dc13f2fbff1d579cfb2eb2d9092e3563b4d05b8e.tar.gz) |

Qt官方上游也可从 [Qt代码站](https://code.qt.io/)、[Qt官方源码下载](https://download.qt.io/official_releases/qt/) 和 [Qt for Python构建文档](https://doc.qt.io/qtforpython-6/building_from_source/index.html) 获取相应版本与构建信息。固定tag为v6.12.0；本说明没有把最新main分支当作对应源码。

## Qt第三方材料

本次从Qt/PySide官方项目的v6.12.0源tag补齐190份许可证、第三方版权文件与 `qt_attribution.json`，覆盖pyside-setup、qtbase、qtsvg、qtimageformats。每文件来源、原Git blob及SHA-256保存在 `licenses/Qt-6.12.0/SOURCES.json`。这些材料包含源码模块可能支持的平台，不代表每个组件都在此Windows应用中启用；保留原声明而不删去其权利信息。

本说明服务于本机用户运行与库替换。若未来另行公开分发或修改第三方库，发行人应继续保留相应许可证、准确源码和修改/构建信息，并按实际分发方式完成源代码可获得性安排；不能只靠本页声明推断任意后续分发都已满足全部条件。
