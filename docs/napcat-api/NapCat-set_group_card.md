# NapCat `set_group_card`：设置群名片

功能：设置群名片

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656913e0.md

调用方法：先 `napcat_describe(action="set_group_card")` 核对本机参数，再 `napcat_call(action="set_group_card", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

设置群聊中指定成员的群名片

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
      "description": "用户QQ",
      "type": "string"
    },
    "card": {
      "description": "群名片",
      "type": "string"
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
  "user_id": "123456789",
  "card": "新名片"
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

