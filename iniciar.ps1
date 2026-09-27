# Levanta OpenCaption Live con Docker Compose.
# Uso: powershell -ExecutionPolicy Bypass -File .\iniciar.ps1 [-Motor local|gemini|mock] [-ConOllama]
param(
    [ValidateSet("local", "gemini", "mock")]
    [string]$Motor,
    [switch]$ConOllama
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "No encontré Docker. Instalá Docker Desktop."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker no está corriendo: abrí Docker Desktop y esperá 'Engine running'."
}

$envPath = Join-Path $PSScriptRoot ".env"
$utf8 = New-Object System.Text.UTF8Encoding $false  # sin BOM

function Get-EnvValue([string]$Key) {
    $line = Get-Content -Encoding UTF8 $envPath | Where-Object { $_ -match "^$Key=" } | Select-Object -Last 1
    if ($line) { return $line.Substring($Key.Length + 1) }
    return ""
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $lines = [System.Collections.Generic.List[string]](Get-Content -Encoding UTF8 $envPath)
    $index = $lines.FindIndex([Predicate[string]]{ param($l) $l -match "^$Key=" })
    if ($index -ge 0) { $lines[$index] = "$Key=$Value" } else { $lines.Add("$Key=$Value") }
    [System.IO.File]::WriteAllLines($envPath, $lines, $utf8)
}

if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $envPath
    Write-Host "Creé .env a partir de .env.example."
}
if (-not (Get-EnvValue "INGEST_TOKEN")) {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $token = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
    Set-EnvValue "INGEST_TOKEN" $token
    Write-Host "Generé un INGEST_TOKEN aleatorio en .env."
}

$motorElegido = $Motor
if (-not $Motor) { $Motor = Get-EnvValue "CAPTION_ENGINE" }
if (-not $Motor) { $Motor = "local" }
if ($Motor -eq "gemini" -and -not (Get-EnvValue "GEMINI_API_KEY")) {
    Write-Error "El motor gemini necesita GEMINI_API_KEY en .env."
}
if ($motorElegido) { Set-EnvValue "CAPTION_ENGINE" $Motor }

$composeArgs = @("compose", "-f", "docker-compose.yml")
if ($ConOllama) {
    if ($Motor -ne "local") { Write-Warning "Ollama solo se usa con el motor local (el actual es $Motor)." }
    $composeArgs += @("-f", "docker-compose.ollama.yml")
}

Write-Host "Levantando OpenCaption Live (motor: $Motor)..."
& docker @composeArgs up -d --build
if ($LASTEXITCODE -ne 0) { Write-Error "docker compose falló." }

$port = Get-EnvValue "PORT"
if (-not $port) { $port = "8000" }
$url = "http://localhost:$port"
Write-Host -NoNewline "Esperando a que responda $url "
for ($i = 0; $i -lt 90; $i++) {
    try {
        # 127.0.0.1 y no localhost: localhost puede resolver primero a IPv6 (::1)
        # y Docker publica el puerto solo en IPv4.
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$port/health" | Out-Null
        Write-Host " listo."
        break
    } catch {
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
    }
}

$compose = "docker " + ($composeArgs -join " ")
Write-Host ""
Write-Host "  Vista de audiencia:  $url"
Write-Host "  Emitir audio:        $url/admin.html"
Write-Host "  Overlay para OBS:    $url/overlay.html?session=<sesion>&lang=es"
Write-Host "  Token de emision:    $(Get-EnvValue 'INGEST_TOKEN')"
Write-Host ""
Write-Host "  Logs:     $compose logs -f"
Write-Host "  Detener:  $compose down"
if ($Motor -eq "local") {
    Write-Host "  La primera vez el motor local descarga sus modelos (~550 MB): mira los logs."
}
