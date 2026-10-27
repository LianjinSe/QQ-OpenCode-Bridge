# NapCat `set_msg_emoji_like`：设置消息表情点赞

功能：设置消息表情点赞

分类：消息扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659104e0.md

调用方法：先 `napcat_describe(action="set_msg_emoji_like")` 核对本机参数，再 `napcat_call(action="set_msg_emoji_like", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "message_id": {
      "description": "消息ID",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "emoji_id": {
      "description": "表情ID",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "set": {
      "description": "是否设置",
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "message_id",
    "emoji_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "message_id": 12345,
  "emoji_id": "123",
  "set": true
}
```

## 返回数据结构

```json
{
  "description": "操作结果"
}
```

