# NapCat `set_group_search`：设置群搜索选项

功能：设置群搜索选项

分类：群组扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/301542170e0.md

调用方法：先 `napcat_describe(action="set_group_search")` 核对本机参数，再 `napcat_call(action="set_group_search", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "no_code_finger_open": {
      "description": "未知",
      "type": "number"
    },
    "no_finger_open": {
      "description": "未知",
      "type": "number"
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
  "description": "返回结果",
  "type": "null"
}
```

