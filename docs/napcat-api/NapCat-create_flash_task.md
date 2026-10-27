# NapCat `create_flash_task`：创建闪传任务

功能：创建闪传任务

分类：文件扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/410334666e0.md

调用方法：先 `napcat_describe(action="create_flash_task")` 核对本机参数，再 `napcat_call(action="create_flash_task", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "files": {
      "description": "文件列表或单个文件路径",
      "anyOf": [
        {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        {
          "type": "string"
        }
      ]
    },
    "name": {
      "description": "任务名称",
      "type": "string"
    },
    "thumb_path": {
      "description": "缩略图路径",
      "type": "string"
    },
    "validitySeconds": {
      "description": "文件集有效期（秒），可选 14 天 1209600 / 90 天 7776000 / 180 天 15552000，默认 1209600",
      "type": "number"
    }
  },
  "required": [
    "files"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "files": "C:\\test.jpg",
  "name": "test_task",
  "validitySeconds": 1209600
}
```

## 返回数据结构

```json
{
  "description": "任务创建结果"
}
```

