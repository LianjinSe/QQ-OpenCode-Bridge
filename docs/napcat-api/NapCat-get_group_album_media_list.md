# NapCat `get_group_album_media_list`：获取群相册媒体列表

功能：获取群相册媒体列表

分类：群组扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/395459066e0.md

调用方法：先 `napcat_describe(action="get_group_album_media_list")` 核对本机参数，再 `napcat_call(action="get_group_album_media_list", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
    "attach_info": {
      "default": "",
      "description": "附加信息（用于分页）",
      "type": "string"
    }
  },
  "required": [
    "group_id",
    "album_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "album_id": "album_id_1"
}
```

## 返回数据结构

```json
{
  "description": "相册媒体列表"
}
```

