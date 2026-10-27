# NapCat `test_download_stream`：测试下载流

功能：测试下载流

分类：流式传输扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/395355338e0.md

调用方法：先 `napcat_describe(action="test_download_stream")` 核对本机参数，再 `napcat_call(action="test_download_stream", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "error": {
      "default": false,
      "description": "是否触发测试错误",
      "type": "boolean"
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "url": "http://example.com/file"
}
```

## 返回数据结构

```json
{
  "description": "测试流数据"
}
```

