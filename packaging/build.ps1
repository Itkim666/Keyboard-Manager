param(
    [string]$Python = '.buildenv/Scripts/python.exe',
    [string]$Nsis = '.build-tools/Bin/makensis.exe',
    [string]$Engine = '.build-tools/patched-engine',
    [switch]$SkipInstaller
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
$enginePath = (Resolve-Path $Engine).Path
$pythonPath = (Resolve-Path $Python).Path
$nsisPath = (Resolve-Path $Nsis).Path
$version = & $pythonPath -c "import runpy; print(runpy.run_path('src/keyboard_shortcuts/__init__.py')['VERSION'])"
if ($LASTEXITCODE -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid application version.' }
$dist = [IO.Path]::GetFullPath("dist/$version")
$buildDir = [IO.Path]::GetFullPath(".build-tools/package-$version")
$application = Join-Path $dist 'Keyboard Manager'
$models = (Resolve-Path '.build-tools/capture-models').Path
foreach ($pair in @('zh_en','en_zh')) {
    if (!(Test-Path "$models/$pair/model/model.bin") -or !(Test-Path "$models/$pair/sentencepiece.model")) {
        throw 'Run tools/fetch-capture-models.py before packaging.'
    }
}
$runtime = Join-Path $enginePath 'keymapper.exe'
if (!(Test-Path $runtime)) { throw 'Run tools/build-engine.ps1 first.' }
$nllbFiles = @('model.bin','config.json','shared_vocabulary.json','sentencepiece.bpe.model','LICENSE')
$ocrFiles = @('PP-OCRv6_rec_small.onnx','arabic_PP-OCRv5_rec_mobile.onnx',
              'cyrillic_PP-OCRv5_rec_mobile.onnx','devanagari_PP-OCRv5_rec_mobile.onnx',
              'el_PP-OCRv5_rec_mobile.onnx','korean_PP-OCRv5_rec_mobile.onnx','th_PP-OCRv5_rec_mobile.onnx')
$modelAssets = @($nllbFiles | ForEach-Object { "nllb/$_" }) +
               @($ocrFiles | ForEach-Object { "multilingual-ocr/$_" }) + 'multilingual-sources.txt'
foreach ($entry in $modelAssets) {
    if (!(Test-Path "$models/$entry")) { throw 'Run tools/fetch-multilingual-models.py before packaging.' }
}
New-Item -ItemType Directory -Force $dist, $buildDir | Out-Null

$options = @(
    '--noconfirm', '--windowed', '--icon', (Resolve-Path 'packaging/keyboard-manager.ico').Path,
    '--name', 'Keyboard Manager', '--distpath', $dist, '--workpath', $buildDir, '--specpath', $buildDir,
    '--paths', (Join-Path (Get-Location) 'src'), '--add-binary', "$enginePath/*.exe;keymapper",
    '--add-data', "$models/zh_en;capture-models/zh_en",
    '--add-data', "$models/en_zh;capture-models/en_zh",
    '--add-data', "$models/sources.txt;capture-models",
    '--add-data', "$models/multilingual-sources.txt;capture-models",
    '--add-data', "$(Join-Path (Get-Location) 'src/keyboard_shortcuts/capture_manga.py');keyboard_shortcuts",
    '--collect-data', 'rapidocr_onnxruntime',
    '--collect-data', 'langdetect', '--collect-data', 'py3langid',
    '--copy-metadata', 'py3langid', '--copy-metadata', 'langdetect',
    '--collect-binaries', 'ctranslate2', '--collect-binaries', 'onnxruntime',
    '--exclude-module', 'PyQt5.QtQml', '--exclude-module', 'PyQt5.QtQuick'
)
foreach ($name in $nllbFiles) {
    $options += '--add-data', "$models/nllb/$name;capture-models/nllb"
}
foreach ($name in $ocrFiles) {
    $options += '--add-data', "$models/multilingual-ocr/$name;capture-models/multilingual-ocr"
}
& $pythonPath -m PyInstaller @options src/launch.py
if ($LASTEXITCODE) { throw 'PyInstaller build failed.' }

# Qt loads its local C++ runtime before the OCR/translation extensions.
$runtimeFolder = Join-Path $application '_internal'
$qtBin = Join-Path $runtimeFolder 'PyQt5/Qt5/bin'
foreach ($dll in @('msvcp140.dll','msvcp140_1.dll','vcruntime140.dll','vcruntime140_1.dll')) {
    $modern = Get-Item -LiteralPath (Join-Path $runtimeFolder $dll)
    if ($modern.VersionInfo.FileMajorPart -ne 14 -or $modern.VersionInfo.FileMinorPart -lt 40) {
        throw "The build needs a Visual C++ runtime 14.40 or newer ($dll)."
    }
    Copy-Item -LiteralPath $modern.FullName -Destination (Join-Path $qtBin $dll) -Force
}

Copy-Item packaging/使用说明.txt -Destination $application
Copy-Item "$enginePath/LICENSE" -Destination (Join-Path $application 'GPL-3.0.txt')
$licenseDir = Join-Path $application 'Licenses'
New-Item -ItemType Directory -Force $licenseDir | Out-Null
$sitePackages = & $pythonPath -c "import sysconfig; print(sysconfig.get_path('purelib'))"
Get-ChildItem -LiteralPath $sitePackages -Directory -Filter '*.dist-info' | ForEach-Object {
    $metadata = $_
    $files = @(Get-ChildItem $metadata.FullName -Recurse -File | Where-Object { $_.Name -match '^(LICENSE|COPYING|NOTICE)' })
    foreach ($file in $files) {
        $name = "$($metadata.BaseName)-$($file.Name)"
        Copy-Item $file.FullName -Destination (Join-Path $licenseDir $name)
    }
}
Compress-Archive -LiteralPath $application -DestinationPath (Join-Path $dist "Keyboard-Manager-Portable-$version.zip") -Force
if (!$SkipInstaller) {
    & $nsisPath "/DAPPDIR=$application" "/DOUTDIR=$dist" "/DPRODUCT_VERSION=$version" 'packaging/setup.nsi'
    if ($LASTEXITCODE) { throw 'Installer build failed.' }
}

$sourceStage = Join-Path $dist 'Keyboard-Manager-Source'
New-Item -ItemType Directory -Force $sourceStage | Out-Null
Copy-Item src,tools,tests,packaging,pytest.ini -Destination $sourceStage -Recurse -Force
$sourceRepo = (Resolve-Path keymapper-upstream).Path
git -c "safe.directory=$($sourceRepo.Replace('\','/'))" -C $sourceRepo archive --format=zip --prefix=keymapper-upstream/ --output="$sourceStage/keymapper-5.8.1.zip" 5.8.1
if ($LASTEXITCODE) { throw 'Could not package keymapper source.' }
Compress-Archive -LiteralPath $sourceStage -DestinationPath (Join-Path $dist "Keyboard-Manager-$version-Source.zip") -Force
Get-ChildItem $dist -File | Select-Object Name, Length


