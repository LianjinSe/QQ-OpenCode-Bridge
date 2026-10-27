# NapCat `set_custom_face_desc`：修改自定义表情描述

功能：修改自定义表情描述

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/467693195e0.md

调用方法：先 `napcat_describe(action="set_custom_face_desc")` 核对本机参数，再 `napcat_call(action="set_custom_face_desc", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "emoji_id": {
      "description": "表情ID",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "res_id": {
      "description": "资源ID",
      "type": "string"
    },
    "md5": {
      "description": "表情MD5",
      "type": "string"
    },
    "desc": {
      "description": "新的表情描述",
      "type": "string"
    }
  },
  "required": [
    "emoji_id",
    "res_id",
    "md5",
    "desc"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "emoji_id": 1,
  "res_id": "resource-id",
  "md5": "d41d8cd98f00b204e9800998ecf8427e",
  "desc": "新的描述"
}
```

## 返回数据结构

```json
{
  "description": "修改结果"
}
```

