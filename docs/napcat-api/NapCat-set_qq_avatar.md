# NapCat `set_qq_avatar`：设置QQ头像

功能：设置QQ头像

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658980e0.md

调用方法：先 `napcat_describe(action="set_qq_avatar")` 核对本机参数，再 `napcat_call(action="set_qq_avatar", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

修改当前账号的QQ头像

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "file": {
      "description": "图片路径、URL或Base64",
      "type": "string"
    }
  },
  "required": [
    "file"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "file": "base64://..."
}
```

## 返回数据结构

```json
{
  "description": "设置结果",
  "type": "null"
}
```

