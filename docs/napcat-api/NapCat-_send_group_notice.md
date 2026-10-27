# NapCat `_send_group_notice`：发送群公告

功能：发送群公告

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658740e0.md

调用方法：先 `napcat_describe(action="_send_group_notice")` 核对本机参数，再 `napcat_call(action="_send_group_notice", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

在指定群聊中发布新的公告

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "content": {
      "description": "公告内容",
      "type": "string"
    },
    "image": {
      "description": "公告图片路径或 URL",
      "type": "string"
    },
    "pinned": {
      "default": 0,
      "description": "是否置顶 (0/1)",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "type": {
      "default": 1,
      "description": "类型 (默认为 1)",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "confirm_required": {
      "default": 1,
      "description": "是否需要确认 (0/1)",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "is_show_edit_card": {
      "default": 0,
      "description": "是否显示修改群名片引导 (0/1)",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "tip_window_type": {
      "default": 0,
      "description": "弹窗类型 (默认为 0)",
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
    "group_id",
    "content",
    "pinned",
    "type",
    "confirm_required",
    "is_show_edit_card",
    "tip_window_type"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "content": "公告内容",
  "image": "base64://..."
}
```

## 返回数据结构

```json
{
  "type": "null"
}
```

