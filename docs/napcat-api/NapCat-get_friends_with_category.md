# NapCat `get_friends_with_category`：获取带分组的好友列表

功能：获取带分组的好友列表

分类：用户扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658978e0.md

调用方法：先 `napcat_describe(action="get_friends_with_category")` 核对本机参数，再 `napcat_call(action="get_friends_with_category", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
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
  "description": "带分组的好友列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "categoryId": {
        "description": "分组ID",
        "type": "number"
      },
      "categoryName": {
        "description": "分组名称",
        "type": "string"
      },
      "categoryMbCount": {
        "description": "分组内好友数量",
        "type": "number"
      },
      "buddyList": {
        "description": "好友列表",
        "type": "array",
        "items": {
          "$ref": "#/$defs/OB11User"
        }
      }
    },
    "required": [
      "categoryId",
      "categoryName",
      "categoryMbCount",
      "buddyList"
    ]
  }
}
```

`#/$defs/...` 的具体消息段和数据类型见《NapCat-公共数据类型》，或用 `napcat_schema(name)` 按需读取。
