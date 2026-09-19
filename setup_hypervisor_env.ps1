[CmdletBinding()]
param(
    [string]$VMName = "HwidHvLab",

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ })]
    [string]$IsoPath,

    [string]$VhdPath = "$env:PUBLIC\Documents\Hyper-V\Virtual Hard Disks\HwidHvLab.vhdx",

    [string]$SwitchName,

    [UInt64]$MemoryStartupBytes = 6GB,
    [UInt64]$VhdSizeBytes = 80GB,

    [ValidateRange(2, 64)]
    [int]$ProcessorCount = 4,

    [switch]$EnableMacSpoofing,
    [switch]$DisableSecureBootForTestSigning,

    [PSCredential]$GuestCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[HV-LAB] $Message" -ForegroundColor Cyan
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell session."
    }
}

function Assert-HyperV {
    Write-Step "Checking Hyper-V host components..."

    $feature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -ErrorAction SilentlyContinue
    if (-not $feature -or $feature.State -ne "Enabled") {
        throw @"
Hyper-V is not enabled on this host.

Enable it from an elevated PowerShell and reboot:
  Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All

Then run this script again.
"@
    }

    if (-not (Get-Command Get-VM -ErrorAction SilentlyContinue)) {
        throw "Hyper-V PowerShell cmdlets are not available."
    }
}

function Resolve-VMSwitch {
    param([string]$RequestedSwitch)

    if ($RequestedSwitch) {
        $switch = Get-VMSwitch -Name $RequestedSwitch -ErrorAction Stop
        return $switch.Name
    }

    $external = Get-VMSwitch | Where-Object SwitchType -eq "External" | Select-Object -First 1
    if ($external) {
        return $external.Name
    }

    $default = Get-VMSwitch -Name "Default Switch" -ErrorAction SilentlyContinue
    if ($default) {
        return $default.Name
    }

    throw "No usable Hyper-V virtual switch was found. Create one or pass -SwitchName."
}

function Configure-GuestDevelopment {
    param(
        [string]$Name,
        [PSCredential]$Credential
    )

    Write-Step "Applying guest development settings through PowerShell Direct..."

    Invoke-Command -VMName $Name -Credential $Credential -ScriptBlock {
        $ErrorActionPreference = "Stop"

        Set-ItemProperty `
            -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" `
            -Name "fDenyTSConnections" `
            -Value 0

        Enable-NetFirewallRule -DisplayGroup "Remote Desktop" -ErrorAction SilentlyContinue

        bcdedit /set testsigning on | Out-Host

        Write-Host ""
        Write-Host "Guest development configuration applied."
        Write-Host "Reboot the guest before loading a test-signed driver."
    }
}

Assert-Administrator
Assert-HyperV

$resolvedSwitch = Resolve-VMSwitch -RequestedSwitch $SwitchName
Write-Step "Using virtual switch '$resolvedSwitch'."

$vm = Get-VM -Name $VMName -ErrorAction SilentlyContinue

if (-not $vm) {
    Write-Step "Creating Generation 2 VM '$VMName'..."

    $vhdDirectory = Split-Path -Parent $VhdPath
    if (-not (Test-Path $vhdDirectory)) {
        New-Item -ItemType Directory -Path $vhdDirectory -Force | Out-Null
    }

    New-VM `
        -Name $VMName `
        -Generation 2 `
        -MemoryStartupBytes $MemoryStartupBytes `
        -NewVHDPath $VhdPath `
        -NewVHDSizeBytes $VhdSizeBytes `
        -SwitchName $resolvedSwitch | Out-Null

    Set-VMProcessor -VMName $VMName -Count $ProcessorCount
    Set-VMMemory -VMName $VMName -DynamicMemoryEnabled $false
    Set-VM -Name $VMName -AutomaticCheckpointsEnabled $false

    $dvd = Add-VMDvdDrive -VMName $VMName -Path (Resolve-Path $IsoPath).Path -Passthru
    Set-VMFirmware -VMName $VMName -FirstBootDevice $dvd

    if ($DisableSecureBootForTestSigning) {
        Set-VMFirmware -VMName $VMName -EnableSecureBoot Off
    }
}
else {
    Write-Step "VM '$VMName' already exists; reusing it."
}

$vm = Get-VM -Name $VMName
$processor = Get-VMProcessor -VMName $VMName

if (-not $processor.ExposeVirtualizationExtensions) {
    if ($vm.State -ne "Off") {
        throw "The VM must be OFF before nested virtualization can be enabled. Shut it down and run the script again."
    }

    Write-Step "Exposing hardware virtualization extensions to the guest..."
    Set-VMProcessor -VMName $VMName -ExposeVirtualizationExtensions $true
}
else {
    Write-Step "Nested virtualization is already enabled."
}

if ($EnableMacSpoofing) {
    Write-Step "Enabling MAC-address spoofing on the L1 VM network adapter..."
    Get-VMNetworkAdapter -VMName $VMName | Set-VMNetworkAdapter -MacAddressSpoofing On
}

$vm = Get-VM -Name $VMName
if ($vm.State -eq "Off") {
    Write-Step "Starting VM '$VMName'..."
    Start-VM -Name $VMName | Out-Null
}
else {
    Write-Step "VM '$VMName' is already running."
}

Write-Host ""
Write-Host "VM created/configured successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Important for this custom-VMX lab:"
Write-Host "  1. Install Windows in the VM from the attached ISO."
Write-Host "  2. Do NOT enable the Hyper-V role inside the guest."
Write-Host "     The custom driver needs the exposed VMX extensions itself."
Write-Host "  3. Install Visual Studio Build Tools/Visual Studio + WDK in the guest."
Write-Host "  4. Build the driver in the guest and use a test certificate."
Write-Host "  5. Verify in the guest that CPUID reports VMX before sending IOCTL_START_HYPERVISOR."
Write-Host ""
Write-Host "Nested setting:"
Get-VMProcessor -VMName $VMName |
    Select-Object VMName, Count, ExposeVirtualizationExtensions |
    Format-Table -AutoSize

if ($GuestCredential) {
    try {
        Configure-GuestDevelopment -Name $VMName -Credential $GuestCredential
    }
    catch {
        Write-Warning "Guest configuration could not be applied yet. Finish Windows setup, then rerun with -GuestCredential."
        Write-Warning $_
    }
}
else {
    Write-Host ""
    Write-Host "After Windows setup you can enable RDP/test-signing automatically by rerunning"
    Write-Host "this script with -GuestCredential <credential> while the guest is running."
}
