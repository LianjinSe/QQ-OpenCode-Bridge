# NapCat `delete_essence_msg`：移出精华消息

功能：移出精华消息

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658678e0.md

调用方法：先 `napcat_describe(action="delete_essence_msg")` 核对本机参数，再 `napcat_call(action="delete_essence_msg", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

将一条消息从群精华消息列表中移出

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "message_id": {
      "description": "消息ID",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "msg_seq": {
      "description": "消息序号",
      "type": "string"
    },
    "msg_random": {
      "description": "消息随机数",
      "type": "string"
    },
    "group_id": {
      "description": "群号",
      "type": "string"
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "message_id": 123456
}
```

## 返回数据结构

```json
{
  "description": "操作结果"
}
```

