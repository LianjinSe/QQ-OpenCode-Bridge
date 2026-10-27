# NapCat `_get_group_notice`：获取群公告

功能：获取群公告

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658742e0.md

调用方法：先 `napcat_describe(action="_get_group_notice")` 核对本机参数，再 `napcat_call(action="_get_group_notice", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定群聊中的公告列表

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
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
  "description": "群公告列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "sender_id": {
        "description": "发送者QQ",
        "type": "number"
      },
      "publish_time": {
        "description": "发布时间",
        "type": "number"
      },
      "notice_id": {
        "description": "公告ID",
        "type": "string"
      },
      "message": {
        "description": "公告内容",
        "type": "object",
        "properties": {
          "text": {
            "description": "文本内容",
            "type": "string"
          },
          "image": {
            "description": "图片列表",
            "type": "array",
            "items": {}
          },
          "images": {
            "description": "图片列表",
            "type": "array",
            "items": {}
          }
        },
        "required": [
          "text",
          "image",
          "images"
        ]
      },
      "settings": {
        "description": "设置项"
      },
      "read_num": {
        "description": "阅读数",
        "type": "number"
      },
      "send_to_new_member": {
        "description": "是否为「发给新成员」公告",
        "type": "boolean"
      },
      "pinned": {
        "description": "是否置顶（仅「发给新成员」公告可读到）",
        "type": "boolean"
      }
    },
    "required": [
      "sender_id",
      "publish_time",
      "notice_id",
      "message"
    ]
  }
}
```

