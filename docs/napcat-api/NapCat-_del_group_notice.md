# NapCat `_del_group_notice`：删除群公告

功能：删除群公告

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659240e0.md

调用方法：先 `napcat_describe(action="_del_group_notice")` 核对本机参数，再 `napcat_call(action="_del_group_notice", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

删除群聊中的公告

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "notice_id": {
      "description": "公告ID",
      "type": "string"
    }
  },
  "required": [
    "group_id",
    "notice_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "notice_id": "notice_123"
}
```

## 返回数据结构

```json
{
  "description": "操作结果"
}
```

