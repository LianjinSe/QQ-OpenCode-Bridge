# NapCat `get_msg`：获取消息

功能：获取消息

分类：消息接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656707e0.md

调用方法：先 `napcat_describe(action="get_msg")` 核对本机参数，再 `napcat_call(action="get_msg", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

根据消息 ID 获取消息详细信息

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
  "message_id": 123456
}
```

## 返回数据结构

```json
{
  "description": "OneBot 11 消息",
  "type": "object",
  "properties": {
    "time": {
      "description": "发送时间",
      "type": "number"
    },
    "message_type": {
      "description": "消息类型",
      "type": "string"
    },
    "message_id": {
      "description": "消息ID",
      "type": "number"
    },
    "real_id": {
      "description": "真实ID",
      "type": "number"
    },
    "message_seq": {
      "description": "消息序号",
      "type": "number"
    },
    "sender": {
      "description": "发送者"
    },
    "message": {
      "description": "消息内容"
    },
    "raw_message": {
      "description": "原始消息内容",
      "type": "string"
    },
    "font": {
      "description": "字体",
      "type": "number"
    },
    "group_id": {
      "description": "群号",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "user_id": {
      "description": "发送者QQ号",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "emoji_likes_list": {
      "description": "表情回应列表",
      "type": "array",
      "items": {}
    }
  },
  "required": [
    "time",
    "message_type",
    "message_id",
    "real_id",
    "message_seq",
    "sender",
    "message",
    "raw_message",
    "font",
    "user_id"
  ]
}
```

