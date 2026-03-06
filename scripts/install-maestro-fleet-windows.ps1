$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$installRoot = if ($env:MAESTRO_INSTALL_ROOT) { $env:MAESTRO_INSTALL_ROOT } else { Join-Path $HOME ".maestro" }
$fleetHome = if ($env:MAESTRO_FLEET_HOME) { $env:MAESTRO_FLEET_HOME } else { Join-Path $HOME ".maestro-fleet" }
$venvDir = if ($env:MAESTRO_VENV_DIR) { $env:MAESTRO_VENV_DIR } else { Join-Path $HOME "maestro-venv-fleet" }
$packageSpec = [string]$env:MAESTRO_FLEET_PACKAGE_SPEC
$autoApproveRaw = if ($env:MAESTRO_INSTALL_AUTO) { [string]$env:MAESTRO_INSTALL_AUTO } else { "auto" }
$requireTailscaleRaw = if ($env:MAESTRO_FLEET_REQUIRE_TAILSCALE) { [string]$env:MAESTRO_FLEET_REQUIRE_TAILSCALE } else { "1" }
$autoDeployRaw = if ($env:MAESTRO_FLEET_DEPLOY) { [string]$env:MAESTRO_FLEET_DEPLOY } else { "1" }
$openclawProfile = if ($env:MAESTRO_OPENCLAW_PROFILE) { [string]$env:MAESTRO_OPENCLAW_PROFILE } else { "maestro-fleet" }
$script:pythonHostCommand = @()
$script:pythonExe = ""
$script:autoApprove = $false
$script:requireTailscale = $false
$script:autoDeploy = $true
$script:portablePythonRoot = ""

function Write-Log([string]$message) {
  Write-Host "[maestro-fleet-install] $message"
}

function Write-Warn([string]$message) {
  Write-Warning "[maestro-fleet-install] $message"
}

function Fail([string]$message) {
  throw "[maestro-fleet-install] $message"
}

function Resolve-Flag([string]$raw, [bool]$defaultValue, [bool]$autoMeansNonInteractive) {
  $clean = if ($null -eq $raw) { "" } else { [string]$raw }
  $clean = $clean.Trim().ToLowerInvariant()
  switch ($clean) {
    "1" { return $true }
    "true" { return $true }
    "yes" { return $true }
    "on" { return $true }
    "0" { return $false }
    "false" { return $false }
    "no" { return $false }
    "off" { return $false }
    "" { return $defaultValue }
    "auto" {
      if ($autoMeansNonInteractive) {
        return (-not [Environment]::UserInteractive)
      }
      return $defaultValue
    }
    default { Fail "Invalid boolean value: $raw" }
  }
}

function Prompt-YesNo([string]$prompt, [bool]$defaultYes) {
  if ($script:autoApprove) {
    Write-Log ("{0} (auto-{1})" -f $prompt, ($(if ($defaultYes) { "yes" } else { "no" })))
    return $defaultYes
  }
  $suffix = if ($defaultYes) { "[Y/n]" } else { "[y/N]" }
  $reply = Read-Host "$prompt $suffix"
  if ([string]::IsNullOrWhiteSpace($reply)) {
    return $defaultYes
  }
  switch ($reply.Trim().ToLowerInvariant()) {
    "y" { return $true }
    "yes" { return $true }
    default { return $false }
  }
}

function Ensure-Directory([string]$path) {
  if (-not (Test-Path $path)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
  }
}

function Ensure-PathEntry([string]$entry) {
  if ([string]::IsNullOrWhiteSpace($entry)) {
    return
  }
  if ($env:PATH -notlike "*$entry*") {
    $env:PATH = "$entry;$env:PATH"
  }
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if ([string]::IsNullOrWhiteSpace($userPath)) {
    [Environment]::SetEnvironmentVariable("Path", $entry, "User")
    return
  }
  $parts = $userPath.Split(";") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  if ($parts -contains $entry) {
    return
  }
  [Environment]::SetEnvironmentVariable("Path", "$entry;$userPath", "User")
}

