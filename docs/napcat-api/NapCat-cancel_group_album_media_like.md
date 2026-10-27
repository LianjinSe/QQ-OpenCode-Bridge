# NapCat `cancel_group_album_media_like`：取消点赞群相册媒体

功能：取消点赞群相册媒体

分类：群组扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/462330906e0.md

调用方法：先 `napcat_describe(action="cancel_group_album_media_like")` 核对本机参数，再 `napcat_call(action="cancel_group_album_media_like", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "album_id": {
      "description": "相册ID",
      "type": "string"
    },
    "batch_id": {
      "description": "batch_id",
      "type": "string"
    },
    "lloc": {
      "description": "lloc，若对整个上传操作则不填",
      "type": "string"
    }
  },
  "required": [
    "group_id",
    "album_id",
    "batch_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "album_id": "album_id",
  "batch_id": "112233",
  "lloc": "aabbcc"
}
```

## 返回数据结构

```json
{
  "description": "操作结果"
}
```

