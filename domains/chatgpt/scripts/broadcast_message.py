#!/usr/bin/env python
"""
批量发送消息脚本：通过钉钉机器人向所有有权限的用户发送指定消息。

使用方法：
    # 查看用户列表
    python broadcast_message.py --list
    
    # 向所有用户发送消息
    python broadcast_message.py --message "这是测试消息"
    
    # 向所有用户发送 Markdown 消息
    python broadcast_message.py --message "**重要通知**\n\n系统将于今晚维护" --markdown --title "系统通知"
    
    # 向指定用户发送消息
    python broadcast_message.py --message "测试" --users 17331048354297047,12345678
    
    # 预览模式（不实际发送）
    python broadcast_message.py --message "测试" --dry-run
"""

import argparse
import asyncio
import sys
import os
from dataclasses import dataclass
from typing import List

# 添加项目根目录到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
package_root = os.path.dirname(script_dir)
repo_root = os.path.dirname(package_root)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# 钉钉机器人凭证
CLIENT_ID = os.getenv("DING_CLIENT_ID", "ding9hx6vrnawujh9jru")
CLIENT_SECRET = os.getenv("DING_CLIENT_SECRET", "Oj91CHqlsoIFeCYzqaduQyzFbOYEQRXdlZByEZgumWCyHqPSHlix2k38giQNNofO")
ROBOT_CODE = os.getenv("DING_ROBOT_CODE", "ding9hx6vrnawujh9jru")

# 有权限使用机器人的用户ID列表
DEFAULT_USER_IDS = [
    "17331048354297047",
    "17490880140202841",
    "17585057805545058",
    "17439904366695445",
    "17506435638027211",
    "17496925056054051",
    "454365106138190421",
    "62394843421394760007",
    "01364646263121664148",
    "1765330560146600",
    "250755202726645853",
    "17427794048531392",
    "17490879808802516",
    "17403614178121993",
    "17465848709312615",
    "290435484624363486",
    "153901355623458228",
    "17554807676693214",
    "17441633442965653",
    "16063564311489688",
    "17621342403159969",
    "01076420214327759759",
    "17633432685584853",
    "395439341733212350",
    "23210537641286444",
    "350843032936428602",
    "17489140420206931",
    "17429534556529296",
]


@dataclass
class Config:
    """配置类，模拟原有的 config 对象"""
    client_id: str = CLIENT_ID
    client_secret: str = CLIENT_SECRET
    robot_code: str = ROBOT_CODE


async def send_message_to_users(
    user_ids: List[str],
    message: str,
    title: str = "机器人通知",
    use_markdown: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    向指定用户列表发送消息。
    
    Args:
        user_ids: 用户ID列表
        message: 消息内容
        title: 消息标题（Markdown 模式下使用）
        use_markdown: 是否使用 Markdown 格式
        dry_run: 是否为预览模式（不实际发送）
    
    Returns:
        dict: 发送结果
    """
    from dingtalk_gpt_bot.utils.dingtalk_api import get_token, send_robot_private_message
    
    config = Config()
    
    if dry_run:
        print("\n[预览模式] 以下用户将收到消息（未实际发送）:")
        for uid in user_ids:
            print(f"  - {uid}")
        print(f"\n消息内容:\n{message}")
        return {"dry_run": True, "user_count": len(user_ids)}
    
    # 获取 access_token
    access_token = await get_token(config)
    if not access_token:
        return {"error": "获取 access_token 失败"}
    
    # 钉钉批量发送限制每次最多20个用户
    batch_size = 20
    success_count = 0
    fail_count = 0
    
    for i in range(0, len(user_ids), batch_size):
        batch = user_ids[i:i + batch_size]
        try:
            result = send_robot_private_message(
                access_token=access_token,
                config=config,
                user_ids=batch,
                message=message,
                msg_title=title,
                use_markdown=use_markdown,
            )
            if result:
                success_count += len(batch)
                print(f"[成功] 已发送给 {len(batch)} 个用户 (批次 {i // batch_size + 1})")
            else:
                fail_count += len(batch)
                print(f"[失败] 发送失败 (批次 {i // batch_size + 1})")
        except Exception as exc:
            fail_count += len(batch)
            print(f"[错误] 发送失败: {exc}")
    
    return {
        "total": len(user_ids),
        "success": success_count,
        "failed": fail_count,
    }


async def main():
    parser = argparse.ArgumentParser(description="通过钉钉机器人批量发送消息")
    parser.add_argument("--list", action="store_true", help="列出默认用户列表")
    parser.add_argument("--message", "-m", type=str, help="要发送的消息内容")
    parser.add_argument("--title", "-t", type=str, default="机器人通知", help="消息标题（Markdown 模式）")
    parser.add_argument("--markdown", action="store_true", help="使用 Markdown 格式")
    parser.add_argument("--users", "-u", type=str, help="指定用户ID列表（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际发送")
    # 快捷消息
    parser.add_argument("--stop", action="store_true", help="发送停止服务通知")
    parser.add_argument("--resume", action="store_true", help="发送恢复服务通知")
    
    args = parser.parse_args()
    
    # 快捷消息
    if args.stop:
        args.message = "更新程序，需要停止一下服务~~"
    elif args.resume:
        args.message = "已正常恢复服务~~"
    
    # 列出默认用户
    if args.list:
        print(f"\n默认用户列表（共 {len(DEFAULT_USER_IDS)} 个）:\n")
        for i, uid in enumerate(DEFAULT_USER_IDS, 1):
            print(f"  {i:2}. {uid}")
        return
    
    # 发送消息
    if args.message:
        # 确定目标用户
        if args.users:
            user_ids = [uid.strip() for uid in args.users.split(",")]
            print(f"\n将向 {len(user_ids)} 个指定用户发送消息")
        else:
            # 默认使用配置的用户列表
            user_ids = DEFAULT_USER_IDS
            print(f"\n将向 {len(user_ids)} 个用户发送消息（使用默认列表）")
        
        # 发送确认
        if not args.dry_run:
            confirm = input(f"\n确认向 {len(user_ids)} 个用户发送消息？(y/N): ")
            if confirm.lower() != 'y':
                print("已取消发送")
                return
        
        # 发送消息
        result = await send_message_to_users(
            user_ids=user_ids,
            message=args.message,
            title=args.title,
            use_markdown=args.markdown,
            dry_run=args.dry_run,
        )
        
        print(f"\n发送结果: {result}")
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