function Invoke-WingetInstall([string]$packageId, [string]$label) {
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    Fail "$label is required and winget.exe is unavailable."
  }
  $installArgs = @(
    "install",
    "--id", $packageId,
    "--exact",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--disable-interactivity",
    "--silent"
  )

  Write-Log "Installing $label via winget."
  $installOutput = & $winget.Source @installArgs 2>&1
  $installCode = $LASTEXITCODE
  if ($installCode -eq 0) {
    return
  }

  $outputText = [string]($installOutput | Out-String)
  $outputText = $outputText.Trim()
  $normalized = $outputText.ToLowerInvariant()
  $staleRegistrationDetected = (
    $normalized.Contains("found an existing package already installed") -and
    (
      $normalized.Contains("no available upgrade found") -or
      $normalized.Contains("no newer package versions are available")
    )
  )

  if ($staleRegistrationDetected) {
    Write-Warn "$label appears registered in winget but is not currently usable. Attempting uninstall and reinstall."
    & $winget.Source uninstall --id $packageId --exact --source winget --disable-interactivity --silent 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    $retryOutput = & $winget.Source @installArgs 2>&1
    $retryCode = $LASTEXITCODE
    if ($retryCode -eq 0) {
      return
    }
    $outputText = [string]($retryOutput | Out-String)
    $outputText = $outputText.Trim()
  }

  Fail ("winget install failed for {0}`n{1}" -f $packageId, $outputText)
}

function Test-PythonCommand([string[]]$commandParts) {
  if ($commandParts.Count -eq 0) {
    return $false
  }
  try {
    if ($commandParts.Count -eq 1) {
      & $commandParts[0] -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    } else {
      & $commandParts[0] @($commandParts[1..($commandParts.Count - 1)]) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    }
    return ($LASTEXITCODE -eq 0)
  }
  catch {
    return $false
  }
}

function Add-ExistingPathEntries([string[]]$entries) {
  foreach ($entry in $entries) {
    if ([string]::IsNullOrWhiteSpace($entry)) {
      continue
    }
    if (Test-Path $entry) {
      Ensure-PathEntry $entry
    }
  }
}

function Resolve-PortablePythonRoot() {
  if (-not [string]::IsNullOrWhiteSpace($script:portablePythonRoot)) {
    return $script:portablePythonRoot
  }

  $candidates = @()
  if (-not [string]::IsNullOrWhiteSpace($env:MAESTRO_WINDOWS_PYTHON_HOME)) {
    $candidates += [string]$env:MAESTRO_WINDOWS_PYTHON_HOME
  }
  if (-not [string]::IsNullOrWhiteSpace($env:PUBLIC)) {
    $candidates += (Join-Path $env:PUBLIC "maestro-python")
  }
  if (-not [string]::IsNullOrWhiteSpace($env:ProgramData)) {
    $candidates += (Join-Path $env:ProgramData "maestro-python")
  }
  $candidates += "C:\maestro-python"

  foreach ($candidate in $candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) {
      continue
    }
    try {
      Ensure-Directory $candidate
      $probe = Join-Path $candidate ".write-test"
      Set-Content -Path $probe -Value "ok" -Force
      Remove-Item $probe -Force -ErrorAction SilentlyContinue
      $script:portablePythonRoot = $candidate
      return $script:portablePythonRoot
    }
    catch {
    }
  }

  Fail "Unable to find a writable directory for the Windows Python bootstrap."
}

function Refresh-InstalledToolPaths() {
  $portableRoot = Resolve-PortablePythonRoot
  Add-ExistingPathEntries @(
    (Join-Path $HOME "AppData\Local\Programs\Python\Launcher"),
    (Join-Path $HOME "AppData\Local\Programs\Python\Python313"),
    (Join-Path $HOME "AppData\Local\Programs\Python\Python312"),
    (Join-Path $HOME "AppData\Local\Programs\Python\Python311"),
    (Join-Path $portableRoot "python\tools"),
    (Join-Path $portableRoot "python\scripts"),
    "C:\Python313",
    "C:\Python312",
    "C:\Python311",
    "C:\Program Files\Python313",
    "C:\Program Files\Python312",
    "C:\Program Files\Python311",
    "C:\Program Files\nodejs",
    "C:\Program Files\Tailscale"
  )
}

