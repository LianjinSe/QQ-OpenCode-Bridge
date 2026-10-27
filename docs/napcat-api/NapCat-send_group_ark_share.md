# NapCat `send_group_ark_share`：分享群 (Ark)

功能：分享群 (Ark)

分类：消息扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/410334664e0.md

调用方法：先 `napcat_describe(action="send_group_ark_share")` 核对本机参数，再 `napcat_call(action="send_group_ark_share", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取群分享的 Ark 内容

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
  "description": "Ark Json内容",
  "type": "string"
}
```

