# NapCat `.ocr_image`：图片 OCR 识别 (内部)

功能：图片 OCR 识别 (内部)

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658234e0.md

调用方法：先 `napcat_describe(action=".ocr_image")` 核对本机参数，再 `napcat_call(action=".ocr_image", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

识别图片中的文字内容(仅Windows端支持)

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "image": {
      "description": "图片路径、URL或Base64",
      "type": "string"
    }
  },
  "required": [
    "image"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "image": "image_id_123"
}
```

## 返回数据结构

```json
{
  "description": "OCR结果"
}
```

