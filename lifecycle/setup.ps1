param(
 [ValidateSet('Status','Register','Uninstall')][string]$Action,
 [string]$AppRoot,[string]$SupportRoot,[string]$ExpectedFingerprint,[string]$Report
)
$ErrorActionPreference='Stop'
$product='RecordArchive.PortableShare'
$publisher='CN=LocalRecordArchive Development'
$registry='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RecordArchive.PortableShare'
function Result($value) { $value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Report -Encoding UTF8 }
try {
 $app=[IO.Path]::GetFullPath($AppRoot).TrimEnd('\')
 $support=[IO.Path]::GetFullPath($SupportRoot).TrimEnd('\')
 if ($ExpectedFingerprint -ne '945694BF185971C80B144A97421C58D564C32FD5') { throw 'Unexpected certificate identity.' }
 $packages=@(Get-AppxPackage -Name $product | Where-Object { $_.Publisher -eq $publisher })
 $null=[Windows.Management.Deployment.PackageManager,Windows.Management.Deployment,ContentType=WindowsRuntime]
 $manager=New-Object Windows.Management.Deployment.PackageManager
 $location=$null
 if ($packages.Count -eq 1) { try { $location=$manager.FindPackageForUser('', $packages[0].PackageFullName).EffectiveLocation.Path } catch {} }
 if ($Action -eq 'Uninstall') {
  $existing=$null
  try { $existing=[Threading.Mutex]::OpenExisting('Local\RecordArchive.PortableShare.Main') } catch [Threading.WaitHandleCannotBeOpenedException] {}
  if ($existing) { $existing.Dispose();throw '请保存并关闭记录归档后再卸载。' }
  if ($location -and [IO.Path]::GetFullPath($location).TrimEnd('\') -ine $app) { throw '分享入口属于另一个目录，请从新位置卸载，未修改该入口。' }
  foreach ($package in $packages) { Remove-AppxPackage -Package $package.PackageFullName -ErrorAction Stop }
  if (@(Get-AppxPackage -Name $product | Where-Object { $_.Publisher -eq $publisher }).Count) { throw '分享入口尚未注销，未删除程序文件。' }
  if (Test-Path -LiteralPath $registry) {
   $registered=Get-ItemProperty -LiteralPath $registry
   if ($registered.InstallLocation -ine $app) { throw '卸载信息属于另一个目录，未删除它。' }
   Remove-Item -LiteralPath $registry -ErrorAction Stop
  }
  Result @{ok=$true;unregistered=$true};exit 0
 }
 $info=Get-Content -LiteralPath (Join-Path $app '_internal\build-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
 if ($info.package_name -ne $product -or $info.publisher -ne $publisher) { throw '应用身份不匹配。' }
 $package=Join-Path $app 'share\RecordArchive.Identity.msix'
 if ((Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash -ine $info.registration_package_sha256) { throw '分享组件被修改，请重新解压完整文件。' }
 $signature=Get-AuthenticodeSignature -LiteralPath $package
 $cert=$signature.SignerCertificate
 if (-not $cert -or $cert.Thumbprint -ne $ExpectedFingerprint -or $cert.Subject -ne $publisher -or $signature.Status -eq 'HashMismatch') { throw '分享组件签名不匹配。' }
 if ($cert.NotBefore -gt (Get-Date) -or $cert.NotAfter -le (Get-Date)) { throw '此测试签名尚未生效或已过期，请获取正式签名新版。' }
 $trusted=$signature.Status -eq 'Valid'
 $resourceCheck=Join-Path $app '_internal\share_resources.ps1'
 $resourcesValid=& ([ScriptBlock]::Create([IO.File]::ReadAllText($resourceCheck))) -AppRoot $app
 if($resourcesValid -ne $true){throw '分享组件资源校验未完成。'}
 $receiver=Join-Path $app '_internal\RecordShareReceiver.exe'
 if ($info.receiver_probe_version -ne 1 -or -not $info.receiver_sha256 -or
     -not (Test-Path -LiteralPath $receiver -PathType Leaf) -or
     (Get-FileHash -LiteralPath $receiver).Hash -ine $info.receiver_sha256) {
  throw '分享接收器与当前版本不匹配，请完整解压新版后再运行。'
 }
 $same=$packages.Count -eq 1 -and [string]$packages[0].Version -eq $info.version -and $location -and [IO.Path]::GetFullPath($location).TrimEnd('\') -ieq $app
 if ($Action -eq 'Status') { Result @{ok=$true;trusted=$trusted;registered=[bool]$same;uninstall_entry=(Test-Path -LiteralPath $registry);version=$info.version;expires=$cert.NotAfter.ToString('yyyy-MM-dd')};exit 0 }
 if (-not $trusted) { throw '测试证书尚未受本机信任，未注册分享入口。' }
 $registration=Join-Path ([IO.Path]::GetTempPath()) ('RecordArchiveRegistration-'+[Guid]::NewGuid().ToString('N')+'.json')
 try {
  $process=Start-Process -FilePath (Join-Path $app '_internal\WeChatRecordExporter.Core.exe') -ArgumentList @('--register-share',('"'+$registration+'"')) -WorkingDirectory $app -WindowStyle Hidden -Wait -PassThru
  $result=Get-Content -LiteralPath $registration -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($process.ExitCode -ne 0 -or -not $result.ok) { throw ('分享注册失败：'+$result.error) }
 } finally { if (Test-Path -LiteralPath $registration) { Remove-Item -LiteralPath $registration } }
 if ($info.receiver_probe_version -ne 1) { throw '分享组件缺少运行身份探针，请获取完整新版。' }
 $probe=Join-Path ([IO.Path]::GetTempPath()) ('RecordArchiveIdentity-'+[Guid]::NewGuid().ToString('N')+'.json')
 try {
  $process=Start-Process -FilePath $receiver -ArgumentList @('--registration-check',('"'+$probe+'"')) -WorkingDirectory $app -WindowStyle Hidden -PassThru
  if (-not $process.WaitForExit(10000)) { $process.Kill();throw '分享接收器运行身份检查超时。' }
  $identity=Get-Content -LiteralPath $probe -Raw -Encoding UTF8 | ConvertFrom-Json
  $registered=@(Get-AppxPackage -Name $product | Where-Object {$_.Publisher -ceq $publisher})
  if ($process.ExitCode -ne 0 -or -not $identity.ok -or $registered.Count -ne 1 -or
      $identity.package_full_name -cne $registered[0].PackageFullName -or
      $identity.application_id -cne ($registered[0].PackageFamilyName+'!App')) {
   throw ('分享注册存在，但接收器未取得匹配的运行身份。包错误码：'+$identity.package_error+'；应用错误码：'+$identity.application_error)
  }
 } finally { if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe } }
 $cache=Join-Path ([Environment]::GetFolderPath('UserProfile')) '.record-archive\RecordArchiveLifecycle'
 if (Test-Path -LiteralPath $cache) { if ((Get-Item -LiteralPath $cache -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '卸载器缓存路径被重定向。' } }
 $null=New-Item -ItemType Directory -Path $cache -Force
 Copy-Item -LiteralPath (Join-Path $app 'WeChatRecordExporter.exe') -Destination (Join-Path $cache 'Uninstall.exe') -Force
 foreach ($name in @('setup.ps1','cleanup.ps1','owned-files.json')) { Copy-Item -LiteralPath (Join-Path $support $name) -Destination (Join-Path $cache $name) -Force }
 @{root=$app;product=$product;version=$info.version} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $cache 'install.json') -Encoding UTF8
 $null=New-Item -Path $registry -Force
 foreach ($entry in @{
   DisplayName='记录归档';DisplayVersion=$info.version;Publisher='记录归档（本地测试版）';
   InstallLocation=$app;DisplayIcon=(Join-Path $app 'WeChatRecordExporter.exe');
   UninstallString=('"'+(Join-Path $cache 'Uninstall.exe')+'" --uninstall');
   InstallDate=(Get-Date).ToString('yyyyMMdd')
 }.GetEnumerator()) { $null=New-ItemProperty -LiteralPath $registry -Name $entry.Key -Value $entry.Value -PropertyType String -Force }
 $null=New-ItemProperty -LiteralPath $registry -Name NoModify -Value 1 -PropertyType DWord -Force
 $null=New-ItemProperty -LiteralPath $registry -Name NoRepair -Value 1 -PropertyType DWord -Force
 Result @{ok=$true;registered=$true;uninstall_entry=$true};exit 0
} catch { Result @{ok=$false;error=$_.Exception.Message};exit 1 }
