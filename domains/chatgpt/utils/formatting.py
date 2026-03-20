#!/usr/bin/env python
"""通用格式化工具（已搬迁）：format_gpt_response, setup_logger"""
import logging
import re
from typing import Optional


_SECTION_TITLES = {
    "结论",
    "基础数据",
    "核心指标对比",
    "全品14天汇总",
    "阈值",
    "阈值（基于全品14天 thresholds）",
    "补充执行建议",
}

_BULLET_PREFIXES = (
    "动作：",
    "当前：",
    "备注：",
    "建议：",
    "词：",
    "ASIN：",
)

_BULLET_STARTS = (
    "低 ",
    "高 ",
    "超高 ",
    "其余情况",
    "高点击",
    "低点击",
)


def _is_section_header(line: str) -> bool:
    if re.match(r"^\d+\)", line):
        return True
    if line in _SECTION_TITLES:
        return True
    if line.startswith("规则-"):
        return True
    if line.endswith("：") and len(line) <= 12:
        return True
    return False


def _should_bullet(line: str) -> bool:
    if line.startswith(_BULLET_PREFIXES):
        return True
    if line.startswith(_BULLET_STARTS):
        return True
    return False


def _looks_like_markdown(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return True
        if stripped.startswith(("- ", "* ", "> ")):
            return True
        if "```" in stripped:
            return True
    return False


def format_gpt_response(text: str) -> str:
    """格式化 GPT 响应为 Markdown（若已是 Markdown 则保持原样）。"""
    if _looks_like_markdown(text):
        return text.strip()

    lines = text.splitlines()
    formatted = []
    in_section = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if formatted and formatted[-1] != "":
                formatted.append("")
            continue

        if _is_section_header(stripped):
            header = stripped.rstrip("：")
            formatted.append(f"## {header}")
            in_section = True
            continue

        if in_section:
            content = stripped
            if content.startswith("- "):
                content = content[2:].lstrip()
            if content.startswith(_BULLET_PREFIXES):
                formatted.append(f"  - {content}")
            elif _should_bullet(content):
                formatted.append(f"- {content}")
            else:
                formatted.append(content)
        else:
            formatted.append(stripped)

    return "\n".join(formatted).strip()


def setup_logger() -> logging.Logger:
    """设置并返回日志记录器。"""
    logger = logging.getLogger()
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('%(asctime)s %(name)-8s %(levelname)-8s %(message)s [%(filename)s:%(lineno)d]'))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


