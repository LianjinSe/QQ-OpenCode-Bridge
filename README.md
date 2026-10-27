# QQ-OpenCode-Bridge

通过 NapCat OneBot v11 正向 WebSocket，把 QQ 私聊和群聊连接到 **OpenCode v2** 的 Python 桥接服务。
支持持续会话、工具调用、文件交付、长期记忆、文档知识库和独立管理台。

首次部署请按 [Agent 部署指引](docs/DEPLOYMENT.md) 操作。也可以把该文件交给部署 Agent，
按目标机器和你自己的账号、模型配置逐步安装。维护源码前阅读 [AGENTS.md](AGENTS.md)。

## 功能

- 私聊用户白名单、群白名单及真实 @ 触发；私聊和不同群隔离，同群成员共享上下文。
- 普通任务串行执行；同一私聊运行中的补充消息通过 OpenCode `steer` 加入当前任务，群聊保持排队。
- 按 NapCat 真实 QQ 和当前任务判断权限；超级管理员任务默认授权，普通群成员的文件修改等操作需审批。
- 引用文字、图片、视频、音频、文件、合并转发与网页分享卡片；直接附件以 `file:` URI 提交给 OpenCode。
- 原生 `qq_send_files` 发送图片、视频、文件和音频；持久化快照、累计限制、幂等及不确定发送保护。
- 可选 Mem0 + pgvector 个人记忆：证据、范围隔离、遗忘、纠正和每日摘要。
- 可选 LlamaIndex + 独立 pgvector schema 文档知识库：中文关键词和语义检索、重排、版本切换、方法笔记。
- 可选 NapCat 原生接口工具：运行时 schema、管理员及当前群限制、不透明凭据引用和最小调用回执。
- WebUI 独立账号登录，查看历史、任务、工具、记忆和知识库，显式切换会话映射、取消任务和重启桥接。

## 部署入口

需要 Linux、Python 3.12+、`file`、Node.js（OpenCode 及插件运行时）、OpenCode **v2**、NapCat。
Docker Compose 用于所附 NapCat 和 PostgreSQL 模板；已有服务也可以接入。
Mem0 与 LlamaIndex 是桥接内的 Python 依赖，无需另部署它们的云服务或独立 HTTP 服务。

```bash
git clone https://github.com/LianjinSe/QQ-OpenCode-Bridge.git
cd QQ-OpenCode-Bridge
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock -e .
.venv/bin/python deploy/configure.py --workdir "$HOME/qq-agent-workspace"
```

初始化只创建本机配置和目录，不启动服务，不覆盖已有 `.env`、人格或工具文件。
随后根据部署指引完成 QQ 登录、OneBot Token、白名单、模型、插件注册和连接检查，再启动桥接。
不要直接把模板 systemd 文件安装到系统；使用初始化生成的 `deploy/qqbot.local.service`。

**必须为 OpenCode 提供独立工作目录及其中的 `AGENTS.md`。** 源码目录、数据目录和机器人工作目录要分开。
仓库根 `AGENTS.md` 给维护／部署 Agent 使用；`deploy/qq-persona.md` 才是 QQ 聊天运行指引，
初始化时复制到 `OPENCODE_WORKDIR/AGENTS.md`。不让 QQ Agent 在源码仓库或包含私人资料的目录中执行任务。

## 配置

全部变量见 [.env.example](.env.example)，环境变量优先于 `.env`。密钥只在目标机器填写。

| 配置 | 作用 |
| --- | --- |
| `NAPCAT_WS_URL`、`NAPCAT_TOKEN` | 正向 WS 连接和 OneBot Token；与 NapCat WebUI 登录 Token 分开 |
| `ALLOWED_USERS`、`ALLOWED_GROUPS` | 私聊与群白名单；群白名单为空时只开放私聊 |
| `SUPERADMIN_USER_ID` | 真实管理员 QQ，必须同时在用户白名单中 |
| `OPENCODE_WORKDIR` | 独立工作目录的绝对路径，包含运行时 `AGENTS.md` 和插件配置 |
| `OPENCODE_BINARY`、`OPENCODE_SERVICE_FILE` | 当前服务用户的 OpenCode 可执行文件及私有服务发现文件 |
| `OPENCODE_MODEL` | 可选 `provider/model` 覆盖；为空时继承 OpenCode 默认模型 |
| `STATE_DB`、`MEMORY_DB` | 桥接与记忆 SQLite 路径；初始化生成当前仓库下的绝对路径 |
| `MEMORY_ENABLED`、`KNOWLEDGE_ENABLED` | 分别启用个人记忆和文档知识库，默认关闭 |
| `NAPCAT_TOOLS_ENABLED` | 启用管理员 NapCat 接口能力，默认关闭 |
| `WEBUI_ENABLED`、`WEBUI_PUBLIC_URL` | 管理台和可选自有 HTTPS 地址；无预设公网域名 |
| `IMAGE_GENERATION_ENABLED` | 可选图片生成／编辑，需自有 Images API 供应商和模型，默认关闭 |
| `DELIVERY_IMMEDIATE` | `false` 在任务成功后交付附件；`true` 允许执行期间开始发送 |
| `EXCLUDED_PREFIXES` | 兼容其他机器人的消息前缀；不需要时可设为空 |

