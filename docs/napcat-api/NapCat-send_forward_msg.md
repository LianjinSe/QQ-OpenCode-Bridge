# NapCat `send_forward_msg`：发送合并转发消息

功能：发送合并转发消息

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659136e0.md

调用方法：先 `napcat_describe(action="send_forward_msg")` 核对本机参数，再 `napcat_call(action="send_forward_msg", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

发送合并转发消息

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "message_type": {
      "description": "消息类型 (private/group)",
      "anyOf": [
        {
          "const": "private",
          "type": "string"
        },
        {
          "const": "group",
          "type": "string"
        }
      ]
    },
    "user_id": {
      "description": "用户QQ",
      "type": "string"
    },
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "message": {
      "$ref": "#/$defs/OB11MessageMixType"
    },
    "auto_escape": {
      "description": "是否作为纯文本发送",
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "string"
        }
      ]
    },
    "source": {
      "description": "合并转发来源",
      "type": "string"
    },
    "news": {
      "description": "合并转发新闻",
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "text": {
            "type": "string"
          }
        },
        "required": [
          "text"
        ]
      }
    },
    "summary": {
      "description": "合并转发摘要",
      "type": "string"
    },
    "prompt": {
      "description": "合并转发提示",
      "type": "string"
    },
    "timeout": {
      "description": "自定义发送超时(毫秒)，覆盖自动计算值",
      "type": "number"
    }
  },
  "required": [
    "message"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456789",
  "messages": []
}
```

## 返回数据结构

```json
{
  "type": "object",
  "properties": {
    "message_id": {
      "description": "消息ID",
      "type": "number"
    },
    "res_id": {
      "description": "转发消息的 res_id",
      "type": "string"
    },
    "forward_id": {
      "description": "转发消息的 forward_id",
      "type": "string"
    }
  },
  "required": [
    "message_id"
  ]
}
```

`#/$defs/...` 的具体消息段和数据类型见《NapCat-公共数据类型》，或用 `napcat_schema(name)` 按需读取。
