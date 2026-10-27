# NapCat `_set_model_show`：设置机型

功能：设置机型

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/227233993e0.md

调用方法：先 `napcat_describe(action="_set_model_show")` 核对本机参数，再 `napcat_call(action="_set_model_show", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

设置当前账号的设备机型名称

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {}
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "model": "iPhone 13",
  "model_show": "iPhone 13"
}
```

## 返回数据结构

```json
{
  "type": "null"
}
```

