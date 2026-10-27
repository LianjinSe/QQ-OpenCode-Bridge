# NapCat `get_group_share_link`：获取群分享链接

功能：获取群分享链接

分类：群组扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/514638630e0.md

调用方法：先 `napcat_describe(action="get_group_share_link")` 核对本机参数，再 `napcat_call(action="get_group_share_link", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

通过 NTQQ 原生 getJoinGroupLink 获取群的 H5 分享/加群链接 (qm.qq.com/q/xxx 或 qun.qq.com/universal-share/share?...)

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "need_short_url": {
      "default": true,
      "description": "是否返回短链 (qm.qq.com/q/xxx)，false 返回完整 universal-share 链接",
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "string"
        }
      ]
    },
    "src_id": {
      "default": 73,
      "description": "分享来源 ID",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "additional_param": {
      "default": "",
      "description": "附加参数",
      "type": "string"
    }
  },
  "required": [
    "group_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "need_short_url": true
}
```

## 返回数据结构

```json
{
  "description": "群分享链接",
  "type": "object",
  "properties": {
    "url": {
      "description": "群分享链接",
      "type": "string"
    }
  },
  "required": [
    "url"
  ]
}
```

