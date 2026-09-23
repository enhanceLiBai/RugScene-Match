param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    docker compose exec -T app python -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; x=torch.ones(4,device='cuda'); assert x.sum().item()==4; print(torch.cuda.get_device_name(0))"
    if ($LASTEXITCODE -ne 0) { throw 'Container GPU check failed' }
    foreach ($path in @('/', '/health', '/api/library', '/api/history')) {
        $response = Invoke-WebRequest "http://127.0.0.1:$Port$path" -UseBasicParsing -TimeoutSec 15
        Write-Output "$path : $($response.StatusCode)"
    }
} finally { Pop-Location }
