# NapCat `get_login_info`：获取登录号信息

功能：获取登录号信息

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226656952e0.md

调用方法：先 `napcat_describe(action="get_login_info")` 核对本机参数，再 `napcat_call(action="get_login_info", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取当前登录帐号的信息

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {}
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{}
```

## 返回数据结构

```json
{
  "$ref": "#/$defs/OB11User"
}
```

`#/$defs/...` 的具体消息段和数据类型见《NapCat-公共数据类型》，或用 `napcat_schema(name)` 按需读取。
