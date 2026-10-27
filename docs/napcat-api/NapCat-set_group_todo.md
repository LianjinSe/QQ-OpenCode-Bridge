# NapCat `set_group_todo`：设置群待办

功能：设置群待办

分类：核心接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/395460568e0.md

调用方法：先 `napcat_describe(action="set_group_todo")` 核对本机参数，再 `napcat_call(action="set_group_todo", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

将指定消息设置为群待办

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "number"
        }
      ]
    },
    "message_id": {
      "description": "消息ID",
      "type": "string"
    },
    "message_seq": {
      "description": "消息Seq (可选)",
      "type": "string"
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
  "message_id": "123456789"
}
```

## 返回数据结构

```json
{
  "type": "null"
}
```

