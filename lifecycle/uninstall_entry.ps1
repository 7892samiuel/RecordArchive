param([Parameter(Mandatory=$true)][string]$AppRoot)
$ErrorActionPreference='Stop'
$app=[IO.Path]::GetFullPath($AppRoot).TrimEnd('\')
$launcher=Join-Path $app 'WeChatRecordExporter.exe'
if (Test-Path -LiteralPath $launcher -PathType Leaf) {
    $process=Start-Process -FilePath $launcher -ArgumentList '--uninstall' -WorkingDirectory $app -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw '卸载未完成，请检查窗口中的提示。' }
    return
}
# The main executable may already have been deleted. The cached uninstaller
# was deliberately saved independently of the extraction directory.
$cache=Join-Path ([Environment]::GetFolderPath('UserProfile')) '.record-archive\RecordArchiveLifecycle'
$info=Join-Path $cache 'install.json'
$uninstaller=Join-Path $cache 'Uninstall.exe'
if ((Test-Path -LiteralPath $info -PathType Leaf) -and (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    $state=Get-Content -LiteralPath $info -Raw -Encoding UTF8 | ConvertFrom-Json
    $signature=Get-AuthenticodeSignature -LiteralPath $uninstaller
    if ($state.product -ceq 'RecordArchive.PortableShare' -and $state.root -ieq $app -and
        $signature.Status -eq 'Valid' -and $signature.SignerCertificate.Thumbprint -eq '945694BF185971C80B144A97421C58D564C32FD5') {
        $process=Start-Process -FilePath $uninstaller -ArgumentList '--uninstall' -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw '卸载未完成，请检查窗口中的提示。' }
        return
    }
}
# No executable is needed to remove the current user's orphaned share target.
& ([ScriptBlock]::Create([IO.File]::ReadAllText((Join-Path $app '_internal\distribution\remove_share_registration.ps1'))))
