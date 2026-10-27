# NapCat `ArkSharePeer`：分享用户 (Ark)

功能：分享用户 (Ark)

分类：消息扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658965e0.md

调用方法：先 `napcat_describe(action="ArkSharePeer")` 核对本机参数，再 `napcat_call(action="ArkSharePeer", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取用户推荐的 Ark 内容

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "QQ号",
      "type": "string"
    },
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "phone_number": {
      "default": "",
      "description": "手机号",
      "type": "string"
    }
  },
  "required": [
    "phone_number"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456",
  "phone_number": ""
}
```

## 返回数据结构

```json
{
  "description": "分享结果"
}
```

