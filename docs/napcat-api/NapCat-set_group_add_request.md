# NapCat `set_group_add_request`：处理加群请求

功能：处理加群请求

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656947e0.md

调用方法：先 `napcat_describe(action="set_group_add_request")` 核对本机参数，再 `napcat_call(action="set_group_add_request", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

同意或拒绝加群请求或邀请

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "flag": {
      "description": "请求flag",
      "type": "string"
    },
    "approve": {
      "description": "是否同意",
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "string"
        }
      ]
    },
    "reason": {
      "description": "拒绝理由",
      "anyOf": [
        {
          "default": " ",
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "count": {
      "default": 100,
      "description": "搜索通知数量",
      "type": "number"
    }
  },
  "required": [
    "flag"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "flag": "flag_123",
  "sub_type": "add",
  "approve": true
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

