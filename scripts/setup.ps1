<#
.SYNOPSIS
  Instalacion del Convertidor 3D (Nuxt 4 + Nitro + worker Python). Windows.

.DESCRIPTION
  Arquitectura hibrida: servidor Node/Nitro (UI + API) + worker Python para la
  IA (invocado por subproceso). Este script prepara AMBOS runtimes.

  Sin parametros: Node (npm ci + build) + FFmpeg embebido + venv base del worker.
                  La app arranca y funciona en modo simulacion.

  Instalacion por MOTOR (addons de worker\engines\<id>\manifest.json):
  -Engine <ids>   lista separada por comas, p.ej. -Engine depth_da2_onnx,stereo_fast_telea
  -ListEngines    tabla de motores disponibles (no instala nada)

  Alias retrocompatibles (mapean a motores):
  -AI      depth_vda + stereo_fast + stereo_fast_telea (PyTorch CUDA)
  -DML     depth_da2_onnx + stereo_fast + stereo_fast_telea (sin NVIDIA)
  -HQ      stereo_sc_svd (StereoCrafter; pesos SVD GATED: exige token HF)
  -All     todos los motores

  -Yes     desatendido: sin prompts interactivos (CI / clon limpio)

.NOTES
  Los pesos de VDA Base/Large y DA2 Base/Large son CC-BY-NC-4.0 y los de
  StereoCrafter/SVD no comerciales: solo uso personal/investigacion.
  FFmpeg y modelos se copian del proyecto hermano ..\convertidor-3d si existe
  (rapido, sin descargar). El proyecto hermano NO se modifica (solo lectura).
  Log completo de cada ejecucion en .cache\setup-*.log; pip freeze de las
  instalaciones buenas en .cache\freeze-*.txt.
  Fichero deliberadamente en ASCII (sin tildes): PowerShell 5.1 lee los .ps1
  sin BOM como ANSI y los caracteres multi-byte rompen el parser.
#>
param(
  [switch]$AI,
  [switch]$DML,
  [switch]$HQ,
  [switch]$All,
  [string]$Engine = '',
  [switch]$Yes,
  [switch]$ListEngines
)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$EnginesDir = Join-Path $Root 'worker\engines'
$ModelsDir = Join-Path $Root 'models'
$Constraints = Join-Path $Root 'worker\constraints.txt'

# ---- manifests de motores ---------------------------------------------------
function Get-EngineManifests {
  $out = @()
  if (-not (Test-Path $EnginesDir)) { return $out }
  foreach ($d in (Get-ChildItem $EnginesDir -Directory | Sort-Object Name)) {
    $mf = Join-Path $d.FullName 'manifest.json'
    if (-not (Test-Path $mf)) { continue }
    try {
      $m = Get-Content $mf -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
      Write-Host ("AVISO: manifest ilegible en " + $d.Name + ": " + $_.Exception.Message) -ForegroundColor Yellow
      continue
    }
    if ($m.id -ne $d.Name) {
      Write-Host ("AVISO: manifest de " + $d.Name + " con id distinto (" + $m.id + "); omitido") -ForegroundColor Yellow
      continue
    }
    $out += [pscustomobject]@{ Id = $m.id; Dir = $d.FullName; Manifest = $m }
  }
  return $out
}

function Test-NvidiaGpu {
  $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  if (-not $smi) { return $false }
  & nvidia-smi -L *> $null
  return ($LASTEXITCODE -eq 0)
}

$AllManifests = Get-EngineManifests

if ($ListEngines) {
  Write-Host "Motores disponibles (worker\engines):" -ForegroundColor Cyan
  foreach ($e in $AllManifests) {
    $m = $e.Manifest
    $req = @($m.requires_compute) -join ','
    if (-not $req) { $req = 'cualquiera' }
    $gated = 'no'
    foreach ($w in @($m.weights)) { if ($w -and $w.gated) { $gated = 'SI' } }
    Write-Host ("  {0,-20} etapa={1,-7} computo={2,-10} gated={3,-3} {4}" -f $e.Id, $m.stage, $req, $gated, $m.label)
  }
  exit 0
}

