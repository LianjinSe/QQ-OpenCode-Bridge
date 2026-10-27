# NapCat `get_mini_app_ark`：获取小程序 Ark

功能：获取小程序 Ark

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/227738594e0.md

调用方法：先 `napcat_describe(action="get_mini_app_ark")` 核对本机参数，再 `napcat_call(action="get_mini_app_ark", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "description": "小程序Ark参数",
  "anyOf": [
    {
      "type": "object",
      "properties": {
        "type": {
          "description": "模板类型",
          "anyOf": [
            {
              "const": "bili",
              "type": "string"
            },
            {
              "const": "weibo",
              "type": "string"
            }
          ]
        },
        "title": {
          "description": "标题",
          "type": "string"
        },
        "desc": {
          "description": "描述",
          "type": "string"
        },
        "picUrl": {
          "description": "图片URL",
          "type": "string"
        },
        "jumpUrl": {
          "description": "跳转URL",
          "type": "string"
        },
        "webUrl": {
          "description": "网页URL",
          "type": "string"
        },
        "rawArkData": {
          "description": "是否返回原始Ark数据",
          "type": "string"
        }
      },
      "required": [
        "type",
        "title",
        "desc",
        "picUrl",
        "jumpUrl"
      ]
    },
    {
      "type": "object",
      "properties": {
        "title": {
          "description": "标题",
          "type": "string"
        },
        "desc": {
          "description": "描述",
          "type": "string"
        },
        "picUrl": {
          "description": "图片URL",
          "type": "string"
        },
        "jumpUrl": {
          "description": "跳转URL",
          "type": "string"
        },
        "iconUrl": {
          "description": "图标URL",
          "type": "string"
        },
        "webUrl": {
          "description": "网页URL",
          "type": "string"
        },
        "appId": {
          "description": "小程序AppID",
          "type": "string"
        },
        "scene": {
          "description": "场景ID",
          "type": "string"
        },
        "templateType": {
          "description": "模板类型",
          "type": "string"
        },
        "businessType": {
          "description": "业务类型",
          "type": "string"
        },
        "verType": {
          "description": "版本类型",
          "type": "string"
        },
        "shareType": {
          "description": "分享类型",
          "type": "string"
        },
        "versionId": {
          "description": "版本ID",
          "type": "string"
        },
        "sdkId": {
          "description": "SDK ID",
          "type": "string"
        },
        "withShareTicket": {
          "description": "是否携带分享票据",
          "type": "string"
        },
        "rawArkData": {
          "description": "是否返回原始Ark数据",
          "type": "string"
        }
      },
      "required": [
        "title",
        "desc",
        "picUrl",
        "jumpUrl",
        "iconUrl",
        "appId",
        "scene",
        "templateType",
        "businessType",
        "verType",
        "shareType",
        "versionId",
        "sdkId",
        "withShareTicket"
      ]
    }
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "type": "bili",
  "title": "测试标题",
  "desc": "测试描述",
  "picUrl": "http://example.com/pic.jpg",
  "jumpUrl": "http://example.com"
}
```

## 返回数据结构

```json
{
  "description": "获取小程序Ark结果",
  "type": "object",
  "properties": {
    "data": {
      "description": "Ark数据"
    }
  },
  "required": [
    "data"
  ]
}
```

