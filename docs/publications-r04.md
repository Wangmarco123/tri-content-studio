> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R04：作品查询与发布回读

Windows 版本 1.3.0。账号页增加“查询作品”，CLI、HTTP 与 MCP 共用同一任务队列和账号锁。HTTP 仅监听本机，仍需本地 Bearer token；不要把 token、cookies 或用户浏览器目录交给外部服务。

## AI 接口

- `POST /api/v1/publications/query`：`{"platform":"douyin","account":"creator"}`。返回只读查询任务；轮询 `/jobs/{id}` 获取作品编号、链接、标题、时间、时长、可见范围与证据。
- `GET /api/v1/publications`：查询历史。
- `POST /api/v1/jobs/{id}/reconcile`：`{"query_job_id":"job_...","remote_id":"..."}`。严格核对同平台、同账号、标题、提交时间和时长，再记录实际可见范围。
- `POST /api/v1/publications/update`：B站修改已核实原稿，需 `draft_id`、`matched_job_id`、明确 `visibility`。复用原视频编号，回读标题、简介、TAG 和可见范围；不会创建新视频。
- `POST /api/v1/jobs/{id}/resolve-unsubmitted`：仅处理有完整旧事件证据、明确在提交前失败的旧任务。查不到作品本身不足以解除重复保护。

MCP 新增 `query_publications`、`reconcile_publication`、`resolve_unsubmitted`、`update_publication`，共21项工具。CLI可用 `request` 调用同一路由。

## 完成与重复保护

发布回执、作品存在、可见范围和平台审核分别记录。响应不明时不再次点击发布。相同文件即使换路径或重复导入也按SHA256查重；存在待执行、正在执行、已提交或结果不明的同平台任务时阻止重复上传。

抖音和小红书查询使用本软件自己的持久会话与浏览器运行时，读取创作者页面的返回数据。小红书空的权限文案不会被当成公开：另打开既有作品权限面板读取当前值，然后取消，不修改设置。B站查询走登录态HTTP。平台验证码、扫码和设备验证仍交由本人完成。

作品列表覆盖有限：抖音、小红书为当前页；B站最多5页、每页20条。未查到不能证明未发布。接口不承诺审核通过、推荐流量或永不触发验证。发布仍依赖平台当前页面和登录状态，并不是三个平台均有官方发布API。
