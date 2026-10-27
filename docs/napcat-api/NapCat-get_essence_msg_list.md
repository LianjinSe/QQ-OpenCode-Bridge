# NapCat `get_essence_msg_list`：获取群精华消息

功能：获取群精华消息

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658664e0.md

调用方法：先 `napcat_describe(action="get_essence_msg_list")` 核对本机参数，再 `napcat_call(action="get_essence_msg_list", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定群聊中的精华消息列表

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
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
  "group_id": "123456"
}
```

## 返回数据结构

```json
{
  "description": "精华消息列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "msg_seq": {
        "description": "消息序号",
        "type": "number"
      },
      "msg_random": {
        "description": "消息随机数",
        "type": "number"
      },
      "sender_id": {
        "description": "发送者QQ",
        "type": "number"
      },
      "sender_nick": {
        "description": "发送者昵称",
        "type": "string"
      },
      "operator_id": {
        "description": "操作者QQ",
        "type": "number"
      },
      "operator_nick": {
        "description": "操作者昵称",
        "type": "string"
      },
      "message_id": {
        "description": "消息ID",
        "type": "number"
      },
      "operator_time": {
        "description": "操作时间",
        "type": "number"
      },
      "content": {
        "description": "消息内容",
        "type": "array",
        "items": {}
      }
    },
    "required": [
      "msg_seq",
      "msg_random",
      "sender_id",
      "sender_nick",
      "operator_id",
      "operator_nick",
      "message_id",
      "operator_time",
      "content"
    ]
  }
}
```

