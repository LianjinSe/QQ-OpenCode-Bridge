# NapCat `set_group_portrait`：设置群头像

功能：设置群头像

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658669e0.md

调用方法：先 `napcat_describe(action="set_group_portrait")` 核对本机参数，再 `napcat_call(action="set_group_portrait", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

修改指定群聊的头像

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "file": {
      "description": "头像文件路径或 URL",
      "type": "string"
    },
    "group_id": {
      "description": "群号",
      "type": "string"
    }
  },
  "required": [
    "file",
    "group_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "file": "base64://..."
}
```

## 返回数据结构

```json
{
  "description": "设置结果",
  "type": "object",
  "properties": {
    "result": {
      "type": "number"
    },
    "errMsg": {
      "type": "string"
    }
  },
  "required": [
    "result",
    "errMsg"
  ]
}
```

