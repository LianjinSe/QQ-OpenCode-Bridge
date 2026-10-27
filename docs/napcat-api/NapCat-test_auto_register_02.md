# NapCat `test_auto_register_02`：内部自动注册测试接口（非业务功能）

功能：内部自动注册测试接口（非业务功能）

分类：内部接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://github.com/NapNeko/NapCatQQ/blob/v4.18.41/packages/napcat-onebot/action/index.ts

调用方法：先 `napcat_describe(action="test_auto_register_02")` 核对本机参数，再 `napcat_call(action="test_auto_register_02", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
  "description": "测试返回内容",
  "type": "string"
}
```

