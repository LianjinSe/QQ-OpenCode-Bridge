"""Shared query parsing helpers for dashboard endpoints."""


def page_number(request, name, *, maximum=100000):
    value = request.query.get(name, "0")
    if not value.isascii() or not value.isdecimal() or int(value) > maximum:
        raise ValueError("分页参数无效")
    return int(value)
