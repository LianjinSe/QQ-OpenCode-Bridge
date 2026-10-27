# NapCat `add_custom_face`：添加自定义表情

功能：添加自定义表情

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/467693193e0.md

调用方法：先 `napcat_describe(action="add_custom_face")` 核对本机参数，再 `napcat_call(action="add_custom_face", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "file": {
      "description": "本地表情文件路径",
      "type": "string"
    },
    "emoji_id": {
      "description": "表情ID，未提供时传空字符串",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "number"
        }
      ]
    },
    "package_id": {
      "description": "表情包ID，未提供时传0",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "number"
        }
      ]
    },
    "file_name": {
      "description": "文件名，未提供时从file路径取basename",
      "type": "string"
    },
    "file_size": {
      "description": "文件大小，未提供时读取本地文件",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "number"
        }
      ]
    },
    "md5": {
      "description": "文件MD5，未提供时读取本地文件计算",
      "type": "string"
    },
    "is_mark_face": {
      "description": "是否商城表情",
      "type": "boolean"
    },
    "is_origin": {
      "description": "是否原图",
      "type": "boolean"
    }
  },
  "required": [
    "file"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "file": "C:\\Users\\Public\\face.png",
  "is_origin": true
}
```

## 返回数据结构

```json
{
  "description": "添加结果"
}
```

