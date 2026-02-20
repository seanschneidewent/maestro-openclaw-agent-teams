#!/usr/bin/env python3
"""
Maestro Setup Wizard
Interactive CLI to get construction superintendents up and running with Maestro.
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

# Fix Windows Unicode encoding
if platform.system() == "Windows":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except:
        pass

# ANSI color codes
class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

# Symbols with ASCII fallbacks
CHECK = '✓' if sys.stdout.encoding and 'utf' in sys.stdout.encoding.lower() else '+'
CROSS = '✗' if sys.stdout.encoding and 'utf' in sys.stdout.encoding.lower() else 'x'
WARNING = '⚠' if sys.stdout.encoding and 'utf' in sys.stdout.encoding.lower() else '!'
INFO = 'ℹ' if sys.stdout.encoding and 'utf' in sys.stdout.encoding.lower() else 'i'

def print_header(text: str):
    """Print a bold header"""
    print(f"\n{Color.BOLD}{Color.CYAN}{text}{Color.END}\n")

def print_success(text: str):
    """Print success message with checkmark"""
    print(f"{Color.GREEN}{CHECK}{Color.END} {text}")

def print_warning(text: str):
    """Print warning message"""
    print(f"{Color.YELLOW}{WARNING}{Color.END} {text}")

def print_error(text: str):
    """Print error message"""
    print(f"{Color.RED}{CROSS}{Color.END} {text}")

def print_info(text: str):
    """Print info message"""
    print(f"{Color.BLUE}{INFO}{Color.END} {text}")

class SetupWizard:
    """Maestro setup wizard"""
    
    def __init__(self):
        self.progress_file = Path.home() / ".maestro-setup.json"
        self.progress = self.load_progress()
        self.is_windows = platform.system() == "Windows"
        
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
    
    def get_input(self, prompt: str, default: Optional[str] = None) -> str:
        """Get user input with optional default"""
        if default:
            full_prompt = f"{prompt} [{default}]: "
        else:
            full_prompt = f"{prompt}: "
        
        value = input(full_prompt).strip()
        return value if value else (default or "")
    
    def confirm(self, prompt: str, default: bool = False) -> bool:
        """Ask yes/no question"""
        default_str = "Y/n" if default else "y/N"
        response = self.get_input(f"{prompt} ({default_str})", "y" if default else "n").lower()
        return response in ['y', 'yes'] if response else default
    
    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run shell command and return result"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            if check:
                raise
            return e
    
    def step_welcome(self) -> bool:
        """Step 1: Welcome and license key"""
        print_header("=== Welcome to Maestro Setup ===")
        print("This wizard will get you up and running with Maestro,")
        print("your AI assistant for construction plans.")
        print()
        
        if self.progress.get('license_key'):
            print_info(f"Using saved license key: {self.progress['license_key'][:8]}...")
            if not self.confirm("Continue with this key?", True):
                self.progress.pop('license_key', None)
        
        if not self.progress.get('license_key'):
            print()
            print("First, let's verify your license key.")
            license_key = self.get_input("Enter your Maestro license key")
            
            # Basic validation - just check it looks like a key
            if not license_key or len(license_key) < 8:
                print_error("That doesn't look like a valid license key.")
                return False
            
            self.progress['license_key'] = license_key
            self.save_progress()
        
        print_success("License key verified")
        return True
    
    def step_prerequisites(self) -> bool:
        """Step 2: Check prerequisites"""
        print_header("=== Checking Prerequisites ===")
        
        # Check Python version
        py_version = sys.version_info
        if py_version < (3, 11):
            print_error(f"Python 3.11+ required, you have {py_version.major}.{py_version.minor}")
            return False
        print_success(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
        
        # Check OpenClaw
        result = self.run_command("openclaw --version", check=False)
        if result.returncode != 0:
            print_warning("OpenClaw is not installed")
            print()
            print("OpenClaw is the AI agent platform that powers Maestro.")
            print("Open a separate terminal window and run:")
            print()
            print(f"  {Color.BOLD}npm install -g openclaw{Color.END}")
            print()
            print("Then come back here when it's done.")
            print()
            if self.confirm("Have you installed OpenClaw?", False):
                # Check again
                result = self.run_command("openclaw --version", check=False)
                if result.returncode != 0:
                    print_error("Still can't find OpenClaw. Make sure npm is in your PATH.")
                    return False
            else:
                return False
        
        version = result.stdout.strip()
        print_success(f"OpenClaw {version}")
        
        self.progress['prerequisites'] = True
        self.save_progress()
        return True
    
    def step_ai_provider(self) -> bool:
        """Step 3: Choose AI provider and get API key"""
        print_header("=== Choose Your AI Provider ===")
        
        if self.progress.get('provider') and self.progress.get('provider_key'):
            provider = self.progress['provider']
            print_info(f"Using saved provider: {provider}")
            if not self.confirm("Keep this provider?", True):
                self.progress.pop('provider', None)
                self.progress.pop('provider_key', None)
        
        if not self.progress.get('provider'):
            print("Maestro works with any of these AI providers.")
            print("Choose based on your budget and preference:")
            print()
            print(f"  {Color.BOLD}1. Google Gemini 3.1 Pro{Color.END}")
            print(f"     $2 input / $12 output per million tokens")
            print(f"     {Color.GREEN}Best value — also powers plan vision analysis{Color.END}")
            print()
            print(f"  {Color.BOLD}2. Anthropic Claude Opus 4.6{Color.END}")
            print(f"     $5 input / $25 output per million tokens")
            print(f"     Top-tier reasoning")
            print()
            print(f"  {Color.BOLD}3. OpenAI GPT-5.2{Color.END}")
            print(f"     $1.75 input / $14 output per million tokens")
            print(f"     Great all-rounder")
            print()
            
            choice = self.get_input("Enter 1, 2, or 3")
            
            providers = {
                '1': ('google', 'google/gemini-2.5-pro', 'GEMINI_API_KEY'),
                '2': ('anthropic', 'anthropic/claude-opus-4-6', 'ANTHROPIC_API_KEY'),
                '3': ('openai', 'openai/gpt-5.2', 'OPENAI_API_KEY'),
            }
            
            if choice not in providers:
                print_error("Invalid choice. Enter 1, 2, or 3.")
                return False
            
            provider, model, env_key = providers[choice]
            self.progress['provider'] = provider
            self.progress['model'] = model
            self.progress['provider_env_key'] = env_key
            self.save_progress()
        
        provider = self.progress['provider']
        
        # Get API key for chosen provider
        if not self.progress.get('provider_key'):
            if provider == 'google':
                print()
                print(f"Get your Google Gemini API key:")
                print(f"  1. Visit {Color.BOLD}https://aistudio.google.com/apikey{Color.END}")
                print(f"  2. Sign in with Google")
                print(f"  3. Create an API key")
            elif provider == 'anthropic':
                print()
                print(f"Get your Anthropic API key:")
                print(f"  1. Visit {Color.BOLD}https://console.anthropic.com{Color.END}")
                print(f"  2. Sign in or create an account")
                print(f"  3. Go to API Keys and create a new key")
            elif provider == 'openai':
                print()
                print(f"Get your OpenAI API key:")
                print(f"  1. Visit {Color.BOLD}https://platform.openai.com/api-keys{Color.END}")
                print(f"  2. Sign in or create an account")
                print(f"  3. Create a new secret key")
            
            print()
            api_key = self.get_input("Paste your API key")
            
            if not api_key or len(api_key) < 8:
                print_error("That doesn't look like a valid API key")
                return False
            
            # Validate key format
            if provider == 'anthropic' and not api_key.startswith('sk-ant-'):
                print_error("Anthropic keys start with 'sk-ant-'")
                return False
            if provider == 'openai' and not api_key.startswith('sk-'):
                print_error("OpenAI keys start with 'sk-'")
                return False
            
            # Test the key
            print("Testing API key...")
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
                    print_error("API key is invalid")
                    return False
            except Exception as e:
                print_warning(f"Couldn't validate key (network issue?): {e}")
                if not self.confirm("Use this key anyway?", False):
                    return False
            
            self.progress['provider_key'] = api_key
            # If Google chosen, same key powers vision — store as gemini_key too
            if provider == 'google':
                self.progress['gemini_key'] = api_key
            self.save_progress()
        
        print_success(f"{provider.title()} API key configured")
        return True
    
    def step_gemini_key(self) -> bool:
        """Step 4: Gemini API key (for vision — skipped if Google is the main provider)"""
        # If they chose Google as provider, the same key works for vision
        if self.progress.get('provider') == 'google':
            self.progress['gemini_key'] = self.progress['provider_key']
            self.save_progress()
            print_info("Using your Gemini key for plan vision analysis too")
            return True
        
        print_header("=== Gemini Vision Key ===")
        
        if self.progress.get('gemini_key'):
            print_info("Using saved Gemini API key")
            if not self.confirm("Keep this key?", True):
                self.progress.pop('gemini_key', None)
        
        if not self.progress.get('gemini_key'):
            print("Maestro also uses Google Gemini for vision analysis")
            print("(highlighting details on your plans).")
            print()
            print(f"1. Visit {Color.BOLD}https://aistudio.google.com/apikey{Color.END}")
            print("2. Sign in with Google")
            print("3. Create an API key")
            print()
            
            api_key = self.get_input("Paste your Gemini API key")
            
            if not api_key or len(api_key) < 20:
                print_error("That doesn't look like a valid API key")
                return False
            
            # Test the key
            print("Testing API key...")
            try:
                import httpx
                response = httpx.get(
                    f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                    timeout=10
                )
                if response.status_code != 200:
                    print_error("API key is invalid")
                    return False
            except Exception as e:
                print_warning(f"Couldn't validate key (network issue?): {e}")
                if not self.confirm("Use this key anyway?", False):
                    return False
            
            self.progress['gemini_key'] = api_key
            self.save_progress()
        
        print_success("Gemini vision key configured")
        return True
    
    def step_telegram_bot(self) -> bool:
        """Step 5: Telegram bot setup"""
        print_header("=== Telegram Bot Setup ===")
        
        if self.progress.get('telegram_token'):
            print_info("Using saved Telegram bot token")
            if not self.confirm("Keep this bot?", True):
                self.progress.pop('telegram_token', None)
        
        if not self.progress.get('telegram_token'):
            print("Maestro runs as a Telegram bot so you can text it from the job site.")
            print()
            print("To create a bot:")
            print(f"1. Open Telegram and message {Color.BOLD}@BotFather{Color.END}")
            print("2. Send /newbot")
            print("3. Follow prompts to name your bot")
            print("4. Copy the bot token (long string with numbers and letters)")
            print()
            
            bot_token = self.get_input("Paste your bot token")
            
            # Validate format: should be like 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
            if not re.match(r'^\d+:[A-Za-z0-9_-]+$', bot_token):
                print_error("That doesn't look like a valid bot token")
                return False
            
            # Test the token
            print("Testing bot token...")
            try:
                import httpx
                response = httpx.get(
                    f"https://api.telegram.org/bot{bot_token}/getMe",
                    timeout=10
                )
                if response.status_code != 200:
                    print_error("Bot token is invalid")
                    return False
                
                bot_info = response.json()
                bot_username = bot_info['result']['username']
                print_success(f"Bot verified: @{bot_username}")
                self.progress['bot_username'] = bot_username
            except Exception as e:
                print_warning(f"Couldn't validate token (network issue?): {e}")
                if not self.confirm("Use this token anyway?", False):
                    return False
            
            self.progress['telegram_token'] = bot_token
            self.save_progress()
        
        print_success("Telegram bot configured")
        return True
    
    def step_tailscale(self) -> bool:
        """Step 6: Tailscale setup"""
        print_header("=== Tailscale Setup ===")
        
        print("Tailscale creates a secure private network so you can access")
        print("your plan viewer from anywhere.")
        print()
        
        # Check if Tailscale is installed
        result = self.run_command("tailscale --version", check=False)
        if result.returncode != 0:
            print_warning("Tailscale is not installed")
            print()
            if self.is_windows:
                print(f"Download from: {Color.BOLD}https://tailscale.com/download/windows{Color.END}")
            else:
                print(f"Download from: {Color.BOLD}https://tailscale.com/download{Color.END}")
            print()
            
            if not self.confirm("Have you installed Tailscale?", False):
                print_warning("Skipping Tailscale setup - you can add it later")
                self.progress['tailscale_skip'] = True
                self.save_progress()
                return True
            
            # Check again
            result = self.run_command("tailscale --version", check=False)
            if result.returncode != 0:
                print_error("Still can't find Tailscale")
                return False
        
        print_success("Tailscale is installed")
        
        # Check if logged in
        result = self.run_command("tailscale status", check=False)
        if "Logged out" in result.stdout or result.returncode != 0:
            print_warning("Not logged into Tailscale")
            print()
            print("Run this command to log in:")
            print(f"  {Color.BOLD}tailscale up{Color.END}")
            print()
            
            if not self.confirm("Have you logged in?", False):
                print_warning("Skipping Tailscale - you can configure it later")
                self.progress['tailscale_skip'] = True
                self.save_progress()
                return True
        
        # Get Tailscale IP
        result = self.run_command("tailscale ip -4", check=False)
        if result.returncode == 0:
            tailscale_ip = result.stdout.strip()
            print_success(f"Tailscale IP: {tailscale_ip}")
            self.progress['tailscale_ip'] = tailscale_ip
            self.save_progress()
        
        self.progress['tailscale_enabled'] = True
        self.save_progress()
        return True
    
    def step_configure_openclaw(self) -> bool:
        """Step 7: Configure OpenClaw"""
        print_header("=== Configuring OpenClaw ===")
        
        # OpenClaw reads from ~/.openclaw/openclaw.json on all platforms
        config_dir = Path.home() / ".openclaw"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "openclaw.json"
        
        workspace_path = str(Path.home() / ".openclaw" / "workspace-maestro")
        
        # Load existing config or create new
        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)
            print_info("Found existing OpenClaw config, merging...")
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
        
        print_success(f"OpenClaw config written to {config_file}")
        self.progress['openclaw_configured'] = True
        self.progress['workspace'] = workspace_path
        self.save_progress()
        return True
    
    def step_configure_maestro(self) -> bool:
        """Step 8: Configure Maestro workspace"""
        print_header("=== Setting Up Maestro Workspace ===")
        
        # Get workspace path
        if self.is_windows:
            default_workspace = Path.home() / ".openclaw" / "workspace-maestro"
        else:
            default_workspace = Path.home() / ".openclaw" / "workspace-maestro"
        
        workspace_input = self.get_input(
            "Workspace directory",
            str(default_workspace)
        )
        workspace = Path(workspace_input)
        workspace.mkdir(parents=True, exist_ok=True)
        
        print_info(f"Using workspace: {workspace}")
        
        # Find soul files - check multiple locations
        maestro_pkg = Path(__file__).parent  # maestro/ package dir
        repo_root = maestro_pkg.parent       # repo root
        agent_dir = repo_root / "agent"      # agent/ directory
        
        # Copy SOUL.md and AGENTS.md from agent/ dir (shipped with repo)
        for filename in ['SOUL.md', 'AGENTS.md']:
            src = None
            for search_dir in [agent_dir, repo_root, maestro_pkg]:
                candidate = search_dir / filename
                if candidate.exists():
                    src = candidate
                    break
            
            if src:
                shutil.copy2(src, workspace / filename)
                print_success(f"Copied {filename}")
            else:
                print_warning(f"Couldn't find {filename} - you can add it later")
        
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
        print_success("Generated TOOLS.md")
        
        # Create knowledge_store directory
        knowledge_store = workspace / "knowledge_store"
        knowledge_store.mkdir(exist_ok=True)
        print_success("Created knowledge_store/")
        
        # Create skills directory structure
        skills_dir = workspace / "skills" / "maestro"
        skills_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy skill files (SKILL.md + scripts shims)
        skill_src = agent_dir / "skills" / "maestro"
        if skill_src.exists():
            if skills_dir.exists():
                shutil.rmtree(skills_dir)
            shutil.copytree(skill_src, skills_dir)
            print_success("Copied Maestro skill")
        else:
            print_warning("Couldn't find skill files - tools will still work via CLI")
        
        # Write .env file
        env_file = workspace / ".env"
        env_content = f"""# Maestro Environment
