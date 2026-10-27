# NapCat `set_group_member_invite_policy`：设置群成员邀请策略

功能：设置群成员邀请策略

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/496813055e0.md

调用方法：先 `napcat_describe(action="set_group_member_invite_policy")` 核对本机参数，再 `napcat_call(action="set_group_member_invite_policy", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

设置是否允许群成员邀请好友进群，以及邀请是否需要管理员审核

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "policy": {
      "description": "成员邀请策略：禁止、需要管理员审核、无需审核、群成员少于100人时无需审核",
      "anyOf": [
        {
          "const": "disabled",
          "type": "string"
        },
        {
          "const": "require_approval",
          "type": "string"
        },
        {
          "const": "no_approval",
          "type": "string"
        },
        {
          "const": "no_approval_under_100",
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "group_id",
    "policy"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "policy": "require_approval"
}
```

## 返回数据结构

```json
{
  "description": "操作结果",
  "type": "null"
}
```

