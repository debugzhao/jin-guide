from __future__ import annotations

import re


_CHARSET_PATTERN = re.compile(rb"charset=[\"']?\s*([a-zA-Z0-9_-]+)", re.IGNORECASE)

# gb18030 是 gb2312/gbk 的超集，用它解码能同时兼容三者，比精确匹配声明的编码名更安全
_ALIASES = {"gb2312": "gb18030", "gbk": "gb18030"}


def decode_html_bytes(raw: bytes) -> str:
    """部分政府/高校官网仍用 GB2312/GBK 编码（如杭州师范大学 zsjh_2.html），统一当
    UTF-8 解码会把中文标题读成乱码——discovery 标题匹配、正文提取会全部失效且不报错
    （errors="replace" 不会抛异常，只是静默产出垃圾文本），已用真实线上页面验证过。
    优先从 HTML 头部的 charset 声明识别真实编码，读不到才回退 UTF-8。
    """
    match = _CHARSET_PATTERN.search(raw[:2048])
    if match:
        charset = match.group(1).decode("ascii", errors="ignore").lower()
        charset = _ALIASES.get(charset, charset)
        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            pass
    return raw.decode("utf-8", errors="replace")
