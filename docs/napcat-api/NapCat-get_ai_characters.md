# NapCat `get_ai_characters`：获取AI角色列表

功能：获取AI角色列表

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/229485683e0.md

调用方法：先 `napcat_describe(action="get_ai_characters")` 核对本机参数，再 `napcat_call(action="get_ai_characters", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取群聊中的AI角色列表

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "chat_type": {
      "default": 1,
      "description": "聊天类型",
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
    "group_id",
    "chat_type"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456"
}
```

## 返回数据结构

```json
{
  "description": "AI角色列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "type": {
        "description": "角色类型",
        "type": "string"
      },
      "characters": {
        "description": "角色列表",
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "character_id": {
              "description": "角色ID",
              "type": "string"
            },
            "character_name": {
              "description": "角色名称",
              "type": "string"
            },
            "preview_url": {
              "description": "预览URL",
              "type": "string"
            }
          },
          "required": [
            "character_id",
            "character_name",
            "preview_url"
          ]
        }
      }
    },
    "required": [
      "type",
      "characters"
    ]
  }
}
```

