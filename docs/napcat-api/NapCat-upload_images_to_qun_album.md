# NapCat `upload_images_to_qun_album`：上传多张图片到群相册

功能：上传多张图片到群相册

分类：群组扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/521420068e0.md

调用方法：先 `napcat_describe(action="upload_images_to_qun_album")` 核对本机参数，再 `napcat_call(action="upload_images_to_qun_album", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

一次上传多张图片，这些图片在群相册里显示为同一条上传

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
    "album_name": {
      "description": "相册名称",
      "type": "string"
    },
    "files": {
      "description": "图片路径、URL或Base64 数组，一次上传多张",
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "required": [
    "group_id",
    "album_id",
    "album_name",
    "files"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "album_id": "album_id_1",
  "album_name": "相册1",
  "files": [
    "/path/to/1.jpg",
    "/path/to/2.jpg"
  ]
}
```

## 返回数据结构

```json
{
  "description": "上传结果"
}
```

