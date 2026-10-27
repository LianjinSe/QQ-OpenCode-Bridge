# NapCat `get_image`：获取图片

功能：获取图片

分类：文件接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657066e0.md

调用方法：先 `napcat_describe(action="get_image")` 核对本机参数，再 `napcat_call(action="get_image", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定图片的信息及路径

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "file": {
      "description": "文件路径、URL或Base64",
      "type": "string"
    },
    "file_id": {
      "description": "文件ID",
      "type": "string"
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "file": "image_id_123"
}
```

## 返回数据结构

```json
{
  "description": "文件信息",
  "type": "object",
  "properties": {
    "file": {
      "description": "本地路径",
      "type": "string"
    },
    "url": {
      "description": "下载URL",
      "type": "string"
    },
    "file_size": {
      "description": "文件大小",
      "type": "string"
    },
    "file_name": {
      "description": "文件名",
      "type": "string"
    },
    "base64": {
      "description": "Base64编码",
      "type": "string"
    }
  }
}
```