function Resolve-PythonHostCommand() {
  Refresh-InstalledToolPaths
  $portableRoot = Resolve-PortablePythonRoot

  $candidates = @(
    @((Join-Path $portableRoot "python\tools\python.exe")),
    @("py", "-3.13"),
    @("py", "-3.12"),
    @("py", "-3.11"),
    @("python"),
    @((Join-Path $HOME "AppData\Local\Programs\Python\Launcher\py.exe"), "-3.13"),
    @((Join-Path $HOME "AppData\Local\Programs\Python\Launcher\py.exe"), "-3.12"),
    @((Join-Path $HOME "AppData\Local\Programs\Python\Launcher\py.exe"), "-3.11"),
    @((Join-Path $HOME "AppData\Local\Programs\Python\Python313\python.exe")),
    @((Join-Path $HOME "AppData\Local\Programs\Python\Python312\python.exe")),
    @((Join-Path $HOME "AppData\Local\Programs\Python\Python311\python.exe")),
    @("C:\Python313\python.exe"),
    @("C:\Python312\python.exe"),
    @("C:\Python311\python.exe"),
    @("C:\Program Files\Python313\python.exe"),
    @("C:\Program Files\Python312\python.exe"),
    @("C:\Program Files\Python311\python.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-PythonCommand $candidate) {
      $script:pythonHostCommand = $candidate
      return $true
    }
  }
  return $false
}

function Remove-StalePythonRegistrations() {
  $entries = Get-ItemProperty `
    HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*, `
    HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*, `
    HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\* `
    -ErrorAction SilentlyContinue |
    Where-Object {
      $name = [string]$_.DisplayName
      $name -like "Python 3.12*" -or $name -eq "Python Launcher"
    }

  foreach ($entry in $entries) {
    $raw = @($entry.QuietUninstallString, $entry.UninstallString) | Where-Object { $_ } | Select-Object -First 1
    $guid = $null
    if ([string]$raw -match "\{[A-F0-9-]+\}") {
      $guid = $matches[0]
    }
    try {
      if ($guid) {
        Start-Process msiexec.exe -ArgumentList @("/x", $guid, "/qn", "/norestart") -Wait -NoNewWindow
      } elseif ($raw) {
        $command = [string]$raw
        if ($command -notmatch "(?i)/quiet") {
          $command = "$command /quiet"
        }
        if ($command -notmatch "(?i)/uninstall") {
          $command = "$command /uninstall"
        }
        Start-Process cmd.exe -ArgumentList @("/c", $command) -Wait -NoNewWindow
      }
    }
    catch {
      Write-Warn ("Stale Python uninstall attempt failed for " + [string]$entry.DisplayName)
    }
  }

  foreach ($path in @(
    (Join-Path $HOME "AppData\Local\Programs\Python"),
    (Join-Path (Resolve-PortablePythonRoot) "python"),
    "C:\Python312",
    "C:\Program Files\Python312"
  )) {
    if (Test-Path $path) {
      try {
        Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue
      }
      catch {
      }
    }
  }
}

function Invoke-NugetPythonInstall([string]$label) {
  $version = if ($env:MAESTRO_WINDOWS_PYTHON_VERSION) { [string]$env:MAESTRO_WINDOWS_PYTHON_VERSION } else { "3.12.10" }
  $root = Resolve-PortablePythonRoot
  $nuget = Join-Path $root "nuget.exe"
  $packageDir = Join-Path $root "python"

  if (Test-Path $packageDir) {
    Remove-Item -Recurse -Force $packageDir -ErrorAction SilentlyContinue
  }

  if (-not (Test-Path $nuget)) {
    Write-Log ("Downloading NuGet CLI for " + $label + ".")
    Invoke-WebRequest -UseBasicParsing -Uri "https://aka.ms/nugetclidl" -OutFile $nuget
  }

  Write-Log ("Installing " + $label + " via the official NuGet package.")
  & $nuget install python -Version $version -ExcludeVersion -OutputDirectory $root -DirectDownload -NonInteractive
  if ($LASTEXITCODE -ne 0) {
    Fail ("NuGet Python install failed for version " + $version)
  }
}

