#!/usr/bin/env python3
"""
Maestro Setup Wizard
Interactive CLI to get construction superintendents up and running with Maestro.
Rich TUI with cyan/blue Tron-inspired theme.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.prompt import Prompt, Confirm
from rich.align import Align
from rich import box
try:
    from .workspace_templates import render_company_agents_md, render_tools_md, render_workspace_env
    from .install_state import save_install_state
except ImportError:  # pragma: no cover - direct script execution fallback
    from maestro.workspace_templates import render_company_agents_md, render_tools_md, render_workspace_env
    from maestro.install_state import save_install_state

# Theme colors
CYAN = "cyan"
BLUE = "blue"
BRIGHT_CYAN = "bright_cyan"
DIM = "dim"

console = Console(force_terminal=True if platform.system() == "Windows" else None)

TOTAL_STEPS = 10


def step_header(step: int, title: str):
    """Show a step panel with progress info."""
    console.print()
    console.print(Panel(
        f"[bold {BRIGHT_CYAN}]{title}[/]",
        border_style=CYAN,
        subtitle=f"[{DIM}]Step {step} of {TOTAL_STEPS}[/]",
        subtitle_align="right",
        width=60,
    ))
    # Progress bar
    filled = int((step / TOTAL_STEPS) * 30)
    bar = "━" * filled + "─" * (30 - filled)
    pct = int((step / TOTAL_STEPS) * 100)
    console.print(f"  [{CYAN}]{bar}[/] [{DIM}]{pct}%[/]")
    console.print()


def success(text: str):
    console.print(f"  [green]✓[/] {text}")

def warning(text: str):
    console.print(f"  [yellow]⚠[/] {text}")

def error(text: str):
    console.print(f"  [red]✗[/] {text}")

def info(text: str):
    console.print(f"  [{CYAN}]ℹ[/] {text}")


class SetupWizard:
    """Maestro setup wizard"""

    def __init__(self):
        self.progress_file = Path.home() / ".maestro-setup.json"
        self.progress = self.load_progress()
        self.is_windows = platform.system() == "Windows"

    def load_progress(self) -> Dict[str, Any]:
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_progress(self):
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            if check:
                raise
            return e

    # ── Steps ─────────────────────────────────────────────────────

    def step_welcome(self) -> bool:
        """Step 1: Welcome + Company Name"""
        console.print()
        console.print(Rule(style=CYAN))
        console.print(Align.center(Text("M A E S T R O", style=f"bold {BRIGHT_CYAN}")))
        console.print(Align.center(Text("The OS for Builders", style=DIM)))
        console.print(Rule(style=CYAN))
        console.print()
        console.print(Panel(
            "[white]This wizard will get you up and running with Maestro,\n"
            "your AI assistant for construction plans.[/]\n\n"
            f"[{DIM}]9 steps · ~5 minutes · progress saved automatically[/]",
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Welcome[/]",
            width=60,
        ))

        step_header(1, "Company Name")

        if self.progress.get('company_name'):
            info(f"Using saved company name: {self.progress['company_name']}")
            if not Confirm.ask(f"  [{CYAN}]Keep this name?[/]", default=True, console=console):
                self.progress.pop('company_name', None)

        if not self.progress.get('company_name'):
            console.print(f"  [{DIM}]This appears in your Command Center and agent conversations.[/]")
            company_name = Prompt.ask(f"  [{CYAN}]Company name[/]", console=console).strip()

            if not company_name:
                error("Company name is required.")
                return False

            self.progress['company_name'] = company_name
            self.save_progress()

        # Auto-generate install UUID if not present
        if not self.progress.get('install_id'):
            self.progress['install_id'] = str(uuid.uuid4())
            self.save_progress()

        success(f"Company: {self.progress['company_name']}")
        return True

    def step_prerequisites(self) -> bool:
        """Step 2: Check prerequisites"""
        step_header(2, "Prerequisites")

        console.print(f"  [{DIM}]Checking system requirements...[/]")
        console.print()

        has_node = False
        has_npm = False
        has_openclaw = False

        # 1. OS detection
        time.sleep(0.3)
        system = platform.system()
        release = platform.release()
        machine = platform.machine()

        if system == "Darwin":
            # macOS — get version from platform.mac_ver()
            mac_ver = platform.mac_ver()[0] or release
            chip = "Apple Silicon" if machine == "arm64" else "Intel"
            os_label = f"macOS {mac_ver} ({chip})"
        elif system == "Windows":
            # Detect Windows version: release may be "11" or "10" directly,
            # or a build number. Also check build from platform.version().
            try:
                if release == "11":
                    win_ver = "11"
                elif release == "10":
                    # Could still be Windows 11 — check build number
                    build = int(platform.version().split(".")[-1])
                    win_ver = "11" if build >= 22000 else "10"
                else:
                    build = int(release)
                    win_ver = "11" if build >= 22000 else "10"
            except (ValueError, IndexError):
                win_ver = release
            arch = "x64" if machine in ("AMD64", "x86_64") else machine
            os_label = f"Windows {win_ver} ({arch})"
        else:
            # Linux — try to get distro name
            distro_name = ""
            try:
                os_release = platform.freedesktop_os_release()
                distro_name = os_release.get("PRETTY_NAME", "")
            except (OSError, AttributeError):
                pass
            if distro_name:
                os_label = f"{distro_name} ({machine})"
            else:
                os_label = f"Linux {release} ({machine})"

        success(os_label)
        self.progress['os'] = os_label
        self.save_progress()

        # 2. Python
        time.sleep(0.3)
        py_version = sys.version_info
        if py_version < (3, 11):
            error(f"Python {py_version.major}.{py_version.minor} — version 3.11+ required")
            return False
        success(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")

        # 3. Node.js
        time.sleep(0.3)
        node_result = self.run_command("node --version", check=False)
        if node_result.returncode == 0:
            has_node = True
            success(f"Node.js {node_result.stdout.strip()}")
        else:
            error(f"Node.js — not installed  [{DIM}]https://nodejs.org[/]")

        # 4. npm
        time.sleep(0.3)
        npm_result = self.run_command("npm --version", check=False)
        if npm_result.returncode == 0:
            has_npm = True
            success(f"npm {npm_result.stdout.strip()}")
        else:
            error(f"npm — not installed  [{DIM}](comes with Node.js)[/]")

        # 5. git
        time.sleep(0.3)
        git_result = self.run_command("git --version", check=False)
        if git_result.returncode == 0:
            git_ver = git_result.stdout.strip().replace("git version ", "")
            success(f"git {git_ver}")
        else:
            warning(f"git — not installed  [{DIM}](recommended but not required)[/]")

        # 6. OpenClaw
        time.sleep(0.3)
        oc_result = self.run_command("openclaw --version", check=False)
        if oc_result.returncode == 0:
            has_openclaw = True
            success(f"OpenClaw {oc_result.stdout.strip()}")
        else:
            warning("OpenClaw — not installed")

        # If OpenClaw is found, we're done
        if has_openclaw:
            self.progress['prerequisites'] = True
            self.save_progress()
            return True

        # OpenClaw not found — show install walkthrough
        console.print()

        # Platform-specific terminal hint
        if system == "Darwin":
            terminal_hint = f"[{DIM}italic]Tip: Press [bold]⌘T[/bold] for a new tab, or [bold]⌘N[/bold] for a new window.[/]"
        elif system == "Windows":
            terminal_hint = f"[{DIM}italic]Tip: Press [bold]Ctrl+Shift+T[/bold] for a new tab, or search for [bold]Terminal[/bold] / [bold]PowerShell[/bold] in Start.[/]"
        else:
            terminal_hint = f"[{DIM}italic]Tip: Press [bold]Ctrl+Shift+T[/bold] for a new terminal tab.[/]"

        if has_node and has_npm:
            panel_body = (
                f"OpenClaw is the AI agent platform that powers Maestro.\n"
                f"Let's get it installed. [bold white]Keep this terminal open.[/]\n"
                f"\n"
                f"Open a [bold white]NEW[/] terminal window and follow these steps:\n"
                f"  {terminal_hint}\n"
                f"\n"
                f"[bold {BRIGHT_CYAN}]Step 1:[/] Open a new terminal and run:\n"
                f"  [bold white]npm install -g openclaw[/]\n"
                f"\n"
                f"[bold {BRIGHT_CYAN}]Step 2:[/] Come back here and press Enter"
            )
        else:
            panel_body = (
                f"OpenClaw is the AI agent platform that powers Maestro.\n"
                f"Let's get it installed. [bold white]Keep this terminal open.[/]\n"
                f"\n"
                f"Open a [bold white]NEW[/] terminal window and follow these steps:\n"
                f"  {terminal_hint}\n"
                f"\n"
                f"[bold {BRIGHT_CYAN}]Step 1:[/] Install Node.js\n"
                f"  Download from: [bold white]https://nodejs.org[/]\n"
                f"  Choose the LTS version and run the installer.\n"
                f"\n"
                f"[bold {BRIGHT_CYAN}]Step 2:[/] Open a new terminal and run:\n"
                f"  [bold white]npm install -g openclaw[/]\n"
                f"\n"
                f"[bold {BRIGHT_CYAN}]Step 3:[/] Come back here and press Enter"
            )

        console.print(Panel(
            panel_body,
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]\U0001f99e Install OpenClaw[/]",
            width=60,
        ))
        console.print()
        Prompt.ask(f"  [{CYAN}]Press Enter when you're done[/]", default="", console=console)

        # Re-check
        oc_result = self.run_command("openclaw --version", check=False)
        if oc_result.returncode == 0:
            success(f"OpenClaw {oc_result.stdout.strip()}")
            self.progress['prerequisites'] = True
            self.save_progress()
            return True

        # Still not found
        console.print()
        console.print(Panel(
            "Still can't find OpenClaw.\n"
            "\n"
            "This usually means your terminal hasn't picked up\n"
            "the new PATH yet. Try this:\n"
            "\n"
            "  1. Close [bold white]BOTH[/] terminals\n"
            "  2. Open a fresh terminal\n"
            f"  3. Run: [bold white]maestro-setup[/]\n"
            f"     [{DIM}](your progress is saved — it'll resume here)[/]",
            border_style="yellow",
            width=60,
        ))
        console.print()
        choice = Prompt.ask(
            f"  [{CYAN}][1] Try again  [2] Skip for now  [3] Quit[/]",
            choices=["1", "2", "3"],
            default="1",
            console=console,
        )

        if choice == "1":
            oc_result = self.run_command("openclaw --version", check=False)
            if oc_result.returncode != 0:
                error("Still can't find OpenClaw. Close both terminals, reopen, and run maestro-setup.")
                return False
            success(f"OpenClaw {oc_result.stdout.strip()}")
        elif choice == "2":
            warning("Skipping OpenClaw — you'll need it before starting the gateway")
            self.progress['openclaw_skip'] = True
            self.progress['prerequisites'] = True
            self.save_progress()
            return True
        else:
            console.print()
            info("Close both terminals, open a fresh one, and run:")
            console.print(f"  [bold white]maestro-setup[/]")
            console.print(f"  [{DIM}]Your progress is saved automatically.[/]")
            sys.exit(0)

        self.progress['prerequisites'] = True
        self.save_progress()
        return True

    def step_ai_provider(self) -> bool:
        """Step 3: Choose AI provider and get API key"""
        step_header(3, "Choose Your AI Provider")

        if self.progress.get('provider') and self.progress.get('provider_key'):
            provider = self.progress['provider']
            info(f"Using saved provider: {provider}")
            if not Confirm.ask(f"  [{CYAN}]Keep this provider?[/]", default=True, console=console):
                self.progress.pop('provider', None)
                self.progress.pop('provider_key', None)

        if not self.progress.get('provider'):
            # Stacked provider cards
            console.print()
            console.print(Panel(
                f"[{DIM}]$2 / $12 per M tokens  •  1M context[/]\n"
                "\n"
                f"The [bold {BRIGHT_CYAN}]broadest knowledge base[/] of any model. [bold {BRIGHT_CYAN}]Native\n"
                f"vision[/] means it actually reads your drawings — not\n"
                f"just text descriptions of them. Strong at [bold {BRIGHT_CYAN}]synthesizing\n"
                f"information across many sheets[/] at once. [bold {BRIGHT_CYAN}]One API key[/]\n"
                "powers both the agent and plan analysis.\n"
                "\n"
                f"[{DIM}]Watch for: Can occasionally drift on very specific\n"
                f"multi-step instructions.[/]",
                border_style=BRIGHT_CYAN,
                title=f"[bold {BRIGHT_CYAN}]★ Recommended: Google Gemini 3 Pro[/]",
                width=72,
            ))
            console.print()
            console.print(Panel(
                f"[{DIM}]$5 / $25 per M tokens  •  1M context[/]\n"
                "\n"
                f"The [bold {BRIGHT_CYAN}]most precise instruction follower[/] available.\n"
                f"Excels at [bold {BRIGHT_CYAN}]complex coordination questions[/] that span\n"
                f"multiple trades and disciplines. [bold {BRIGHT_CYAN}]Maintains accuracy\n"
                f"across massive context[/] with minimal drift. Creative\n"
                f"at [bold {BRIGHT_CYAN}]finding connections others miss[/].\n"
                "\n"
                f"[{DIM}]Watch for: Most expensive option. Still needs a\n"
                f"separate Gemini key for plan vision.[/]",
                border_style=DIM,
                title=f"[{DIM}]2.[/] [bold {BRIGHT_CYAN}]Anthropic Claude Opus 4.6[/]",
                width=72,
            ))
            console.print()
            console.print(Panel(
                f"[{DIM}]$1.75 / $14 per M tokens  •  400K context[/]\n"
                "\n"
                f"[bold {BRIGHT_CYAN}]Fastest responses[/] and the [bold {BRIGHT_CYAN}]lowest hallucination rate[/]\n"
                f"of any frontier model. Gives [bold {BRIGHT_CYAN}]clean, direct answers[/].\n"
                f"Great for [bold {BRIGHT_CYAN}]rapid-fire jobsite questions[/] where speed\n"
                "matters more than deep analysis.\n"
                "\n"
                f"[{DIM}]Watch for: Smaller context window may limit\n"
                f"performance on very large plan sets. Needs separate\n"
                f"Gemini key for vision.[/]",
                border_style=DIM,
                title=f"[{DIM}]3.[/] [bold {BRIGHT_CYAN}]OpenAI GPT-5.2[/]",
                width=72,
            ))
            console.print()

            # Recommended callout
            console.print(Panel(
                f"[bold {BRIGHT_CYAN}]★ Recommended:[/] [white]Google Gemini 3 Pro — best price-to-performance, "
                "and the same API key powers plan vision analysis (saves a step).[/]",
                border_style=CYAN,
                width=72,
            ))
            console.print()

            choice = Prompt.ask(
                f"  [{CYAN}]Enter 1, 2, or 3[/]",
                choices=["1", "2", "3"],
                default="1",
                console=console,
            )

            providers = {
                '1': ('google', 'google/gemini-3-pro-preview', 'GEMINI_API_KEY'),
                '2': ('anthropic', 'anthropic/claude-opus-4-6', 'ANTHROPIC_API_KEY'),
                '3': ('openai', 'openai/gpt-5.2', 'OPENAI_API_KEY'),
            }

            provider, model, env_key = providers[choice]
            self.progress['provider'] = provider
            self.progress['model'] = model
            self.progress['provider_env_key'] = env_key
            self.save_progress()

        provider = self.progress['provider']

        # Get API key
        if not self.progress.get('provider_key'):
            key_instructions = {
                'google': (
                    "Get your Google Gemini API key:\n"
                    "  1. Visit [bold white]https://aistudio.google.com/apikey[/]\n"
                    "  2. Sign in with Google\n"
                    "  3. Create an API key"
                ),
                'anthropic': (
                    "Get your Anthropic API key:\n"
                    "  1. Visit [bold white]https://console.anthropic.com[/]\n"
                    "  2. Sign in or create an account\n"
                    "  3. Go to API Keys → create a new key"
                ),
                'openai': (
                    "Get your OpenAI API key:\n"
                    "  1. Visit [bold white]https://platform.openai.com/api-keys[/]\n"
                    "  2. Sign in or create an account\n"
                    "  3. Create a new secret key"
                ),
            }
            console.print()
            console.print(Panel(key_instructions[provider], border_style=CYAN, width=60))
            console.print()

            api_key = Prompt.ask(f"  [{CYAN}]Paste your API key[/]", console=console).strip()

            if not api_key or len(api_key) < 8:
                error("That doesn't look like a valid API key")
                return False

            if provider == 'anthropic' and not api_key.startswith('sk-ant-'):
                error("Anthropic keys start with 'sk-ant-'")
                return False
            if provider == 'openai' and not api_key.startswith('sk-'):
                error("OpenAI keys start with 'sk-'")
                return False

            # Test the key
            info("Testing API key...")
            try:
                import httpx
                if provider == 'google':
                    response = httpx.get(
                        f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                        timeout=10,
                    )
                    valid = response.status_code == 200
                elif provider == 'anthropic':
                    response = httpx.get(
                        "https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                        timeout=10,
                    )
                    valid = response.status_code != 401
                elif provider == 'openai':
                    response = httpx.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=10,
                    )
                    valid = response.status_code == 200
                else:
                    valid = True

                if not valid:
                    error("API key is invalid")
                    return False
            except Exception as e:
                warning(f"Couldn't validate key (network issue?): {e}")
                if not Confirm.ask(f"  [{CYAN}]Use this key anyway?[/]", default=False, console=console):
                    return False

            self.progress['provider_key'] = api_key
            if provider == 'google':
                self.progress['gemini_key'] = api_key
            self.save_progress()

        success(f"{provider.title()} API key configured")
        return True

    def step_gemini_key(self) -> bool:
        """Step 4: Gemini API key (for vision — skipped if Google is main provider)"""
        if self.progress.get('provider') == 'google':
            self.progress['gemini_key'] = self.progress['provider_key']
            self.save_progress()
            step_header(4, "Gemini Vision Key")
            info("Using your Gemini key for plan vision analysis too")
            success("Gemini vision key configured")
            return True

        step_header(4, "Gemini Vision Key")

        if self.progress.get('gemini_key'):
            info("Using saved Gemini API key")
            if not Confirm.ask(f"  [{CYAN}]Keep this key?[/]", default=True, console=console):
                self.progress.pop('gemini_key', None)

        if not self.progress.get('gemini_key'):
            console.print(Panel(
                "Maestro uses Google Gemini for vision analysis\n"
                "(highlighting details on your construction plans).\n\n"
                "  1. Visit [bold white]https://aistudio.google.com/apikey[/]\n"
                "  2. Sign in with Google\n"
                "  3. Create an API key",
                border_style=CYAN,
                width=60,
            ))
            console.print()

            api_key = Prompt.ask(f"  [{CYAN}]Paste your Gemini API key[/]", console=console).strip()

            if not api_key or len(api_key) < 20:
                error("That doesn't look like a valid API key")
                return False

            info("Testing API key...")
            try:
                import httpx
                response = httpx.get(
                    f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                    timeout=10,
                )
                if response.status_code != 200:
                    error("API key is invalid")
                    return False
            except Exception as e:
                warning(f"Couldn't validate key (network issue?): {e}")
                if not Confirm.ask(f"  [{CYAN}]Use this key anyway?[/]", default=False, console=console):
                    return False

            self.progress['gemini_key'] = api_key
            self.save_progress()

        success("Gemini vision key configured")
        return True

    def step_telegram_bot(self) -> bool:
        """Step 5: Telegram bot setup"""
        step_header(5, "Telegram Bot Setup")

        if self.progress.get('telegram_token'):
            info("Using saved Telegram bot token")
            if not Confirm.ask(f"  [{CYAN}]Keep this bot?[/]", default=True, console=console):
                self.progress.pop('telegram_token', None)

        if not self.progress.get('telegram_token'):
            console.print(Panel(
                "Maestro runs as a Telegram bot so you can text it from the job site.\n\n"
                "To create a bot:\n"
                "  1. Open Telegram and message [bold white]@BotFather[/]\n"
                "  2. Send /newbot\n"
                "  3. Follow prompts to name your bot\n"
                "  4. Copy the bot token",
                border_style=CYAN,
                width=60,
            ))
            console.print()

            bot_token = Prompt.ask(f"  [{CYAN}]Paste your bot token[/]", console=console).strip()

            if not re.match(r'^\d+:[A-Za-z0-9_-]+$', bot_token):
                error("That doesn't look like a valid bot token")
                return False

            info("Testing bot token...")
            try:
                import httpx
                response = httpx.get(
                    f"https://api.telegram.org/bot{bot_token}/getMe",
                    timeout=10,
                )
                if response.status_code != 200:
                    error("Bot token is invalid")
                    return False

                bot_info = response.json()
                bot_username = bot_info['result']['username']
                success(f"Bot verified: @{bot_username}")
                self.progress['bot_username'] = bot_username
            except Exception as e:
                warning(f"Couldn't validate token (network issue?): {e}")
                if not Confirm.ask(f"  [{CYAN}]Use this token anyway?[/]", default=False, console=console):
                    return False

            self.progress['telegram_token'] = bot_token
            self.save_progress()

        success("Telegram bot configured")
        return True

    def step_tailscale(self) -> bool:
        """Step 6: Tailscale setup"""
        step_header(6, "Tailscale Setup")

        console.print(Panel(
            "Tailscale creates a secure private network so you can\n"
            "access your plan viewer from anywhere.",
            border_style=CYAN,
            width=60,
        ))

        result = self.run_command("tailscale --version", check=False)
        if result.returncode != 0:
            warning("Tailscale is not installed")
            if self.is_windows:
                console.print(f"  [{DIM}]Download from:[/] [bold white]https://tailscale.com/download/windows[/]")
            else:
                console.print(f"  [{DIM}]Download from:[/] [bold white]https://tailscale.com/download[/]")
            console.print()

            if not Confirm.ask(f"  [{CYAN}]Have you installed Tailscale?[/]", default=False, console=console):
                warning("Skipping Tailscale setup — you can add it later")
                self.progress['tailscale_skip'] = True
                self.save_progress()
                return True

            result = self.run_command("tailscale --version", check=False)
            if result.returncode != 0:
                error("Still can't find Tailscale")
                return False

        success("Tailscale is installed")

        result = self.run_command("tailscale status", check=False)
        if "Logged out" in result.stdout or result.returncode != 0:
            warning("Not logged into Tailscale")
            console.print(f"  [{DIM}]Run:[/] [bold white]tailscale up[/]")
            console.print()
            if not Confirm.ask(f"  [{CYAN}]Have you logged in?[/]", default=False, console=console):
                warning("Skipping Tailscale — you can configure it later")
                self.progress['tailscale_skip'] = True
                self.save_progress()
                return True

        result = self.run_command("tailscale ip -4", check=False)
        if result.returncode == 0:
            tailscale_ip = result.stdout.strip()
            success(f"Tailscale IP: {tailscale_ip}")
            self.progress['tailscale_ip'] = tailscale_ip
            self.save_progress()

        self.progress['tailscale_enabled'] = True
        self.save_progress()
        return True

    def step_configure_openclaw(self) -> bool:
        """Step 7: Configure OpenClaw"""
        step_header(7, "Configuring OpenClaw")

        config_dir = Path.home() / ".openclaw"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "openclaw.json"

        workspace_path = str(Path.home() / ".openclaw" / "workspace-maestro")

        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)
            info("Found existing OpenClaw config, merging...")
        else:
            config = {}

        if 'gateway' not in config:
            config['gateway'] = {}
        config['gateway']['mode'] = 'local'

        # Store install metadata in ~/.maestro-setup.json (NOT in openclaw.json —
        # OpenClaw rejects unknown top-level keys and will crash the gateway)
        # Clean up any stale 'maestro' key from previous installs
        config.pop('maestro', None)

        if 'env' not in config:
            config['env'] = {}

        env_key = self.progress['provider_env_key']
        config['env'][env_key] = self.progress['provider_key']
        config['env']['GEMINI_API_KEY'] = self.progress['gemini_key']

        # The Commander as default agent
        if 'agents' not in config:
            config['agents'] = {}
        if 'list' not in config['agents']:
            config['agents']['list'] = []

        # Remove any existing maestro/company agent
        config['agents']['list'] = [
            a for a in config['agents']['list']
            if a.get('id') not in ('maestro', 'maestro-company')
        ]

        config['agents']['list'].append({
            "id": "maestro-company",
            "name": "The Commander",
            "default": True,
            "model": self.progress['model'],
            "workspace": workspace_path,
        })

        if 'channels' not in config:
            config['channels'] = {}

        bot_token = self.progress['telegram_token']
        config['channels']['telegram'] = {
            "enabled": True,
            "botToken": bot_token,
            "dmPolicy": "pairing",
            "groupPolicy": "allowlist",
            "streamMode": "partial",
            "accounts": {
                "maestro-company": {
                    "botToken": bot_token,
                    "dmPolicy": "pairing",
                    "groupPolicy": "allowlist",
                    "streamMode": "partial",
                }
            },
        }

        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)

        success(f"OpenClaw config written to {config_file}")

        # Create session directory that OpenClaw expects
        sessions_dir = config_dir / "agents" / "maestro-company" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        success("Created agent session directory")

        self.progress['openclaw_configured'] = True
        self.progress['workspace'] = workspace_path
        self.save_progress()
        return True

    def step_configure_maestro(self) -> bool:
        """Step 8: Configure Commander workspace"""
        step_header(8, "Commander Workspace")

        default_workspace = Path.home() / ".openclaw" / "workspace-maestro"

        workspace_input = Prompt.ask(
            f"  [{CYAN}]Workspace directory[/]",
            default=str(default_workspace),
            console=console,
        ).strip()
        workspace = Path(workspace_input)
        workspace.mkdir(parents=True, exist_ok=True)

        info(f"Using workspace: {workspace}")

        maestro_pkg = Path(__file__).parent
        repo_root = maestro_pkg.parent
        agent_dir = maestro_pkg / "agent" if (maestro_pkg / "agent").exists() else repo_root / "agent"

        for filename in ['SOUL.md', 'AGENTS.md', 'IDENTITY.md', 'USER.md']:
            src = None
            for search_dir in [agent_dir, repo_root, maestro_pkg]:
                candidate = search_dir / filename
                if candidate.exists():
                    src = candidate
                    break

            if src:
                shutil.copy2(src, workspace / filename)
                success(f"Copied {filename}")
            else:
                warning(f"Couldn't find {filename} — you can add it later")

        # Company workspace uses control-plane-only AGENTS instructions.
        with open(workspace / "AGENTS.md", "w") as f:
            f.write(render_company_agents_md())
        success("Generated Company AGENTS.md")

        company_name = self.progress.get('company_name', 'My Company')
        provider_env_key = self.progress.get('provider_env_key', 'GEMINI_API_KEY')
        tools_md = render_tools_md(
            company_name=company_name,
            active_provider_env_key=provider_env_key,
        )
        with open(workspace / "TOOLS.md", 'w') as f:
            f.write(tools_md)
        success("Generated TOOLS.md")

        knowledge_store = workspace / "knowledge_store"
        knowledge_store.mkdir(exist_ok=True)
        success("Created knowledge_store/")
        self.progress['fleet_store_root'] = str(knowledge_store.resolve())

        skills_dir = workspace / "skills" / "maestro"
        skills_dir.mkdir(parents=True, exist_ok=True)

        skill_src = agent_dir / "skills" / "maestro"
        if skill_src.exists():
            if skills_dir.exists():
                shutil.rmtree(skills_dir)
            shutil.copytree(skill_src, skills_dir)
            success("Copied Maestro skill")
        else:
            warning("Couldn't find skill files — tools will still work via CLI")

        env_file = workspace / ".env"
        env_content = render_workspace_env(
            store_path="knowledge_store/",
            provider_env_key=self.progress.get('provider_env_key', 'GEMINI_API_KEY'),
            provider_key=self.progress.get('provider_key', ''),
            gemini_key=self.progress.get('gemini_key', ''),
            agent_role="company",
        )
        with open(env_file, 'w') as f:
            f.write(env_content)
        success("Created .env")

        # Build frontend if it exists
        frontend_dir = repo_root / "frontend"
        if frontend_dir.exists() and (frontend_dir / "package.json").exists():
            console.print()
            info("Building plan viewer...")

            npm_check = self.run_command("npm --version", check=False)
            if npm_check.returncode == 0:
                install_result = self.run_command(
                    f'npm install --prefix "{frontend_dir}"', check=False
                )
                if install_result.returncode == 0:
                    build_result = self.run_command(
                        f'npm run build --prefix "{frontend_dir}"', check=False
                    )
                    if build_result.returncode == 0:
                        success("Plan viewer built")
                    else:
                        warning("Frontend build failed — you can try later:")
                        console.print(f"  [{DIM}]cd {frontend_dir}[/]")
                        console.print(f"  [{DIM}]npm run build[/]")
                else:
                    warning("npm install failed — you can try later:")
                    console.print(f"  [{DIM}]cd {frontend_dir}[/]")
                    console.print(f"  [{DIM}]npm install[/]")
                    console.print(f"  [{DIM}]npm run build[/]")
            else:
                warning("npm not found — plan viewer needs Node.js to build")
                console.print(f"  [{DIM}]Install Node.js from https://nodejs.org[/]")
                console.print(f"  [{DIM}]Then: cd {frontend_dir}[/]")
                console.print(f"  [{DIM}]npm install[/]")
                console.print(f"  [{DIM}]npm run build[/]")

        self.progress['workspace'] = str(workspace)
        self.save_progress()

        install_state = {
            "install_id": self.progress.get("install_id", ""),
            "company_name": self.progress.get("company_name", "Company"),
            "workspace_root": str(workspace.resolve()),
            "fleet_store_root": str(knowledge_store.resolve()),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_install_state(install_state)
        success("Saved install state")

        success(f"Workspace ready at {workspace}")
        return True

    def step_connect_telegram(self) -> bool:
        """Step 9: Start gateway and auto-pair Telegram"""
        step_header(9, "Connect Telegram")

        if self.progress.get('telegram_paired'):
            info("Telegram already paired")
            return True

        if self.progress.get('openclaw_skip'):
            warning("OpenClaw not installed — skipping Telegram connection")
            info("After installing OpenClaw, run: maestro up")
            return True

        bot_username = self.progress.get('bot_username', 'your bot')

        console.print(Panel(
            f"Starting the gateway and connecting your Telegram account.\n"
            f"This is a one-time setup step.\n"
            f"\n"
            f"[bold {BRIGHT_CYAN}]When prompted, send any message to @{bot_username} on Telegram.[/]",
            border_style=CYAN,
            width=60,
        ))
        console.print()

        # Start the gateway
        info("Starting OpenClaw gateway...")
        start_result = self.run_command("openclaw gateway start", check=False)
        if start_result.returncode != 0:
            # Try restart in case it's already running
            self.run_command("openclaw gateway restart", check=False)

        # Give gateway a moment to start
        time.sleep(3)

        # Verify gateway is running
        status_result = self.run_command("openclaw gateway status", check=False)
        if "not running" in status_result.stdout.lower() and "not running" in (status_result.stderr or "").lower():
            warning("Gateway may not have started — check logs with: openclaw logs --follow")

        success("Gateway started")
        console.print()
        console.print(f"  [bold {BRIGHT_CYAN}]👉 Now open Telegram and send any message to @{bot_username}[/]")
        console.print()

        # Wait for user to message the bot, then paste the pairing code
        # (We can't poll Telegram Bot API — OpenClaw's gateway is already
        # consuming updates, only one consumer allowed)
        console.print()
        console.print(Panel(
            f"[bold white]1.[/] Open Telegram and send any message to [bold white]@{bot_username}[/]\n"
            f"[bold white]2.[/] You'll get a reply with a [bold {BRIGHT_CYAN}]pairing code[/]\n"
            f"[bold white]3.[/] Paste that code below",
            border_style=CYAN,
            width=60,
        ))
        console.print()

        pairing_code = Prompt.ask(
            f"  [{CYAN}]Paste pairing code (or press Enter to skip)[/]",
            default="",
            console=console,
        ).strip()

        if pairing_code:
            info(f"Approving pairing code: {pairing_code}")
            approve_result = self.run_command(
                f"openclaw pairing approve telegram {pairing_code}",
                check=False,
            )
            if approve_result.returncode == 0:
                success("Telegram connected! 🎉")
                self.progress['telegram_paired'] = True
                self.save_progress()
            else:
                err_output = (approve_result.stderr or approve_result.stdout or "").strip()
                if err_output:
                    warning(f"Pairing response: {err_output}")
                # Try anyway — sometimes exit code is nonzero but it works
                self.progress['telegram_paired'] = True
                self.save_progress()
                info("If Mike responds to your next message, you're good!")
        else:
            warning("Skipping auto-pair — you can pair manually later")
            info("Send a message to your bot, then run:")
            console.print(f"  [bold white]openclaw pairing approve telegram <CODE>[/]")

        return True

    def step_done(self):
        """Step 10: Show summary and next steps"""
        step_header(10, "Setup Complete")

        company_name = self.progress.get('company_name', 'N/A')
        tailscale_ip = self.progress.get('tailscale_ip')
        cc_url = f"http://{tailscale_ip}:3000/command-center" if tailscale_ip else "http://localhost:3000/command-center"

        # Build summary rows
        rows = []
        rows.append(f"[bold white]Company:[/]     {company_name}")
        rows.append(f"[bold white]Agent:[/]       The Commander (default)")
        rows.append(f"[bold white]Provider:[/]    {self.progress.get('provider', 'N/A').title()}")
        rows.append(f"[bold white]Model:[/]       {self.progress.get('model', 'N/A')}")
        if self.progress.get('bot_username'):
            rows.append(f"[bold white]Telegram:[/]    @{self.progress['bot_username']}")
        if tailscale_ip:
            rows.append(f"[bold white]Tailscale:[/]   {tailscale_ip}")
        rows.append(f"[bold white]Cmd Center:[/]  {cc_url}")
        rows.append(f"[bold white]Workspace:[/]   {self.progress.get('workspace', 'N/A')}")
        if self.progress.get('fleet_store_root'):
            rows.append(f"[bold white]Fleet Store:[/] {self.progress.get('fleet_store_root')}")

        console.print(Panel(
            "\n".join(rows),
            border_style="green",
            title=f"[bold green]✓ {company_name} — Maestro is Ready[/]",
            width=68,
        ))

        # Next steps
        next_lines = []
        if self.progress.get('telegram_paired'):
            next_lines.append(f"  1. Start chatting:          [bold white]@{self.progress.get('bot_username', 'your bot')}[/] on Telegram")
            next_lines.append(f"  2. Open Command Center:     [bold white]{cc_url}[/]")
            next_lines.append("")
            next_lines.append(f"  [{DIM}]Use maestro up anytime to re-run health checks + launch server.[/]")
        else:
            next_lines.append(f"  1. Start Maestro:           [bold white]maestro up[/]")
            if self.progress.get('bot_username'):
                next_lines.append(f"  2. Message your bot:        [bold white]@{self.progress['bot_username']}[/] on Telegram")
            next_lines.append(f"  3. Open Command Center:     [bold white]{cc_url}[/]")
        next_lines.append("")
        next_lines.append(f"  [{DIM}]The Commander will help you set up your first project.[/]")

        console.print()
        console.print(Panel(
            "\n".join(next_lines),
            border_style=CYAN,
            title=f"[bold {BRIGHT_CYAN}]Next Steps[/]",
            width=68,
        ))

        if self.progress.get('openclaw_skip'):
            console.print()
            warning("OpenClaw not installed — install it before starting:")
            console.print(f"  [bold white]npm install -g openclaw[/]")

        if self.progress.get('tailscale_skip'):
            console.print()
            warning("Tailscale skipped — Command Center only accessible on localhost.")
            console.print(f"  [{DIM}]Install Tailscale to access from your phone.[/]")

        console.print()
        console.print(Rule(style=CYAN))
        console.print(Align.center(Text("Built for builders.", style=f"bold {BRIGHT_CYAN}")))
        console.print(Rule(style=CYAN))
        console.print()

        # Clean up progress file
        if self.progress_file.exists():
            self.progress_file.unlink()

    def run(self):
        """Run the setup wizard"""
        steps = [
            ("Welcome", self.step_welcome),
            ("Prerequisites", self.step_prerequisites),
            ("AI Provider", self.step_ai_provider),
            ("Gemini Vision Key", self.step_gemini_key),
            ("Telegram Bot", self.step_telegram_bot),
            ("Tailscale", self.step_tailscale),
            ("Configure OpenClaw", self.step_configure_openclaw),
            ("Configure Workspace", self.step_configure_maestro),
            ("Connect Telegram", self.step_connect_telegram),
        ]

        for step_name, step_func in steps:
            try:
                if not step_func():
                    console.print()
                    error(f"Setup failed at: {step_name}")
                    console.print(f"  [{DIM}]Progress saved. Run[/] [bold white]maestro-setup[/] [{DIM}]again to resume.[/]")
                    sys.exit(1)
            except KeyboardInterrupt:
                console.print()
                warning("Setup interrupted")
                console.print(f"  [{DIM}]Progress saved. Run[/] [bold white]maestro-setup[/] [{DIM}]again to resume.[/]")
                sys.exit(0)
            except Exception as e:
                console.print()
                error(f"Unexpected error in {step_name}: {e}")
                console.print(f"  [{DIM}]Progress saved. Run[/] [bold white]maestro-setup[/] [{DIM}]again to resume.[/]")
                sys.exit(1)

        # All steps complete
        self.step_done()


def main():
    """Main entry point"""
    wizard = SetupWizard()
    wizard.run()


if __name__ == '__main__':
    main()
