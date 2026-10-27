# NapCat `set_group_new_member_history_visibility`：设置新成员历史消息可见性

功能：设置新成员历史消息可见性

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/496813057e0.md

调用方法：先 `napcat_describe(action="set_group_new_member_history_visibility")` 核对本机参数，再 `napcat_call(action="set_group_new_member_history_visibility", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

设置新入群成员默认是否可以查看最近聊天记录

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "visible": {
      "description": "新成员默认可见最近聊天记录",
      "type": "boolean"
    }
  },
  "required": [
    "group_id",
    "visible"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "visible": true
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

