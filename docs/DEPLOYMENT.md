# 部署与迁移指引（供人和 Agent 阅读）

目标：在一台新 Linux 主机上部署 QQ ↔ NapCat ↔ OpenCode v2，并按需启用 Mem0、
LlamaIndex、NapCat 原生工具和 WebUI。所有目录、账号和密钥都属于目标机器。
本仓库不包含可直接沿用的 QQ 登录、供应商凭据、聊天数据或私人角色设定。

## 0. 执行约定与需要的输入

部署 Agent 按本文件顺序推进，每阶段核对结果；缺少账号或模型信息时列出准确缺项，
继续完成不依赖这些输入的安装。不猜 QQ 号、模型、密钥和公网地址，不在回复中展示凭据。
不要通过真实发消息、点赞或禁言验证生产能力；最终 QQ 聊天联调由部署者主动发起。

先确认：Linux 发行版、Python 3.12+、网络与磁盘、Docker Compose、当前服务用户及 sudo 权限，
以及是否已有 NapCat、OpenCode 或 PostgreSQL。已有服务优先复用，不覆盖认证或重启无关服务。
配置和启动 OpenCode、安装插件、运行桥接必须使用同一系统用户，否则服务发现和配置目录会不一致。

需要部署者在本机提供：机器人 QQ 登录；授权用户和群号；可选超级管理员及记忆所有者；
主聊天供应商、真实模型 ID、API 地址和凭据；启用记忆／知识库时的模型凭据；可选管理域名及证书。
默认用普通服务用户运行即可，QQ Agent 能执行该用户有权执行的操作，应为它准备专用账户和资料目录。

## 1. 安装基础依赖并克隆

以下以 Ubuntu 24.04、当前登录用户为例。已有软件无需重复安装，其他发行版替换包管理命令。

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-dev build-essential file git curl
git clone https://github.com/LianjinSe/QQ-OpenCode-Bridge.git
cd QQ-OpenCode-Bridge
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock -e .
.venv/bin/python -m pip check
```

安装 Docker Engine 和 Compose plugin 后，用 `docker compose version` 确认。
普通用户需要已有的 Docker 操作权限；不要因为本项目随意改其他服务的 Docker 或代理配置。
Node.js 建议使用受支持的 22+ 版本，安装后用 `node --version` 核对，供 OpenCode 及插件运行时使用。
依赖安装失败时先定位网络、平台和具体包；不要无约束升级全部依赖。

## 2. 安装 OpenCode v2 并配置主模型

本桥接使用 **v2** 的 `/api/session`、prompt、steer、权限、表单和 instructions 等接口。
不能把 OpenCode v1 的 `provider/options/plugin` 配置当作 v2 的 `providers/settings/plugins`。
安装入口与配置参考：[v2 安装](https://dev.opencode.ai/v2/docs/)、
[v2 供应商](https://dev.opencode.ai/v2/docs/providers/)。

```bash
curl -fsSL https://opencode.ai/v2/install -o /tmp/qq-bridge-opencode-install.sh
bash /tmp/qq-bridge-opencode-install.sh
opencode --version
command -v opencode
```

确认版本以 `2.` 开头，并确保后台服务和 systemd 能找到该可执行文件。
也可使用官方列出的 `npm install -g @opencode/cli`。本分发版验证使用 v2.1.4；
其他版本必须经过末尾 `--check` 的 API 能力检查，不能仅凭版本号宣布兼容。

以**将运行桥接的同一用户**启动 OpenCode，在交互界面 `/connect` 配置账号、`/models` 选择主模型。
主模型必须支持工具调用；需要图片理解时还必须支持图片输入。
自定义 OpenAI 兼容供应商可参考 `deploy/opencode.example.json`，合并进该用户的
`~/.config/opencode/opencode.json`，不覆盖原有配置。替换 `custom`、API 地址、
`your-chat-model`；模型 ID 和工具能力必须与供应商真实支持一致。

示例的 `apiKey` 使用 `{file:./provider-api-key.txt}`，请在同一配置目录创建该私密文件并设 0600。
OpenCode 全局配置也设 0600。不把 API Key 写进命令参数、仓库或 Agent 提示词。
聊天模型的思考强度等参数按供应商和 v2 配置填写，不照抄别的模型参数。

```bash
opencode service start
opencode reload
opencode models
```

服务发现默认读取当前用户的 `~/.local/state/opencode/service.json`；该文件可能含认证，不打印。
显式连接已有远端 v2 时，可配置 `OPENCODE_URL/USERNAME/PASSWORD`，需已有安全连接和认证。
插件依赖同机 Unix socket，本指引的完整原生工具方案要求 OpenCode 与桥接在同一宿主机和用户下。

## 3. 建立独立工作目录和运行人格

在**仓库根目录**运行：

```bash
.venv/bin/python deploy/configure.py --workdir "$HOME/qq-agent-workspace"
```

它会生成当前机器专用的 `.env`、`deploy/compose.env`、`deploy/qqbot.local.service`，
安装以下目录结构；不会启动服务、打印密钥或覆盖已有文件：

```text
QQ-OpenCode-Bridge/          源码与 .venv
  .env                     私密配置，初始化填入本机绝对路径
  data/                    桥接／记忆 SQLite、知识原文、回执和 Docker 数据
  deploy/compose.env       生成的 NapCat WebUI Token 和数据库密码
  deploy/qqbot.local.service  按当前路径和用户生成的 systemd 单元
