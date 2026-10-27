# NapCat `get_version_info`：获取版本信息

功能：获取版本信息

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657087e0.md

调用方法：先 `napcat_describe(action="get_version_info")` 核对本机参数，再 `napcat_call(action="get_version_info", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取版本信息

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
  "description": "版本信息",
  "type": "object",
  "properties": {
    "app_name": {
      "description": "应用名称",
      "type": "string"
    },
    "protocol_version": {
      "description": "协议版本",
      "type": "string"
    },
    "app_version": {
      "description": "应用版本",
      "type": "string"
    }
  },
  "required": [
    "app_name",
    "protocol_version",
    "app_version"
  ]
}
```