function Invoke-DirectPythonInstall([string]$label) {
  $version = if ($env:MAESTRO_WINDOWS_PYTHON_VERSION) { [string]$env:MAESTRO_WINDOWS_PYTHON_VERSION } else { "3.12.10" }
  $url = if ($env:MAESTRO_WINDOWS_PYTHON_URL) {
    [string]$env:MAESTRO_WINDOWS_PYTHON_URL
  } else {
    "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
  }

  $tmpInstaller = Join-Path ([System.IO.Path]::GetTempPath()) ("maestro-python-" + $version + ".exe")
  Write-Log ("Downloading " + $label + " installer from python.org.")
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tmpInstaller
  try {
    $args = @(
      "/quiet",
      "InstallAllUsers=0",
      "PrependPath=1",
      "Include_launcher=1",
      "Include_pip=1",
      "Include_lib=1",
      "Include_exe=1",
      "Include_dev=1",
      "Include_tcltk=1",
      "Include_tools=1",
      "Include_test=0",
      "SimpleInstall=0"
    )
    Write-Log ("Installing " + $label + " via direct installer.")
    $process = Start-Process -FilePath $tmpInstaller -ArgumentList $args -Wait -NoNewWindow -PassThru
    if ($process.ExitCode -ne 0) {
      Fail ("Direct Python installer failed with exit code " + $process.ExitCode)
    }
  }
  finally {
    Remove-Item $tmpInstaller -Force -ErrorAction SilentlyContinue
  }
}

function Ensure-Python() {
  $script:pythonHostCommand = @()
  [void](Resolve-PythonHostCommand)
  if ($script:pythonHostCommand.Count -eq 0) {
    Write-Warn "Python 3.11+ is required."
    if (-not (Prompt-YesNo "Install Python now?" $true)) {
      Fail "Python 3.11+ is required."
    }
    try {
      Invoke-NugetPythonInstall "Python 3.12"
    }
    catch {
      Write-Warn "NuGet Python install failed. Trying direct python.org installer."
      try {
        Invoke-DirectPythonInstall "Python 3.12"
      }
      catch {
        Write-Warn "Direct Python installer failed. Trying winget fallback."
        try {
          Invoke-WingetInstall "Python.Python.3.12" "Python 3.12"
        }
        catch {
          Write-Warn "Python bootstrap fallback failed. Attempting stale-registration cleanup and NuGet reinstall."
          Remove-StalePythonRegistrations
          Invoke-NugetPythonInstall "Python 3.12"
        }
      }
    }
    Start-Sleep -Seconds 2
    if (-not (Resolve-PythonHostCommand)) {
      Write-Warn "Python bootstrap did not produce a usable launcher. Cleaning up stale installs and retrying with NuGet."
      Remove-StalePythonRegistrations
      Invoke-NugetPythonInstall "Python 3.12"
      Start-Sleep -Seconds 2
      if (-not (Resolve-PythonHostCommand)) {
        Fail "Python 3.12 install did not produce a usable launcher."
      }
    }
  }
  if ($script:pythonHostCommand.Count -eq 1) {
    $script:pythonExe = (& $script:pythonHostCommand[0] -c "import sys; print(sys.executable)") | Select-Object -First 1
  } else {
    $script:pythonExe = (& $script:pythonHostCommand[0] @($script:pythonHostCommand[1..($script:pythonHostCommand.Count - 1)]) -c "import sys; print(sys.executable)") | Select-Object -First 1
  }
  Write-Log ("Python: " + (& $script:pythonExe --version 2>&1))
}

