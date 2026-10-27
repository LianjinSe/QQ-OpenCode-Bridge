# NapCat `_get_model_show`：获取机型显示

功能：获取机型显示

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/227233981e0.md

调用方法：先 `napcat_describe(action="_get_model_show")` 核对本机参数，再 `napcat_call(action="_get_model_show", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取当前账号可用的设备机型显示名称列表

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "model": {
      "description": "模型名称",
      "type": "string"
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "model": "iPhone 13"
}
```

## 返回数据结构

```json
{
  "description": "机型显示列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "variants": {
        "type": "object",
        "properties": {
          "model_show": {
            "description": "显示名称",
            "type": "string"
          },
          "need_pay": {
            "description": "是否需要付费",
            "type": "boolean"
          }
        },
        "required": [
          "model_show",
          "need_pay"
        ]
      }
    },
    "required": [
      "variants"
    ]
  }
}
```

