# NapCat `get_qun_album_list`：获取群相册列表

功能：获取群相册列表

分类：群组扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/395460287e0.md

调用方法：先 `napcat_describe(action="get_qun_album_list")` 核对本机参数，再 `napcat_call(action="get_qun_album_list", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "attach_info": {
      "default": "",
      "description": "附加信息（用于分页，从上一次返回结果中获取）",
      "type": "string"
    }
  },
  "required": [
    "group_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "attach_info": ""
}
```

## 返回数据结构

```json
{
  "description": "群相册列表响应",
  "type": "object",
  "properties": {
    "album_list": {
      "description": "群相册列表",
      "type": "array",
      "items": {}
    },
    "attach_info": {
      "description": "分页附加信息，传入下一次请求以获取更多数据",
      "type": "string"
    },
    "has_more": {
      "description": "是否有更多数据",
      "type": "boolean"
    }
  },
  "required": [
    "album_list",
    "attach_info",
    "has_more"
  ]
}
```

