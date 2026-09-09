param(
    [string]$PythonExecutable = "python",
    [string]$EnvironmentName = ".ven"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot $EnvironmentName
$venvPython = Join-Path $venvPath "Scripts\python.exe"

# 将所有持久化缓存限制在项目目录，避免模型和安装包写入 C 盘用户缓存。
$env:PYTHONIOENCODING = "utf-8"
$env:PIP_CACHE_DIR = Join-Path $projectRoot ".cache\pip"
$env:TORCH_HOME = Join-Path $projectRoot ".cache\torch"
$env:HF_HOME = Join-Path $projectRoot ".cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $env:HF_HOME "hub"

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonExecutable -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败。" }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "升级 pip 失败。" }
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements.in")
if ($LASTEXITCODE -ne 0) { throw "安装项目依赖失败。" }
