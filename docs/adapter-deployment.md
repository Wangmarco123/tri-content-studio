> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# Adapter deployment — Windows x64 R01

核对时间：2026-11-16。本文是内部部署记录。核对的是当前适配器、已安装运行组件与冻结 worker 路径；没有读取账号状态、登录、上传或调用 CUA。

## 最小独立目录

```text
release/
  三平台内容发布助手.exe       # GUI；以实际打包名称为准
  ContentCtl.exe              # 必须与 GUI 同级，支持 _worker
  _internal/                  # 若使用 PyInstaller onedir，保留完整目录
    patchright/
      driver/
        node.exe
        package/              # 整个目录，不仅 cli.js
          cli.js
          browsers.json
          lib/ ...
    ...                       # Python/PySide6/segno/greenlet 等打包依赖
  components/
    biliup/
      biliup.exe
      LICENSE
      THIRD-PARTY-NOTICES.txt
    browsers-douyin/
      chromium-1248/
        INSTALLATION_COMPLETE
        DEPENDENCIES_VALIDATED
        chrome-win64/         # 完整目录，含所有 DLL、pak、locales、resources 等
          chrome.exe
          chrome.dll
          icudtl.dat
          locales/ ...
          resources/ ...
  licenses/ ...               # 按发布清单保留第三方许可
```

若采用 onefile，Patchright 的 driver 位于 PyInstaller 临时解包目录；`inspect.getfile(patchright)` 会用于定位它，不能改成开发环境绝对路径。外置 `components` 仍相对 GUI/ContentCtl 所在 release 根定位。

账号、运行数据库和 API token 应由软件首次运行创建。干净发布副本不得预装项目现有 `state`、浏览器 profile、Cookie、日志、request/result/events、账户二维码、桌面数据库或 LLM 配置。客户包不需要原脚本工程、内部版本记录或本文。

## 需要复制的来源及范围

1. B站：从项目 `runtime/biliup/biliupR-v1.3.5-x86_64-windows/` 复制 `biliup.exe` 和 `THIRD-PARTY-NOTICES.txt`；从 `原始制作/biliup/LICENSE` 保留对应项目许可证。当前视频上传适配器不使用 render-tools、字体或渲染工具，不需要为此复制这些大文件。若以后开放 B站渲染功能，须重新核对它们。
2. 浏览器：完整复制 `runtime/browsers-douyin/chromium-1248/`。只复制 `chrome.exe` 不可运行，必须保留同目录 DLL、资源、locale 和子目录。适配器使用显式 `executable_path`、`headless=False`，不会运行浏览器下载器。
3. 当前可见浏览器动作不需要 `chromium_headless_shell-1248`。没有录像/录屏动作，不需要外置 `ffmpeg-1013`。显式浏览器路径也不依赖 `winldd-1007` 或开发环境 `.links`；这些可不复制。为保守完整发行而保留 ffmpeg/winldd 也可以，但应保留许可证。切勿复制 `.links` 中的开发环境路径。
4. Python 包：打包入口实际需要 `patchright`、`segno`、`greenlet` 及依赖。Patchright 1.64.4 当前驱动配套 Chromium revision 1248，版本 156.0.8078.4。应保持这一组合，不混入旧 1.58.2 driver。

## PyInstaller 关键要求

- 两个入口 `desktop_main.py` 与 `contentctl.py` 都必须包含 `studio.adapters` 和 `studio.browser_worker`；若 spec 未自动分析 worker 的动态导入，显式加 hidden-import。
- 使用 PyInstaller 的 Patchright hook，或 `--collect-all patchright` 收集整个包。打包后必须实际存在 `patchright/driver/node.exe`、`driver/package/cli.js`、`driver/package/browsers.json` 与驱动 package 的其余文件。
- `--collect-all segno`（或验证分析已带入 writers 等动态模块）；B站二维码输出 PNG，不要求额外图片库。
- 运行环境若设置 `PLAYWRIGHT_NODEJS_PATH`，Patchright 会优先用该路径。独立版验证应清除此开发环境覆盖，确保使用包内 node.exe；不能依赖电脑已有 Python/Node/Chrome。
- `ContentCtl.exe` 需支持 `_worker --request <file> --events <file> --result <file>`。当前 `jobs.worker_command()` 在 frozen 情况下先找同级 ContentCtl.exe。缺失时虽然回退 GUI exe，但当前 GUI 入口没有 `_worker` CLI 分派，因此应将 ContentCtl.exe 同级存在作为强制打包检查，不能依赖 fallback。
- 当前 `studio.app` 的 frozen 根为 `Path(sys.executable).parent`，根队列以该根传 `engine_root`，适配器据此发现 components；不需要开发工程源码路径。

## 路径发现与账号隔离

`find_bili()` 依次在 engine_root 下扫描 `runtime/biliup`、`components/biliup`、`biliup`。`browser_options()` 支持 context.browser_path 指向明确 chrome.exe/浏览器目录，否则依次扫描 `runtime/browsers-douyin`、`components/browsers-douyin`、`browsers-douyin`。最小 release 只保留一版组件，避免模糊选择。

队列传入的 `state_root` 是 release/state 根。抖音 profile 为 `state/douyin/profiles/<account>`；小红书为 `state/xiaohongshu-sau/profiles/<account>`。B站 creator 沿用 `state/bilibili/cookies.json`，其它账号隔离到 `accounts/<account>/cookies.json`。首次干净运行无会话时只报告需要登录，不访问原项目或其它软件账户。

不要复制活跃浏览器 profile；不能以 Cookie JSON 备份代替完整 profile 的 IndexedDB。运行中的账号锁由 OS 释放，适配器不会删除外部锁或杀已有浏览器。

## 当前核验结果与后续门禁

- 已检查安装组件：B站 exe 的 `upload --help` 支持 `--submit web`、`--limit`、`--is-only-self`；没有账号操作。
- 已检查 Patchright `_impl/_driver.py`：按包位置寻找 driver/node.exe 和 package/cli.js；当前 browsers.json 是 Chromium 1248。
- 已检查 Chromium 可执行文件的依赖文件及 resources/locales 等子目录存在。组件发现逻辑已用空临时 fixture 验证 components 布局，不运行 fixture exe。
- adapter 的 16 项离线安全测试通过；部署路径测试另覆盖 components 下 B站和浏览器发现。
- 本次检查时 outputs 仅有测试素材，尚没有完成的独立 release。因此**不能宣称最终 release 已排除认证资料，也不能宣称冻结 worker/Patchright 已在搬移目录启动成功**。

root 组装后需在独立含中文和空格路径检查：两个 exe 同级；Patchright driver 资源齐全；components 完整；未含任何原项目 state/auth 文件。首次启动会创建新的运行 state，因此审计应在第一次运行之前做，并将之后 smoke-test 的临时账号/数据库与干净发行副本分开。

建议最终冻结 smoke 使用本地 about:blank 或 set_content 的浏览器动作，不登录、不访问账号、不上传；同时执行 ContentCtl.exe 帮助/health 与 _worker 的离线测试任务，验证 Qt GUI 调度不会错误地重新启动 GUI。平台线上行为仍需用户授权的独立验收，打包验证不等于客户电脑或账号发布验收。
