"""
Aimfox Analytics Dashboard
----------------------------
Fetches campaigns, connection events, leads, and conversation messages.
Always auto-saves JSON + CSV + HTML to reports/ folder.

Usage:
    python main.py
    python main.py --api-key YOUR_KEY
    python main.py --no-messages   (skip full message threads, faster)
    python main.py --quiet         (suppress terminal output, for scheduler)
"""

import argparse
import os
import shutil
import sys
from datetime import datetime

from aimfox_client import AimfoxClient
from analytics import (
    build_campaign_stats,
    fetch_accounts,
    fetch_campaigns,
    fetch_conversations_with_messages,
    fetch_recent_leads,
    print_account_limits,
    print_accounts,
    print_campaigns,
    print_conversations,
    print_global_summary,
    print_recent_leads,
)
from report_builder import save_all
from colorama import Fore, Style, init

init(autoreset=True)


def parse_args():
    p = argparse.ArgumentParser(description="Aimfox Analytics Dashboard")
    p.add_argument("--api-key", help="Aimfox API key (overrides .env)")
    p.add_argument("--no-messages", action="store_true", help="Skip full message threads")
    p.add_argument("--quiet", action="store_true", help="No terminal output (for scheduler)")
    return p.parse_args()


def step(msg: str, quiet: bool = False):
    if not quiet:
        print(f"{Fore.WHITE}>> {msg}...{Style.RESET_ALL}")


def main():
    args = parse_args()

    if not args.quiet:
        print(f"\n{Fore.CYAN}{'='*64}")
        print(f"  Aimfox Analytics Dashboard")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*64}{Style.RESET_ALL}")

    try:
        client = AimfoxClient(api_key=args.api_key)
    except ValueError as e:
        print(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")
        sys.exit(1)

    # ── Accounts ──────────────────────────────────────────────────────────────
    step("Fetching LinkedIn accounts", args.quiet)
    accounts = fetch_accounts(client)
    if not args.quiet:
        print_accounts(accounts)
        print_account_limits(client, accounts)

    # ── Campaigns ─────────────────────────────────────────────────────────────
    step("Fetching campaigns", args.quiet)
    campaigns = fetch_campaigns(client)

    step("Fetching recent analytics (accepted connections & replies)", args.quiet)
    recent_leads = fetch_recent_leads(client)
    campaign_rows = build_campaign_stats(campaigns, recent_leads)

    if not args.quiet:
        print_campaigns(campaign_rows)
        if recent_leads:
            print_recent_leads(recent_leads, accounts)

    # ── Conversations ─────────────────────────────────────────────────────────
    if not args.no_messages:
        step("Fetching conversations and message threads", args.quiet)
        conversations = fetch_conversations_with_messages(client)
        if not args.quiet:
            print_conversations(conversations)
    else:
        step("Fetching conversations (no message threads)", args.quiet)
        conversations = client.list_conversations()

    if not args.quiet:
        print_global_summary(campaign_rows, recent_leads, conversations, accounts)

    # ── Always auto-save reports ───────────────────────────────────────────────
    step("Saving reports (JSON / CSV / HTML)", args.quiet)
    paths = save_all(accounts, campaign_rows, recent_leads, conversations)

    # Keep index.html in sync for GitHub Pages
    shutil.copy(os.path.join("reports", "report_latest.html"), "index.html")

    if not args.quiet:
        print(f"\n{Fore.GREEN}Reports saved to reports/{Style.RESET_ALL}")
        for kind, path in paths.items():
            print(f"  {kind:20s} -> {path}")

    return paths


if __name__ == "__main__":
    main()
