# NapCat `fetch_ptt_text`：获取语音转文字结果

功能：获取语音转文字结果

分类：消息扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/458248103e0.md

调用方法：先 `napcat_describe(action="fetch_ptt_text")` 核对本机参数，再 `napcat_call(action="fetch_ptt_text", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
    }
  },
  "required": [
    "message_id"
  ]
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
  "type": "object",
  "properties": {
    "text": {
      "description": "得到的文本",
      "type": "string"
    }
  },
  "required": [
    "text"
  ]
}
```

