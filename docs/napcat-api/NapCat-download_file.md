# NapCat `download_file`：下载文件

功能：下载文件

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658887e0.md

调用方法：先 `napcat_describe(action="download_file")` 核对本机参数，再 `napcat_call(action="download_file", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

下载网络文件到本地临时目录

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "url": {
      "description": "下载链接",
      "type": "string"
    },
    "base64": {
      "description": "base64数据",
      "type": "string"
    },
    "name": {
      "description": "文件名",
      "type": "string"
    },
    "headers": {
      "description": "请求头",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        }
      ]
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "url": "https://example.com/file.png",
  "thread_count": 1,
  "headers": "User-Agent: NapCat"
}
```

## 返回数据结构

```json
{
  "description": "下载结果",
  "type": "object",
  "properties": {
    "file": {
      "description": "文件路径",
      "type": "string"
    }
  },
  "required": [
    "file"
  ]
}
```

