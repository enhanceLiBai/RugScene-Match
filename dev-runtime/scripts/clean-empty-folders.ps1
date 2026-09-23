param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Root,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
    throw '根目录必须是可访问的文件夹。'
}

# 从最深层目录向上处理；仅删除确实没有子项的目录，永不删除指定根目录。
$emptyDirectories = @(
    Get-ChildItem -LiteralPath $resolvedRoot -Directory -Recurse -Force |
        Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName -Force | Select-Object -First 1) }
)

if (-not $emptyDirectories) {
    Write-Output '没有空文件夹。'
    exit 0
}

if (-not $Execute) {
    Write-Output "发现 $($emptyDirectories.Count) 个空文件夹。以下为预览，未执行删除："
    $emptyDirectories | ForEach-Object { Write-Output $_.FullName }
    Write-Output '确认后使用：scripts\clean-empty-folders.ps1 -Root "目录路径" -Execute'
    exit 0
}

$removed = 0
foreach ($directory in $emptyDirectories) {
    # 再次确认，避免脚本扫描后有其他任务写入图片时误删。
    if (-not (Get-ChildItem -LiteralPath $directory.FullName -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $directory.FullName -Force
        $removed++
        Write-Output "已删除：$($directory.FullName)"
    }
}
Write-Output "完成：删除 $removed 个空文件夹。"
