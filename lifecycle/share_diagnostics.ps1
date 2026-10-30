param([Parameter(Mandatory=$true)][string]$AppRoot)
$ErrorActionPreference='Stop'
$env:PSModulePath=Join-Path $PSHOME 'Modules'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$result=[ordered]@{}
try {
    $os=Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    $result.windows_display_version=[string]$os.DisplayVersion
    $result.windows_build=([string]$os.CurrentBuildNumber+'.'+[string]$os.UBR)
    $result.is_64_bit_os=[Environment]::Is64BitOperatingSystem
} catch { $result.os_probe_error=$_.Exception.HResult }
try {
    $versions=@(Get-Process -Name Weixin,WeChat -ErrorAction SilentlyContinue | ForEach-Object {
        try { [regex]::Match($_.MainModule.FileVersionInfo.ProductVersion,'\d+(\.\d+){1,3}').Value } catch {}
    } | Where-Object {$_} | Sort-Object -Unique)
    $result.wechat_versions=$versions
} catch { $result.wechat_probe_error=$_.Exception.HResult }
try {
    $packages=@(Get-AppxPackage -Name 'RecordArchive.PortableShare' | Where-Object {$_.Publisher -ceq 'CN=LocalRecordArchive Development'})
    $result.share_package_count=$packages.Count
    if ($packages.Count -eq 1) {
        $result.share_package_version=[string]$packages[0].Version
        $result.share_package_status=[string]$packages[0].Status
        $manifest=Get-AppxPackageManifest -Package $packages[0].PackageFullName
        $result.share_entry_hidden=([string]$manifest.Package.Applications.Application.VisualElements.AppListEntry -ceq 'none')
        $result.receiver_path_matches=([string]$manifest.Package.Applications.Application.Executable -ceq '_internal\RecordShareReceiver.exe')
        $null=[Windows.Management.Deployment.PackageManager,Windows.Management.Deployment,ContentType=WindowsRuntime]
        $manager=New-Object Windows.Management.Deployment.PackageManager
        $location=$manager.FindPackageForUser('',$packages[0].PackageFullName).EffectiveLocation.Path
        $result.share_location_matches=([IO.Path]::GetFullPath($location).TrimEnd('\') -ieq [IO.Path]::GetFullPath($AppRoot).TrimEnd('\'))
    }
    $package=Join-Path $AppRoot 'share\RecordArchive.Identity.msix'
    $result.package_signature_status=[string](Get-AuthenticodeSignature -LiteralPath $package).Status
    $result.receiver_file_present=Test-Path -LiteralPath (Join-Path $AppRoot '_internal\RecordShareReceiver.exe') -PathType Leaf
    try{
        $resourceCheck=Join-Path $AppRoot '_internal\share_resources.ps1'
        $result.share_resources_match=(& ([ScriptBlock]::Create([IO.File]::ReadAllText($resourceCheck))) -AppRoot $AppRoot) -eq $true
    }catch{$result.share_resources_match=$false}
    $info=Get-Content -LiteralPath (Join-Path $AppRoot '_internal\build-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $receiver=Join-Path $AppRoot '_internal\RecordShareReceiver.exe'
    $result.receiver_hash_matches=($info.receiver_sha256 -and $result.receiver_file_present -and
        (Get-FileHash -LiteralPath $receiver).Hash -ieq $info.receiver_sha256)
    if ($info.receiver_probe_version -eq 1 -and $result.receiver_hash_matches) {
        $probe=Join-Path ([IO.Path]::GetTempPath()) ('RecordArchiveIdentity-'+[Guid]::NewGuid().ToString('N')+'.json')
        try {
            $process=Start-Process -FilePath $receiver -ArgumentList @('--registration-check',('"'+$probe+'"')) -WindowStyle Hidden -PassThru
            if (-not $process.WaitForExit(10000)) {$process.Kill();throw 'Identity probe timed out'}
            $identity=Get-Content -LiteralPath $probe -Raw -Encoding UTF8 | ConvertFrom-Json
            $result.receiver_runtime_identity_matches=($process.ExitCode -eq 0 -and $identity.ok -and $packages.Count -eq 1 -and
                $identity.package_full_name -ceq $packages[0].PackageFullName -and $identity.application_id -ceq ($packages[0].PackageFamilyName+'!App'))
            $result.receiver_package_error=$identity.package_error
            $result.receiver_application_error=$identity.application_error
            $result.app_list_entry_count=$identity.app_list_entry_count
            $result.app_list_entry_resolved=$identity.app_list_entry_resolved
            $result.app_logo_readable=$identity.app_logo_readable
            $result.app_logo_indexed=$identity.app_logo_indexed
            if($identity.resource_index_error){$result.resource_index_error=$identity.resource_index_error}
        } finally {if(Test-Path -LiteralPath $probe){Remove-Item -LiteralPath $probe}}
    }
} catch { $result.registration_probe_error=$_.Exception.HResult }
$result | ConvertTo-Json -Depth 4 -Compress
