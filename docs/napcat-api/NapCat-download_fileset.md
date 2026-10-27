# NapCat `download_fileset`：下载文件集

功能：下载文件集

分类：文件扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/410334678e0.md

调用方法：先 `napcat_describe(action="download_fileset")` 核对本机参数，再 `napcat_call(action="download_fileset", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "fileset_id": {
      "description": "文件集 ID",
      "type": "string"
    }
  },
  "required": [
    "fileset_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "fileset_id": "set_123"
}
```

## 返回数据结构

```json
{
  "description": "下载结果"
}
```

