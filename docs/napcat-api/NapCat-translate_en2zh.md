# NapCat `translate_en2zh`：英文单词翻译

功能：英文单词翻译

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659102e0.md

调用方法：先 `napcat_describe(action="translate_en2zh")` 核对本机参数，再 `napcat_call(action="translate_en2zh", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

将英文单词列表翻译为中文

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "words": {
      "description": "待翻译单词列表",
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "required": [
    "words"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "words": [
    "hello"
  ]
}
```

## 返回数据结构

```json
{
  "description": "翻译结果",
  "type": "object",
  "properties": {
    "words": {
      "description": "翻译结果列表",
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "required": [
    "words"
  ]
}
```

