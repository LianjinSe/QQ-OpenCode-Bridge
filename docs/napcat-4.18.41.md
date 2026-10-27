# NapCat 4.18.41 接口更新核对

本文是随分发提供的 NapCat 4.18.41 接口参考，记录相对 4.18.13 的差异。
新部署需以自己已登录实例的 `/api/Debug/schemas` 和 `get_version_info` 为准。
4.18.13 的 172 个注册接口在 4.18.41 中增至 180 个；未移除原有接口。
目录包含两个内部自动注册测试接口，其余 178 个业务接口与本次官方文档覆盖范围一致。
注册和参数匹配不代表当前 QQ 账号拥有执行每项群管理操作的权限。

## 新增的八个注册接口

| action | 功能 |
| --- | --- |
| `get_group_share_link` | 获取群分享／加群链接 |
| `upload_images_to_qun_album` | 向群相册批量上传图片 |
| `upload_video_to_qun_album` | 向群相册上传视频 |
| `send_qzone_msg` | 发布 QQ 空间说说 |
| `delete_qzone_msg` | 删除 QQ 空间说说 |
| `set_group_member_invite_policy` | 设置群成员邀请策略 |
| `set_group_member_permissions` | 设置群成员上传相册、临时会话等权限 |
| `set_group_new_member_history_visibility` | 设置新成员历史消息可见性 |

这些接口此前只有新版文档说明，旧实例未注册；更新后目录中的 available 为 true。
真实管理员、当前群范围和不确定结果防重发规则继续由现有工具服务校验。

## 既有接口的参数和返回变化

- `do_group_album_comment`：lloc 改为可选，并增加 batch_id；至少提供其中一项。
  只有 batch_id 时评论整个上传批次，有 lloc 时评论单张图片。
- `delete_group_file`：增加 bus_id 和兼容字段 busid，范围为 1–4294967295；
  同时提供时必须一致，file_id 也需属于指定群。
- `create_flash_task`：增加 validitySeconds，支持指定闪传文件集有效期。
- `_get_group_notice`：返回结构增加 send_to_new_member、pinned，涵盖发给新成员的公告。
- `get_version_info`、`_mark_all_as_read`：运行时不再提供请求 schema，目录规范化为空参数对象，
  不从公共文档补出运行时没有声明的参数。
- 两个内部自动注册测试接口的描述发生变化，不计作业务能力变化。

所有注册接口的请求参数均逐项与本机导出核对，普通消息和文件流等其他接口未发现 schema 差异。
本次同步使用既有文档版本机制，保留资料库开放范围、会话映射和非参考资料。

源码对照：[4.18.13 → 4.18.41](https://github.com/NapNeko/NapCatQQ/compare/v4.18.13...v4.18.41)。
接口说明来源：[NapCat 官方接口文档](https://napcat.apifox.cn/llms.txt)。
