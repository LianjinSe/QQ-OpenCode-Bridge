# NapCat `get_group_honor_info`：获取群荣誉信息

功能：获取群荣誉信息

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657036e0.md

调用方法：先 `napcat_describe(action="get_group_honor_info")` 核对本机参数，再 `napcat_call(action="get_group_honor_info", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定群聊的荣誉信息，如龙王等

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "type": {
      "description": "荣誉类型",
      "anyOf": [
        {
          "const": "all",
          "type": "string"
        },
        {
          "const": "talkative",
          "type": "string"
        },
        {
          "const": "performer",
          "type": "string"
        },
        {
          "const": "legend",
          "type": "string"
        },
        {
          "const": "strong_newbie",
          "type": "string"
        },
        {
          "const": "emotion",
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "group_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "type": "all"
}
```

## 返回数据结构

```json
{
  "description": "群荣誉信息",
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "number"
    },
    "current_talkative": {
      "description": "当前龙王",
      "type": "object",
      "patternProperties": {
        "^(.*)$": {}
      }
    },
    "talkative_list": {
      "description": "龙王列表",
      "type": "array",
      "items": {}
    },
    "performer_list": {
      "description": "群聊之火列表",
      "type": "array",
      "items": {}
    },
    "legend_list": {
      "description": "群聊炽热列表",
      "type": "array",
      "items": {}
    },
    "emotion_list": {
      "description": "快乐源泉列表",
      "type": "array",
      "items": {}
    },
    "strong_newbie_list": {
      "description": "冒尖小春笋列表",
      "type": "array",
      "items": {}
    }
  },
  "required": [
    "group_id",
    "current_talkative",
    "talkative_list",
    "performer_list",
    "legend_list",
    "emotion_list",
    "strong_newbie_list"
  ]
}
```

