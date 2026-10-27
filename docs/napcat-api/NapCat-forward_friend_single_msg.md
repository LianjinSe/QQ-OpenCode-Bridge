# NapCat `forward_friend_single_msg`：转发单条消息

功能：转发单条消息

分类：消息接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659051e0.md

调用方法：先 `napcat_describe(action="forward_friend_single_msg")` 核对本机参数，再 `napcat_call(action="forward_friend_single_msg", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

转发单条消息

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
    "group_id": {
      "description": "目标群号",
      "type": "string"
    },
    "user_id": {
      "description": "目标用户QQ",
      "type": "string"
    }
  },
  "required": [
    "message_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "message_id": 12345,
  "group_id": "123456"
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

