from __future__ import annotations

import json
import math
import re


class AnswerError(ValueError):
    pass


def next_field(form: dict, state: dict) -> dict | None:
    values = state.setdefault("values", {})
    skipped = state.setdefault("skipped", [])
    for field in form.get("fields", []):
        key = field["key"]
        visible = True
        for condition in field.get("when", []):
            equal = values.get(condition["key"]) == condition["value"]
            if (condition["op"] == "eq" and not equal) or (condition["op"] == "neq" and equal):
                visible = False
        if not visible or key in values or key in skipped:
            continue
        if field.get("hidden") and "default" in field:
            values[key] = field["default"]
            continue
        return field
    return None


def render_form(code: str, form: dict, state: dict) -> str:
    field = next_field(form, state)
    if field is None:
        return "你的回答都记下啦，我正在提交~"
    title = str(field.get("title") or field["key"])
    lines = [f"我还想确认一下呀 [{code}]：{form.get('title', '')}", title]
    if field.get("description"):
        lines.append(str(field["description"]))
    if field.get("hidden") or field.get("type") == "external":
        lines.append("这一项需要到 OpenCode 界面填一下呀，填好我就能接着做啦~")
        return "\n".join(lines)
    for index, option in enumerate(field.get("options", []), 1):
        lines.append(f"{index}. {option['label']}")
    if field["type"] == "multiselect":
        lines.append("可以用逗号分隔多个选项编号哦。")
    elif field["type"] == "boolean":
        lines.append("回我 是 / 否 就行啦。")
    elif field["type"] in {"number", "integer"}:
        lines.append("这一项填数字就行啦。")
    if not field.get("required", True):
        lines.append(f"这一项可以跳过：/answer {code} /skip")
    lines.append(f"/answer {code} <回答>")
    return "\n".join(lines)


def _option(text: str, options: list[dict], custom: bool) -> str:
    if text.isascii() and text.isdecimal() and 1 <= int(text) <= len(options):
        return options[int(text) - 1]["value"]
    for option in options:
        if text in {option["value"], option["label"]}:
            return option["value"]
    if options and not custom:
        raise AnswerError("这个选项没对上呀，回我一个有效的选项编号或名称就行啦~")
    return text


def add_answer(form: dict, state: dict, text: str) -> dict:
    state = json.loads(json.dumps(state))
    field = next_field(form, state)
    if field is None:
        raise AnswerError("这个问题的回答已经收齐啦，不用再填一次哦~")
    if field.get("hidden") or field["type"] == "external":
        raise AnswerError("这一项得在 OpenCode 界面填呀，填好我再继续~")
    key, kind = field["key"], field["type"]
    if text.strip() == "/skip":
        if field.get("required", True):
            raise AnswerError("这一项是必填的呀，不能跳过，给我一个回答吧~")
        if "default" in field:
            state["values"][key] = field["default"]
        else:
            state["skipped"].append(key)
        return state
    match kind:
        case "string":
            value = _option(text, field.get("options", []), field.get("custom", False))
            if len(value) < field.get("minLength", 0):
                raise AnswerError("这条回答有点太短啦，再多写一点呀~")
            if "maxLength" in field and len(value) > field["maxLength"]:
                raise AnswerError("这条回答有点太长啦，稍微缩短一点再发我吧~")
            if "pattern" in field:
                try:
                    if not re.search(field["pattern"], value):
                        raise AnswerError("这条回答的格式没对上呀，照着题目要求再填一次吧~")
                except re.error as exc:
                    raise AnswerError(
                        "这一项的格式规则我没法解析呀，到 OpenCode 界面填一下吧~"
                    ) from exc
        case "number" | "integer":
            try:
                value = float(text.strip()) if kind == "number" else int(text.strip())
                if not math.isfinite(value):
                    raise ValueError
            except ValueError as exc:
                raise AnswerError("这个数字没读懂呀，回我一个有效的数字吧~") from exc
            if value < field.get("minimum", -math.inf) or value > field.get("maximum", math.inf):
                raise AnswerError("这个数字超出允许范围啦，照着题目里的范围再填一次吧~")
            if "exclusiveMinimum" in field and value <= field["exclusiveMinimum"]:
                raise AnswerError("这个数字超出允许范围啦，照着题目里的范围再填一次吧~")
            if "exclusiveMaximum" in field and value >= field["exclusiveMaximum"]:
                raise AnswerError("这个数字超出允许范围啦，照着题目里的范围再填一次吧~")
        case "boolean":
            normalized = text.strip().casefold()
            if normalized not in {"是", "否", "true", "false", "yes", "no", "1", "0"}:
                raise AnswerError("这一项回我 是 / 否 就行啦~")
            value = normalized in {"是", "true", "yes", "1"}
        case "multiselect":
            try:
                entries = (
                    json.loads(text) if text.strip().startswith("[") else re.split(r"[,，]", text)
                )
                if not isinstance(entries, list) or not all(isinstance(v, str) for v in entries):
                    raise ValueError
                value = list(
                    dict.fromkeys(
                        _option(entry.strip(), field.get("options", []), field.get("custom", False))
                        for entry in entries
                        if entry.strip()
                    )
                )
            except (ValueError, TypeError) as exc:
                raise AnswerError("多选的编号没读对呀，用逗号分隔选项编号再发一次吧~") from exc
            if len(value) < field.get("minItems", 0) or len(value) > field.get(
                "maxItems", math.inf
            ):
                raise AnswerError("选项的数量没对上题目要求呀，增减一下再发我吧~")
        case _:
            raise AnswerError("这一类问题需要在 OpenCode 界面回答呀，填好我再继续~")
    state["values"][key] = value
    return state
