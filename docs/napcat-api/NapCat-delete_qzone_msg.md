# NapCat `delete_qzone_msg`：删除QQ空间说说

功能：删除QQ空间说说

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/496813059e0.md

调用方法：先 `napcat_describe(action="delete_qzone_msg")` 核对本机参数，再 `napcat_call(action="delete_qzone_msg", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

删除QQ空间(Qzone)的一条说说, 按 tid 删除

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "tid": {
      "description": "说说 tid (来自 get_qzone_msg_list / send_qzone_msg)",
      "type": "string"
    }
  },
  "required": [
    "tid"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "tid": "1234567890abcdef1234567890"
}
```

## 返回数据结构

```json
{
  "type": "null"
}
```

