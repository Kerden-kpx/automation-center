#!/usr/bin/env python3
"""
测试每周周报发送脚本。

用法示例:
    # 仅预览周报内容（默认）
    python scripts/test_weekly_report_send.py
    python scripts/test_weekly_report_send.py --preview

    # 实际发送（读取 DAILY_REPORT_RECIPIENTS）
    python scripts/test_weekly_report_send.py --send

    # 临时覆盖接收人并发送
    python scripts/test_weekly_report_send.py --send --recipients "17331048354297047,17490880140202841"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import types
from pathlib import Path


def _load_env_files() -> None:
    """Load .env without overriding existing environment variables."""
    script_dir = Path(__file__).resolve().parent
    package_root = script_dir.parent
    candidates = [
        Path.cwd() / ".env",
        script_dir / ".env",
        package_root / ".env",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _bootstrap_package_import() -> None:
    """
    允许在脚本模式下导入 dingtalk_gpt_bot.* 包。
    仓库目录名为 chatgpt，包名采用 dingtalk_gpt_bot。
    """
    script_dir = Path(__file__).resolve().parent
    package_root = script_dir.parent
    repo_root = package_root.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    package_name = "dingtalk_gpt_bot"
    if package_name not in sys.modules:
        package_module = types.ModuleType(package_name)
        package_module.__path__ = [str(package_root)]  # type: ignore[attr-defined]
        package_module.__file__ = str(package_root / "__init__.py")
        sys.modules[package_name] = package_module


def _parse_recipients(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def _run(args: argparse.Namespace) -> int:
    from dingtalk_gpt_bot.services.auto_sync import _generate_daily_report, _send_daily_report
    from dingtalk_gpt_bot.services.synchronize import Settings, _close_db_pool, _close_http_session

    if args.recipients:
        os.environ["DAILY_REPORT_RECIPIENTS"] = args.recipients.strip()

    recipients = _parse_recipients(os.getenv("DAILY_REPORT_RECIPIENTS", ""))
    settings = Settings()

    try:
        if args.send:
            if not recipients:
                print("未配置接收人：请设置 DAILY_REPORT_RECIPIENTS 或使用 --recipients")
                return 1
            if not args.yes:
                confirm = input(f"确认发送周报给 {len(recipients)} 人？(y/N): ").strip().lower()
                if confirm != "y":
                    print("已取消发送")
                    return 0
            print(f"开始发送周报，接收人数量: {len(recipients)}")
            await _send_daily_report(settings)
            print("发送流程执行完成")
            return 0

        # default: preview mode
        report = await _generate_daily_report(settings)
        print("=== 周报预览开始 ===")
        print(report)
        print("=== 周报预览结束 ===")
        print(f"当前接收人数量: {len(recipients)}")
        return 0
    finally:
        await _close_http_session()
        await _close_db_pool()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="测试每周周报生成与发送")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preview", action="store_true", help="仅预览周报内容（默认）")
    group.add_argument("--send", action="store_true", help="实际发送周报")
    parser.add_argument(
        "--recipients",
        type=str,
        help="临时覆盖接收人 userId（逗号分隔），会覆盖 DAILY_REPORT_RECIPIENTS",
    )
    parser.add_argument("--yes", action="store_true", help="发送前不二次确认")
    return parser


def main() -> int:
    _load_env_files()
    _bootstrap_package_import()
    parser = _build_parser()
    args = parser.parse_args()
    if not args.preview and not args.send:
        args.preview = True
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