~/qq-agent-workspace/       独立 OPENCODE_WORKDIR
  AGENTS.md                通用 QQ 人格及原生工具使用规则
  opencode.json            稍后由 provision 脚本合并插件
  tools/imagegen.py        生图入口
  tools/bridge-python      指向本克隆 .venv/bin/python
  .qq-attachments/         任务输入（运行时产生）
  .qq-outbound/            本轮交付目录及快照（运行时产生）
```

**独立目录和其中的 AGENTS.md 是必需部署项。** 不能把源码仓库、某个私人项目或系统家目录本身当成
机器人工作目录，也不能把仓库根维护 `AGENTS.md` 当作运行人格。初始化会拒绝工作目录与仓库相互包含。
自定义人格可编辑独立目录的 `AGENTS.md`，按需要调整语气和工具使用说明。
已有文件会保留，部署 Agent 需要核对其内容与当前版本要求。

本地编辑 `.env`：填 `ALLOWED_USERS`，按需填 `ALLOWED_GROUPS`、`SUPERADMIN_USER_ID`、
`MEMORY_OWNER_USER_ID`。管理员必须在用户白名单内；群成员无需逐个加入用户白名单。
没有其他机器人时可将 `EXCLUDED_PREFIXES=` 清空。
初始化生成的 `NAPCAT_TOKEN` 稍后填入 NapCat 的 OneBot WS 配置，与 WebUI Token 分开。

如果有需求，建议按自己的使用场景修改权限，不建议完全不设置权限。优先从用户和群白名单、
管理员及已核实的只读工具范围等配置开始调整；需要改变默认审批或工具范围时，明确修改对应的
后端策略并验证。只改 `AGENTS.md` 的说明不会改变真实身份校验和后端权限判断。

## 4. 部署 NapCat 并登录

已有已登录 NapCat 时直接配置其正向 WS，不另启动同名容器。
新部署可使用 [NapCat 官方 Docker 项目](https://github.com/NapNeko/NapCat-Docker) 的镜像方案：

```bash
docker compose --env-file deploy/compose.env -f deploy/compose.yaml up -d napcat
docker compose --env-file deploy/compose.env -f deploy/compose.yaml ps
```

模板将 WebUI `6099` 和正向 WS `3001` 只绑定宿主机回环地址，容器内 WS 监听 `0.0.0.0:3001`。
远程服务器可在本地电脑执行 `ssh -L 6099:127.0.0.1:6099 服务用户@服务器`，
再访问 `http://127.0.0.1:6099/webui`。在服务器本地查看 `deploy/compose.env` 中的 WebUI Token，
自行登录并扫码 QQ；不要在聊天中转贴 Token、二维码、Cookie 或日志原文。

