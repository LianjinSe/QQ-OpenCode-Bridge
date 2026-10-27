# NapCat `delete_custom_face`：删除自定义表情

功能：删除自定义表情

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/467693194e0.md

调用方法：先 `napcat_describe(action="delete_custom_face")` 核对本机参数，再 `napcat_call(action="delete_custom_face", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "res_id": {
      "anyOf": [
        {
          "description": "fetch_custom_face_detail返回的resId",
          "type": "string"
        },
        {
          "type": "array",
          "items": {
            "description": "fetch_custom_face_detail返回的resId",
            "type": "string"
          }
        }
      ]
    },
    "id": {
      "anyOf": [
        {
          "description": "native deleteFavEmoji字符串ID，通常为resId",
          "type": "string"
        },
        {
          "type": "array",
          "items": {
            "description": "native deleteFavEmoji字符串ID，通常为resId",
            "type": "string"
          }
        }
      ]
    },
    "ids": {
      "type": "array",
      "items": {
        "description": "native deleteFavEmoji字符串ID列表，通常为resId列表",
        "type": "string"
      }
    },
    "md5": {
      "anyOf": [
        {
          "description": "表情MD5，不能直接删除，请先通过fetch_custom_face_detail获取resId",
          "type": "string"
        },
        {
          "type": "array",
          "items": {
            "description": "表情MD5，不能直接删除，请先通过fetch_custom_face_detail获取resId",
            "type": "string"
          }
        }
      ]
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "res_id": "2707600964_0_0_0_D8EAA70984B402EE10B0F33DB88F4173_0_0"
}
```

## 返回数据结构

```json
{
  "description": "删除结果"
}
```

