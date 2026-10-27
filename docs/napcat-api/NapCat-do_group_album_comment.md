# NapCat `do_group_album_comment`：发表群相册评论

功能：发表群相册评论

分类：群组扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/395458911e0.md

调用方法：先 `napcat_describe(action="do_group_album_comment")` 核对本机参数，再 `napcat_call(action="do_group_album_comment", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

lloc 与 batch_id 至少提供一项。传入 lloc 时评论单张图片；仅传 batch_id 时评论整个上传批次。

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
      "description": "相册 ID",
      "type": "string"
    },
    "lloc": {
      "description": "图片 ID；不传或为空时评论整个上传批次，此时必须提供 batch_id",
      "type": "string"
    },
    "batch_id": {
      "description": "上传批次 ID，可取自 get_group_album_media_list 返回的 batch.link_id 或 media[].batch_id",
      "type": "string"
    },
    "content": {
      "description": "评论内容",
      "type": "string"
    }
  },
  "required": [
    "group_id",
    "album_id",
    "content"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "album_id": "album_id_1",
  "batch_id": "2147483658",
  "content": "很有意思"
}
```

## 返回数据结构

```json
{
  "description": "评论结果"
}
```