在 NapCat WebUI 的 OneBot 网络设置添加／核对 **WebSocket Server（正向）**：
启用、监听 `0.0.0.0`、端口 3001、消息格式 array、开启自身消息以外的推送，
`enableForcePushEvent=true`，OneBot Token 与桥接 `.env` 的 `NAPCAT_TOKEN` 一致。
字段模板见 `deploy/napcat-websocket.json`，不是整份 NapCat 配置，不覆盖已有网络客户端。
桥接使用 `NAPCAT_WS_URL=ws://127.0.0.1:3001`。WebUI 登录 Token 与 OneBot Token 不可混用。

所附 Docker 模板使用上游 `latest`；正式长期部署应记录并固定实际镜像标签或 digest。
容器账户、QQ 登录数据和插件目录都在 `data/napcat/`，不进入 Git。
若使用现有其他容器名，原生目录同步脚本当前默认访问 `napcat`，请在目标机器调整脚本或使用其
`--runtime-catalogue` 输入方式；不要为适应示例重命名或重建已有生产容器。

## 5. 注册基础附件工具

完成 `.env` 的白名单和 Token 后，在仓库根运行：

```bash
.venv/bin/python deploy/provision_delivery_tools.py
opencode reload
.venv/bin/python -m qqbot --check
```

provision 将本克隆的绝对插件路径和 socket/token 路径合并到独立工作目录的 `opencode.json`，
不修改供应商或其他插件。已有 JSONC 时脚本会明确拒绝新建覆盖配置，请手工合并同等条目。
以后启用其他能力按同样方式注册。插件仅通过本地认证 socket 调用桥接，活动任务绑定真实身份。

`--check` 不启动 OpenCode、不创建模型任务、不向 QQ 发消息。它必须同时确认 v2 API 和 QQ 在线。
若失败，停在连接问题排查，不把服务进程存在当作已部署成功。

## 6. Mem0 与 PostgreSQL/pgvector（可选）

Mem0 Python 包随 `requirements.lock` 安装，版本 `mem0ai==2.2.1`。
不需要 Mem0 云账号或另一个 Mem0 Server；本项目已实现证据、owner、遗忘和范围控制，保持 `infer=False`。
不要用官方通用示例另建不受这些规则约束的自动写入链路。

新部署可启用所附独立 PostgreSQL 16 / pgvector 容器：

```bash
docker compose --env-file deploy/compose.env -f deploy/compose.yaml --profile memory up -d postgres
docker compose --env-file deploy/compose.env -f deploy/compose.yaml exec -T postgres psql -U qqbridge -d qqbridge -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
```

