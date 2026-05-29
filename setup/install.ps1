# Lamp one-command installer (Windows 10/11).
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/thebreadcat/lamp-ai/main/setup/install.ps1 | iex"
# Or double-click setup/install.bat
#
# Optional env vars (set before running):
#   $env:LAMP_INSTALL_DIR = "$env:USERPROFILE\lamp"
#   $env:LAMP_SKIP_OLLAMA = "1"
#   $env:LAMP_SKIP_PULL = "1"
#   $env:LAMP_START = "0"
$ErrorActionPreference = "Stop"

$LampGithub = if ($env:LAMP_GITHUB) { $env:LAMP_GITHUB } else { "thebreadcat/lamp-ai" }
$LampBranch = if ($env:LAMP_BRANCH) { $env:LAMP_BRANCH } else { "main" }
$WorkshopGithub = if ($env:WORKSHOP_GITHUB) { $env:WORKSHOP_GITHUB } else { "thebreadcat/workshop" }
$TortoiseGithub = if ($env:TORTOISE_GITHUB) { $env:TORTOISE_GITHUB } else { "thebreadcat/tortoise" }
$InstallDir = if ($env:LAMP_INSTALL_DIR) { $env:LAMP_INSTALL_DIR } else { Join-Path $env:USERPROFILE "lamp" }
$Port = if ($env:LAMP_PORT) { $env:LAMP_PORT } else { "7700" }
$HostBind = if ($env:LAMP_HOST) { $env:LAMP_HOST } else { "0.0.0.0" }

function Log($msg) { Write-Host "  [lamp] $msg" }
function Warn($msg) { Write-Host "  [lamp] warning: $msg" -ForegroundColor Yellow }

function Get-RamGb {
    $cs = Get-CimInstance Win32_ComputerSystem
    [int][math]::Round($cs.TotalPhysicalMemory / 1GB)
}

function Pick-Model([int]$Gb) {
    if ($Gb -ge 16) { return "qwen2.5:7b" }
    if ($Gb -ge 8) { return "qwen2.5:3b" }
    if ($Gb -ge 4) { return "qwen2.5:3b" }
    return "qwen2.5:1.5b"
}

function Ensure-Python {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
    if ($py) {
        $ver = & $py.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        $parts = $ver.Split(".")
        if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
            Log "Python $ver"
            return $py.Source
        }
    }
    Log "Installing Python 3.12 (winget)…"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements | Out-Null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
        $py = Get-Command python -ErrorAction SilentlyContinue
        if ($py) { return $py.Source }
    }
    throw "Install Python 3.10+ from https://www.python.org/downloads/ then re-run this script."
}

function Download-ZipRepo([string]$Repo, [string]$Dest) {
    $tmp = Join-Path $env:TEMP ("lamp-dl-" + [guid]::NewGuid().ToString("n"))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $zip = Join-Path $tmp "repo.zip"
    $url = "https://github.com/$Repo/archive/refs/heads/$LampBranch.zip"
    Log "Downloading $Repo…"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $root = Get-ChildItem $tmp -Directory | Where-Object { $_.Name -ne (Split-Path $zip -Leaf) } | Select-Object -First 1
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    New-Item -ItemType Directory -Path (Split-Path $Dest -Parent) -Force | Out-Null
    Move-Item $root.FullName $Dest
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

function Ensure-LampTree {
    if (Test-Path (Join-Path $InstallDir "lamp.py")) {
        Log "Lamp already at $InstallDir"
        return
    }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        Log "Cloning Lamp (git)…"
        & git clone --depth 1 --branch $LampBranch "https://github.com/$LampGithub.git" $InstallDir 2>$null
        if (-not $?) { & git clone --depth 1 "https://github.com/$LampGithub.git" $InstallDir }
        Push-Location $InstallDir
        & git submodule update --init --recursive 2>$null
        Pop-Location
    } else {
        Log "Git not found — downloading zip…"
        Download-ZipRepo $LampGithub $InstallDir
    }
    if (-not (Test-Path (Join-Path $InstallDir "lamp.py"))) {
        throw "Install failed — lamp.py missing"
    }
}

function Ensure-Workshop {
    $ws = Join-Path $InstallDir "vendor\workshop\workshop.py"
    if (Test-Path $ws) { return }
    Log "Installing Workshop…"
    if (Test-Path (Join-Path $InstallDir ".git")) {
        Push-Location $InstallDir
        & git submodule update --init --recursive 2>$null
        Pop-Location
        if (Test-Path $ws) { return }
    }
    Download-ZipRepo $WorkshopGithub (Join-Path $InstallDir "vendor\workshop")
}

function Ensure-Tortoise {
    $t = Join-Path $InstallDir "vendor\workshop\vendor\tortoise\tortoise.py"
    if (Test-Path $t) { return }
    Log "Installing Tortoise…"
    $dest = Join-Path $InstallDir "vendor\workshop\vendor\tortoise"
    New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        & git clone --depth 1 "https://github.com/$TortoiseGithub.git" $dest 2>$null
        if (Test-Path $t) { return }
    }
    Download-ZipRepo $TortoiseGithub $dest
    if (-not (Test-Path $t)) { throw "Tortoise install failed" }
}

