> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R02 一键AI方案接口约定

用户已明确授权改造：选择视频、一键调用AI自动研究和生成，五块结果直接可见。R01完整复制、哈希802文件一致，R01冻结交付保留。

## Service（root实现）

- `ai_status()` -> `{codex:{available:bool, logged_in:bool, message:str}, api:{configured:bool}, default_provider:'codex'|'api'|'none'}`。不回传凭据。
- `start_campaign(payload)` -> campaign record。payload `{asset_id,provider:'auto'|'codex'|'api', goal?:str}`，默认auto优先本机已登录Codex。异步启动，不阻塞Qt。
- `campaigns()` / `get_campaign(id)` / `cancel_campaign(id)`。
- `save_campaign(payload)` -> `{items:[draft,...],count:3,jobs:[job,...]}`。payload `{id, selections?:{bilibili:int,xiaohongshu:int}, queue_drafts?:bool}`。所有文案默认本地draft，queue_drafts只创建抖音/小红书草稿，B站仅存本地；不公开发布。完成生成已自动保存第一候选为三平台本地文案，用户选其他标题后save更新既有draft版本。

campaign record `{id,asset_id,status:'queued'|'running'|'complete'|'failed'|'cancelled',stage,progress,message,provider,created_at,updated_at,result:null|CampaignResult,draft_ids:[str]}`。

stage `media`抽取画面/字幕、`research`读取公开热点、`ai`AI搜索匹配和生成、`validate`校验保存、`complete`。GUI每1秒读get_campaign，失败显示真实原因，不伪造结果。可取消AI子进程，不涉及平台发布。

## CampaignResult（operations agent校验）

`validate_campaign(payload, asset, evidence, media=None) -> normalized dict`，payload：

```
{
  asset_id: string,
  summary: string,
  opportunities: [{id:string,platform:bilibili|douyin|xiaohongshu,title:string,
    kind:hot_topic|activity|expression|evergreen,evidence_ids:[string],why_relevant:string,query_time:string}],
  fit_assessments: [{opportunity_id:string,verdict:direct|connection|not_fit|needs_extra,
    reason:string,segments:[{start:number,end:number,observation:string,
      evidence_type:sampled_frame|subtitle|user_fact}],supports_features:[string],limits:[string]}],
  packages: [{platform,title,title_candidates:[string],caption,tags:[string],hook,
    category_suggestion:string,search_keywords:[string],visibility:draft,
    evidence_ids:[string],fit_reason,tag_checks:[...]}],
  no_trend_reason:string
}
```

恰好三平台各1包。B站和小红书各2~5候选标题（不强制不自然数量也可先实现2~5）；抖音hook必填。B站category_suggestion、XHSsearch_keywords必填。其他平台无关字段可为空。title须为候选之一。热点至少真实来源、同平台ID；没有合适热点允许opportunities空但no_trend_reason非空。引用同平台证据，不将榜单快照冒充涨速。segments时间必须0<=start<=end<=media.duration（有media时）；没有抽帧/字幕不得声称分析完整视频或听过声音。

root另给最终result添加 `sources:[evidence,...]` 与`media:{duration,width,height,frames:[{timestamp,path}],transcript:[...],analysis_scope,warnings}` 供GUI直接展示来源、时间、片段依据。

R01 `validate_packages`扩展保留title_candidates/category_suggestion/search_keywords，但旧包未提供仍兼容。`build_brief(asset,evidence,media=None)`可扩展可选media；root新AI provider会用campaign专门prompt/schema，因此不要让旧API provider强制返回整个campaign。

AI模型可以返回 `research_sources:[{id,platform,title,source_url,queried_at,source_published_at,notes}]`（新搜索原链接）——root先限制平台域名、重映射ID并导入证据，再调用validate_campaign；validator只处理已存在evidence ID。UI不直接解析research_sources，用result.sources。

## 媒体（media agent实现）

`analyze_media(asset,work_dir:Path,engine_root:Path,emit=None)` -> `{duration,width,height,frames:[{timestamp,path}],transcript:[{start,end,text}],analysis_scope:'sampled_frames_and_supplied_subtitles',warnings:[string]}`。无字幕不声称完成ASR。root将ffmpeg/ffprobe复制到runtime/ffmpeg/bin并随包。
