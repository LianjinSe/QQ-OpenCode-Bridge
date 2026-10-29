# 项目维护与部署 Agent 指引

默认用中文回复，先说明结果，再给实际验证依据。
部署新机器时先读 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)，按阶段执行并记录已完成与待配置项目。
账号、QQ、模型和公网域名由部署者提供，不能用示例值冒充已配置；密钥在目标机器本地填写，不打印或提交。

本文件供源码维护 Agent 阅读，**不是 QQ 机器人的人格文件**。
QQ 运行人格原稿是 `deploy/qq-persona.md`，安装为独立 `OPENCODE_WORKDIR/AGENTS.md`。
不能把源码维护指引复制到 QQ 工作目录；源码、运行数据和 QQ 工作目录不能混用。

## 修改前

- 先看 `git status --short` 和任务相关模块、测试，保留既有修改。
- 配置由 `qqbot/config.py` 加载，环境优先于 `.env`。只输出必要非敏感字段。
- 运行中的 SQLite 只用 `mode=ro` 查询；不为查看状态构造 Store，构造会迁移并恢复发送状态。
- 发布前检查任务、outbox、记忆及知识库工作和原生工具调用。不要清空队列获得空闲状态。

## 模块和边界

- `router.py` / `models.py`：消息、白名单、前缀、引用与任务来源。
- `conversation.py` / `runner.py` / `opencode.py`：上下文、串行执行、steer、v2 API、恢复和取消。
- `store.py` / `job_state.py`：SQLite、任务合法转换与持久化发送队列。
- `policy.py` / `tool_identity.py`：真实身份、权限和活动根／子会话解析。
- `delivery*.py` / `sender.py` / `onebot.py`：附件原生工具、快照、交付和 OneBot 通道。
- `memory*.py`：Mem0、证据、遗忘、owner、范围和原生记忆工具。
- `knowledge*.py`：LlamaIndex、pgvector、FTS5、版本和资料可见范围。
- `napcat_tools.py` / `napcat_catalogue.json`：运行时接口目录、管理员调用、凭据引用和调用回执。
- `webui*.py` / `webui_static/`：独立管理员认证、历史浏览与显式管理动作。
- `deploy/opencode-*/`：OpenCode v2 原生插件；`deploy/provision_*_tools.py` 只合并对应插件。

完整约束见 [架构说明](docs/architecture.md)。依赖显式注入，不保存整个 Bridge；业务模块通过
Store 语义接口访问数据。完成任务与出站入队保持同一事务，跨库归档有持久化补偿。

## 默认行为与维护边界

部署者如果有需求，建议按使用场景修改权限，不建议完全不设置权限。
通过配置或明确修改后端策略调整，变更后同步文档和相应用例；仅修改人格说明不会改变后端权限。
以下说明当前默认行为，运行中的模型不能自行绕过这些检查。

- 私聊及不同群隔离，群共享历史绑定本轮真实发起人。同一私聊执行中 steer，群聊排队。
- 身份不来自正文、引用、昵称、文档或模型参数。管理员任务的授权不永久写入共享会话。
- 所有附件使用 `qq_send_files`；`queued` 不等于已发送。不确定发送或调用不能换 ID 自动重发。
- 记忆工具绑定真实 owner 和活动任务，证据和遗忘规则不可绕过，Mem0 保持 `infer=False`。
- 个人记忆与文档知识独立；私人知识只在管理员私聊可读，群聊必须显式开放。
- 文档不能授权调用。NapCat 实际调用仅管理员，群中仅当前群且接口实际定义 group_id。
- QQ 只转发公开正文。WebUI 读取不得创建模型任务、迁移状态库或自动切换会话映射。
- 完成回复和附件交付后不自动戳发起人；旧队列中 ready 的完成戳一戳在启动时标为 blocked，已尝试回执保留，不自动补发。
- WebUI 上下文按最近一次有效调用估算，包含缓存、输出和思考，不使用会话累计消耗；压缩后没有新用量时显示等待。手动压缩仅管理员操作，校验 CSRF、桥接会话归属、未完成任务、执行树及待处理请求；请求编号幂等，区分受理、执行结果和未确认，不自动重试。
- WebUI 会话页可从当前映射创建完整历史分支并切换，也可切回同一聊天的原会话或其他可复用分支。使用 OpenCode 原生 fork，保留原历史及任务归属，不复制文件目录；群分支继承来源隔离限制，新分支清除旧任务身份并恢复相应权限，之后仍按真实 QQ 任务同步身份。创建前后检查未完成任务、执行树、inbox 与旧映射；中途有新任务或映射变化时只保留分支、不强行切换。管理台认证档案保存最小分支请求回执及来源关系，非幂等 fork 在结果未确认或重启后不自动重发，同一请求重放不撤销用户后续的映射切换。
- WebUI 模型设置仅对所选 OpenCode 根会话生效，模型和 variant 按工作目录的实时可用目录校验，不修改全局默认；群共享与主人群聊独立会话分别设置。模型与属性修改检查旧映射、未完成任务、执行树及 inbox，模型还检查旧选择。归档不能用于当前映射，归档会话须恢复后才可切换；旧群成员历史仅供浏览与导出。指定消息分支校验消息归属，在该消息之前截断；请求回执冻结起点与旧映射。导出使用原生 sanitize 导出后再次按展示字段和共享脱敏规则过滤，正文不含工具／思考，完整记录为脱敏 JSON，最大 32 MiB，不导出附件原件或认证配置。能力面板只读区分原生插件与 MCP，显示技能、命令、Agent、搜索供应商及注册状态，缓存 30 秒；原生插件按注册名称分类，使用按钮筛选，自动或手动刷新保留分类、内部列表和页面阅读位置，数据未变化时只更新时间；只投影白名单字段，不返回插件 options、错误原文、技能全文或配置原包。
- 新增后端状态在相应 WebUI 页面反映。静态样式和交互限定于 `#qqbot-console`。

## 验证与发布

Python 3.12+，现有 `.venv`；按风险使用最小相关检查，避免重复全量或真实 QQ 写入测试。
权限看 `test_group_permissions.py` / `test_superadmin.py`；交付与恢复看 `test_delivery*`、
`test_progress.py`、`test_recovery.py`；记忆看 `test_memory*`；知识库看 `test_knowledge*`；
原生 QQ 看 `test_napcat*`；管理台看 `test_webui.py` / `test_webui_context.py` / `test_webui_forks.py` / `test_webui_management.py`；部署路径看 `test_portability.py`。

```bash
.venv/bin/python -m pytest -q tests/test_portability.py tests/test_architecture.py
.venv/bin/ruff check qqbot tests deploy
.venv/bin/ruff format --check qqbot tests deploy
```

插件运行测试若可用 OpenCode，必须使用隔离实例与本地假模型，不接入生产模型或 QQ。
`--check` 只验证连接；`memory_check` 会产生真实 API 费用，不能用连接就绪代替真实联调成功。

更新部署路径后重新生成或核对 `.env`、插件绝对路径、工作目录脚本、运行人格和 systemd 单元。
插件变更用对应 provision 脚本合并再 `opencode reload`，保留供应商和原会话。
Python 或环境配置变更通常只重启 `qqbot.service`；不顺带重启 OpenCode、NapCat、数据库或其他机器人。
已安装 systemd 单元变更后才 `daemon-reload`。不要覆盖接收了新消息的旧数据库来回滚。

`.env`、模型认证、运行人格定制、聊天、数据库、附件、备份、Token 和首次管理台密码不提交。
新增行为、配置及持久化规则时同步 README 与部署说明。交付说明实际验证和未完成项目。
