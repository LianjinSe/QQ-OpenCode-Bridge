# NapCat `send_packet`：发送原始数据包

功能：发送原始数据包

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/250286903e0.md

调用方法：先 `napcat_describe(action="send_packet")` 核对本机参数，再 `napcat_call(action="send_packet", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "cmd": {
      "description": "命令字",
      "type": "string"
    },
    "data": {
      "description": "十六进制数据",
      "type": "string"
    },
    "rsp": {
      "default": true,
      "description": "是否等待响应",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "boolean"
        }
      ]
    }
  },
  "required": [
    "cmd",
    "data",
    "rsp"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "cmd": "Example.Cmd",
  "data": "123456",
  "rsp": true
}
```

## 返回数据结构

```json
{
  "description": "发包结果",
  "anyOf": [
    {
      "description": "响应十六进制数据",
      "type": "string"
    },
    {
      "type": "undefined"
    }
  ]
}
```


凭据和原始包返回值通过本地不透明引用处理，不把 Cookie、密钥或票据写进聊天、文档或个人记忆。