# ---- seleccion de motores ---------------------------------------------------
$EngineIds = @()
if ($Engine) { $EngineIds += ($Engine -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
if ($All) { $AI = $true; $DML = $true; $HQ = $true }
if ($AI) { $EngineIds += @('depth_vda', 'stereo_fast', 'stereo_fast_telea') }
if ($DML) { $EngineIds += @('depth_da2_onnx', 'stereo_fast', 'stereo_fast_telea') }
if ($HQ) { $EngineIds += @('stereo_sc_svd') }
$EngineIds = @($EngineIds | Select-Object -Unique)

# log de toda la ejecucion
New-Item -ItemType Directory -Force (Join-Path $Root '.cache') | Out-Null
$LogPath = Join-Path $Root ('.cache\setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
try { Start-Transcript -Path $LogPath -ErrorAction Stop | Out-Null } catch {}

$Results = @()
$ExitCode = 0
try {

# cache de pip y temporales dentro de la carpeta (no ensucia C:)
$env:PIP_CACHE_DIR = "$Root\.cache\pip"
$env:TMP = "$Root\.cache\tmp"; $env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:TMP | Out-Null
$Sibling = Join-Path (Split-Path -Parent $Root) 'convertidor-3d'
Write-Host "== Convertidor 3D (Nuxt) - setup ==" -ForegroundColor Cyan

# ---- Node + dependencias + build -------------------------------------------
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Node.js no encontrado. Instala Node 20+ desde nodejs.org" }
Write-Host ("Node " + (& node --version))
if (Test-Path "$Root\package-lock.json") { $npmCmd = 'ci' } else { $npmCmd = 'install' }
Write-Host ("Instalando dependencias Node (npm " + $npmCmd + ")...")
& npm $npmCmd
if ($LASTEXITCODE -ne 0) {
  # EPERM/unlink transitorio tipico: OneDrive sincronizando o un node.exe
  # residual bloqueando un binario nativo de node_modules. Un reintento tras
  # una pausa lo resuelve casi siempre (cazado en instalacion real 2026-07-18).
  Write-Host "npm fallo; reintentando en 10 s (bloqueo transitorio de ficheros?)..." -ForegroundColor Yellow
  Start-Sleep -Seconds 10
  & npm $npmCmd
  if ($LASTEXITCODE -ne 0) {
    throw "Fallo la instalacion de dependencias Node (2 intentos). Si el proyecto esta en OneDrive, pausa la sincronizacion y cierra procesos node.exe."
  }
}
Write-Host "Compilando la app (npm run build)..."
& npm run build
if ($LASTEXITCODE -ne 0) { throw "Fallo el build de Nuxt" }

# ---- FFmpeg embebido (tools\ffmpeg\bin) ------------------------------------
$ffTarget = "$Root\tools\ffmpeg"
if (Test-Path "$ffTarget\bin\ffmpeg.exe") {
  Write-Host "FFmpeg embebido OK"
} else {
  $ffSrc = "$Sibling\tools\ffmpeg"
  if (Test-Path "$ffSrc\bin\ffmpeg.exe") {
    Write-Host "Copiando FFmpeg embebido del proyecto hermano (~700 MB)..."
    New-Item -ItemType Directory -Force $ffTarget | Out-Null
    & robocopy $ffSrc $ffTarget /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Fallo la copia de FFmpeg (robocopy $LASTEXITCODE)" }
    Write-Host "FFmpeg copiado a tools\ffmpeg"
  } elseif (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "FFmpeg encontrado en el PATH (no embebido)."
  } else {
    Write-Host "FFmpeg no encontrado." -ForegroundColor Yellow
    $installFf = $Yes
    if (-not $Yes) {
      $r = Read-Host "Instalar FFmpeg con winget (Gyan.FFmpeg)? [s/N]"
      if ($r -match '^[sS]') { $installFf = $true }
    }
    if ($installFf) {
      winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
      Write-Host "FFmpeg instalado via winget. Reabre la terminal (o relanza run.bat) para refrescar el PATH." -ForegroundColor Yellow
    } else {
      Write-Host "Instalalo manualmente (build FULL, con zscale): https://www.gyan.dev/ffmpeg/builds/"
    }
  }
}

# ---- Python (worker) -------------------------------------------------------
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python no encontrado. Instala Python 3.11-3.14 desde python.org" }
$ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Python $ver"
$pyv = "$Root\.venv\Scripts\python.exe"
if (-not (Test-Path $pyv)) {
  # .venv ausente O roto/parcial (carpeta sin interprete): recrear de cero
  # (cazado en instalacion real 2026-07-18: un .venv sin pip.exe ni python)
  if (Test-Path "$Root\.venv") {
    Write-Host ".venv incompleto: recreando..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "$Root\.venv"
  }
  Write-Host "Creando entorno virtual .venv..."
  python -m venv "$Root\.venv"
  if (-not (Test-Path $pyv)) { throw "No se pudo crear el venv (.venv\Scripts\python.exe ausente)" }
}
# pip via 'python -m pip' SIEMPRE (un venv puede existir sin pip.exe)
& $pyv -m ensurepip --upgrade 2>&1 | Out-Null
& $pyv -m pip install --upgrade pip -q
if ($LASTEXITCODE -ne 0) { throw "pip no funciona en el venv" }
Write-Host "Instalando base del worker..."
& $pyv -m pip install -r "$Root\worker\requirements.txt" -c $Constraints -q
if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion base del worker" }

# ---- Modelos: copiar los del proyecto hermano si existen -------------------
if ((Test-Path "$Sibling\models") -and (-not (Test-Path $ModelsDir))) {
  Write-Host "Copiando modelos del proyecto hermano..."
  & robocopy "$Sibling\models" $ModelsDir /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
  if ($LASTEXITCODE -ge 8) { Write-Host "Aviso: fallo la copia de modelos (robocopy $LASTEXITCODE)" -ForegroundColor Yellow }
}
New-Item -ItemType Directory -Force $ModelsDir | Out-Null

# ---- Motores (addons) ------------------------------------------------------
if ($EngineIds.Count -gt 0) {
  $HasNvidia = Test-NvidiaGpu
  if ($HasNvidia) { Write-Host "GPU NVIDIA detectada: torch con index cu126 donde aplique." }
  else { Write-Host "Sin GPU NVIDIA: torch con index cpu; motores CUDA-only se saltan." }

  # los motores CUDA primero: fijan la variante de torch correcta antes de que
  # otro requirements con torch>=X se resuelva desde el index cpu
  $Ordered = @()
  foreach ($id in $EngineIds) {
    $e = $AllManifests | Where-Object { $_.Id -eq $id }
    if (-not $e) {
      Write-Host ("Motor desconocido: " + $id) -ForegroundColor Yellow
      $Results += [pscustomobject]@{ Id = $id; Estado = 'FALLO'; Detalle = 'manifest no encontrado' }
      $ExitCode = 1
      continue
    }
    $Ordered += $e
  }
  $Ordered = @($Ordered | Sort-Object { if (@($_.Manifest.requires_compute) -contains 'cuda') { 0 } else { 1 } })

  foreach ($e in $Ordered) {
    $m = $e.Manifest
    $needsCuda = (@($m.requires_compute) -contains 'cuda')
    Write-Host ("`n-- Motor " + $e.Id + " (" + $m.label + ") --") -ForegroundColor Cyan

    if ($needsCuda -and -not $HasNvidia) {
      Write-Host "  SALTADO: requiere GPU NVIDIA con CUDA y no se detecta." -ForegroundColor Yellow
      $Results += [pscustomobject]@{ Id = $e.Id; Estado = 'SALTADO'; Detalle = 'requiere CUDA' }
      continue
    }

    $failed = $null

    # 1) dependencias pip propias del motor, acotadas por constraints.txt
    if ($m.requirements) {
      $reqFile = Join-Path $e.Dir $m.requirements
      if ($needsCuda) { $idx = 'https://download.pytorch.org/whl/cu126' }
      else { $idx = 'https://download.pytorch.org/whl/cpu' }
      Write-Host ("  pip install -r " + $m.requirements + " (index extra: " + $idx + ")")
      & $pyv -m pip install -r $reqFile -c $Constraints --extra-index-url $idx
      if ($LASTEXITCODE -ne 0) {
        Write-Host "  reintentando pip tras fallo..." -ForegroundColor Yellow
        & $pyv -m pip install -r $reqFile -c $Constraints --extra-index-url $idx
        if ($LASTEXITCODE -ne 0) { $failed = 'pip fallo' }
      }
    }

    # 2) repos git (a commit pineado si el manifest lo trae)
    if (-not $failed) {
      foreach ($w in @($m.weights)) {
        if (-not $w -or $w.kind -ne 'git') { continue }
        $dst = Join-Path $ModelsDir $w.dest
        if (Test-Path $dst) { Write-Host ("  repo ya presente: " + $w.dest); continue }
        $ok = $false
        foreach ($attempt in 1, 2) {
          try {
            if ($w.commit) {
              git init $dst 2>&1 | Out-Null
              git -C $dst remote add origin $w.url
              git -C $dst fetch --depth 1 origin $w.commit
              git -C $dst checkout $w.commit 2>&1 | Out-Null
              if ($LASTEXITCODE -ne 0) { throw "checkout $($w.commit) fallo" }
            } else {
              git clone --depth 1 $w.url $dst
              if ($LASTEXITCODE -ne 0) { throw "clone fallo" }
            }
            $ok = $true; break
          } catch {
            Write-Host ("  reintento de clone tras fallo: " + $_.Exception.Message) -ForegroundColor Yellow
            if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
          }
        }
        if ($ok) { Write-Host ("  OK repo " + $w.dest + " @ " + $w.commit) }
        else { $failed = ("clone de " + $w.url + " fallo") ; break }
      }
    }

    # 3) pesos HF (gated se comprueba dentro ANTES de descargar nada)
    if (-not $failed) {
      & $pyv (Join-Path $Root 'scripts\engine_install.py') (Join-Path $e.Dir 'manifest.json') $ModelsDir
      if ($LASTEXITCODE -eq 2) { $failed = 'falta token HF (pesos gated)' }
      elseif ($LASTEXITCODE -ne 0) { $failed = 'descarga de pesos fallo' }
    }

    if ($failed) {
      Write-Host ("  FALLO: " + $failed) -ForegroundColor Red
      $Results += [pscustomobject]@{ Id = $e.Id; Estado = 'FALLO'; Detalle = $failed }
      $ExitCode = 1
    } else {
      $Results += [pscustomobject]@{ Id = $e.Id; Estado = 'OK'; Detalle = '' }
    }
  }

  # pins exactos de esta instalacion (referencia para futuros constraints)
  $freeze = Join-Path $Root ('.cache\freeze-' + (Get-Date -Format 'yyyyMMdd') + '.txt')
  & $pyv -m pip freeze | Out-File -FilePath $freeze -Encoding utf8
  Write-Host ("`npip freeze -> " + $freeze)
}

# ---- resumen ----------------------------------------------------------------
if ($Results.Count -gt 0) {
  Write-Host "`n== Resumen de motores ==" -ForegroundColor Cyan
  foreach ($r in $Results) {
    $color = 'Green'
    if ($r.Estado -eq 'SALTADO') { $color = 'Yellow' }
    if ($r.Estado -eq 'FALLO') { $color = 'Red' }
    $line = ("  {0,-20} {1}" -f $r.Id, $r.Estado)
    if ($r.Detalle) { $line += (" (" + $r.Detalle + ")") }
    Write-Host $line -ForegroundColor $color
  }
}
Write-Host "`n== Listo. Arranque: run.bat  (o: npm run preview) ==" -ForegroundColor Green
Write-Host "  La app abre en http://127.0.0.1:8765"
Write-Host ("  Log de esta instalacion: " + $LogPath)

} finally {
  try { Stop-Transcript | Out-Null } catch {}
}
exit $ExitCode
