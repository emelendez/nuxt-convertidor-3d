<#
.SYNOPSIS
  Instalacion del Convertidor 3D (Nuxt 4 + Nitro + worker Python). Windows.

.DESCRIPTION
  Arquitectura hibrida: servidor Node/Nitro (UI + API) + worker Python para la
  IA (invocado por subproceso). Este script prepara AMBOS runtimes.

  Sin parametros: Node (npm ci + build) + FFmpeg embebido + venv base del worker.
                  La app arranca y funciona en modo simulacion.
  -AI      pila PyTorch CUDA + Video Depth Anything (repo + checkpoints S/B/L)
  -DML     equipos SIN GPU NVIDIA: torch CPU + ONNX Runtime DirectML + modelos ONNX
  -HQ      ademas StereoCrafter + pesos SVD (modo Calidad; requiere token HF)
  -All     todo lo anterior

.NOTES
  Los pesos de VDA Base/Large son CC-BY-NC-4.0 y los de StereoCrafter no
  comerciales: solo uso personal/investigacion.
  FFmpeg y modelos se copian del proyecto hermano ..\convertidor-3d si existe
  (rapido, sin descargar). El proyecto hermano NO se modifica (solo lectura).
  Fichero deliberadamente en ASCII (sin tildes): PowerShell 5.1 lee los .ps1
  sin BOM como ANSI y los caracteres multi-byte rompen el parser.
#>
param(
  [switch]$AI,
  [switch]$DML,
  [switch]$HQ,
  [switch]$All
)
$ErrorActionPreference = 'Stop'
if ($All) { $AI = $true; $DML = $true; $HQ = $true }

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
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
if (Test-Path "$Root\package-lock.json") {
  Write-Host "Instalando dependencias Node (npm ci)..."
  & npm ci
} else {
  Write-Host "Instalando dependencias Node (npm install)..."
  & npm install
}
if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de dependencias Node" }
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
    $r = Read-Host "Instalar FFmpeg con winget (Gyan.FFmpeg)? [s/N]"
    if ($r -match '^[sS]') {
      winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
      Write-Host "Cierra y reabre la terminal para refrescar el PATH." -ForegroundColor Yellow
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
if (-not (Test-Path "$Root\.venv")) {
  Write-Host "Creando entorno virtual .venv..."
  python -m venv "$Root\.venv"
}
$pip = "$Root\.venv\Scripts\pip.exe"
$pyv = "$Root\.venv\Scripts\python.exe"
& $pip install --upgrade pip -q
Write-Host "Instalando base del worker..."
& $pip install -r "$Root\worker\requirements.txt" -q

# ---- Modelos: copiar los del proyecto hermano si existen -------------------
if ((Test-Path "$Sibling\models") -and (-not (Test-Path "$Root\models"))) {
  Write-Host "Copiando modelos del proyecto hermano..."
  & robocopy "$Sibling\models" "$Root\models" /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
  if ($LASTEXITCODE -ge 8) { Write-Host "Aviso: fallo la copia de modelos (robocopy $LASTEXITCODE)" -ForegroundColor Yellow }
}

# ---- Pila de IA con CUDA (NVIDIA) ------------------------------------------
if ($AI) {
  Write-Host "`nInstalando PyTorch CUDA + dependencias de IA (varios GB)..." -ForegroundColor Cyan
  & $pip install -r "$Root\worker\requirements-ai.txt" `
      --extra-index-url https://download.pytorch.org/whl/cu126
  $vda = "$Root\models\Video-Depth-Anything"
  if (-not (Test-Path $vda)) {
    Write-Host "Clonando Video-Depth-Anything..."
    git clone --depth 1 https://github.com/DepthAnything/Video-Depth-Anything $vda
  }
  Write-Host "Descargando checkpoints VDA (S/B/L)..."
  New-Item -ItemType Directory -Force "$Root\models\checkpoints" | Out-Null
  & $pyv -c @"
from huggingface_hub import hf_hub_download
import shutil, os
dst = r'$Root\models\checkpoints'
for repo, f in [
    ('depth-anything/Video-Depth-Anything-Small', 'video_depth_anything_vits.pth'),
    ('depth-anything/Video-Depth-Anything-Base',  'video_depth_anything_vitb.pth'),
    ('depth-anything/Video-Depth-Anything-Large', 'video_depth_anything_vitl.pth')]:
    p = hf_hub_download(repo_id=repo, filename=f)
    shutil.copy(p, os.path.join(dst, f))
    print('OK', f)
"@
}

# ---- Sin NVIDIA: CPU / DirectML (Depth Anything V2 ONNX + torch CPU) -------
if ($DML) {
  Write-Host "`nInstalando pila sin CUDA (torch CPU + ONNX Runtime DirectML)..." -ForegroundColor Cyan
  Write-Host "AVISO: mucho mas lento que CUDA. Modo Calidad no disponible."
  & $pip install -r "$Root\worker\requirements-ai-cpu.txt" `
      --extra-index-url https://download.pytorch.org/whl/cpu
  $onnxDir = "$Root\models\checkpoints\onnx"
  New-Item -ItemType Directory -Force $onnxDir | Out-Null
  if (Test-Path "$onnxDir\da2_s.onnx") {
    Write-Host "Modelo ONNX da2_s ya presente."
  } else {
    Write-Host "Descargando Depth Anything V2 ONNX (Small fp16 ~50 MB; B/L opcionales)..."
    & $pyv -c @"
import shutil, os
from huggingface_hub import hf_hub_download
dst = r'$onnxDir'
p = hf_hub_download('onnx-community/depth-anything-v2-small', 'onnx/model_fp16.onnx')
shutil.copy(p, os.path.join(dst, 'da2_s.onnx')); print('OK da2_s.onnx')
for repo, name in [('onnx-community/depth-anything-v2-base', 'da2_b.onnx'),
                   ('onnx-community/depth-anything-v2-large', 'da2_l.onnx')]:
    try:
        p = hf_hub_download(repo, 'onnx/model_fp16.onnx')
        shutil.copy(p, os.path.join(dst, name)); print('OK', name)
    except Exception as e:
        print('Omitido', name, '->', type(e).__name__)
"@
  }
}

# ---- Modo Calidad (StereoCrafter) ------------------------------------------
if ($HQ) {
  Write-Host "`nModo Calidad: StereoCrafter + SVD." -ForegroundColor Cyan
  Write-Host "AVISO: pesos NO comerciales. SVD img2vid-xt-1-1 es 'gated' en HF:"
  Write-Host "  1) Acepta la licencia en huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt-1-1"
  Write-Host "  2) huggingface-cli login  (o variable HF_TOKEN)"
  $sc = "$Root\models\StereoCrafter"
  if (-not (Test-Path $sc)) {
    git clone --depth 1 https://github.com/TencentARC/StereoCrafter $sc
  }
  & $pyv -c @"
from huggingface_hub import snapshot_download
snapshot_download('TencentARC/StereoCrafter', local_dir=r'$Root\models\checkpoints\StereoCrafter')
snapshot_download('stabilityai/stable-video-diffusion-img2vid-xt-1-1',
                  local_dir=r'$Root\models\checkpoints\stable-video-diffusion-img2vid-xt-1-1')
print('Pesos HQ descargados')
"@
}

Write-Host "`n== Listo. Arranque: run.bat  (o: npm run preview) ==" -ForegroundColor Green
Write-Host "  La app abre en http://127.0.0.1:8765"