默认宿主端口 `127.0.0.1:55432`，初始化已把专用随机密码和连接串写入 `.env`。
容器启动脚本只在空数据目录创建 `vector` 扩展；已有数据不自动更改密码或执行初始化 SQL。
该模板的数据库账号是**独立容器内**的初始化管理员，数据库仅用于本桥接，不连接共享业务数据库。
已有 PostgreSQL 时，管理员创建专用用户、数据库，执行 `CREATE EXTENSION IF NOT EXISTS vector`，
并配置自己的 `MEMORY_DATABASE_URL`，无需启动容器或安装 `qqbot-memory.conf`。
原生 PostgreSQL 安装参考 [官方 Ubuntu 说明](https://www.postgresql.org/download/linux/ubuntu/) 和
[pgvector 安装](https://github.com/pgvector/pgvector#installation)。

在本机 `.env` 填写并核对：

```dotenv
MEMORY_ENABLED=true
MEMORY_OWNER_USER_ID=你自己的真实QQ号
SILICONFLOW_API_KEY=仅在本机填写
MEMORY_BASE_URL=https://api.siliconflow.cn/v1
MEMORY_MODEL=deepseek-ai/DeepSeek-V3.2
MEMORY_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
MEMORY_RERANK_MODEL=Qwen/Qwen3-Reranker-8B
MEMORY_DIMENSIONS=1024
MEMORY_RERANK_ENABLED=true
MEM0_TELEMETRY=false
```

QQ 号占位文字不可直接使用；所有者必须在用户白名单中。模型名称为可调整示例，先确认供应商账户可用。
`SILICONFLOW_API_KEY` 是现有配置变量名；换兼容服务时也由它传入对应密钥。
接口必须支持当前客户端的结构化聊天、Embedding（包括维度）与重排协议，不能只验证普通对话。
本机不加载模型权重；主聊天、记忆和生图的模型用途相互独立。

```bash
.venv/bin/python deploy/provision_memory_tools.py
opencode reload
```

真正联调记忆时才运行 `.venv/bin/python -m qqbot.memory_check`：它会调用真实模型计费，
使用隔离临时集合，不发送 QQ 消息。常规部署不应默默运行付费联调。
参考 [Mem0 Python 文档](https://docs.mem0.ai/open-source/python-quickstart)，实际行为以本项目集成为准。

## 7. LlamaIndex 文档知识库（可选）

LlamaIndex core、PostgreSQL vector store、pypdf 和 Jieba 已随锁定依赖安装，
不需要另开 LlamaCloud、LlamaParse 或独立知识库进程。
复用第 6 步的模型配置和数据库，使用独立 `qq_knowledge` schema，SQLite FTS5 保存中文关键词索引。
可以只启用知识库、保持 `MEMORY_ENABLED=false`，但仍需要模型与数据库配置及真实超级管理员。

在 `.env` 设置 `KNOWLEDGE_ENABLED=true`，然后：

```bash
.venv/bin/python deploy/provision_knowledge_tools.py
opencode reload
```

启动桥接及 WebUI 后创建资料库，明确私人或开放群号，上传 Markdown、TXT、文字型 PDF。
单文件最多 10 MiB、100 万字符，PDF 最多 200 页；普通聊天附件不自动收录。
等后台索引就绪后，再从当前允许范围检索。失败时保留旧版，确认新版本而非旧版能检索才算更新完成。
`knowledge_write` 仅管理员私聊提交笔记，返回受理不代表索引完成。

Embedding 地址、模型和维度共同确定向量空间。已存在 Mem0／知识向量时不能直接改配置混用，
应备份并规划重建／迁移。更多范围与版本行为见 [knowledge.md](knowledge.md)，
上游组件参考 [LlamaIndex vector stores](https://developers.llamaindex.ai/python/framework/module_guides/storing/vector_stores/)。

## 8. NapCat 原生工具（可选）

需配置真实 `SUPERADMIN_USER_ID`，并在 `.env` 设置 `NAPCAT_TOOLS_ENABLED=true`。
随仓库提供的 4.18.41 目录是接口 schema 参考，不含账号状态；新机器必须核对实际版本和运行时目录。
QQ 已登录且 OneBot 已初始化后，在桥接**尚未启动**或维护窗口内运行：

```bash
.venv/bin/python deploy/sync_napcat_reference.py --output-root /tmp/qq-napcat-preview --refresh-docs
```

核对预览的 schema、版本与官方来源后，再不带 `--output-root` 发布到当前克隆，注册插件并重载：

```bash
.venv/bin/python deploy/sync_napcat_reference.py
.venv/bin/python deploy/provision_napcat_tools.py
opencode reload
```

目录同步只读获取本机能力，不执行发消息等动作。可选导入接口资料需已启用知识库、桥接停止且队列已复查：
`.venv/bin/python deploy/sync_napcat_reference.py --import-knowledge`。不要为导入构造在线状态库对象。
实际调用限制、幂等与 uncertain 处理见 [napcat.md](napcat.md)。

## 9. WebUI 和可选生图

管理台启用 `WEBUI_ENABLED=true`，默认只监听 `127.0.0.1:8093`。
SSH 转发：在自己电脑运行 `ssh -L 8093:127.0.0.1:8093 服务用户@服务器`，
打开 `http://127.0.0.1:8093`；使用这种方式时 `WEBUI_PUBLIC_URL` 保持空。
首次启动的本地 `data/webui-login.txt` 保存账号及初始密码，登录改密后删除。

需要公网管理域名时，修改 `deploy/qqbot-webui.nginx.conf` 中 `bot.example.com` 和证书路径，
将 `.env` 的 `WEBUI_PUBLIC_URL` 设为相同 HTTPS origin，不带路径。核对后安装配置、`nginx -t`，
再 reload Nginx。模板允许 11 MiB 知识上传，普通 JSON 仍限制 64 KiB。
不要把数据库、工作目录、Git 或整个项目挂到静态根目录。
管理台提供当前会话上下文占用估算和手动压缩，历史与子会话可单独查看。
压缩需要 OpenCode v2 原生 compact 接口并调用模型，确认聊天任务及执行树空闲后再操作；
受理不等于完成，按页面展示的实际状态核对，接口不支持时会明确提示。
升级后完成回复不再自动戳发起人，未发送的旧通知会被阻止，已尝试的历史回执保留。

WebUI 是可读取全历史的管理入口，使用独立管理员认证，界面不预装任何私人身份或域名。

非 root 服务用户使用 WebUI 重启按钮时，需要系统管理员单独授权对 `qqbot.service` 的 restart。
可参考 `deploy/qqbot-webui.rules.example`，仅替换服务用户并安装到 `/etc/polkit-1/rules.d/`。
不需要该功能时不安装；拒绝请求时界面如实显示失败。不要为此授予任意免密 sudo。

生图默认关闭；需要时设置 `IMAGE_GENERATION_ENABLED=true`、`IMAGE_PROVIDER`、真实 `IMAGE_MODEL`、
`IMAGE_OPENCODE_CONFIG`。当前生图客户端读取 v2 **JSON** 中 `providers.<id>.settings.baseURL/apiKey`，
支持 env/file 凭据引用，供应商必须支持 Images generations 和需要的 edits 协议。
仅配置 OpenCode 登录凭据而没有这些字段不够；示例模型名不能直接调用。
人格已说明使用独立工作目录中的 `tools/bridge-python tools/imagegen.py`，按本轮目录生成后调用 `qq_send_files`。

## 10. 启动、验收与升级

首次安装使用生成的单元，启动前确认当前 `.env` 和工作目录可由生成单元中的用户读取：

```bash
set -e
.venv/bin/python -m qqbot --check
sudo install -m 644 deploy/qqbot.local.service /etc/systemd/system/qqbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now qqbot.service
systemctl is-active qqbot.service
journalctl -u qqbot.service -n 60 --no-pager
```

日志应表明 OpenCode 已连接、NapCat `online=True`；启用记忆时还需存储就绪，知识库在管理台显示对应状态。
不要把日志中的原文和凭据完整复制到 Agent 回复。依赖不可用时说明缺项，不能把进程 active 当作全部能力成功。
验收独立目录／人格、插件绝对路径、QQ 登录、模型与连接后，由部署者自行从白名单 QQ 发普通消息，
再视需要测试一个附件、记忆和知识查询。未经明确要求不让部署 Agent 主动给真实 QQ 发测试消息。

升级前检查任务、出站、记忆和知识工作，以及原生工具 pending/uncertain 状态；
排空后停止桥接并复查再备份。不清空队列，不自动改会话映射，不重启无关服务。
只改代码／环境通常只重启桥接；插件变更重新 provision 并 `opencode reload`。
修改已安装 systemd 单元后才 `daemon-reload`。

## 11. 迁移与备份

首次分发使用全新数据；迁移自己已有部署时，在停机且队列复查后一致性备份：
桥接及记忆 SQLite（含正确处理 WAL）、`data/knowledge` 原文和目录、NapCat 登录卷、
专用 PostgreSQL 逻辑备份、OpenCode 配置／认证／历史与服务用户目录、QQ 工作目录及定制人格。
这些都是私密迁移材料，只通过私密渠道运输，不能推到公共仓库。
Docker PostgreSQL 可用 `docker compose ... exec -T postgres pg_dump -U qqbridge qqbridge` 做逻辑备份，
恢复时核对 PostgreSQL、扩展及向量配置版本。

新机代码目录、用户或工作目录变化后，更新 `.env` 全部绝对路径、重新注册所有已启用插件，
更新 `tools/bridge-python` 链接和服务单元，再运行连接检查。
现有 OpenCode 会话绑定旧工作目录，不能仅改字符串宣称历史可复用；需要保留路径布局或显式规划会话迁移。
QQ 已接收新消息后，不覆盖旧数据库回滚，以免丢任务或重复发送。

公开 Git 的内容仅限源码、测试、通用人格与模板。提交前检查 `git diff --cached`：
不能包含 `.env`、compose.env、auth、Token、数据库、日志、登录二维码、聊天、附件、备份或自定义私人 AGENTS.md。
工具返回 `queued`、HTTP 受理、模型连通和实际 QQ 交付是不同状态，交付报告必须准确区分。
