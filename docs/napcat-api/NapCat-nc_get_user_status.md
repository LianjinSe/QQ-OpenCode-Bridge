# NapCat `nc_get_user_status`：获取用户在线状态

功能：获取用户在线状态

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659292e0.md

调用方法：先 `napcat_describe(action="nc_get_user_status")` 核对本机参数，再 `napcat_call(action="nc_get_user_status", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "QQ号",
      "type": "string"
    }
  },
  "required": [
    "user_id"
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
  "description": "用户状态",
  "type": "object",
  "properties": {
    "status": {
      "description": "在线状态",
      "type": "number"
    },
    "ext_status": {
      "description": "扩展状态",
      "type": "number"
    }
  },
  "required": [
    "status",
    "ext_status"
  ]
}
```

