# NapCat `set_restart`：重启服务

功能：重启服务

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/410334662e0.md

调用方法：先 `napcat_describe(action="set_restart")` 核对本机参数，再 `napcat_call(action="set_restart", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

重启服务

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
  "type": "null"
}
```

