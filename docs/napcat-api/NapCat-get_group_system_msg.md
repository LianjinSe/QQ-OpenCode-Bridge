# NapCat `get_group_system_msg`：获取群系统消息

功能：获取群系统消息

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658660e0.md

调用方法：先 `napcat_describe(action="get_group_system_msg")` 核对本机参数，再 `napcat_call(action="get_group_system_msg", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取群系统消息

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "count": {
      "default": 50,
      "description": "获取的消息数量",
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
  "count": 50
}
```

## 返回数据结构

```json
{
  "type": "object",
  "properties": {
    "invited_requests": {
      "description": "进群邀请列表",
      "type": "array",
      "items": {
        "$ref": "#/$defs/OB11Notify"
      }
    },
    "InvitedRequest": {
      "description": "进群邀请列表 (兼容)",
      "type": "array",
      "items": {
        "$ref": "#/$defs/OB11Notify"
      }
    },
    "join_requests": {
      "description": "进群申请列表",
      "type": "array",
      "items": {
        "$ref": "#/$defs/OB11Notify"
      }
    }
  },
  "required": [
    "invited_requests",
    "InvitedRequest",
    "join_requests"
  ]
}
```

`#/$defs/...` 的具体消息段和数据类型见《NapCat-公共数据类型》，或用 `napcat_schema(name)` 按需读取。
