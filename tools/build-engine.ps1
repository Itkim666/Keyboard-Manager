param([string]$Output = '.build-tools/patched-engine')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$out = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force $out | Out-Null
$stage = Join-Path $env:TEMP ('keyboard-manager-build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $stage | Out-Null
$source = Join-Path $root 'keymapper-upstream'
$archive = Join-Path $stage 'source.zip'
git -c "safe.directory=$($source.Replace('\','/'))" -C $source archive --format=zip --output=$archive 5.8.1
if ($LASTEXITCODE) { throw 'Could not extract the pinned keymapper tag.' }
Expand-Archive $archive (Join-Path $stage 'source')
$source = Join-Path $stage 'source'
python (Join-Path $PSScriptRoot 'patch_engine.py') $source
if ($LASTEXITCODE) { throw 'keymapper patch failed.' }
Push-Location $source
try {
    '"5.8.1-km1"' | Set-Content -Encoding ascii src/common/_version.h
    $common = @('src/common/Connection.cpp','src/common/Host.cpp','src/common/output.cpp','src/common/windows/win.cpp')
    $config = @('src/config/ParseConfig.cpp','src/config/ParseKeySequence.cpp','src/config/get_key_name.cpp')
    $runtime = @('src/runtime/MatchKeySequence.cpp','src/runtime/Stage.cpp','src/runtime/MultiStage.cpp')
    $server = @('src/server/ClientPort.cpp','src/server/Settings.cpp','src/server/ServerState.cpp','src/server/windows/Devices.cpp','src/server/windows/Hooks.cpp','src/server/windows/main.cpp')
    $client = @('src/client/ConfigFile.cpp','src/client/ServerPort.cpp','src/client/Settings.cpp','src/client/ControlPort.cpp','src/client/ClientState.cpp','src/client/windows/FocusedWindow.cpp','src/client/windows/StringTyper.cpp','src/client/windows/execute_terminal_command.cpp','src/client/windows/main.cpp')
    $control = @('src/control/ClientPort.cpp','src/control/Settings.cpp','src/control/main.cpp','src/control/windows/expand_command.cpp')
    $flags = @('-std=c++17','-O1','-DNDEBUG','-static','-municode','-I','src','-include','utility','-include','cstring')
    g++ @flags -mwindows @server @common @runtime -o keymapperd.exe -lws2_32 -lcfgmgr32 -lhid -luser32 -luuid
    if ($LASTEXITCODE) { throw 'keymapperd build failed.' }
    g++ @flags -mwindows @client @common @config -o keymapper.exe -lwtsapi32 -lws2_32 -lole32 -luuid
    if ($LASTEXITCODE) { throw 'keymapper build failed.' }
    g++ @flags @control @common -o keymapperctl.exe -lws2_32
    if ($LASTEXITCODE) { throw 'keymapperctl build failed.' }
    Copy-Item keymapper.exe,keymapperd.exe,keymapperctl.exe,LICENSE -Destination $out
} finally {
    Pop-Location
}
Write-Output "Patched engine in $out"



