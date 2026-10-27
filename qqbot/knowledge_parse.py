"""Bounded, separate-process parsing of explicitly uploaded knowledge documents."""

from __future__ import annotations

import json
import re
import resource
import sys
from pathlib import Path

MAX_TEXT = 1_000_000


def parse(path, suffix):
    if suffix == ".pdf":
        from pypdf import PdfReader

        pdf = PdfReader(path)
        if pdf.is_encrypted:
            raise ValueError("暂不支持加密 PDF，请先解密")
        if len(pdf.pages) > 200:
            raise ValueError("PDF 超过 200 页，请拆分后导入")
        sections = []
        total = 0
        for number, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_TEXT:
                raise ValueError("正文超过 100 万字符，请拆分后导入")
            if text.strip():
                sections.append({"text": text, "page": number, "heading": ""})
        if not sections:
            raise ValueError("PDF 中没有可提取文字；扫描件需要先做 OCR")
        return sections
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ValueError("文本编码无法识别，请保存为 UTF-8") from exc
    if "\x00" in text:
        raise ValueError("文件不是可识别的文字文档")
    if len(text) > MAX_TEXT:
        raise ValueError("正文超过 100 万字符，请拆分后导入")
    if not text.strip():
        raise ValueError("文档没有正文")
    sections, buffer, heading = [], [], ""
    for line in text.splitlines(keepends=True):
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line) if suffix in {".md", ".markdown"} else None
        if match:
            if buffer:
                sections.append({"text": "".join(buffer), "page": None, "heading": heading})
            heading, buffer = match[1][:200], [line]
        else:
            buffer.append(line)
    if buffer:
        sections.append({"text": "".join(buffer), "page": None, "heading": heading})
    return sections


def main():
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    try:
        result = {"sections": parse(sys.argv[1], sys.argv[2])}
    except ValueError as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "文档无法解析，请检查格式或重新导出"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
