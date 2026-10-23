# Windows PowerShell 5.1 compatible. Invoked by Setup-SoulLink.cmd.
[CmdletBinding()]
param(
    [string]$BuildRoot = "$env:SystemDrive\SoulLinkBuild-$([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)",
    [string]$InstallRoot = "$env:LOCALAPPDATA\EmeraldSoulLink",
    [switch]$NoLaunch,
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Download([string]$Url, [string]$Destination) {
    Write-Host "Downloading $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile "$Destination.partial"
    Move-Item -LiteralPath "$Destination.partial" -Destination $Destination -Force
}

function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE)." }
}

function Bash([string]$Command) {
    Run "$script:Msys\usr\bin\bash.exe" @('--login', '-c', $Command)
}

try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'Setup requires an Intel/AMD 64-bit Windows 10 or Windows 11 PC.'
    }
    $BuildRoot = [IO.Path]::GetFullPath($BuildRoot).TrimEnd('\')
    if ($BuildRoot -notmatch '^[A-Za-z]:\\[A-Za-z0-9_\\-]+$') {
        throw 'The build folder must be a local drive path containing only ASCII letters, numbers, underscores, dashes, and backslashes (no spaces).'
    }
    $Source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
    if ($Source.StartsWith($BuildRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $BuildRoot.StartsWith($Source + '\', [StringComparison]::OrdinalIgnoreCase) -or $Source -eq $BuildRoot) {
        throw 'The build folder must be outside the source folder.'
    }
    New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
    # Prevent a second setup from changing the tools/source during a build.
    $Lock = [IO.File]::Open((Join-Path $BuildRoot 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $Log = Join-Path $BuildRoot 'setup.log'
    Start-Transcript -Path $Log -Force | Out-Null
    Write-Host "Emerald Soul Link setup. Log: $Log"
    Write-Host 'This downloads the compilers, Python and mGBA, builds the game locally, and installs the app.'
    Write-Host 'The first run can take a while and needs several GB of free space. Leave this window open.'

    Write-Host '[1/6] Preparing private build tools'
    $Msys = Join-Path $BuildRoot 'msys64'
    if (-not (Test-Path "$Msys\usr\bin\bash.exe")) {
        $Archive = Join-Path $BuildRoot 'msys2.sfx.exe'
        $Url = 'https://repo.msys2.org/distrib/x86_64/msys2-base-x86_64-20260927.sfx.exe'
        Download $Url $Archive
        # Published checksum: github.com/msys2/msys2-installer/releases/tag/2026-09-27
        if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne 'ad336cccfda47758b5e15cda993fbba421115cb0b126697daef1ee4dfe37209f') {
            throw 'MSYS2 download checksum does not match.'
        }
        Run $Archive @('-y', "-o$BuildRoot")
    }
    $env:MSYSTEM = 'UCRT64'
    $env:CHERE_INVOKING = '1'
    # Core MSYS2 updates can terminate their shell. A new shell completes the update;
    # the final full update and package installation must both succeed.
    & "$Msys\usr\bin\bash.exe" --login -c 'pacman -Syu --noconfirm'
    Bash 'pacman -Syu --noconfirm'
    Bash 'pacman -S --needed --noconfirm make bsdtar mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-libpng mingw-w64-ucrt-x86_64-pkgconf mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-arm-none-eabi-gcc mingw-w64-ucrt-x86_64-arm-none-eabi-binutils mingw-w64-ucrt-x86_64-arm-none-eabi-newlib'

    Write-Host '[2/6] Preparing Windows Python for the launcher build'
    $PythonDir = Join-Path $BuildRoot 'python'
    $Python = Join-Path $PythonDir 'python.exe'
    # Reuse a compatible registered Python instead of moving an existing installation.
    if (-not (Test-Path $Python)) {
        foreach ($Version in @('3.13', '3.12')) {
            foreach ($Hive in @('HKCU:', 'HKLM:')) {
                $Key = "$Hive\Software\Python\PythonCore\$Version\InstallPath"
                if (Test-Path $Key) {
                    $Candidate = Join-Path (Get-Item $Key).GetValue('') 'python.exe'
                    if (Test-Path $Candidate) {
                        & $Candidate -c "import sys, struct, tkinter; assert sys.platform == 'win32' and struct.calcsize('P') == 8"
                        if ($LASTEXITCODE -eq 0) { $Python = $Candidate; break }
                    }
                }
            }
            if (Test-Path $Python) { break }
        }
    }
    if (-not (Test-Path $Python)) {
        $Installer = Join-Path $BuildRoot 'python-installer.exe'
        Download 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe' $Installer
        if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash -ne '5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190') {
            throw 'Python download checksum does not match.'
        }
        $Process = Start-Process -FilePath $Installer -ArgumentList @('/quiet', 'InstallAllUsers=0', "TargetDir=$PythonDir", 'Include_launcher=0', 'Include_test=0', 'PrependPath=0', 'Shortcuts=0', 'Include_tcltk=1') -Wait -PassThru
        if ($Process.ExitCode -ne 0) { throw "Python installation failed (exit $($Process.ExitCode))." }
    }
    Run $Python @('-c', "import sys, struct, tkinter; assert sys.version_info[:2] in ((3, 12), (3, 13)) and struct.calcsize('P') == 8")

    Write-Host '[3/6] Copying source and building the ROM'
    $BuildSource = Join-Path $Msys 'soullink-source'
    # The Makefiles require a path without spaces; the original source stays untouched.
    # Exclude private data and output, including files when running from an existing checkout.
    & robocopy.exe $Source $BuildSource /MIR /XJ /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD .git build dist release players .launcher-venv __pycache__ /XF *.sqlite3* *.db *.db-shm *.db-wal *.player.lua .env .env.*
    if ($LASTEXITCODE -ge 8) { throw "Source copy failed (robocopy exit $LASTEXITCODE)." }
    Bash 'bash /soullink-source/soullink/setup/build.sh'

    Write-Host '[4/6] Building and checking SoulLink.exe'
    $Venv = Join-Path $BuildRoot 'launcher-venv'
    Run $Python @('-m', 'venv', $Venv)
    $Builder = Join-Path $Venv 'Scripts\python.exe'
    Push-Location $BuildSource
    try {
        Run $Builder @('-m', 'pip', 'install', '-r', 'soullink\launcher\requirements-build.txt')
        Run $Builder @('-m', 'soullink.tools.build_launcher')

        Write-Host '[5/6] Downloading mGBA with script support'
        $MgbaArchive = Join-Path $BuildRoot 'mgba.7z'
        Download 'https://s3.amazonaws.com/mgba/mGBA-build-latest-win64.7z' $MgbaArchive
        $MgbaDir = Join-Path $BuildRoot 'mgba'
        if (Test-Path $MgbaDir) { Remove-Item -LiteralPath $MgbaDir -Recurse -Force }
        New-Item -ItemType Directory -Path $MgbaDir | Out-Null
        Run "$Msys\usr\bin\bsdtar.exe" @('-xf', $MgbaArchive, '-C', $MgbaDir)

        Write-Host '[6/6] Installing game, emulator, and desktop shortcut'
        $InstallArgs = @('-m', 'soullink.tools.install', '--package', 'dist', '--launcher', 'release\launcher', '--emulator-directory', $MgbaDir, '--root', $InstallRoot)
        if ($NoLaunch) { $InstallArgs += '--no-launch' }
        if ($NoShortcut) { $InstallArgs += '--no-shortcut' }
        Run $Builder $InstallArgs
    } finally {
        Pop-Location
    }
    Write-Host "Setup complete. Installed under $InstallRoot"
    Stop-Transcript | Out-Null
    $Lock.Dispose()
    exit 0
} catch {
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    if ($Log) { Write-Host "Log: $Log. Run Setup-SoulLink.cmd again to retry." }
    try { Stop-Transcript | Out-Null } catch { }
    if ($Lock) { $Lock.Dispose() }
    exit 1
}
