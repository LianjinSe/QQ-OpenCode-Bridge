# NapCat `get_collection_list`：获取收藏列表

功能：获取收藏列表

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659182e0.md

调用方法：先 `napcat_describe(action="get_collection_list")` 核对本机参数，再 `napcat_call(action="get_collection_list", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "category": {
      "description": "分类ID",
      "type": "string"
    },
    "count": {
      "default": "50",
      "description": "获取数量",
      "type": "string"
    }
  },
  "required": [
    "category",
    "count"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "category": "0",
  "count": "50"
}
```

## 返回数据结构

```json
{
  "description": "收藏列表"
}
```

