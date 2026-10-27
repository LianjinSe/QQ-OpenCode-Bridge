# NapCat `get_stranger_info`：获取陌生人信息

功能：获取陌生人信息

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656970e0.md

调用方法：先 `napcat_describe(action="get_stranger_info")` 核对本机参数，再 `napcat_call(action="get_stranger_info", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定非好友用户的信息

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "用户QQ",
      "type": "string"
    },
    "no_cache": {
      "default": false,
      "description": "是否不使用缓存",
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "user_id",
    "no_cache"
  ]
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
{
  "description": "陌生人信息",
  "type": "object",
  "properties": {
    "user_id": {
      "description": "用户QQ",
      "type": "number"
    },
    "uid": {
      "description": "UID",
      "type": "string"
    },
    "nickname": {
      "description": "昵称",
      "type": "string"
    },
    "age": {
      "description": "年龄",
      "type": "number"
    },
    "qid": {
      "description": "QID",
      "type": "string"
    },
    "qqLevel": {
      "description": "QQ等级",
      "type": "number"
    },
    "sex": {
      "description": "性别",
      "type": "string"
    },
    "long_nick": {
      "description": "个性签名",
      "type": "string"
    },
    "reg_time": {
      "description": "注册时间",
      "type": "number"
    },
    "is_vip": {
      "description": "是否VIP",
      "type": "boolean"
    },
    "is_years_vip": {
      "description": "是否年费VIP",
      "type": "boolean"
    },
    "vip_level": {
      "description": "VIP等级",
      "type": "number"
    },
    "remark": {
      "description": "备注",
      "type": "string"
    },
    "status": {
      "description": "状态",
      "type": "number"
    },
    "login_days": {
      "description": "登录天数",
      "type": "number"
    }
  },
  "required": [
    "user_id",
    "uid",
    "nickname",
    "age",
    "qid",
    "qqLevel",
    "sex",
    "long_nick",
    "reg_time",
    "is_vip",
    "is_years_vip",
    "vip_level",
    "remark",
    "status",
    "login_days"
  ]
}
```