function Ensure-Node() {
  Refresh-InstalledToolPaths
  $node = Get-Command node.exe -ErrorAction SilentlyContinue
  $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if ($node -and $npm) {
    Write-Log ("Node: " + (& $node.Source --version))
    Write-Log ("npm: " + (& $npm.Source --version))
    return
  }
  Write-Warn "Node.js and npm are required."
  if (-not (Prompt-YesNo "Install Node.js LTS now?" $true)) {
    Fail "Node.js and npm are required."
  }
  Invoke-WingetInstall "OpenJS.NodeJS.LTS" "Node.js LTS"
  Refresh-InstalledToolPaths
  $node = Get-Command node.exe -ErrorAction SilentlyContinue
  $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $node -or -not $npm) {
    Fail "Node.js install did not produce node.exe/npm.cmd."
  }
  Write-Log ("Node: " + (& $node.Source --version))
  Write-Log ("npm: " + (& $npm.Source --version))
}

function Ensure-OpenClaw() {
  $openclaw = Get-Command openclaw.cmd -ErrorAction SilentlyContinue
  if ($openclaw) {
    Write-Log "OpenClaw: available"
    return
  }
  Write-Warn "OpenClaw CLI is required."
  if (-not (Prompt-YesNo "Install OpenClaw now (npm install -g openclaw)?" $true)) {
    Fail "OpenClaw CLI is required."
  }
  $npm = Get-Command npm.cmd -ErrorAction Stop
  & $npm.Source install -g openclaw --no-audit --no-fund
  if ($LASTEXITCODE -ne 0) {
    Fail "OpenClaw install failed."
  }
  $globalNpmBin = Join-Path $HOME "AppData\Roaming\npm"
  Ensure-PathEntry $globalNpmBin
  $openclaw = Get-Command openclaw.cmd -ErrorAction SilentlyContinue
  if (-not $openclaw) {
    Fail "OpenClaw CLI not found on PATH after install."
  }
  Write-Log "OpenClaw: available"
}

function Get-TailscaleIPv4() {
  $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
  if (-not $tailscale) {
    return ""
  }
  try {
    $lines = & $tailscale.Source ip -4 2>$null
  }
  catch {
    return ""
  }
  if (-not $lines) {
    return ""
  }
  foreach ($line in $lines) {
    $clean = [string]$line
    $clean = $clean.Trim()
    if ($clean) {
      return $clean
    }
  }
  return ""
}

function Ensure-TailscaleIfRequired() {
  Refresh-InstalledToolPaths
  if (-not $script:requireTailscale) {
    return
  }
  $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
  if (-not $tailscale) {
    Write-Warn "Tailscale is required in this deploy mode."
    if (-not (Prompt-YesNo "Install Tailscale now?" $true)) {
      Fail "Tailscale is required when MAESTRO_FLEET_REQUIRE_TAILSCALE=1."
    }
    Invoke-WingetInstall "Tailscale.Tailscale" "Tailscale"
    Refresh-InstalledToolPaths
    $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if (-not $tailscale) {
      Fail "Tailscale install failed."
    }
  }
  $ip = Get-TailscaleIPv4
  if ($ip) {
    Write-Log "Tailscale IPv4: $ip"
    return
  }
  if ($script:autoApprove) {
    Fail "Tailscale is installed but not connected. Complete Tailscale sign-in and rerun, or use MAESTRO_FLEET_REQUIRE_TAILSCALE=0."
  }
  Write-Warn "Tailscale is installed but not connected."
  Fail "Complete Tailscale sign-in and rerun, or use MAESTRO_FLEET_REQUIRE_TAILSCALE=0."
}

function Ensure-VirtualEnv() {
  Ensure-Directory $installRoot
  Ensure-Directory $fleetHome
  if (-not (Test-Path $venvDir)) {
    Write-Log "Creating virtualenv: $venvDir"
    if ($script:pythonHostCommand.Count -eq 1) {
      & $script:pythonHostCommand[0] -m venv $venvDir
    } else {
      & $script:pythonHostCommand[0] @($script:pythonHostCommand[1..($script:pythonHostCommand.Count - 1)]) -m venv $venvDir
    }
    if ($LASTEXITCODE -ne 0) {
      Fail "Failed to create virtualenv at $venvDir"
    }
  }
  $venvPython = Join-Path $venvDir "Scripts\python.exe"
  if (-not (Test-Path $venvPython)) {
    Fail "Virtualenv python missing at $venvPython"
  }
  & $venvPython -m pip install --upgrade pip setuptools wheel
  if ($LASTEXITCODE -ne 0) {
    Fail "Failed to bootstrap pip/setuptools/wheel in the Fleet virtualenv."
  }
}

