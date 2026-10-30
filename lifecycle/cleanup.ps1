param([string]$AppRoot,[string]$SupportRoot,[int]$OwnerProcessId)
$ErrorActionPreference='Stop'
$app=[IO.Path]::GetFullPath($AppRoot).TrimEnd('\')
$support=[IO.Path]::GetFullPath($SupportRoot).TrimEnd('\')
$cache=Join-Path ([Environment]::GetFolderPath('UserProfile')) '.record-archive\RecordArchiveLifecycle'
$cache=[IO.Path]::GetFullPath($cache).TrimEnd('\')
if ((Test-Path -LiteralPath $cache) -and ((Get-Item -LiteralPath $cache -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Redirected uninstaller cache; cleanup refused.' }
if ($app -ieq [IO.Path]::GetPathRoot($app).TrimEnd('\') -or $app -ieq [Environment]::GetFolderPath('UserProfile') -or $app -ieq [Environment]::GetFolderPath('Windows')) { throw 'Unsafe application cleanup root.' }
if ((Test-Path -LiteralPath $app) -and ((Get-Item -LiteralPath $app -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Redirected application cleanup root.' }
$registry='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RecordArchive.PortableShare'
if (Test-Path -LiteralPath $registry) { throw 'Uninstall registration still exists; cleanup refused.' }
$owned=Get-Content -LiteralPath (Join-Path $support 'owned-files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
try { $owner=Get-Process -Id $OwnerProcessId -ErrorAction Stop; $owner.WaitForExit() } catch [Microsoft.PowerShell.Commands.ProcessCommandException] {}
$directories=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($entry in $owned) {
 if ([IO.Path]::IsPathRooted($entry.path)) { throw 'Absolute owned-file path refused.' }
 $path=[IO.Path]::GetFullPath((Join-Path $app $entry.path))
 if (-not $path.StartsWith($app+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Owned-file path escapes app directory.' }
 if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
 $parent=$path
 $redirected=$false
 while ($parent.Length -ge $app.Length) {
  if ((Get-Item -LiteralPath $parent -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { $redirected=$true;break }
  if ($parent -ieq $app) { break }
  $parent=Split-Path -Parent $parent
 }
 if ($redirected) { continue }
 if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $entry.sha256) { continue }
 Remove-Item -LiteralPath $path -Force
 $parent=Split-Path -Parent $path
 while ($parent.StartsWith($app+'\',[StringComparison]::OrdinalIgnoreCase)) { $null=$directories.Add($parent);$parent=Split-Path -Parent $parent }
}
foreach ($directory in @($directories | Sort-Object Length -Descending)) {
 if ((Test-Path -LiteralPath $directory -PathType Container) -and -not @(Get-ChildItem -LiteralPath $directory -Force).Count) { Remove-Item -LiteralPath $directory -Force }
}
# The owned-file index is intentionally outside its own hash list.
$index=Join-Path $app '_internal\distribution\owned-files.json'
$safeIndex=$true
foreach ($candidate in @($index,(Split-Path $index),(Join-Path $app '_internal'))) { if ((Test-Path -LiteralPath $candidate) -and ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { $safeIndex=$false } }
if ($safeIndex -and (Test-Path -LiteralPath $index) -and (Get-FileHash -LiteralPath $index).Hash -eq (Get-FileHash -LiteralPath (Join-Path $support 'owned-files.json')).Hash) { Remove-Item -LiteralPath $index -Force }
foreach ($directory in @((Join-Path $app '_internal\distribution'),(Join-Path $app '_internal'),$app)) {
 if ((Test-Path -LiteralPath $directory) -and ((Get-Item -LiteralPath $directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
 if ($directory -ieq $app -and @([Environment]::GetFolderPath('DesktopDirectory'),[Environment]::GetFolderPath('MyDocuments'),[Environment]::GetFolderPath('LocalApplicationData'),[Environment]::GetFolderPath('ApplicationData'),[Environment]::GetFolderPath('ProgramFiles')) -contains $app) { continue }
 if ((Test-Path -LiteralPath $directory -PathType Container) -and -not @(Get-ChildItem -LiteralPath $directory -Force).Count) { Remove-Item -LiteralPath $directory -Force }
}
if ($support -ieq $cache) {
 foreach ($name in @('Uninstall.exe','setup.ps1','cleanup.ps1','owned-files.json','install.json')) { $path=Join-Path $cache $name; if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force } }
 if ((Test-Path -LiteralPath $cache) -and -not @(Get-ChildItem -LiteralPath $cache -Force).Count) { Remove-Item -LiteralPath $cache -Force }
}
