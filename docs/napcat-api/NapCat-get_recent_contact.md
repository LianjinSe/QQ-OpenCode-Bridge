# NapCat `get_recent_contact`：获取最近会话

功能：获取最近会话

分类：用户接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659190e0.md

调用方法：先 `napcat_describe(action="get_recent_contact")` 核对本机参数，再 `napcat_call(action="get_recent_contact", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取最近会话

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "count": {
      "default": 10,
      "description": "获取的数量",
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
    "count"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "count": 10
}
```

## 返回数据结构

```json
{
  "description": "最近会话列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "lastestMsg": {
        "description": "最后一条消息"
      },
      "peerUin": {
        "description": "对象QQ",
        "type": "string"
      },
      "remark": {
        "description": "备注",
        "type": "string"
      },
      "msgTime": {
        "description": "消息时间",
        "type": "string"
      },
      "chatType": {
        "description": "聊天类型",
        "type": "number"
      },
      "msgId": {
        "description": "消息ID",
        "type": "string"
      },
      "sendNickName": {
        "description": "发送者昵称",
        "type": "string"
      },
      "sendMemberName": {
        "description": "发送者群名片",
        "type": "string"
      },
      "peerName": {
        "description": "对象名称",
        "type": "string"
      }
    },
    "required": [
      "lastestMsg",
      "peerUin",
      "remark",
      "msgTime",
      "chatType",
      "msgId",
      "sendNickName",
      "sendMemberName",
      "peerName"
    ]
  }
}
```

