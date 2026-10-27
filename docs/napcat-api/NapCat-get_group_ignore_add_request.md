# NapCat `get_group_ignore_add_request`：获取群被忽略的加群请求

功能：获取群被忽略的加群请求

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659234e0.md

调用方法：先 `napcat_describe(action="get_group_ignore_add_request")` 核对本机参数，再 `napcat_call(action="get_group_ignore_add_request", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {}
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{}
```

## 返回数据结构

```json
{
  "description": "群通知列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "request_id": {
        "description": "请求ID",
        "type": "number"
      },
      "invitor_uin": {
        "description": "邀请者QQ",
        "type": "number"
      },
      "invitor_nick": {
        "description": "邀请者昵称",
        "type": "string"
      },
      "group_id": {
        "description": "群号",
        "type": "number"
      },
      "message": {
        "description": "验证信息",
        "type": "string"
      },
      "group_name": {
        "description": "群名称",
        "type": "string"
      },
      "checked": {
        "description": "是否已处理",
        "type": "boolean"
      },
      "actor": {
        "description": "处理者QQ",
        "type": "number"
      },
      "requester_nick": {
        "description": "请求者昵称",
        "type": "string"
      }
    },
    "required": [
      "request_id",
      "invitor_uin",
      "group_id",
      "checked",
      "actor"
    ]
  }
}
```

