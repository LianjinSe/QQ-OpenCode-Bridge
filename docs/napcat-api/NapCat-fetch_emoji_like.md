# NapCat `fetch_emoji_like`：获取表情点赞详情

功能：获取表情点赞详情

分类：消息扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659219e0.md

调用方法：先 `napcat_describe(action="fetch_emoji_like")` 核对本机参数，再 `napcat_call(action="fetch_emoji_like", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
    "emojiId": {
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
    "emojiType": {
      "description": "表情类型",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "count": {
      "default": 20,
      "description": "获取数量",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "cookie": {
      "default": "",
      "description": "分页Cookie",
      "type": "string"
    }
  },
  "required": [
    "message_id",
    "emojiId",
    "emojiType",
    "count",
    "cookie"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "message_id": 12345,
  "emojiId": "123",
  "emojiType": 1,
  "count": 10,
  "cookie": ""
}
```

## 返回数据结构

```json
{
  "description": "表情回应详情",
  "type": "object",
  "properties": {
    "emojiLikesList": {
      "description": "表情回应列表",
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "tinyId": {
            "description": "TinyID",
            "type": "string"
          },
          "nickName": {
            "description": "昵称",
            "type": "string"
          },
          "headUrl": {
            "description": "头像URL",
            "type": "string"
          }
        },
        "required": [
          "tinyId",
          "nickName",
          "headUrl"
        ]
      }
    },
    "cookie": {
      "description": "分页Cookie",
      "type": "string"
    },
    "isLastPage": {
      "description": "是否最后一页",
      "type": "boolean"
    },
    "isFirstPage": {
      "description": "是否第一页",
      "type": "boolean"
    },
    "result": {
      "description": "结果状态码",
      "type": "number"
    },
    "errMsg": {
      "description": "错 误信息",
      "type": "string"
    }
  },
  "required": [
    "emojiLikesList",
    "cookie",
    "isLastPage",
    "isFirstPage",
    "result",
    "errMsg"
  ]
}
```

