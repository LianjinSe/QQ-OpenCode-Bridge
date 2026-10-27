# NapCat `nc_get_packet_status`：获取Packet状态

功能：获取Packet状态

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659280e0.md

调用方法：先 `napcat_describe(action="nc_get_packet_status")` 核对本机参数，再 `napcat_call(action="nc_get_packet_status", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取底层Packet服务的运行状态

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

