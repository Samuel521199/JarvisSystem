param(
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][int]$OwnerPid,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$InstanceId,
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$StatePath
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing,System.Net.Http,System.Web.Extensions
Add-Type -Path (Join-Path $PSScriptRoot 'TrayApplication.cs') -ReferencedAssemblies System.Windows.Forms,System.Drawing,System.Net.Http,System.Web.Extensions
[System.Windows.Forms.Application]::EnableVisualStyles()
[Jarvis.TrayApplication]::Run($Port, $OwnerPid, $InstanceId, $Version, $StatePath)
