# NapCat `upload_file_stream`：上传文件流

功能：上传文件流

分类：流式接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/395363988e0.md

调用方法：先 `napcat_describe(action="upload_file_stream")` 核对本机参数，再 `napcat_call(action="upload_file_stream", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

以流式方式上传文件数据到机器人

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "stream_id": {
      "description": "流 ID",
      "type": "string"
    },
    "chunk_data": {
      "description": "分块数据 (Base64)",
      "type": "string"
    },
    "chunk_index": {
      "description": "分块索引",
      "type": "number"
    },
    "total_chunks": {
      "description": "总分块数",
      "type": "number"
    },
    "file_size": {
      "description": "文件总大小",
      "type": "number"
    },
    "expected_sha256": {
      "description": "期望的 SHA256",
      "type": "string"
    },
    "is_complete": {
      "description": "是否完成",
      "type": "boolean"
    },
    "filename": {
      "description": "文件名",
      "type": "string"
    },
    "reset": {
      "description": "是否重置",
      "type": "boolean"
    },
    "verify_only": {
      "description": "是否仅验证",
      "type": "boolean"
    },
    "file_retention": {
      "default": 300000,
      "description": "文件保留时间 (毫秒)",
      "type": "number"
    }
  },
  "required": [
    "stream_id",
    "file_retention"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "stream_id": "uuid-1234-5678",
  "chunk_data": "SGVsbG8gV29ybGQ=",
  "chunk_index": 0,
  "total_chunks": 1,
  "file_size": 11
}
```

## 返回数据结构

```json
{
  "description": "上传结果 (流式)"
}
```

