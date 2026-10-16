param([Parameter(Mandatory=$true)][string]$SessionRoot)
# Elevated helper for one bounded probe. No adapter/profile/global-rule changes.
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($SessionRoot).TrimEnd('\')
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
if ([IO.Path]::GetDirectoryName($root) -ne $tempRoot -or
    [IO.Path]::GetFileName($root) -notmatch '^jarvis-network-probe-[a-zA-Z0-9_-]+$') {
    throw 'Unexpected probe directory'
}
$configuration = Get-Content -LiteralPath (Join-Path $root 'firewall.json') -Raw | ConvertFrom-Json
if ($configuration.session_id -notmatch '^[a-f0-9]{32}$' -or @($configuration.programs).Count -ne 4) {
    throw 'Invalid probe configuration'
}
$names = @()
$programs = @()
$ready = @{status='failed'; administrator=$false; rules=@()}
$cleanup = @{status='failed'; remaining=@(); errors=@()}
function Save-Result($name, $value) {
    $path = Join-Path $root $name
    $value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath ($path + '.tmp') -Encoding UTF8
    Move-Item -LiteralPath ($path + '.tmp') -Destination $path -Force
}
try {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    $ready.administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $ready.administrator) { throw 'Administrator token required for temporary firewall rules' }
    if (@(Get-NetFirewallProfile -ErrorAction Stop | Where-Object { -not $_.Enabled }).Count) {
        throw 'All firewall profiles must already be enabled; this helper will not change them'
    }
    foreach ($program in $configuration.programs) {
        $absolute = [IO.Path]::GetFullPath($program)
        if (-not $absolute.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $absolute -notmatch '\\runtime\\slots\\release-[a-f0-9]{24}\\(python|source\\runtime-bundle\\worker-python-[^\\]+)\\python.exe$' -or
            -not (Test-Path -LiteralPath $absolute -PathType Leaf)) { throw 'Program escaped verified temporary slots' }
        $inspect = $absolute
        while ($inspect -and $inspect -ne $tempRoot) {
            if ((Get-Item -LiteralPath $inspect -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Reparse points are not allowed in the probe path'
            }
            $inspect = [IO.Path]::GetDirectoryName($inspect)
        }
        $programs += $absolute
    }
    if (@($programs | Select-Object -Unique).Count -ne 4) { throw 'Duplicate executable' }
    if (Test-Path -LiteralPath (Join-Path $root 'firewall-stop')) { throw 'Probe already ended before helper became ready' }
    for ($i=0; $i -lt $programs.Count; $i++) {
        $name = 'JarvisProbe-' + $configuration.session_id + '-' + $i
        if (@(Get-NetFirewallRule -PolicyStore PersistentStore -ErrorAction Stop | Where-Object Name -EQ $name).Count) {
            throw 'Probe rule already exists'
        }
        $names += $name
        New-NetFirewallRule -Name $name -DisplayName $name -Direction Outbound -Action Block -Enabled True `
            -Profile Any -Program $programs[$i] -PolicyStore PersistentStore -ErrorAction Stop | Out-Null
        $rule = Get-NetFirewallRule -Name $name -PolicyStore ActiveStore -ErrorAction Stop
        $filter = $rule | Get-NetFirewallApplicationFilter -ErrorAction Stop
        if ($rule.Enabled -ne 'True' -or $rule.Direction -ne 'Outbound' -or $rule.Action -ne 'Block' -or
            $filter.Program -ne $programs[$i]) { throw 'Effective rule does not match the intended program block' }
        $ready.rules += @{name=$name; program=$programs[$i]; effective=$true}
    }
    $ready.status = 'ready'; Save-Result 'firewall-ready.json' $ready
    $deadline = [DateTime]::UtcNow.AddMinutes(10)
    while (-not (Test-Path -LiteralPath (Join-Path $root 'firewall-stop')) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
} catch {
    $ready.status = 'failed'; $ready.error = $_.Exception.Message
    Save-Result 'firewall-ready.json' $ready
} finally {
    foreach ($name in $names) {
        try {
            $found = @(Get-NetFirewallRule -PolicyStore PersistentStore -ErrorAction Stop | Where-Object Name -EQ $name)
            foreach ($rule in $found) {
                $filter = $rule | Get-NetFirewallApplicationFilter -ErrorAction Stop
                if ($filter.Program -notin $programs) { throw 'Rule program changed; retaining it for inspection' }
                $rule | Remove-NetFirewallRule -ErrorAction Stop
            }
        } catch { $cleanup.errors += $_.Exception.Message }
    }
    try {
        $cleanup.remaining = @(Get-NetFirewallRule -PolicyStore ActiveStore -ErrorAction Stop |
            Where-Object { $_.Name -in $names } | Select-Object -ExpandProperty Name)
        if ($cleanup.remaining.Count -eq 0 -and $cleanup.errors.Count -eq 0) { $cleanup.status='removed' }
    } catch { $cleanup.errors += $_.Exception.Message }
    Save-Result 'firewall-cleanup.json' $cleanup
}
