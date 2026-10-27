# NapCat `get_group_detail_info`：获取群详细信息

功能：获取群详细信息

分类：群组接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/307180859e0.md

调用方法：先 `napcat_describe(action="get_group_detail_info")` 核对本机参数，再 `napcat_call(action="get_group_detail_info", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取群聊的详细信息，包括成员数、最大成员数等

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
  "description": "群详细信息",
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "number"
    },
    "group_name": {
      "description": "群名称",
      "type": "string"
    },
    "member_count": {
      "description": "成员数量",
      "type": "number"
    },
    "max_member_count": {
      "description": "最大成员数量",
      "type": "number"
    },
    "group_all_shut": {
      "description": "全员禁言状态",
      "type": "number"
    },
    "group_remark": {
      "description": "群备注",
      "type": "string"
    }
  },
  "required": [
    "group_id",
    "group_name",
    "member_count",
    "max_member_count",
    "group_all_shut",
    "group_remark"
  ]
}
```

