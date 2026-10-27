# NapCat `refuse_online_file`：拒绝在线文件

功能：拒绝在线文件

分类：文件扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/410334676e0.md

调用方法：先 `napcat_describe(action="refuse_online_file")` 核对本机参数，再 `napcat_call(action="refuse_online_file", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "用户 QQ",
      "type": "string"
    },
    "msg_id": {
      "description": "消息 ID",
      "type": "string"
    },
    "element_id": {
      "description": "元素 ID",
      "type": "string"
    }
  },
  "required": [
    "user_id",
    "msg_id",
    "element_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456789",
  "msg_id": "123"
}
```

## 返回数据结构

```json
{
  "description": "拒绝结果"
}
```

