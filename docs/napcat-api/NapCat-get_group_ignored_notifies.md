# NapCat `get_group_ignored_notifies`：获取群忽略通知

功能：获取群忽略通知

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659323e0.md

调用方法：先 `napcat_describe(action="get_group_ignored_notifies")` 核对本机参数，再 `napcat_call(action="get_group_ignored_notifies", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取被忽略的入群申请和邀请通知

## 请求参数（本机 schema 优先）

```json
{
  "description": "群忽略通知负载",
  "type": "object",
  "properties": {}
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{}
```

## 返回数据结构

```json
{
  "description": "群忽略通知结果",
  "type": "object",
  "properties": {
    "invited_requests": {
      "description": "邀请请求列表",
      "type": "array",
      "items": {}
    },
    "InvitedRequest": {
      "description": "邀请请求列表",
      "type": "array",
      "items": {}
    },
    "join_requests": {
      "description": "加入请求列表",
      "type": "array",
      "items": {}
    }
  },
  "required": [
    "invited_requests",
    "InvitedRequest",
    "join_requests"
  ]
}
```

