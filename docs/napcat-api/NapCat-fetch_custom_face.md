# NapCat `fetch_custom_face`：获取自定义表情

功能：获取自定义表情

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659210e0.md

调用方法：先 `napcat_describe(action="fetch_custom_face")` 核对本机参数，再 `napcat_call(action="fetch_custom_face", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "count": {
      "default": 48,
      "description": "获取数量",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "count"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "count": 10
}
```

## 返回数据结构

```json
{
  "description": "表情URL列表",
  "type": "array",
  "items": {
    "type": "string"
  }
}
```

