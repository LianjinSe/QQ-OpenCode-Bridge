# NapCat `.handle_quick_operation`：处理快速操作

功能：处理快速操作

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658889e0.md

调用方法：先 `napcat_describe(action=".handle_quick_operation")` 核对本机参数，再 `napcat_call(action=".handle_quick_operation", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

处理来自事件上报的快速操作请求

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "context": {
      "description": "事件上下文",
      "type": "object",
      "properties": {
        "time": {
          "description": "事件发生时间",
          "type": "number"
        },
        "self_id": {
          "description": "收到事件的机器人 QQ 号",
          "type": "number"
        },
        "post_type": {
          "description": "上报类型",
          "type": "string"
        },
        "message_type": {
          "description": "消息类型",
          "type": "string"
        },
        "sub_type": {
          "description": "消息子类型",
          "type": "string"
        },
        "user_id": {
          "description": "发送者 QQ 号",
          "type": "string"
        },
        "group_id": {
          "description": "群号",
          "type": "string"
        },
        "message_id": {
          "description": "消息 ID",
          "type": "number"
        },
        "message_seq": {
          "description": "消息序列号",
          "type": "number"
        },
        "real_id": {
          "description": "真实消息 ID",
          "type": "number"
        },
        "sender": {
          "type": "object",
          "properties": {
            "user_id": {
              "description": "用户ID",
              "type": "string"
            },
            "nickname": {
              "description": "昵称",
              "type": "string"
            },
            "sex": {
              "description": "性别",
              "type": "string"
            },
            "age": {
              "description": "年龄",
              "type": "number"
            },
            "card": {
              "description": "群名片",
              "type": "string"
            },
            "level": {
              "description": "群等级",
              "type": "string"
            },
            "role": {
              "description": "群角色",
              "type": "string"
            }
          },
          "required": [
            "user_id",
            "nickname"
          ]
        },
        "message": {
          "description": "消息内容"
        },
        "message_format": {
          "description": "消息格式",
          "type": "string"
        },
        "raw_message": {
          "description": "原始消息内容",
          "type": "string"
        },
        "font": {
          "description": "字体",
          "type": "number"
        },
        "notice_type": {
          "description": "通知类型",
          "type": "string"
        },
        "meta_event_type": {
          "description": "元事件类型",
          "type": "string"
        }
      },
      "required": [
        "time",
        "self_id",
        "post_type",
        "user_id"
      ]
    },
    "operation": {
      "description": "快速操作内容",
      "type": "object",
      "properties": {
        "reply": {
          "$ref": "#/$defs/OB11MessageMixType"
        },
        "auto_escape": {
          "description": "是否作为纯文本发送",
          "type": "boolean"
        },
        "at_sender": {
          "description": "是否 @ 发送者",
          "type": "boolean"
        },
        "delete": {
          "description": "是否撤回该消息",
          "type": "boolean"
        },
        "kick": {
          "description": "是否踢出发送者",
          "type": "boolean"
        },
        "ban": {
          "description": "是否禁言发送者",
          "type": "boolean"
        },
        "ban_duration": {
          "description": "禁言时长",
          "type": "number"
        },
        "approve": {
          "description": "是否同意请求/加群",
          "type": "boolean"
        },
        "remark": {
          "description": "好友备注",
          "type": "string"
        },
        "reason": {
          "description": "拒绝理由",
          "type": "string"
        }
      }
    }
  },
  "required": [
    "context",
    "operation"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "context": {},
  "operation": {}
}
```

## 返回数据结构

```json
{
  "type": "null"
}
```

`#/$defs/...` 的具体消息段和数据类型见《NapCat-公共数据类型》，或用 `napcat_schema(name)` 按需读取。
