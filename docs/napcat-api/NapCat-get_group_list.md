# NapCat `get_group_list`：获取群列表

功能：获取群列表

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656992e0.md

调用方法：先 `napcat_describe(action="get_group_list")` 核对本机参数，再 `napcat_call(action="get_group_list", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取当前帐号的群聊列表

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "no_cache": {
      "description": "是否不使用缓存",
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "string"
        }
      ]
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{}
```

## 返回数据结构

```json
{
  "description": "群列表",
  "type": "array",
  "items": {
    "$ref": "#/$defs/OB11Group"
  }
}
```

`#/$defs/...` 的具体消息段和数据类型见《NapCat-公共数据类型》，或用 `napcat_schema(name)` 按需读取。
