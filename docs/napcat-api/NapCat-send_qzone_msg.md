# NapCat `send_qzone_msg`：发表QQ空间说说

功能：发表QQ空间说说

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/496813058e0.md

调用方法：先 `napcat_describe(action="send_qzone_msg")` 核对本机参数，再 `napcat_call(action="send_qzone_msg", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

在QQ空间(Qzone)发表说说, 支持纯文字或带(多)图, 可设置查看权限

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "content": {
      "description": "说说正文",
      "type": "string"
    },
    "images": {
      "description": "图片数组, 支持 file:// http(s):// base64:// , 自动上传",
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "ugc_right": {
      "default": 1,
      "description": "查看权限: 1所有人可见 4好友可见 16部分好友可见 64仅自己可见 128部分好友不可见",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "target_uins": {
      "description": "ugc_right为16/128时, 权限作用的QQ号数组",
      "type": "array",
      "items": {
        "anyOf": [
          {
            "type": "number"
          },
          {
            "type": "string"
          }
        ]
      }
    }
  },
  "required": [
    "content"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "content": "今天天气不错",
  "images": [],
  "ugc_right": 1,
  "target_uins": []
}
```

## 返回数据结构

```json
{
  "description": "发说说结果",
  "type": "object",
  "properties": {
    "tid": {
      "description": "说说Tid",
      "type": "string"
    }
  },
  "required": [
    "tid"
  ]
}
```

