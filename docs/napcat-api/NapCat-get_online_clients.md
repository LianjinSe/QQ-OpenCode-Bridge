# NapCat `get_online_clients`：获取在线客户端

功能：获取在线客户端

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657379e0.md

调用方法：先 `napcat_describe(action="get_online_clients")` 核对本机参数，再 `napcat_call(action="get_online_clients", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取当前登录账号的在线客户端列表

## 请求参数（本机 schema 优先）

```json
{
  "description": "在线客户端负载",
  "type": "object",
  "properties": {}
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "no_cache": false
}
```

## 返回数据结构

```json
{
  "description": "在线客户端列表",
  "type": "array",
  "items": {}
}
```

