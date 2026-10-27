# NapCat `download_file_record_stream`：下载语音文件流

功能：下载语音文件流

分类：流式传输扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/395417040e0.md

调用方法：先 `napcat_describe(action="download_file_record_stream")` 核对本机参数，再 `napcat_call(action="download_file_record_stream", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "file": {
      "description": "文件路径或 URL",
      "type": "string"
    },
    "file_id": {
      "description": "文件 ID",
      "type": "string"
    },
    "chunk_size": {
      "default": 65536,
      "description": "分块大小 (字节)",
      "type": "number"
    },
    "out_format": {
      "description": "输出格式",
      "type": "string"
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "file": "record_file_id"
}
```

## 返回数据结构

```json
{
  "description": "下载结果 (流式)"
}
```

