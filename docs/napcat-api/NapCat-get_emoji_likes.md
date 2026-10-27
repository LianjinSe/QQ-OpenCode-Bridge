# NapCat `get_emoji_likes`：获取消息表情点赞列表

功能：获取消息表情点赞列表

分类：消息扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/410334663e0.md

调用方法：先 `napcat_describe(action="get_emoji_likes")` 核对本机参数，再 `napcat_call(action="get_emoji_likes", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号，短ID可不传",
      "type": "string"
    },
    "message_id": {
      "description": "消息ID，可以传递长ID或短ID",
      "type": "string"
    },
    "emoji_id": {
      "description": "表情ID",
      "type": "string"
    },
    "emoji_type": {
      "description": "表情类型",
      "type": "string"
    },
    "count": {
      "default": 0,
      "description": "数量，0代表全部",
      "type": "number"
    }
  },
  "required": [
    "message_id",
    "emoji_id",
    "count"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "message_id": "12345",
  "emoji_id": "123"
}
```

## 返回数据结构

```json
{
  "type": "object",
  "properties": {
    "emoji_like_list": {
      "description": "表情回应列表",
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "user_id": {
            "description": "点击者QQ号",
            "type": "string"
          },
          "nick_name": {
            "description": "昵称?",
            "type": "string"
          }
        },
        "required": [
          "user_id",
          "nick_name"
        ]
      }
    }
  },
  "required": [
    "emoji_like_list"
  ]
}
```