GEMINI_API_KEY={self.progress['gemini_key']}
MAESTRO_STORE=knowledge_store/
"""
        with open(env_file, 'w') as f:
            f.write(env_content)
        print_success("Created .env")
        
        self.progress['workspace'] = str(workspace)
        self.save_progress()
        print_success(f"Workspace ready at {workspace}")
        return True
    
    def step_ingest_plans(self) -> bool:
        """Step 9: First plans ingest"""
        print_header("=== Ingest Construction Plans ===")
        
        print("Maestro needs to analyze your PDF plans before you can ask questions.")
        print()
        
        if not self.confirm("Do you have PDF plans ready to ingest?", False):
            print_info("No problem - you can ingest plans later with:")
            print(f"  {Color.BOLD}maestro ingest <path-to-pdfs>{Color.END}")
            self.progress['ingest_skip'] = True
            self.save_progress()
            return True
        
        pdf_path = self.get_input("Path to PDF file or directory")
        pdf_path = Path(pdf_path).expanduser().resolve()
        
        if not pdf_path.exists():
            print_error(f"Path not found: {pdf_path}")
            return False
        
        print()
        print(f"Ingesting plans from {pdf_path}...")
        print("This may take a few minutes depending on plan size.")
        print()
        
        # Run ingest
        workspace = Path(self.progress['workspace'])
        os.chdir(workspace)
        
        result = self.run_command(f"maestro ingest {pdf_path}", check=False)
        
        if result.returncode != 0:
            print_error("Ingest failed")
            print(result.stderr)
            return False
        
        print_success("Plans ingested successfully!")
        self.progress['plans_ingested'] = True
        self.save_progress()
        return True
    
    def step_done(self):
        """Step 10: Show summary and next steps"""
        print_header("=== Maestro is Ready! ===")
        
        print(f"{Color.GREEN}Setup complete!{Color.END}")
        print()
        
        # Show bot link
        if self.progress.get('bot_username'):
            bot_link = f"https://t.me/{self.progress['bot_username']}"
            print(f"Your Maestro bot: {Color.BOLD}{bot_link}{Color.END}")
        
        # Show plan viewer URL
        if self.progress.get('tailscale_ip'):
            viewer_url = f"http://{self.progress['tailscale_ip']}:3000"
            print(f"Plan viewer: {Color.BOLD}{viewer_url}{Color.END}")
        
        print()
        print("Next steps:")
        print(f"  1. Start OpenClaw gateway: {Color.BOLD}openclaw gateway start{Color.END}")
        
        if self.progress.get('bot_username'):
            print(f"  2. Message your bot on Telegram: @{self.progress['bot_username']}")
        
        if not self.progress.get('plans_ingested'):
            print(f"  3. Ingest your plans: {Color.BOLD}maestro ingest <pdf-path>{Color.END}")
        
        print()
        print(f"{Color.CYAN}Questions? Check the docs or ask on the Maestro community.{Color.END}")
        print()
        
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
                    print()
                    print_error(f"Setup failed at: {step_name}")
                    print(f"Progress saved. Run {Color.BOLD}maestro-setup{Color.END} again to resume.")
                    sys.exit(1)
            except KeyboardInterrupt:
                print()
                print_warning("Setup interrupted")
                print(f"Progress saved. Run {Color.BOLD}maestro-setup{Color.END} again to resume.")
                sys.exit(0)
            except Exception as e:
                print()
                print_error(f"Unexpected error in {step_name}: {e}")
                print(f"Progress saved. Run {Color.BOLD}maestro-setup{Color.END} again to resume.")
                sys.exit(1)
        
        # All steps complete
        self.step_done()


def main():
    """Main entry point"""
    wizard = SetupWizard()
    wizard.run()


if __name__ == '__main__':
    main()
