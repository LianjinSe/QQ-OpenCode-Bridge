# NapCat `get_profile_like`：获取资料点赞

功能：获取资料点赞

分类：用户扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659197e0.md

调用方法：先 `napcat_describe(action="get_profile_like")` 核对本机参数，再 `napcat_call(action="get_profile_like", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "QQ号",
      "type": "string"
    },
    "start": {
      "default": 0,
      "description": "起始位置",
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
      "default": 10,
      "description": "获取数量",
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
    "start",
    "count"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456789",
  "start": 0,
  "count": 10
}
```

## 返回数据结构

```json
{
  "description": "点赞详情",
  "type": "object",
  "properties": {
    "uid": {
      "description": "用户UID",
      "type": "string"
    },
    "time": {
      "description": "时间",
      "type": "string"
    },
    "favoriteInfo": {
      "type": "object",
      "properties": {
        "userInfos": {
          "description": "点赞用户信息",
          "type": "array",
          "items": {}
        },
        "total_count": {
          "description": "总点赞数",
          "type": "number"
        },
        "last_time": {
          "description": "最后点赞时间",
          "type": "number"
        },
        "today_count": {
          "description": "今日点赞数",
          "type": "number"
        }
      },
      "required": [
        "userInfos",
        "total_count",
        "last_time",
        "today_count"
      ]
    },
    "voteInfo": {
      "type": "object",
      "properties": {
        "total_count": {
          "description": "总点赞数",
          "type": "number"
        },
        "new_count": {
          "description": "新增点赞数",
          "type": "number"
        },
        "new_nearby_count": {
          "description": "新增附近点赞数",
          "type": "number"
        },
        "last_visit_time": {
          "description": "最后访问时间",
          "type": "number"
        },
        "userInfos": {
          "description": "点赞用户信息",
          "type": "array",
          "items": {}
        }
      },
      "required": [
        "total_count",
        "new_count",
        "new_nearby_count",
        "last_visit_time",
        "userInfos"
      ]
    }
  },
  "required": [
    "uid",
    "time",
    "favoriteInfo",
    "voteInfo"
  ]
}
```

