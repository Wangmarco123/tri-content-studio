> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# 本机 API 方法与结构化 Schema

R02 使用 OpenAPI 3.0.3。实际文档由当前服务的 `GET /api/v1/openapi.json` 返回；`GET /api/v1/health` 与兼容入口 `GET /health` 不需令牌。其余接口需要 `Authorization: Bearer <本机令牌>`。只接受 loopback Host，拒绝包含 Origin 的浏览器跨源请求。不要把本机令牌写入公开示例或日志。

## 路由与方法

| 路由 | 方法 | 请求 | 成功响应 |
| --- | --- | --- | --- |
| `/api/v1/ai/status` | GET | 无 | AIStatus，不回传凭据 |
| `/api/v1/campaigns` | GET / POST | POST为CampaignStart | GET为Campaign数组；POST返回异步Campaign |
| `/api/v1/campaigns/{id}` | GET | 无 | Campaign，包含五块生成结果 |
| `/api/v1/campaigns/{id}/cancel` | POST | 可无正文 | Campaign，只取消AI生成 |
| `/api/v1/campaigns/{id}/save` | POST | CampaignSave | CampaignSaveResult：items、count=3、jobs |
| `/api/v1/assets` | GET | 无 | Asset 数组 |
| `/api/v1/assets` | POST | AssetCreate | Asset |
| `/api/v1/assets/{id}` | PUT | AssetUpdate | Asset |
| `/api/v1/drafts` | GET / POST | POST 为 DraftCreate | GET 为 Draft 数组；POST 为 Draft |
| `/api/v1/evidence` | GET | 无 | Evidence 数组 |
| `/api/v1/evidence/import` | POST | EvidenceImport | items、count |
| `/api/v1/trends/fetch` | POST | TrendsRequest | items、status、message、来源与时间 |
| `/api/v1/briefs/{id}` | GET | 素材 ID 在路径中 | Brief |
| `/api/v1/packages/import` | POST | PackagesImport | Draft items、count |
| `/api/v1/generate` | POST | GenerateRequest | Draft items、count |
| `/api/v1/jobs` | GET / POST | POST 为 JobCreate | GET 为 Job 数组；POST 为 Job |
| `/api/v1/jobs/{id}` | GET | 无 | Job |
| `/api/v1/jobs/{id}/events` | GET | 无 | Event 数组 |
| `/api/v1/jobs/{id}/cancel` | POST | 可无正文 | Job |
| `/api/v1/jobs/{id}/qrcode` | GET | 无 | `image/png` 二进制 |
| `/api/v1/accounts` | GET | 无 | Account 数组 |
| `/api/v1/settings` | GET / POST | POST 为 SettingsUpdate | Settings，API Key 不回显 |

服务使用与 OpenAPI 相同的路由方法表进行准入，再执行对应服务方法。路径必须完整匹配，除 `/health` 外不提供未版本化别名。已知路由使用不支持的方法返回 JSON 405，并带 `Allow` 头；不存在或多出路径片段的路由返回 JSON 404。`PUT /jobs`、`PUT /settings`、`PUT /evidence/import` 和 `PUT /jobs/{id}/cancel` 都不会执行 POST 操作。PATCH、DELETE、OPTIONS 等已实现的方法入口也遵守相同约束。

## Schema 契约

R02新增AIStatus、CampaignStart、CampaignSave、TitleSelections、Campaign、CampaignResult和CampaignSaveResult。标题选择索引从0开始；queue_drafts默认false，仅保存本地文案。显式true只排抖音/小红书draft，不为B站投稿，也不公开发布。API/MCP版本均从studio.__version__生成；旧R01路由保持兼容。完整五块结果结构见r02-contract.md与operations-r02.md。

`components.schemas` 定义素材、素材新增/编辑、文案、公开证据、导入包、AI任务、模型配置、账号状态、任务快照、任务结果、事件、错误等结构。所有正式请求/响应通过 `$ref` 关联，不再只有泛 `object`。路径 ID、数组元素、必填字段、平台/动作/可见范围枚举、只写密钥、可空结果与二进制二维码分别描述。

JobCreate 使用 `oneOf` 区分三种输入：

- AccountJobCreate：login、check、open_drafts，明确平台，可指定本地账号别名。
- DraftJobCreate：draft，引用已保存的 draft_id，服务强制使用草稿范围。
- PublishJobCreate：publish，引用 draft_id，并要求 visibility 为 private 或 public。

客户端不把本机文件路径直接拼进发布请求。服务从素材和文案生成冻结的 JobSnapshot，保留文件摘要与执行参数。`submitted` 是提交受理，不是审核通过；`outcome_unknown` 需要人工核对，不能自动重发。取消只停止本地工作，不撤回远端稿件。

模型 Key 仅在 LLMConfig 的 `api_key` 写入字段出现，并标记 `writeOnly`。Settings 响应只包含 base_url、model、has_api_key。留空 Key 不覆盖已有值；clear_api_key 可明确清除。

少数扩展点有意保留开放对象：公开指标 Metric 的 provider 字段、适配器 JobResult 的 evidence、嵌入的 JSON Schema 文档，以及 OpenAPI 自身结构。这些不是任意执行入口；不能将公开指标扩展字段解释为统一搜索量、推荐权重或预测结果。

OpenAPI 描述接口结构。素材是否存在、证据引用、平台标题策略、账号别名、同一任务幂等性与可见范围等业务限制仍由 Service 和运营模块校验，HTTP 层不另建第二套业务状态。模型生成只发送明确的事实摘要和公开证据，不接收或传输视频正文。

## 成功与错误

成功使用 HTTP 200，集合查询直接返回 JSON 数组；导入/生成返回带 items、count 的对象。二维码成功响应使用 `image/png`，不能按 JSON 解析。

错误格式为：

```json
{"error":{"code":"invalid_request","message":"可理解的错误原因"}}
```

OpenAPI 分别记录 400（验证失败）、401（令牌不正确）、403（来源或 Host 被拒绝）、404（路径不存在）、405（方法不支持）、413（JSON 正文超过 2 MiB）、500（内部失败）。异常不回传认证信息或内部堆栈。浏览器跨源/Host 检查和私有接口鉴权优先于业务路由调用。

## 本地验证范围

真实 loopback HTTP 测试覆盖令牌、Origin、素材新增/编辑、证据导入、Brief、文案包导入、设置和账号查询、任务创建/取消/事件、精确路径匹配、错方法零写入、Schema引用完整性，以及二维码的二进制响应声明。测试使用隔离 SQLite 与本地素材占位文件，不运行平台上传或真实登录，不据此声称平台已经验收。
