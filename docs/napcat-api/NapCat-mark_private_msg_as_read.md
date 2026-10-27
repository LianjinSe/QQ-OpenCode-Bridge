# NapCat `mark_private_msg_as_read`：标记私聊已读

功能：标记私聊已读

分类：消息接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659165e0.md

调用方法：先 `napcat_describe(action="mark_private_msg_as_read")` 核对本机参数，再 `napcat_call(action="mark_private_msg_as_read", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

标记指定渠道的消息为已读

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "用户QQ",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "number"
        }
      ]
    },
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "message_id": {
      "description": "消息ID",
      "type": "string"
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "message_id": 12345
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

