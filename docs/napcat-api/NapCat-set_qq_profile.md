# NapCat `set_qq_profile`：设置QQ资料

功能：设置QQ资料

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657374e0.md

调用方法：先 `napcat_describe(action="set_qq_profile")` 核对本机参数，再 `napcat_call(action="set_qq_profile", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

修改当前账号的昵称、个性签名等资料

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "nickname": {
      "description": "昵称",
      "type": "string"
    },
    "personal_note": {
      "description": "个性签名",
      "type": "string"
    },
    "sex": {
      "description": "性别 (0: 未知, 1: 男, 2: 女)",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "nickname"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "nickname": "新昵称",
  "personal_note": "个性签名"
}
```

## 返回数据结构

```json
{
  "description": "设置结果"
}
```