function Install-FleetPackages() {
  if ([string]::IsNullOrWhiteSpace($packageSpec)) {
    Fail "MAESTRO_FLEET_PACKAGE_SPEC is empty. Set it to wheel URL(s)."
  }
  $pipArgs = @()
  $normalized = [string]$packageSpec
  $tokens = @()
  if ($normalized.Contains(";") -or $normalized.Contains("`n") -or $normalized.Contains("`r")) {
    $tokens = $normalized -split "[;`r`n]+"
  } else {
    $normalized = $normalized.Replace(",", " ")
    $tokens = $normalized -split "\s+"
  }
  foreach ($token in $tokens) {
    if (-not [string]::IsNullOrWhiteSpace($token)) {
      $pipArgs += $token.Trim()
    }
  }
  if ($pipArgs.Count -eq 0) {
    Fail "No wheel arguments parsed from MAESTRO_FLEET_PACKAGE_SPEC."
  }
  $venvPython = Join-Path $venvDir "Scripts\python.exe"
  Write-Log ("Installing Fleet package spec (" + $pipArgs.Count + " pip arg(s))")
  & $venvPython -m pip install @pipArgs
  if ($LASTEXITCODE -ne 0) {
    Fail "Fleet package install failed."
  }
}

function Validate-Install() {
  $maestroExe = Join-Path $venvDir "Scripts\maestro-fleet.exe"
  if (-not (Test-Path $maestroExe)) {
    Fail "maestro-fleet.exe missing at $maestroExe"
  }
  & $maestroExe --help *> $null
  if ($LASTEXITCODE -ne 0) {
    Fail "maestro-fleet CLI validation failed."
  }
  Write-Log "maestro-fleet CLI installed."
}

function Run-DeployIfEnabled([string[]]$scriptArgs) {
  $maestroExe = Join-Path $venvDir "Scripts\maestro-fleet.exe"
  if (-not $script:autoDeploy) {
    Write-Log "Install complete. Run manually: $maestroExe deploy"
    return
  }
  $deployArgs = @("deploy")
  if ($script:requireTailscale) {
    $deployArgs += "--require-tailscale"
  }
  if ((-not [Environment]::UserInteractive) -and $scriptArgs.Count -eq 0) {
    Write-Warn "Non-interactive install detected with no deploy flags; skipping auto deploy."
    Write-Log "Install complete. Run manually: $maestroExe deploy"
    return
  }
  if (-not [Environment]::UserInteractive) {
    $deployArgs += "--non-interactive"
  }
  $deployArgs += $scriptArgs
  Write-Log "Starting Fleet deploy workflow."
  & $maestroExe @deployArgs
  if ($LASTEXITCODE -ne 0) {
    Fail "Fleet deploy failed."
  }
}

$env:MAESTRO_OPENCLAW_PROFILE = $openclawProfile
$script:autoApprove = Resolve-Flag $autoApproveRaw $false $true
$script:requireTailscale = Resolve-Flag $requireTailscaleRaw $false $false
$script:autoDeploy = Resolve-Flag $autoDeployRaw $true $false

Ensure-Python
Ensure-Node
Ensure-OpenClaw
Ensure-TailscaleIfRequired
Ensure-VirtualEnv
Install-FleetPackages
Validate-Install

if ($script:autoDeploy -and (-not $script:autoApprove)) {
  if (Prompt-YesNo "Run maestro-fleet deploy now?" $true) {
    Run-DeployIfEnabled $args
  } else {
    $maestroExe = Join-Path $venvDir "Scripts\maestro-fleet.exe"
    Write-Log "Skipping deploy. Run manually: $maestroExe deploy"
  }
  exit 0
}

Run-DeployIfEnabled $args
