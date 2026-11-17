> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# R01 module contract

Python package: studio. New version source only. Stdlib core/HTTP, PySide6 UI, Patchright adapters. Agents must not alter sibling module ownership.

## Data

Platforms: bilibili,douyin,xiaohongshu. Account default creator. Asset: id,path,name,size,sha256,summary,audience,facts(list of strings),keywords(list of strings),created_at. Draft: id,asset_id,platform,title,caption,tags(list of strings),hook,visibility(default draft),evidence_ids(list),fit_reason. Evidence: id,platform,title,source_url,fetched_at,source_updated_at(optional),rank(optional),metric(optional dict),verification.

Job: id,platform,account,action(login/check/open_drafts/draft/publish),asset_id(optional),draft_id(optional),payload(snapshot dict),status,message,progress,created_at,updated_at,result. Scheduler serial and durable. status queued/running/awaiting_user/draft_saved/submitted/outcome_unknown/failed/cancelled/complete. Submitted is not published.

## Core (root)

Store(data_dir: Path): persists SQLite. Service(project_root: Path, data_dir: Path|None=None, start_worker=True). service.store exposed. service.health()->dict; assets()->list; add_asset(payload:dict)->dict; update_asset(id,payload)->dict; drafts()->list; save_draft(payload)->dict; evidence()->list; import_evidence(payload:dict with items:list)->dict; fetch_trends(platform:str,keyword:str='')->dict; export_brief(asset_id:str)->dict; import_packages(payload:dict with asset_id/packages:list)->dict; generate(payload:dict)->dict; jobs()->list; create_job(payload:dict)->dict; get_job(id)->dict; events(id)->list; cancel_job(id)->dict; accounts()->list; settings()->dict(redacted); save_settings(payload)->dict; close(). service.paths.data_dir/project_root/token_path.

GUI and core operations use these exact methods. All mutating errors ValueError; API maps to error JSON. Each data record dict has string id. GUI may always catch exceptions and show error. Core default account paths project_root/state/<platform> (xiaohongshu uses xiaohongshu-sau). Existing native MCP is inactive.

## Adapters (agent adapter)

studio/adapters.py: execute(job:dict, context:dict, emit:Callable[[dict],None])->dict. context keys engine_root,state_root,cancel_path (all string paths),browser_path(optional). Job payload includes file,title,caption,tags,visibility,account,remote_id(optional). emit fields stage,message,progress(optional),qr_path(optional),requires_user(optional). Return status,message,remote_id/url/visibility/evidence(optional). A cancellation file signals stop; check during waits; never retry final submit. This function is run in an isolated worker process by root. Worker emits sanitized JSONL into a private job directory. Tests no real accounts. Existing engines found using relative paths or manifest; no shell=True, no reads outside explicit account scopes.

## Operations (agent ops)

studio/operations.py pure API: fetch_trends(platform:str,keyword:str='',timeout:int=15)->dict {items:list,status,message,source_url,fetched_at}. validate_packages(payload:dict,asset:dict,evidence:list)->list[dict] normalized platform draft records, rejecting nonexistent evidence and malformed fields. build_brief(asset:dict,evidence:list)->dict {schema_version,asset,evidence,instructions,response_schema}. generate_packages(asset,evidence,config:dict)->list[dict], optional OpenAI-compatible HTTPS or explicitly local HTTP base_url/model/api_key, bounded timeout; no default credentials. No video transfer; send summary/facts only. Source operations tests use local HTTP server/fixtures. Root handles storage, threading/security. Keep no DB/UI dependencies.

## UI (agent GUI)

studio/gui.py run(service, api_info:dict)->int. api_info contains endpoint,token_path,openapi_url,version. Call service APIs above. Native QtWidgets only. Can use optional entry smoke test. Assets table/add/edit; operations evidence fetch/import, brief export, packages import/generate, three platform draft editor; account login/check; jobs actions and cancel; AI connection docs/token copy local; settings for LLM config. Credentials masked and saved via service. Do not make internet requests from UI outside service. UI long calls in QThread/QRunnable, timer refresh jobs. No automatic publish, only explicit draft/publish action with visibility chosen. Native dialogs/logs in Chinese. Leave cross-platform differences visible.
