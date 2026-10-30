param([Parameter(Mandatory=$true)][string]$SourceRoot)
$ErrorActionPreference = 'Stop'
$source = Join-Path $SourceRoot 'lifecycle\remove_share_registration.ps1'
$script = [ScriptBlock]::Create([IO.File]::ReadAllText($source))
$own = [pscustomobject]@{Name='RecordArchive.PortableShare';Publisher='CN=LocalRecordArchive Development';PackageFullName='owned-package'}
$other = [pscustomobject]@{Name='RecordArchive.PortableShare';Publisher='CN=Different Publisher';PackageFullName='foreign-package'}
$script:mockPackages = @($own,$other)
$script:removed = @()
$script:rejectRemoval = $false
$script:retainRegistration = $false

function Get-AppxPackage {
    [CmdletBinding()]param([string]$Name)
    if ($Name -cne 'RecordArchive.PortableShare') { throw 'Unexpected package selector' }
    $script:mockPackages
}
function Remove-AppxPackage {
    [CmdletBinding()]param([string]$Package)
    if ($script:rejectRemoval) { throw 'simulated deployment failure' }
    $script:removed += $Package
    if (-not $script:retainRegistration) {
        $script:mockPackages = @($script:mockPackages | Where-Object {$_.PackageFullName -cne $Package})
    }
}

& $script
if ($script:removed.Count -ne 1 -or $script:removed[0] -cne 'owned-package') { throw 'Removed a foreign registration' }
if ($script:mockPackages.Count -ne 1 -or $script:mockPackages[0].PackageFullName -cne 'foreign-package') { throw 'Foreign registration changed' }
& $script
if ($script:removed.Count -ne 1) { throw 'Repeated removal was not idempotent' }

$script:mockPackages = @($own)
$script:rejectRemoval = $true
$caught = $false
try { & $script } catch { $caught = $_.Exception.Message -eq 'simulated deployment failure' }
if (-not $caught) { throw 'Deployment error was reported as success' }

$script:rejectRemoval = $false
$script:retainRegistration = $true
$caught = $false
try { & $script } catch { $caught = $_.Exception.Message -like '*移除未完成*' }
if (-not $caught) { throw 'Remaining registration was reported as success' }
Write-Output '{"ok":true,"cases":4,"real_system_registration_modified":false}'
