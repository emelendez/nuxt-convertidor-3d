<#
.SYNOPSIS
  Lanzador portable del Convertidor 3D (Nuxt 4 + Nitro).

.DESCRIPTION
  Hace la carpeta auto-contenida y copiable a cualquier ruta/disco:
   1. Si faltan node_modules, los instala (npm ci / npm install).
   2. Si falta el build (.output), compila la app (npm run build).
   3. Arranca el servidor Node y abre el navegador local.
  Por defecto la app queda VISIBLE EN LA RED (0.0.0.0) protegida por PIN:
  si no se pasa -Pin ni hay NUXT_CONVERTIDOR3D_PIN, se genera uno aleatorio
  y se imprime junto a las URLs para compartir. Sin PIN configurado el
  servidor rechaza a los clientes remotos (fail-closed en el middleware).

  -SoloLocal  vuelve al comportamiento clasico: escucha solo en 127.0.0.1.
  -BindHost   IP concreta donde escuchar (por defecto 0.0.0.0).
  -Pin        PIN de acceso remoto (si no, se autogenera).

  FFmpeg embebido (tools\ffmpeg) y modelos (models\) viajan con la carpeta.
  El worker Python (.venv) es necesario solo para la conversion real; si falta,
  la app funciona igual y avisa (instalalo con scripts\setup.ps1 -AI  o  -DML).

  NOTA: fichero deliberadamente en ASCII (sin tildes) - PowerShell 5.1 lee los
  .ps1 sin BOM como ANSI y los caracteres multi-byte rompen el parser.
#>
param(
  [switch]$SoloLocal,
  [string]$BindHost = '',   # no llamarlo -Host: colisiona con la variable $Host
  [string]$Pin = ''
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = 8765
$Url = "http://127.0.0.1:$Port"

# cache/temporales dentro de la carpeta (no ensucia C:)
$env:PIP_CACHE_DIR = "$Root\.cache\pip"
$env:TMP = "$Root\.cache\tmp"; $env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:TMP | Out-Null

# ---- donde escucha el servidor -------------------------------------------
if ($SoloLocal) {
  $Listen = '127.0.0.1'
} else {
  if ($BindHost) { $Listen = $BindHost } else { $Listen = '0.0.0.0' }
  # PIN de acceso remoto: parametro > variable de entorno > autogenerado
  if (-not $Pin) { $Pin = $env:NUXT_CONVERTIDOR3D_PIN }
  if (-not $Pin) { $Pin = $env:CONVERTIDOR3D_PIN }
  if (-not $Pin) {
    $alphabet = '23456789abcdefghjkmnpqrstuvwxyz'  # sin caracteres ambiguos
    $Pin = -join (1..8 | ForEach-Object { $alphabet[(Get-Random -Maximum $alphabet.Length)] })
  }
  $env:NUXT_CONVERTIDOR3D_PIN = $Pin
}
$env:NITRO_HOST = $Listen; $env:HOST = $Listen
$env:NITRO_PORT = "$Port"; $env:PORT = "$Port"

# FFmpeg embebido al frente del PATH (el plugin de Nitro tambien lo hace)
$ffbin = "$Root\tools\ffmpeg\bin"
if (Test-Path $ffbin) { $env:PATH = "$ffbin;$env:PATH" }

# 1) dependencias Node
if (-not (Test-Path "$Root\node_modules")) {
  $node = Get-Command node -ErrorAction SilentlyContinue
  if (-not $node) { throw "Node.js no encontrado. Instala Node 20+ desde nodejs.org" }
  Write-Host "Instalando dependencias Node (primer arranque)..." -ForegroundColor Yellow
  if (Test-Path "$Root\package-lock.json") { & npm ci } else { & npm install }
  if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de dependencias Node" }
}

# 2) build
if (-not (Test-Path "$Root\.output\server\index.mjs")) {
  Write-Host "Compilando la app (primer arranque)..." -ForegroundColor Yellow
  & npm run build
  if ($LASTEXITCODE -ne 0) { throw "Fallo el build de Nuxt" }
}

# 3) avisos no bloqueantes (worker / modelos)
if (-not (Test-Path "$Root\.venv\Scripts\python.exe")) {
  Write-Host "Falta el worker Python (.venv). Instalandolo automaticamente segun el hardware..." -ForegroundColor Yellow
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\setup.ps1" -Auto -Yes -SkipNode
    if ($LASTEXITCODE -ne 0) { throw "setup.ps1 devolvio codigo $LASTEXITCODE" }
    Write-Host "Worker instalado. Continuando..." -ForegroundColor Green
  } catch {
    Write-Host ("AVISO: no se pudo instalar el worker automaticamente: " + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host "       La web arranca igual (previsualizar/planear). Instalalo luego con: scripts\setup.ps1 -Auto" -ForegroundColor Yellow
  }
}
if (-not (Test-Path $ffbin)) {
  Write-Host "Aviso: falta FFmpeg embebido (tools\ffmpeg). Ejecuta scripts\setup.ps1" -ForegroundColor Yellow
}

# 4) modo red: regla de firewall (idempotente) + URLs para compartir
if (-not $SoloLocal) {
  $ruleName = 'Convertidor3D-8765'
  $have = netsh advfirewall firewall show rule name="$ruleName" 2>$null | Select-String $ruleName
  if (-not $have) {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
      # domain,private a proposito: no abre el puerto en redes de perfil "publico"
      netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$Port profile=domain,private | Out-Null
      Write-Host "Regla de firewall creada ($ruleName, perfiles domain/private)." -ForegroundColor Green
    } else {
      Write-Host "AVISO: sin permisos de administrador no se puede abrir el puerto $Port" -ForegroundColor Yellow
      Write-Host "en el firewall. Ejecuta UNA VEZ en una consola elevada:" -ForegroundColor Yellow
      Write-Host "  netsh advfirewall firewall add rule name=`"$ruleName`" dir=in action=allow protocol=TCP localport=$Port profile=domain,private"
    }
  }
  Write-Host ""
  Write-Host "Acceso desde otros dispositivos (comparte URL; el PIN va incluido):" -ForegroundColor Cyan
  Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    ForEach-Object { Write-Host ("  http://{0}:{1}/?pin={2}" -f $_.IPAddress, $Port, $Pin) -ForegroundColor Cyan }
  Write-Host ("  PIN de acceso remoto: {0}   (en esta maquina no hace falta)" -f $Pin) -ForegroundColor Cyan
  Write-Host ""
}

# abrir el navegador cuando el servidor este escuchando (en segundo plano)
Start-Job -ArgumentList $Port, $Url -ScriptBlock {
  param($Port, $Url)
  for ($i = 0; $i -lt 120; $i++) {
    try {
      $c = New-Object Net.Sockets.TcpClient
      $c.Connect('127.0.0.1', $Port); $c.Close()
      Start-Process $Url; return
    } catch { Start-Sleep -Milliseconds 500 }
  }
} | Out-Null

Write-Host "Servidor en $Url  (Ctrl+C para parar)" -ForegroundColor Green
& node "$Root\.output\server\index.mjs"
