# NapCat `get_private_file_url`：获取私聊文件URL

功能：获取私聊文件URL

分类：文件接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/266151849e0.md

调用方法：先 `napcat_describe(action="get_private_file_url")` 核对本机参数，再 `napcat_call(action="get_private_file_url", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定私聊文件的下载链接

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "description": "文件ID",
      "type": "string"
    }
  },
  "required": [
    "file_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456789",
  "file_id": "file_id_123"
}
```

## 返回数据结构

```json
{
  "description": "私聊文件URL信息",
  "type": "object",
  "properties": {
    "url": {
      "description": "文件下载链接",
      "type": "string"
    }
  }
}
```

