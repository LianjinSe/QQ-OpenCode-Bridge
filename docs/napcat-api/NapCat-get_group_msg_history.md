# NapCat `get_group_msg_history`：获取群历史消息

功能：获取群历史消息

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657401e0.md

调用方法：先 `napcat_describe(action="get_group_msg_history")` 核对本机参数，再 `napcat_call(action="get_group_msg_history", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定群聊的历史聊天记录

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "message_seq": {
      "description": "起始消息序号",
      "type": "string"
    },
    "count": {
      "default": 20,
      "description": "获取消息数量",
      "type": "number"
    },
    "reverse_order": {
      "default": false,
      "description": "是否反向排序",
      "type": "boolean"
    },
    "disable_get_url": {
      "default": false,
      "description": "是否禁用获取URL",
      "type": "boolean"
    },
    "parse_mult_msg": {
      "default": true,
      "description": "是否解析合并消息",
      "type": "boolean"
    },
    "quick_reply": {
      "default": false,
      "description": "是否快速回复",
      "type": "boolean"
    },
    "reverseOrder": {
      "default": false,
      "description": "是否反向排序(旧版本兼容)",
      "type": "boolean"
    }
  },
  "required": [
    "group_id",
    "count",
    "reverse_order",
    "disable_get_url",
    "parse_mult_msg",
    "quick_reply",
    "reverseOrder"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "message_seq": 0,
  "count": 20
}
```

## 返回数据结构

```json
{
  "description": "群历史消息",
  "type": "object",
  "properties": {
    "messages": {
      "description": "消息列表",
      "type": "array",
      "items": {}
    }
  },
  "required": [
    "messages"
  ]
}
```

