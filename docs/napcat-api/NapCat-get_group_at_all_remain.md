# NapCat `get_group_at_all_remain`：获取群艾特全体剩余次数

功能：获取群艾特全体剩余次数

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/227245941e0.md

调用方法：先 `napcat_describe(action="get_group_at_all_remain")` 核对本机参数，再 `napcat_call(action="get_group_at_all_remain", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定群聊中艾特全体成员的剩余次数

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
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
  "group_id": "123456"
}
```

## 返回数据结构

```json
{
  "description": "群艾特全体剩余次数",
  "type": "object",
  "properties": {
    "can_at_all": {
      "description": "是否可以艾特全体",
      "type": "boolean"
    },
    "remain_at_all_count_for_group": {
      "description": "群艾特全体剩余次数",
      "type": "number"
    },
    "remain_at_all_count_for_uin": {
      "description": "个人艾特全体剩余次数",
      "type": "number"
    }
  },
  "required": [
    "can_at_all",
    "remain_at_all_count_for_group",
    "remain_at_all_count_for_uin"
  ]
}
```

