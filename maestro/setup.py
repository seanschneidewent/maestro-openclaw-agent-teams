#!/usr/bin/env python3
"""
Maestro Setup Wizard
Interactive CLI to get construction superintendents up and running with Maestro.
Premium Tron-inspired UI powered by rich.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.prompt import Prompt, Confirm
from rich.rule import Rule
from rich.markdown import Markdown
from rich.style import Style
from rich.text import Text
from rich.traceback import install as install_rich_traceback

# Install rich traceback handler
install_rich_traceback(show_locals=False)

# Initialize console with Tron-inspired theme
console = Console()

# Tron color scheme
THEME = {
    'primary': 'bright_cyan',
    'secondary': 'cyan',
    'success': 'green',
    'warning': 'yellow',
    'error': 'red',
    'header': 'bold bright_cyan',
    'panel_border': 'cyan',
}


class SetupWizard:
    """Maestro setup wizard with premium Tron UI"""
    
    def __init__(self):
        self.progress_file = Path.home() / ".maestro-setup.json"
        self.progress = self.load_progress()
        self.is_windows = platform.system() == "Windows"
        self.total_steps = 10
        self.current_step = 1
        
    def load_progress(self) -> Dict[str, Any]:
        """Load saved progress if exists"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_progress(self):
        """Save progress to file"""
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)
    
    def show_progress_bar(self, step_name: str):
        """Show progress indicator at the top"""
        progress_pct = (self.current_step / self.total_steps) * 100
        
        # Create progress bar text
        bar_length = 30
        filled_length = int(bar_length * self.current_step // self.total_steps)
        bar = '━' * filled_length + '╸' + '━' * (bar_length - filled_length - 1)
        
        progress_text = Text()
        progress_text.append(f"Step {self.current_step} of {self.total_steps} ", style=THEME['primary'])
        progress_text.append(bar, style=THEME['primary'])
        progress_text.append(f" {progress_pct:.0f}%", style=THEME['primary'])
        
        console.print()
        console.print(progress_text)
        console.print()
    
    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run shell command and return result"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=check,
                encoding='utf-8' if self.is_windows else None
            )
            return result
        except subprocess.CalledProcessError as e:
            if check:
                raise
            return e
    
    def step_welcome(self) -> bool:
        """Step 1: Welcome and license key"""
        self.show_progress_bar("Welcome")
        
        # ASCII art welcome
        welcome_art = """
███╗   ███╗ █████╗ ███████╗███████╗████████╗██████╗  ██████╗ 
████╗ ████║██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗
██╔████╔██║███████║█████╗  ███████╗   ██║   ██████╔╝██║   ██║
██║╚██╔╝██║██╔══██║██╔══╝  ╚════██║   ██║   ██╔══██╗██║   ██║
██║ ╚═╝ ██║██║  ██║███████╗███████║   ██║   ██║  ██║╚██████╔╝
╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ 
"""
        
        welcome_panel = Panel(
            welcome_art + "\n[bright_cyan]Your AI Assistant for Construction Plans[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Welcome to Maestro Setup[/bold bright_cyan]",
            title_align="center"
        )
        console.print(welcome_panel)
        console.print()
        
        console.print("This wizard will get you up and running with Maestro,", style=THEME['primary'])
        console.print("your AI assistant for construction plans.", style=THEME['primary'])
        console.print()
        
        if self.progress.get('license_key'):
            console.print(f"[{THEME['primary']}]ℹ Using saved license key: {self.progress['license_key'][:8]}...[/{THEME['primary']}]")
            if not Confirm.ask("[cyan]Continue with this key?[/cyan]", default=True):
                self.progress.pop('license_key', None)
        
        if not self.progress.get('license_key'):
            console.print()
            console.print("First, let's verify your license key.", style=THEME['secondary'])
            license_key = Prompt.ask("[cyan]Enter your Maestro license key[/cyan]")
            
            # Basic validation - just check it looks like a key
            if not license_key or len(license_key) < 8:
                console.print(f"[{THEME['error']}]✗ That doesn't look like a valid license key.[/{THEME['error']}]")
                return False
            
            self.progress['license_key'] = license_key
            self.save_progress()
        
        console.print(f"[{THEME['success']}]✓ License key verified[/{THEME['success']}]")
        self.current_step += 1
        return True
    
    def step_prerequisites(self) -> bool:
        """Step 2: Check prerequisites"""
        self.show_progress_bar("Prerequisites")
        
        prereq_panel = Panel(
            "[bright_cyan]Checking system requirements[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Prerequisites[/bold bright_cyan]"
        )
        console.print(prereq_panel)
        console.print()
        
        # Check Python version
        py_version = sys.version_info
        if py_version < (3, 11):
            console.print(f"[{THEME['error']}]✗ Python 3.11+ required, you have {py_version.major}.{py_version.minor}[/{THEME['error']}]")
            return False
        console.print(f"[{THEME['success']}]✓ Python {py_version.major}.{py_version.minor}.{py_version.micro}[/{THEME['success']}]")
        
        # Check OpenClaw
        result = self.run_command("openclaw --version", check=False)
        if result.returncode != 0:
            console.print(f"[{THEME['warning']}]⚠ OpenClaw is not installed[/{THEME['warning']}]")
            console.print()
            console.print("OpenClaw is the AI agent platform that powers Maestro.")
            console.print("Open a separate terminal window and run:")
            console.print()
            console.print("  [bold bright_cyan]npm install -g openclaw[/bold bright_cyan]")
            console.print()
            console.print("Then come back here when it's done.")
            console.print()
            if Confirm.ask("[cyan]Have you installed OpenClaw?[/cyan]", default=False):
                # Check again
                result = self.run_command("openclaw --version", check=False)
                if result.returncode != 0:
                    console.print(f"[{THEME['error']}]✗ Still can't find OpenClaw. Make sure npm is in your PATH.[/{THEME['error']}]")
                    return False
            else:
                return False
        
        version = result.stdout.strip()
        console.print(f"[{THEME['success']}]✓ OpenClaw {version}[/{THEME['success']}]")
        
        self.progress['prerequisites'] = True
        self.save_progress()
        self.current_step += 1
        return True
    
    def step_ai_provider(self) -> bool:
        """Step 3: Choose AI provider and get API key"""
        self.show_progress_bar("AI Provider")
        
        provider_panel = Panel(
            "[bright_cyan]Select the AI model that will power Maestro[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Choose Your AI Provider[/bold bright_cyan]"
        )
        console.print(provider_panel)
        console.print()
        
        if self.progress.get('provider') and self.progress.get('provider_key'):
            provider = self.progress['provider']
            console.print(f"[{THEME['primary']}]ℹ Using saved provider: {provider}[/{THEME['primary']}]")
            if not Confirm.ask("[cyan]Keep this provider?[/cyan]", default=True):
                self.progress.pop('provider', None)
                self.progress.pop('provider_key', None)
        
        if not self.progress.get('provider'):
            # Create fancy model comparison table
            table = Table(
                show_header=True,
                header_style=f"bold {THEME['header']}",
                border_style=THEME['panel_border'],
                title="[bold bright_cyan]Model Comparison[/bold bright_cyan]",
                title_style=THEME['header']
            )
            
            table.add_column("Option", style=THEME['primary'], width=8)
            table.add_column("Provider", style="bold bright_cyan", width=25)
            table.add_column("Cost/M tokens", style="cyan", width=18)
            table.add_column("Best For", style="white", width=35)
            table.add_column("Context", style="cyan", width=10)
            
            table.add_row(
                "1",
                "Google Gemini 3.1 Pro",
                "$2 / $12",
                "Vision + reasoning • [green]★ Recommended[/green]",
                "1M"
            )
            table.add_row(
                " ",
                "[dim]Same key powers plan analysis (saves a step)[/dim]",
                "",
                "",
                ""
            )
            
            table.add_row(
                "2",
                "Anthropic Claude Opus 4.6",
                "$5 / $25",
                "Best instruction following",
                "1M"
            )
            table.add_row(
                " ",
                "[dim]Most reliable for complex coordination[/dim]",
                "",
                "",
                ""
            )
            
            table.add_row(
                "3",
                "OpenAI GPT-5.2",
                "$1.75 / $14",
                "Fastest + lowest hallucination",
                "400K"
            )
            table.add_row(
                " ",
                "[dim]Best value for quick jobsite answers[/dim]",
                "",
                "",
                ""
            )
            
            console.print(table)
            console.print()
            
            choice = Prompt.ask(
                "[cyan]Enter 1, 2, or 3[/cyan]",
                choices=["1", "2", "3"],
                show_choices=False
            )
            
            providers = {
                '1': ('google', 'google/gemini-2.5-pro', 'GEMINI_API_KEY'),
                '2': ('anthropic', 'anthropic/claude-opus-4-6', 'ANTHROPIC_API_KEY'),
                '3': ('openai', 'openai/gpt-5.2', 'OPENAI_API_KEY'),
            }
            
            provider, model, env_key = providers[choice]
            self.progress['provider'] = provider
            self.progress['model'] = model
            self.progress['provider_env_key'] = env_key
            self.save_progress()
        
        provider = self.progress['provider']
        
        # Get API key for chosen provider
        if not self.progress.get('provider_key'):
            console.print()
            
            if provider == 'google':
                console.print("Get your Google Gemini API key:")
                console.print("  1. Visit [bold bright_cyan]https://aistudio.google.com/apikey[/bold bright_cyan]")
                console.print("  2. Sign in with Google")
                console.print("  3. Create an API key")
            elif provider == 'anthropic':
                console.print("Get your Anthropic API key:")
                console.print("  1. Visit [bold bright_cyan]https://console.anthropic.com[/bold bright_cyan]")
                console.print("  2. Sign in or create an account")
                console.print("  3. Go to API Keys and create a new key")
            elif provider == 'openai':
                console.print("Get your OpenAI API key:")
                console.print("  1. Visit [bold bright_cyan]https://platform.openai.com/api-keys[/bold bright_cyan]")
                console.print("  2. Sign in or create an account")
                console.print("  3. Create a new secret key")
            
            console.print()
            api_key = Prompt.ask("[cyan]Paste your API key[/cyan]", password=True)
            
            if not api_key or len(api_key) < 8:
                console.print(f"[{THEME['error']}]✗ That doesn't look like a valid API key[/{THEME['error']}]")
                return False
            
            # Validate key format
            if provider == 'anthropic' and not api_key.startswith('sk-ant-'):
                console.print(f"[{THEME['error']}]✗ Anthropic keys start with 'sk-ant-'[/{THEME['error']}]")
                return False
            if provider == 'openai' and not api_key.startswith('sk-'):
                console.print(f"[{THEME['error']}]✗ OpenAI keys start with 'sk-'[/{THEME['error']}]")
                return False
            
            # Test the key with spinner
            with console.status("[cyan]Testing API key...[/cyan]", spinner="dots"):
                try:
                    import httpx
                    if provider == 'google':
                        response = httpx.get(
                            f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                            timeout=10
                        )
                        valid = response.status_code == 200
                    elif provider == 'anthropic':
                        response = httpx.get(
                            "https://api.anthropic.com/v1/messages",
                            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                            timeout=10
                        )
                        valid = response.status_code != 401
                    elif provider == 'openai':
                        response = httpx.get(
                            "https://api.openai.com/v1/models",
                            headers={"Authorization": f"Bearer {api_key}"},
                            timeout=10
                        )
                        valid = response.status_code == 200
                    
                    if not valid:
                        console.print(f"[{THEME['error']}]✗ API key is invalid[/{THEME['error']}]")
                        return False
                except Exception as e:
                    console.print(f"[{THEME['warning']}]⚠ Couldn't validate key (network issue?): {e}[/{THEME['warning']}]")
                    if not Confirm.ask("[cyan]Use this key anyway?[/cyan]", default=False):
                        return False
            
            self.progress['provider_key'] = api_key
            # If Google chosen, same key powers vision — store as gemini_key too
            if provider == 'google':
                self.progress['gemini_key'] = api_key
            self.save_progress()
        
        console.print(f"[{THEME['success']}]✓ {provider.title()} API key configured[/{THEME['success']}]")
        self.current_step += 1
        return True
    
    def step_gemini_key(self) -> bool:
        """Step 4: Gemini API key (for vision — skipped if Google is the main provider)"""
        # If they chose Google as provider, the same key works for vision
        if self.progress.get('provider') == 'google':
            self.progress['gemini_key'] = self.progress['provider_key']
            self.save_progress()
            console.print(f"[{THEME['primary']}]ℹ Using your Gemini key for plan vision analysis too[/{THEME['primary']}]")
            self.current_step += 1
            return True
        
        self.show_progress_bar("Gemini Vision Key")
        
        gemini_panel = Panel(
            "[bright_cyan]Gemini powers the plan vision analysis and highlighting[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Gemini Vision Key[/bold bright_cyan]"
        )
        console.print(gemini_panel)
        console.print()
        
        if self.progress.get('gemini_key'):
            console.print(f"[{THEME['primary']}]ℹ Using saved Gemini API key[/{THEME['primary']}]")
            if not Confirm.ask("[cyan]Keep this key?[/cyan]", default=True):
                self.progress.pop('gemini_key', None)
        
        if not self.progress.get('gemini_key'):
            console.print("Maestro also uses Google Gemini for vision analysis")
            console.print("(highlighting details on your plans).")
            console.print()
            console.print("1. Visit [bold bright_cyan]https://aistudio.google.com/apikey[/bold bright_cyan]")
            console.print("2. Sign in with Google")
            console.print("3. Create an API key")
            console.print()
            
            api_key = Prompt.ask("[cyan]Paste your Gemini API key[/cyan]", password=True)
            
            if not api_key or len(api_key) < 20:
                console.print(f"[{THEME['error']}]✗ That doesn't look like a valid API key[/{THEME['error']}]")
                return False
            
            # Test the key
            with console.status("[cyan]Testing API key...[/cyan]", spinner="dots"):
                try:
                    import httpx
                    response = httpx.get(
                        f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                        timeout=10
                    )
                    if response.status_code != 200:
                        console.print(f"[{THEME['error']}]✗ API key is invalid[/{THEME['error']}]")
                        return False
                except Exception as e:
                    console.print(f"[{THEME['warning']}]⚠ Couldn't validate key (network issue?): {e}[/{THEME['warning']}]")
                    if not Confirm.ask("[cyan]Use this key anyway?[/cyan]", default=False):
                        return False
            
            self.progress['gemini_key'] = api_key
            self.save_progress()
        
        console.print(f"[{THEME['success']}]✓ Gemini vision key configured[/{THEME['success']}]")
        self.current_step += 1
        return True
    
    def step_telegram_bot(self) -> bool:
        """Step 5: Telegram bot setup"""
        self.show_progress_bar("Telegram Bot")
        
        telegram_panel = Panel(
            "[bright_cyan]Chat with Maestro from the job site[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Telegram Bot Setup[/bold bright_cyan]"
        )
        console.print(telegram_panel)
        console.print()
        
        if self.progress.get('telegram_token'):
            console.print(f"[{THEME['primary']}]ℹ Using saved Telegram bot token[/{THEME['primary']}]")
            if not Confirm.ask("[cyan]Keep this bot?[/cyan]", default=True):
                self.progress.pop('telegram_token', None)
        
        if not self.progress.get('telegram_token'):
            console.print("Maestro runs as a Telegram bot so you can text it from the job site.")
            console.print()
            console.print("To create a bot:")
            console.print("1. Open Telegram and message [bold bright_cyan]@BotFather[/bold bright_cyan]")
            console.print("2. Send /newbot")
            console.print("3. Follow prompts to name your bot")
            console.print("4. Copy the bot token (long string with numbers and letters)")
            console.print()
            
            bot_token = Prompt.ask("[cyan]Paste your bot token[/cyan]", password=True)
            
            # Validate format: should be like 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
            if not re.match(r'^\d+:[A-Za-z0-9_-]+$', bot_token):
                console.print(f"[{THEME['error']}]✗ That doesn't look like a valid bot token[/{THEME['error']}]")
                return False
            
            # Test the token
            with console.status("[cyan]Testing bot token...[/cyan]", spinner="dots"):
                try:
                    import httpx
                    response = httpx.get(
                        f"https://api.telegram.org/bot{bot_token}/getMe",
                        timeout=10
                    )
                    if response.status_code != 200:
                        console.print(f"[{THEME['error']}]✗ Bot token is invalid[/{THEME['error']}]")
                        return False
                    
                    bot_info = response.json()
                    bot_username = bot_info['result']['username']
                    console.print(f"[{THEME['success']}]✓ Bot verified: @{bot_username}[/{THEME['success']}]")
                    self.progress['bot_username'] = bot_username
                except Exception as e:
                    console.print(f"[{THEME['warning']}]⚠ Couldn't validate token (network issue?): {e}[/{THEME['warning']}]")
                    if not Confirm.ask("[cyan]Use this token anyway?[/cyan]", default=False):
                        return False
            
            self.progress['telegram_token'] = bot_token
            self.save_progress()
        
        console.print(f"[{THEME['success']}]✓ Telegram bot configured[/{THEME['success']}]")
        self.current_step += 1
        return True
    
    def step_tailscale(self) -> bool:
        """Step 6: Tailscale setup"""
        self.show_progress_bar("Tailscale")
        
        tailscale_panel = Panel(
            "[bright_cyan]Access your plan viewer from anywhere securely[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Tailscale Setup[/bold bright_cyan]"
        )
        console.print(tailscale_panel)
        console.print()
        
        console.print("Tailscale creates a secure private network so you can access")
        console.print("your plan viewer from anywhere.")
        console.print()
        
        # Check if Tailscale is installed
        result = self.run_command("tailscale --version", check=False)
        if result.returncode != 0:
            console.print(f"[{THEME['warning']}]⚠ Tailscale is not installed[/{THEME['warning']}]")
            console.print()
            if self.is_windows:
                console.print(f"Download from: [bold bright_cyan]https://tailscale.com/download/windows[/bold bright_cyan]")
            else:
                console.print(f"Download from: [bold bright_cyan]https://tailscale.com/download[/bold bright_cyan]")
            console.print()
            
            if not Confirm.ask("[cyan]Have you installed Tailscale?[/cyan]", default=False):
                console.print(f"[{THEME['warning']}]⚠ Skipping Tailscale setup - you can add it later[/{THEME['warning']}]")
                self.progress['tailscale_skip'] = True
                self.save_progress()
                self.current_step += 1
                return True
            
            # Check again
            result = self.run_command("tailscale --version", check=False)
            if result.returncode != 0:
                console.print(f"[{THEME['error']}]✗ Still can't find Tailscale[/{THEME['error']}]")
                return False
        
        console.print(f"[{THEME['success']}]✓ Tailscale is installed[/{THEME['success']}]")
        
        # Check if logged in
        result = self.run_command("tailscale status", check=False)
        if "Logged out" in result.stdout or result.returncode != 0:
            console.print(f"[{THEME['warning']}]⚠ Not logged into Tailscale[/{THEME['warning']}]")
            console.print()
            console.print("Run this command to log in:")
            console.print("  [bold bright_cyan]tailscale up[/bold bright_cyan]")
            console.print()
            
            if not Confirm.ask("[cyan]Have you logged in?[/cyan]", default=False):
                console.print(f"[{THEME['warning']}]⚠ Skipping Tailscale - you can configure it later[/{THEME['warning']}]")
                self.progress['tailscale_skip'] = True
                self.save_progress()
                self.current_step += 1
                return True
        
        # Get Tailscale IP
        result = self.run_command("tailscale ip -4", check=False)
        if result.returncode == 0:
            tailscale_ip = result.stdout.strip()
            console.print(f"[{THEME['success']}]✓ Tailscale IP: {tailscale_ip}[/{THEME['success']}]")
            self.progress['tailscale_ip'] = tailscale_ip
            self.save_progress()
        
        self.progress['tailscale_enabled'] = True
        self.save_progress()
        self.current_step += 1
        return True
    
    def step_configure_openclaw(self) -> bool:
        """Step 7: Configure OpenClaw"""
        self.show_progress_bar("Configure OpenClaw")
        
        openclaw_panel = Panel(
            "[bright_cyan]Writing OpenClaw configuration[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Configuring OpenClaw[/bold bright_cyan]"
        )
        console.print(openclaw_panel)
        console.print()
        
        # OpenClaw reads from ~/.openclaw/openclaw.json on all platforms
        config_dir = Path.home() / ".openclaw"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "openclaw.json"
        
        workspace_path = str(Path.home() / ".openclaw" / "workspace-maestro")
        
        # Load existing config or create new
        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)
            console.print(f"[{THEME['primary']}]ℹ Found existing OpenClaw config, merging...[/{THEME['primary']}]")
        else:
            config = {}
        
        # Ensure gateway config
        if 'gateway' not in config:
            config['gateway'] = {}
        config['gateway']['mode'] = 'local'
        
        # Set env (API keys at top level so all agents can use them)
        if 'env' not in config:
            config['env'] = {}
        
        # Set provider API key
        env_key = self.progress['provider_env_key']
        config['env'][env_key] = self.progress['provider_key']
        
        # Set Gemini key for vision (may be same as provider key)
        config['env']['GEMINI_API_KEY'] = self.progress['gemini_key']
        
        # Add Maestro agent using agents.list array format
        if 'agents' not in config:
            config['agents'] = {}
        if 'list' not in config['agents']:
            config['agents']['list'] = []
        
        # Remove existing maestro agent if present
        config['agents']['list'] = [
            a for a in config['agents']['list'] if a.get('id') != 'maestro'
        ]
        
        # Add maestro agent with selected model
        config['agents']['list'].append({
            "id": "maestro",
            "name": "Maestro",
            "default": True,
            "model": self.progress['model'],
            "workspace": workspace_path
        })
        
        # Add Telegram channel
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
                "maestro": {
                    "botToken": bot_token,
                    "dmPolicy": "pairing",
                    "groupPolicy": "allowlist",
                    "streamMode": "partial"
                }
            }
        }
        
        # Write config
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        console.print(f"[{THEME['success']}]✓ OpenClaw config written to {config_file}[/{THEME['success']}]")
        self.progress['openclaw_configured'] = True
        self.progress['workspace'] = workspace_path
        self.save_progress()
        self.current_step += 1
        return True
    
    def step_configure_maestro(self) -> bool:
        """Step 8: Configure Maestro workspace"""
        self.show_progress_bar("Configure Maestro")
        
        workspace_panel = Panel(
            "[bright_cyan]Setting up your Maestro workspace[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Setting Up Maestro Workspace[/bold bright_cyan]"
        )
        console.print(workspace_panel)
        console.print()
        
        # Get workspace path
        if self.is_windows:
            default_workspace = Path.home() / ".openclaw" / "workspace-maestro"
        else:
            default_workspace = Path.home() / ".openclaw" / "workspace-maestro"
        
        workspace_input = Prompt.ask(
            "[cyan]Workspace directory[/cyan]",
            default=str(default_workspace)
        )
        workspace = Path(workspace_input)
        workspace.mkdir(parents=True, exist_ok=True)
        
        console.print(f"[{THEME['primary']}]ℹ Using workspace: {workspace}[/{THEME['primary']}]")
        console.print()
        
        # Find soul files - check multiple locations
        maestro_pkg = Path(__file__).parent  # maestro/ package dir
        repo_root = maestro_pkg.parent       # repo root
        # Check bundled location first (pip install), then repo layout
        agent_dir = maestro_pkg / "agent" if (maestro_pkg / "agent").exists() else repo_root / "agent"
        
        # Copy workspace files from agent/ dir (shipped with repo)
        for filename in ['SOUL.md', 'AGENTS.md', 'IDENTITY.md', 'USER.md']:
            src = None
            for search_dir in [agent_dir, repo_root, maestro_pkg]:
                candidate = search_dir / filename
                if candidate.exists():
                    src = candidate
                    break
            
            if src:
                shutil.copy2(src, workspace / filename)
                console.print(f"[{THEME['success']}]✓ Copied {filename}[/{THEME['success']}]")
            else:
                console.print(f"[{THEME['warning']}]⚠ Couldn't find {filename} - you can add it later[/{THEME['warning']}]")
        
        # Generate TOOLS.md with project-specific config
        tools_md = f"""# TOOLS.md — Maestro Local Notes

## Active Project
- **Name:** (not yet configured — ingest plans to set this)
- **Knowledge Store:** knowledge_store/
- **Status:** Awaiting first ingest

## Key Paths
- **Knowledge store:** `knowledge_store/` (relative to workspace)
- **Scripts:** `skills/maestro/scripts/` (tools.py, loader.py)

## Environment Variables
- `MAESTRO_STORE` — Path to knowledge_store/ (set to workspace `knowledge_store/`)
- `GEMINI_API_KEY` — Required for highlight tool (Gemini vision calls)
"""
        with open(workspace / "TOOLS.md", 'w') as f:
            f.write(tools_md)
        console.print(f"[{THEME['success']}]✓ Generated TOOLS.md[/{THEME['success']}]")
        
        # Create knowledge_store directory
        knowledge_store = workspace / "knowledge_store"
        knowledge_store.mkdir(exist_ok=True)
        console.print(f"[{THEME['success']}]✓ Created knowledge_store/[/{THEME['success']}]")
        
        # Create skills directory structure
        skills_dir = workspace / "skills" / "maestro"
        skills_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy skill files (SKILL.md + scripts shims)
        skill_src = agent_dir / "skills" / "maestro"
        if skill_src.exists():
            if skills_dir.exists():
                shutil.rmtree(skills_dir)
            shutil.copytree(skill_src, skills_dir)
            console.print(f"[{THEME['success']}]✓ Copied Maestro skill[/{THEME['success']}]")
        else:
            console.print(f"[{THEME['warning']}]⚠ Couldn't find skill files - tools will still work via CLI[/{THEME['warning']}]")
        
        # Write .env file
        env_file = workspace / ".env"
        env_content = f"""# Maestro Environment
GEMINI_API_KEY={self.progress['gemini_key']}
MAESTRO_STORE=knowledge_store/
"""
        with open(env_file, 'w') as f:
            f.write(env_content)
        console.print(f"[{THEME['success']}]✓ Created .env[/{THEME['success']}]")
        
        # Build frontend if it exists (repo layout only — bundled installs ship pre-built)
        frontend_dir = repo_root / "frontend"
        if frontend_dir.exists() and (frontend_dir / "package.json").exists():
            console.print()
            
            with console.status("[cyan]Building plan viewer...[/cyan]", spinner="dots"):
                # Check for npm
                npm_check = self.run_command("npm --version", check=False)
                if npm_check.returncode == 0:
                    install_result = self.run_command(
                        f'cd "{frontend_dir}" && npm install', check=False
                    )
                    if install_result.returncode == 0:
                        build_result = self.run_command(
                            f'cd "{frontend_dir}" && npm run build', check=False
                        )
                        if build_result.returncode == 0:
                            console.print(f"[{THEME['success']}]✓ Plan viewer built[/{THEME['success']}]")
                        else:
                            console.print(f"[{THEME['warning']}]⚠ Frontend build failed — you can try later:[/{THEME['warning']}]")
                            console.print(f"  cd {frontend_dir} && npm run build")
                    else:
                        console.print(f"[{THEME['warning']}]⚠ npm install failed — you can try later:[/{THEME['warning']}]")
                        console.print(f"  cd {frontend_dir} && npm install && npm run build")
                else:
                    console.print(f"[{THEME['warning']}]⚠ npm not found — plan viewer needs Node.js to build[/{THEME['warning']}]")
                    console.print(f"  Install Node.js from https://nodejs.org")
                    console.print(f"  Then: cd {frontend_dir} && npm install && npm run build")
        
        self.progress['workspace'] = str(workspace)
        self.save_progress()
        console.print()
        console.print(f"[{THEME['success']}]✓ Workspace ready at {workspace}[/{THEME['success']}]")
        self.current_step += 1
        return True
    
    def step_ingest_plans(self) -> bool:
        """Step 9: First plans ingest"""
        self.show_progress_bar("Ingest Plans")
        
        ingest_panel = Panel(
            "[bright_cyan]Import your construction plans for AI analysis[/bright_cyan]",
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Ingest Construction Plans[/bold bright_cyan]"
        )
        console.print(ingest_panel)
        console.print()
        
        console.print("Maestro needs to analyze your PDF plans before you can ask questions.")
        console.print()
        
        if not Confirm.ask("[cyan]Do you have PDF plans ready to ingest?[/cyan]", default=False):
            console.print(f"[{THEME['primary']}]ℹ No problem - you can ingest plans later with:[/{THEME['primary']}]")
            console.print("  [bold bright_cyan]maestro ingest <path-to-pdfs>[/bold bright_cyan]")
            self.progress['ingest_skip'] = True
            self.save_progress()
            self.current_step += 1
            return True
        
        pdf_path = Prompt.ask("[cyan]Path to PDF file or directory[/cyan]")
        pdf_path = Path(pdf_path).expanduser().resolve()
        
        if not pdf_path.exists():
            console.print(f"[{THEME['error']}]✗ Path not found: {pdf_path}[/{THEME['error']}]")
            return False
        
        console.print()
        console.print(f"Ingesting plans from {pdf_path}...")
        console.print("This may take a few minutes depending on plan size.")
        console.print()
        
        # Run ingest
        workspace = Path(self.progress['workspace'])
        os.chdir(workspace)
        
        with console.status("[cyan]Analyzing plans...[/cyan]", spinner="dots"):
            result = self.run_command(f"maestro ingest {pdf_path}", check=False)
        
        if result.returncode != 0:
            console.print(f"[{THEME['error']}]✗ Ingest failed[/{THEME['error']}]")
            console.print(result.stderr)
            return False
        
        console.print(f"[{THEME['success']}]✓ Plans ingested successfully![/{THEME['success']}]")
        self.progress['plans_ingested'] = True
        self.save_progress()
        self.current_step += 1
        return True
    
    def step_done(self):
        """Step 10: Show summary and next steps"""
        console.print()
        console.print(Rule(style=THEME['panel_border']))
        console.print()
        
        # Create completion panel
        completion_art = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   [green]✓[/green]  [bold bright_cyan]MAESTRO IS READY![/bold bright_cyan]                                  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"""
        console.print(completion_art)
        console.print()
        
        # Build summary markdown
        summary_parts = ["## Configuration Summary\n"]
        
        # Bot link
        if self.progress.get('bot_username'):
            bot_link = f"https://t.me/{self.progress['bot_username']}"
            summary_parts.append(f"**Your Maestro Bot:** [{bot_link}]({bot_link})")
        
        # Provider
        if self.progress.get('provider'):
            provider = self.progress['provider'].title()
            model = self.progress.get('model', '').split('/')[-1]
            summary_parts.append(f"**AI Provider:** {provider} ({model})")
        
        # Workspace
        if self.progress.get('workspace'):
            summary_parts.append(f"**Workspace:** `{self.progress['workspace']}`")
        
        # Tailscale IP
        if self.progress.get('tailscale_ip'):
            viewer_url = f"http://{self.progress['tailscale_ip']}:3000"
            summary_parts.append(f"**Plan Viewer:** [{viewer_url}]({viewer_url})")
        
        summary_parts.append("\n## Next Steps\n")
        
        steps = [
            ("Start OpenClaw gateway", "`openclaw gateway start`"),
            ("Start plan viewer", "`maestro serve`"),
        ]
        
        if self.progress.get('bot_username'):
            steps.append((
                "Message your bot on Telegram",
                f"`@{self.progress['bot_username']}`"
            ))
        
        if not self.progress.get('plans_ingested'):
            steps.append((
                "Ingest your plans",
                "`maestro ingest <pdf-path>`"
            ))
        
        for i, (desc, cmd) in enumerate(steps, 1):
            summary_parts.append(f"{i}. **{desc}:** {cmd}")
        
        if self.progress.get('tailscale_skip'):
            summary_parts.append("\n---\n")
            summary_parts.append("⚠️ **Tailscale skipped** — to access the viewer from your phone,")
            summary_parts.append('ask your Maestro bot: "How do I set up Tailscale?"')
        
        summary_parts.append("\n---\n")
        summary_parts.append("💡 Questions? Check the docs or ask on the Maestro community.")
        
        summary_md = "\n".join(summary_parts)
        
        # Render as panel
        summary_panel = Panel(
            Markdown(summary_md),
            border_style=THEME['panel_border'],
            title="[bold bright_cyan]Setup Complete[/bold bright_cyan]",
            title_align="center",
            padding=(1, 2)
        )
        console.print(summary_panel)
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
            ("Configure Maestro", self.step_configure_maestro),
            ("Ingest Plans", self.step_ingest_plans),
        ]
        
        for step_name, step_func in steps:
            try:
                if not step_func():
                    console.print()
                    console.print(f"[{THEME['error']}]✗ Setup failed at: {step_name}[/{THEME['error']}]")
                    console.print(f"Progress saved. Run [bold bright_cyan]maestro-setup[/bold bright_cyan] again to resume.")
                    sys.exit(1)
            except KeyboardInterrupt:
                console.print()
                console.print(f"[{THEME['warning']}]⚠ Setup interrupted[/{THEME['warning']}]")
                console.print(f"Progress saved. Run [bold bright_cyan]maestro-setup[/bold bright_cyan] again to resume.")
                sys.exit(0)
            except Exception as e:
                console.print()
                console.print(Panel(
                    f"[{THEME['error']}]Unexpected error in {step_name}:\n{e}[/{THEME['error']}]",
                    border_style=THEME['error'],
                    title=f"[bold {THEME['error']}]Error[/bold {THEME['error']}]"
                ))
                console.print(f"Progress saved. Run [bold bright_cyan]maestro-setup[/bold bright_cyan] again to resume.")
                import traceback
                traceback.print_exc()
                sys.exit(1)
        
        # All steps complete
        self.step_done()


def main():
    """Main entry point"""
    wizard = SetupWizard()
    wizard.run()


if __name__ == '__main__':
    main()
