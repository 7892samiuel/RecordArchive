param([Parameter(Mandatory=$true)][string]$AppRoot)
$ErrorActionPreference='Stop'
$info=Get-Content -LiteralPath (Join-Path $AppRoot '_internal\build-info.json') -Raw -Encoding UTF8|ConvertFrom-Json
foreach($relative in @('resources.pri','Assets/StoreLogo.png','Assets/Square44x44Logo.png','Assets/Square150x150Logo.png')){
 $entry=$info.share_resources_sha256.PSObject.Properties[$relative]
 $file=Join-Path $AppRoot $relative
 if(-not $entry -or $entry.Value -notmatch '^[a-f0-9]{64}$' -or
    -not (Test-Path -LiteralPath $file -PathType Leaf) -or
    (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $entry.Value){
  throw '分享组件资源缺失或不匹配，请完整解压新版后运行。'
 }
}
$true
