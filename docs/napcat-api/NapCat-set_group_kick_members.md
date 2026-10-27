# NapCat `set_group_kick_members`：批量踢出群成员

功能：批量踢出群成员

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/301542209e0.md

调用方法：先 `napcat_describe(action="set_group_kick_members")` 核对本机参数，再 `napcat_call(action="set_group_kick_members", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

从指定群聊中批量踢出多个成员

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "user_id": {
      "description": "QQ号列表",
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "reject_add_request": {
      "description": "是否拒绝加群请求",
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "group_id",
    "user_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "user_id": [
    "123456789"
  ],
  "reject_add_request": false
}
```

## 返回数据结构

```json
{
  "description": "返回结果",
  "type": "null"
}
```

