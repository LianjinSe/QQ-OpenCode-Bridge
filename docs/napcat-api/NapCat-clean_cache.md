# NapCat `clean_cache`：清理缓存

功能：清理缓存

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/298305106e0.md

调用方法：先 `napcat_describe(action="clean_cache")` 核对本机参数，再 `napcat_call(action="clean_cache", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

清理缓存

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

