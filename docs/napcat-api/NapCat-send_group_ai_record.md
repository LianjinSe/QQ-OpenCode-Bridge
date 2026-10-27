# NapCat `send_group_ai_record`：发送群 AI 语音

功能：发送群 AI 语音

分类：AI 扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/229486774e0.md

调用方法：先 `napcat_describe(action="send_group_ai_record")` 核对本机参数，再 `napcat_call(action="send_group_ai_record", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

发送 AI 生成的语音到指定群聊

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "character": {
      "description": "角色ID",
      "type": "string"
    },
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "text": {
      "description": "语音文本内容",
      "type": "string"
    }
  },
  "required": [
    "character",
    "group_id",
    "text"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "character": "ai_char_1",
  "group_id": "123456",
  "text": "你好"
}
```

## 返回数据结构

```json
{
  "description": "发送结果",
  "type": "object",
  "properties": {
    "message_id": {
      "description": "消息ID",
      "type": "number"
    }
  },
  "required": [
    "message_id"
  ]
}
```

