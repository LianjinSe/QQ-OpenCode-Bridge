# NapCat `set_group_leave`：退出群组

功能：退出群组

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656926e0.md

调用方法：先 `napcat_describe(action="set_group_leave")` 核对本机参数，再 `napcat_call(action="set_group_leave", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

退出或解散指定群聊

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "is_dismiss": {
      "description": "是否解散",
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
    "group_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "is_dismiss": false
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

