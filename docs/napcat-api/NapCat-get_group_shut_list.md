# NapCat `get_group_shut_list`：获取群禁言列表

功能：获取群禁言列表

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659300e0.md

调用方法：先 `napcat_describe(action="get_group_shut_list")` 核对本机参数，再 `napcat_call(action="get_group_shut_list", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
  "group_id": "123456789"
}
```

## 返回数据结构

```json
{
  "description": "禁言成员列表",
  "type": "array",
  "items": {}
}
```

