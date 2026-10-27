# NapCat `get_rkey_server`：获取 RKey 服务器

功能：获取 RKey 服务器

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/283136236e0.md

调用方法：先 `napcat_describe(action="get_rkey_server")` 核对本机参数，再 `napcat_call(action="get_rkey_server", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
  "type": "object",
  "properties": {
    "private_rkey": {
      "description": "私聊 RKey",
      "type": "string"
    },
    "group_rkey": {
      "description": "群聊 RKey",
      "type": "string"
    },
    "expired_time": {
      "description": "过期时间",
      "type": "number"
    },
    "name": {
      "description": "名称",
      "type": "string"
    }
  },
  "required": [
    "name"
  ]
}
```


凭据和原始包返回值通过本地不透明引用处理，不把 Cookie、密钥或票据写进聊天、文档或个人记忆。
