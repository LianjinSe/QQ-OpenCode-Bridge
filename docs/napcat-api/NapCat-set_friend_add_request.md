# NapCat `set_friend_add_request`：处理加好友请求

功能：处理加好友请求

分类：用户接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656932e0.md

调用方法：先 `napcat_describe(action="set_friend_add_request")` 核对本机参数，再 `napcat_call(action="set_friend_add_request", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

同意或拒绝加好友请求

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "flag": {
      "description": "加好友请求的 flag (需从上报中获取)",
      "type": "string"
    },
    "approve": {
      "description": "是否同意请求",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "boolean"
        }
      ]
    },
    "remark": {
      "description": "添加后的好友备注",
      "type": "string"
    }
  },
  "required": [
    "flag"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "flag": "flag_12345",
  "approve": true,
  "remark": "新朋友"
}
```

## 返回数据结构

```json
{
  "type": "null"
}
```

