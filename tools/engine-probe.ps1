$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$runtime = Join-Path $root 'keymapper-runtime/keymapper-5.8.1-Windows-x86_64'
$fixture = Join-Path $root 'tests/engine/fixtures/directions.conf'
$process = Start-Process -FilePath (Join-Path $runtime 'keymapper.exe') -ArgumentList "--check -c `"$fixture`"" -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "keymapper configuration rejected ($($process.ExitCode))" }
Write-Output 'keymapper 5.8.1 accepted the direction fixture.'
