[CmdletBinding()]
param([string]$Report = '')

$ErrorActionPreference = 'Stop'
$product = 'RecordArchive.PortableShare'
$publisher = 'CN=LocalRecordArchive Development'

function Find-RecordArchiveShare {
    @(Get-AppxPackage -Name $product -ErrorAction Stop | Where-Object {
        $_.Name -ceq $product -and $_.Publisher -ceq $publisher
    })
}

try {
    # Never interrupt a receiver or an unsaved editing session.
    $active = $null
    try { $active = [Threading.Mutex]::OpenExisting('Local\RecordArchive.PortableShare.Main') }
    catch [Threading.WaitHandleCannotBeOpenedException] { }
    if ($active) {
        $active.Dispose()
        throw '请先保存并关闭记录归档，再移除微信分享入口。'
    }

    $packages = @(Find-RecordArchiveShare)
    foreach ($package in $packages) {
        Remove-AppxPackage -Package $package.PackageFullName -ErrorAction Stop
    }
    $remaining = @(Find-RecordArchiveShare)
    if ($remaining.Count) { throw 'Windows 仍保留分享注册，移除未完成。' }

    $result = [ordered]@{
        ok = $true
        package_name = $product
        removed_packages = $packages.Count
        remaining_packages = $remaining.Count
        scope = 'current_user_share_registration_only'
    }
    if ($Report) { $result | ConvertTo-Json | Set-Content -LiteralPath $Report -Encoding UTF8 }
    if ($packages.Count) { Write-Host '已移除当前用户的“记录归档”微信分享入口。' }
    else { Write-Host '当前用户没有“记录归档”分享注册，无需重复清理。' }
    Write-Host '若微信菜单仍显示旧入口，请关闭并重新打开分享菜单；必要时重启微信。'
    Write-Host '程序文件、导出文件和签名证书均未删除。重新运行主程序会再次注册入口。'
} catch {
    if ($Report) {
        @{ok=$false;package_name=$product;error=$_.Exception.Message} |
            ConvertTo-Json | Set-Content -LiteralPath $Report -Encoding UTF8
    }
    throw
}
