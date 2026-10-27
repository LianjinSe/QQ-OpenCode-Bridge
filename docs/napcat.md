# NapCat 全接口参考与原生工具

接口知识库与实际调用分别管理。资料覆盖本机 OneBot 注册目录及官方 API 文档，
每个 action 有功能、参数、返回结构、示例、来源和可用状态。
本机目录以登录实例的 `/api/Debug/schemas` 为准，调用前核对 `get_version_info`；
不把官方新版接口的存在等同于当前安装可用，也不会为此自动升级或重启 NapCat。

## 工具

| 工具 | 用途 |
| --- | --- |
| `napcat_list(query?, offset?)` | 按功能和名称查接口，分页每次 25 项 |
| `napcat_describe(action)` | 查本机参数 schema、示例、分类和可用状态 |
| `napcat_schema(name)` | 按需展开公共消息段／数据结构 |
| `napcat_call(action, params)` | 校验并调用本机已注册接口 |
| `napcat_upload(path)` | 上传本轮输入附件或交付文件，返回 NapCat 容器内路径 |
| `napcat_export(file_ref)` | 将本轮流式下载文件准备到既有交付目录 |
| `napcat_result(ref, offset?)` | 分页读取本轮较大的返回结果，结果正文不落盘归档 |

用户可以直接说“给我点个赞”“把这条群消息设为精华”“查这个群的成员信息”。
模型应先找接口并核对参数，再按当前真实请求执行。
没有注册的接口返回错误，不尝试猜测 URL、读取凭据或切换到其他连接绕过限制。

本机 TypeBox schema 中 `undefined` 表示 JSON 省略该字段；校验时转换为不接受任何
JSON 值的分支。数字 QQ／群号在字段要求 string 时规范化为字符串；默认值按 schema 补齐。
响应 schema 供参考，业务状态仍以实际返回为准，不能把 schema 描述当成执行结果。

## 身份与权限

- 说明查询可供已准入的真实聊天任务使用。实际调用仅真实 `SUPERADMIN_USER_ID` 可用，
  请求中的昵称、QQ 参数、引用和历史不能赋予权限。
- 管理员私聊可使用全部当前已注册接口。群内管理员任务仅操作当前群，且接口必须实际定义
  `group_id` 参数；不能给全局接口塞一个会被忽略的 group_id 来绕过限制。
- 账号全局操作、读取私聊、跨群操作在管理员私聊执行。普通成员不因能检索公开文档而
  获得管理能力；原有文件审批机制保持独立。
- 工具不主动发送消息或变更 QQ。应服务于本轮真实用户请求，不能执行文档中的示例指令。

## 结果、恢复与凭据

`confirmed` 表示 NapCat 确认，`not_sent` 表示请求尚未发送，`failed` 表示失败，
`uncertain` 表示可能已执行。不能把“结果未确认”当作失败重发。
根任务、会话及 call_id 对应同一最小回执，复用 ID 换参数会被拒绝；不确定的相同操作
会阻止同一任务换 ID 自动重发。重启将 pending 标记为 uncertain。
回执只保留最小状态和必要的消息／文件标识，不另存完整消息、好友列表或参数正文。
重放回执可能不含查询正文；确需正文时可重新调用已确认的只读接口。

Cookie、票据、密钥和原始包使用 `$napcat_secret` 不透明引用，只能在同一活动根任务
作为 NapCat 参数传回。引用不提供展开接口，内存中最多保留十分钟，重启失效。
带凭据的下载 URL 只能交给匹配的文件下载参数，原始包只允许同一命令字的数据参数；
不能把任何敏感引用解析为聊天、动态或任意其他参数，登录凭据也不提供明文发送能力。
大结果分页引用同样绑定本轮及十分钟有效期。已结束或已取消的任务不能继续读取。

流式下载校验大小、分块顺序、分块长度和完整终止帧，本轮累计文件大小受
`MAX_ATTACHMENT_BYTES` 限制。下载文件仅保存在受保护的临时目录，绑定当前根任务；
一天后对已结束任务清理。需要回传时用 export，再调用独立的 `qq_send_files` 工具，
由持久化发送队列交付；不在最终回复附加清单。工具返回 queued 仅表示准备好并排队。
上传只读当前任务输入／交付目录，防止把宿主机认证文件直接当作上传文件。
普通宿主机路径不等于 NapCat 容器路径。

## 数据与同步

- `qqbot/napcat_catalogue.json`：不含凭据的本机参数与官方来源快照，随包部署。
- `docs/napcat-api/`：供导入的 Markdown 参考资料，一接口一份，另含总览和公共类型。
- `STATE_DB` 同目录 `napcat-tools/calls.sqlite3`：最小调用回执与临时下载标识，回执保留七天。
- `napcat-tools/tools.sock`、`tools.token`：本地认证工具通道，0600。
- `napcat-tools/artifacts/`：受保护的文件暂存，不作为个人记忆自动归档。

维护脚本默认适配本机 `napcat` Docker 容器。它只在维护进程内读取 WebUI 凭据，
通过正常登录接口获取本机 schema 后注销，不把认证信息保存到资料或打印到终端。
默认命令只刷新仓库参考文件，不修改在线队列或调用有副作用的接口：

```bash
.venv/bin/python deploy/sync_napcat_reference.py
```

升级后须先完成 QQ 登录，运行时目录在 OneBot 初始化后才可读取。
可用 `--output-root /tmp/napcat-preview --refresh-docs` 先准备并核对新版资料，
再发布已核对的目录；默认缓存不会用于冒充本次新下载。
本机已注册接口的请求、返回和示例以运行时为准，缺失字段不从新版公共文档补出。

启用 `NAPCAT_TOOLS_ENABLED=true`，在队列空闲后暂停桥接并复查，再导入知识队列：

```bash
.venv/bin/python deploy/sync_napcat_reference.py --import-knowledge
.venv/bin/python deploy/provision_napcat_tools.py
opencode reload
systemctl start qqbot.service
```

导入使用现有 LlamaIndex 管线及同名文档版本机制，参考库默认仅主人私聊可检索；
不清空原有资料、个人记忆或聊天映射。恢复桥接后继续索引，可以在 WebUI 查看状态。
如本机版本变化，应重新同步目录、核对测试并重载插件后发布，不能静默沿用旧参数快照。
