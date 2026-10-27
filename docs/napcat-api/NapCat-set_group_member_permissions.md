# NapCat `set_group_member_permissions`：设置群成员功能权限

功能：设置群成员功能权限

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/496813056e0.md

调用方法：先 `napcat_describe(action="set_group_member_permissions")` 核对本机参数，再 `napcat_call(action="set_group_member_permissions", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

设置群成员上传相册、发起临时会话和发起新群聊的权限；未传入的项目保持不变

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "allow_member_upload_album": {
      "description": "允许成员上传群相册",
      "type": "boolean"
    },
    "allow_member_temporary_session": {
      "description": "允许成员发起临时会话",
      "type": "boolean"
    },
    "allow_member_create_group": {
      "description": "允许成员发起新的群聊",
      "type": "boolean"
    }
  },
  "required": [
    "group_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "allow_member_upload_album": true,
  "allow_member_temporary_session": true,
  "allow_member_create_group": true
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

