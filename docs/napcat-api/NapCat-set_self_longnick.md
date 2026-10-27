# NapCat `set_self_longnick`：设置个性签名

功能：设置个性签名

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659186e0.md

调用方法：先 `napcat_describe(action="set_self_longnick")` 核对本机参数，再 `napcat_call(action="set_self_longnick", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

修改当前登录帐号的个性签名

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "longNick": {
      "description": "签名内容",
      "type": "string"
    }
  },
  "required": [
    "longNick"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "longNick": "个性签名"
}
```

## 返回数据结构

```json
{
  "description": "设置结果"
}
```

