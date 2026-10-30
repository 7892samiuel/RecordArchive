param([string]$Destination)
$ErrorActionPreference='Stop'
if(-not $Destination){$Destination=Join-Path $PSScriptRoot 'build'}
$framework=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$refs=@(Get-ChildItem -LiteralPath (Join-Path $env:WINDIR 'System32\WinMetadata') -Filter '*.winmd' | ForEach-Object {'/r:'+$_.FullName})
$refs+='/r:'+(Join-Path $framework 'System.Runtime.WindowsRuntime.dll')
foreach($name in @('System.Runtime','System.Runtime.InteropServices.WindowsRuntime','System.ObjectModel','System.Threading.Tasks','System.Runtime.Extensions','System.Collections')){
    $dll=Get-ChildItem -LiteralPath (Join-Path $env:WINDIR ('Microsoft.NET\assembly\GAC_MSIL\'+$name)) -Recurse -Filter '*.dll' -ErrorAction SilentlyContinue | Select-Object -First 1
    if($dll){$refs+='/r:'+$dll.FullName}
}
$null=New-Item -ItemType Directory -Path $Destination -Force
[xml]$manifest=[IO.File]::ReadAllText((Join-Path (Split-Path $PSScriptRoot) 'native_share\desktop.manifest'))
$identity=$manifest.CreateElement('msix','urn:schemas-microsoft-com:msix.v1')
$identity.SetAttribute('publisher','CN=LocalRecordArchive Development')
$identity.SetAttribute('packageName','RecordArchive.PortableShare')
$identity.SetAttribute('applicationId','App')
$null=$manifest.assembly.AppendChild($identity)
$manifestPath=Join-Path $Destination 'receiver.manifest';$manifest.Save($manifestPath)
& (Join-Path $framework 'csc.exe') /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll @refs ('/win32manifest:'+$manifestPath) ('/out:'+(Join-Path $Destination 'RecordShareReceiver.exe')) (Join-Path $PSScriptRoot 'Receiver.cs')
if($LASTEXITCODE -ne 0){throw 'Share receiver compilation failed'}
& (Join-Path $framework 'csc.exe') /nologo /target:winexe /platform:x64 /optimize+ /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll @refs ('/out:'+(Join-Path $Destination 'RecordOcrHelper.exe')) (Join-Path $PSScriptRoot 'OcrHelper.cs')
if($LASTEXITCODE -ne 0){throw 'Offline OCR helper compilation failed'}
