# NapCat `send_like`：点赞

功能：点赞

分类：用户接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656717e0.md

调用方法：先 `napcat_describe(action="send_like")` 核对本机参数，再 `napcat_call(action="send_like", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

给指定用户点赞

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "对方 QQ 号",
      "type": "string"
    },
    "times": {
      "default": 1,
      "description": "点赞次数",
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
    "user_id",
    "times"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456",
  "times": 10
}
```

## 返回数据结构

```json
{
  "type": "null"
}
```

