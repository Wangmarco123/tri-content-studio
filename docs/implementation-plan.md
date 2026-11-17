> R05 / 1.4.0：小红书自动登录、账号查询、上传、草稿与发布均已移除。仅保留内容生成与导出，由本人在官方App或网页手动发布。历史说明中的小红书自动操作不再适用。

# 三平台内容发布助手 Implementation Plan

> For agentic workers: independent modules implemented in parallel; root integrates and performs whole application review. Steps track actual verification; no permission pause beyond user authentication.

Goal: deliver a working Windows desktop EXE, persistent jobs and content workspace, AI HTTP/CLI/MCP interfaces and clean release.

Architecture: service and SQLite own state; native desktop and AI transports call it; isolated bounded platform worker. Tech stack: Python3.12, PySide6 Essentials, Patchright, biliup, PyInstaller. Spec: design.md. Contract: contract.md.

## Tasks

- [x] Core: real SQLite CRUD, hash, frozen job snapshots, idempotency/account queue, recovery to outcome_unknown, sanitized events; meaningful tests first.
- [x] Adapter: visible per-account persistent browser login/draft/publish/check and B站 engine; bounded submit-once with cancellation and unknown status; tests with transport/browser seams.
- [x] Operations: actual public hot-board fetch, evidence import, external-AI brief and validated packages, optional model calls; fixture/local server tests.
- [x] Desktop: polished native window with functional workspace, accounts, queue, settings, AI access and async operations; UI smoke and service integration.
- [x] AI transports: authenticated loopback REST+OpenAPI, JSON CLI client and stdio MCP; integration tests for authorization, error/unknown/idempotent paths.
- [x] Build: executable, sidecar browser/engine, clean portable copy, ZIP/hash/license/API docs/skill; relocated test and GUI/API acceptance.

Review focus: accidental public defaults, duplicate submissions, locked profiles, plaintext credential leakage, misleading hot metrics or local/remote completion, path relocation and missing dependencies. No broad tests for cosmetic edits; tests focus behavior and integration.