function Ensure-Ollama {
    if ($env:LAMP_SKIP_OLLAMA -eq "1") {
        Warn "Skipping Ollama (LAMP_SKIP_OLLAMA=1)"
        return
    }
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) {
        Log "Installing Ollama (winget)…"
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements | Out-Null
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
        } else {
            Warn "winget not found — install Ollama from https://ollama.com/download/windows"
        }
    } else {
        Log "Ollama already installed"
    }
    Start-Ollama
}

function Test-OllamaUp {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch { return $false }
}

function Start-Ollama {
    if (Test-OllamaUp) { return }
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollama) {
        Log "Starting Ollama…"
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 4
    }
}

function Wait-Ollama {
    for ($i = 0; $i -lt 45; $i++) {
        if (Test-OllamaUp) { return $true }
        Start-Sleep -Seconds 1
    }
    Warn "Ollama API not responding yet"
    return $false
}

function Pull-Model([string]$Model) {
    if ($env:LAMP_SKIP_OLLAMA -eq "1" -or $env:LAMP_SKIP_PULL -eq "1") { return }
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollama) { Warn "ollama not in PATH"; return }
    [void](Wait-Ollama)
    Log "Pulling model $Model (may take several minutes)…"
    & ollama pull $Model
    if (-not $?) { Warn "Model pull failed — set model later in Lamp" }
}

function Write-WorkshopConfig([string]$Model) {
    $cfgDir = Join-Path $env:USERPROFILE ".workshop"
    $cfgPath = Join-Path $cfgDir "config.json"
    if (Test-Path $cfgPath) {
        Log "Config exists — leaving $cfgPath"
        return
    }
    New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null
    $apps = Join-Path $env:USERPROFILE "workshop-apps"
    New-Item -ItemType Directory -Path $apps -Force | Out-Null
    $cfg = @{
        endpoint = "http://localhost:11434/v1"
        model    = $Model
        api_key  = $null
        apps_dir = $apps
        users    = @()
    } | ConvertTo-Json -Depth 5
    Set-Content -Path $cfgPath -Value $cfg -Encoding UTF8
    Log "Wrote $cfgPath (model: $Model)"
}

function Get-LanIp {
    try {
        $udp = New-Object System.Net.Sockets.UdpClient
        $udp.Connect("8.8.8.8", 80)
        $ip = ($udp.Client.LocalEndPoint).Address.ToString()
        $udp.Close()
        return $ip
    } catch { return $null }
}

function Show-AccessUrls([string]$PythonExe) {
    $scheme = if ($env:LAMP_NO_TLS -eq "1") { "http" } else { "https" }
    Write-Host "  On this computer: ${scheme}://localhost:${Port}"
    $lan = Get-LanIp
    if ($lan -and $HostBind -ne "127.0.0.1" -and $HostBind -ne "localhost") {
        $phoneUrl = "${scheme}://${lan}:${Port}"
        Write-Host "  Phones/tablets (same Wi-Fi): $phoneUrl"
        if ($scheme -eq "https") {
            Write-Host "  On your phone: scan the QR, accept the security warning once, then use the mic."
        }
        $qrPy = Join-Path $InstallDir "lamp_qr.py"
        if ((Test-Path $qrPy) -and $PythonExe) {
            Write-Host ""
            Write-Host "  Scan on your phone:"
            Push-Location $InstallDir
            & $PythonExe -c "import lamp_qr; lamp_qr.print_terminal_qr('$phoneUrl')" 2>$null
            if (-not $?) { Write-Host "    (QR also on the login page in your browser)" }
            Pop-Location
            Write-Host ""
        }
    }
}

function Ensure-Tls([string]$PythonExe) {
    if ($env:LAMP_NO_TLS -eq "1") { return }
    Log "Setting up HTTPS (for microphone on phones)…"
    Push-Location $InstallDir
    & $PythonExe lamp_tls.py
    if ($LASTEXITCODE -ne 0) { throw "HTTPS setup failed — install OpenSSL (Git for Windows includes it) and re-run" }
    Pop-Location
}

function Start-Lamp([string]$Python) {
    if ($env:LAMP_START -eq "0") {
        Log "Setup complete. Start with: cd $InstallDir; python lamp.py --host $HostBind"
        Show-AccessUrls $Python
        return
    }
    Write-Host ""
    Write-Host "  ═══════════════════════════════════════════════════════"
    Write-Host "  Lamp is starting."
    Show-AccessUrls $Python
    Write-Host "  Create your admin name + PIN on first visit."
    Write-Host "  Press Ctrl+C to stop the server."
    Write-Host "  ═══════════════════════════════════════════════════════"
    Write-Host ""
    Set-Location $InstallDir
    $tlsFlag = @()
    if ($env:LAMP_NO_TLS -eq "1") { $tlsFlag = @("--no-tls") }
    & $Python lamp.py --host $HostBind --port $Port @tlsFlag
}

Write-Host ""
Write-Host "  Lamp installer (Windows)"
Write-Host "  ────────────────────────"

$python = Ensure-Python
Ensure-LampTree
Ensure-Workshop
Ensure-Tortoise
$ramGb = Get-RamGb
$model = Pick-Model $ramGb
Log "Detected ~${ramGb} GB RAM → default model: $model"
Ensure-Ollama
Pull-Model $model
Write-WorkshopConfig $model
Ensure-Tls $python
Start-Lamp $python
