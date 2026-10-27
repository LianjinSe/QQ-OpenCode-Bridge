# NapCat `set_doubt_friends_add_request`：处理可疑好友申请

功能：处理可疑好友申请

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/289565525e0.md

调用方法：先 `napcat_describe(action="set_doubt_friends_add_request")` 核对本机参数，再 `napcat_call(action="set_doubt_friends_add_request", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

同意或拒绝系统的可疑好友申请

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "flag": {
      "description": "请求 flag",
      "type": "string"
    },
    "approve": {
      "default": true,
      "description": "是否同意 (强制为 true)",
      "type": "boolean"
    }
  },
  "required": [
    "flag",
    "approve"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "flag": "12345",
  "approve": true
}
```

## 返回数据结构

```json
{}
```

