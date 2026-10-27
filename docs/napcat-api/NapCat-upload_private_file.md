# NapCat `upload_private_file`：上传私聊文件

功能：上传私聊文件

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658883e0.md

调用方法：先 `napcat_describe(action="upload_private_file")` 核对本机参数，再 `napcat_call(action="upload_private_file", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

上传本地文件到指定私聊会话中

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "用户 QQ",
      "type": "string"
    },
    "file": {
      "description": "资源路径或URL",
      "type": "string"
    },
    "name": {
      "description": "文件名",
      "type": "string"
    },
    "upload_file": {
      "default": true,
      "description": "是否执行上传",
      "type": "boolean"
    }
  },
  "required": [
    "user_id",
    "file",
    "name",
    "upload_file"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456789",
  "file": "/path/to/file",
  "name": "test.txt"
}
```

## 返回数据结构

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "description": "文件 ID",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "required": [
    "file_id"
  ]
}
```

