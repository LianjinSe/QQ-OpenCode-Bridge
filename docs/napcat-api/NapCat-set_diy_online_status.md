# NapCat `set_diy_online_status`：设置自定义在线状态

功能：设置自定义在线状态

分类：用户扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/266151905e0.md

调用方法：先 `napcat_describe(action="set_diy_online_status")` 核对本机参数，再 `napcat_call(action="set_diy_online_status", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

设置自定义在线状态

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "face_id": {
      "description": "图标ID",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "face_type": {
      "default": "1",
      "description": "图标类型",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "wording": {
      "default": " ",
      "description": "状态文字内容",
      "type": "string"
    }
  },
  "required": [
    "face_id",
    "face_type",
    "wording"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "face_id": "123",
  "face_type": "1",
  "wording": "自定义状态"
}
```

## 返回数据结构

```json
{
  "description": "错误信息（如果有）",
  "type": "string"
}
```