聊天模型必须支持工具调用。图片理解还需模型支持图片输入；附带配置的模型名称均为占位符。
记忆默认提供 SiliconFlow 的聊天、Embedding 和重排模型示例，可按实际兼容接口配置，
它们与 OpenCode 主聊天及生图配置独立。已有向量索引更换 Embedding 地址、模型或维度时必须迁移。

## 通用聊天人格与工具

分发版使用诚实、友好、正常聊天的 AI 助手人格，无指定 QQ 关系、私人称呼或个人角色经历。
你可以编辑工作目录中的 `AGENTS.md` 自定义语气，但应保留工具、身份、记忆、知识库和交付规则。
人格修改通常在后续请求中加载；无需清空聊天或重置会话映射。

| 原生工具组 | 安装入口 |
| --- | --- |
| `qq_delivery_context`、`qq_send_files` | `deploy/provision_delivery_tools.py`，基础部署必装 |
| `memory_search/remember/update/forget/history/diary/evidence` | `deploy/provision_memory_tools.py`，启用记忆后安装 |
| `knowledge_list/search/read/write` | `deploy/provision_knowledge_tools.py`，启用知识库后安装 |
| `napcat_list/describe/schema/call/upload/export/result` | `deploy/provision_napcat_tools.py`，核对目标 NapCat 目录后安装 |

插件在 OpenCode 专用目录的 `opencode.json` 中合并，保留原有供应商和其他插件。
若已有 JSONC，需手动合并而非新建覆盖；随后 `opencode reload`。身份从活动任务派生，不接受模型自报身份。
生图入口为专用目录的 `tools/imagegen.py`，通过 `tools/bridge-python` 使用桥接虚拟环境。

## WebUI

默认关闭，仅监听 `127.0.0.1:8093`。可用 SSH 转发访问，或配置自有 HTTPS 域名。
首次启动生成管理员 `admin`；初始密码保存在 `STATE_DB` 同目录 `webui-login.txt`，权限 0600。
在服务器本地查看并登录后改密，不把初始密码贴入聊天或日志。

界面使用通用“助手”名称和新建 SVG 图标，不包含原部署的域名、私人头像和人格内容。
登录后的管理页会显示**当前部署**的 QQ、路径和历史以便管理，因此管理入口仍需认证与适当访问控制。
反向代理模板中的 `bot.example.com` 及证书路径必须替换为自己的配置。

## 常用指令

`/help` 查看帮助，`/status` 查看任务，`/cancel` 取消，`/new` 开始新上下文；
`/approve`、`/reject`、`/answer` 处理批准和问题。
启用记忆后提供 `/remember`、`/forget`、`/memories`、`/diary` 及 `/memory` 管理。
`/new` 保留长期记忆；`/memory purge` 的删除范围比普通遗忘更大。

## 文档与验证

- [部署指引（含 Agent 执行顺序、验收与迁移）](docs/DEPLOYMENT.md)
- [架构与事务边界](docs/architecture.md)
- [附件工具与发送语义](docs/delivery.md)
- [知识库及可见范围](docs/knowledge.md)
- [NapCat 工具与接口同步](docs/napcat.md)
- [WebUI 与会话管理](docs/webui.md)

测试使用本地假模型、假 NapCat 和临时数据库，不向真实 QQ 发送消息。
使用 `python -m pytest` 或设置正确 `PYTHONPATH`，确认导入的是当前克隆副本。

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check qqbot tests deploy
.venv/bin/ruff format --check qqbot tests deploy
.venv/bin/python -m qqbot --check
```

`--check` 仅验证 OpenCode v2 API 和 NapCat 在线状态，不创建模型任务。
`python -m qqbot.memory_check` 会调用真实模型并计费，只有需要真实记忆联调时才运行。

项目代码采用 [MIT](LICENSE)。字体、Lucide 图标及 NapCat 参考资料的来源和许可见
[第三方说明](THIRD_PARTY_NOTICES.md)。本仓库只包含分发源码、通用模板和测试，不携带部署数据或认证文件。
