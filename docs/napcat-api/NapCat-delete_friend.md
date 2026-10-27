# NapCat `delete_friend`：删除好友

功能：删除好友

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/227237873e0.md

调用方法：先 `napcat_describe(action="delete_friend")` 核对本机参数，再 `napcat_call(action="delete_friend", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

从好友列表中删除指定用户

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "friend_id": {
      "description": "好友 QQ 号",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "number"
        }
      ]
    },
    "user_id": {
      "description": "用户 QQ 号",
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "number"
        }
      ]
    },
    "temp_block": {
      "description": "是否加入黑名单",
      "type": "boolean"
    },
    "temp_both_del": {
      "description": "是否双向删除",
      "type": "boolean"
    }
  }
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456789"
}
```

## 返回数据结构

```json
{}
```

