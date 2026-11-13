Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WordFunc.nsh"

!ifndef PRODUCT_VERSION
    !error "Pass PRODUCT_VERSION from packaging/build.ps1"
!endif
!define INSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager"
Var ExistingInstall

Name "Keyboard Manager"
OutFile "${OUTDIR}\Keyboard-Manager-Setup-${PRODUCT_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Keyboard Manager"
InstallDirRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "${PRODUCT_VERSION}.0"
VIAddVersionKey "ProductName" "Keyboard Manager"
VIAddVersionKey "FileDescription" "Keyboard Manager 安装程序"
VIAddVersionKey "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey "LegalCopyright" "Keyboard Manager contributors"
!define MUI_ICON "keyboard-manager.ico"
!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipExistingDirectoryPage
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
    ${IfNot} ${IsNativeAMD64}
        MessageBox MB_ICONSTOP "Keyboard Manager 需要 64 位 Windows。"
        Abort
    ${EndIf}
    ReadRegStr $ExistingInstall HKCU "${INSTALL_KEY}" "InstallLocation"
    ${If} $ExistingInstall == ""
        StrCpy $ExistingInstall "$LOCALAPPDATA\Programs\Keyboard Manager"
    ${EndIf}
    ReadRegStr $0 HKCU "${INSTALL_KEY}" "UninstallString"
    StrCmp $0 '$\"$ExistingInstall\Uninstall.exe$\"' 0 fresh_install
    IfFileExists "$ExistingInstall\Keyboard Manager.exe" 0 fresh_install
    ReadRegStr $1 HKCU "${INSTALL_KEY}" "DisplayVersion"
    ${If} $1 == ""
        MessageBox MB_ICONSTOP "无法确认已安装的 Keyboard Manager 版本。" /SD IDOK
        Abort
    ${EndIf}
    StrCpy $INSTDIR $ExistingInstall
    ${VersionCompare} "$1" "${PRODUCT_VERSION}" $2
    ${If} $2 == 1
        MessageBox MB_ICONSTOP "已安装较新版本 $1，已停止安装。" /SD IDOK
        Abort
    ${ElseIf} $2 == 0
        MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON2 "当前已经安装此版本（$1）。是否修复安装？" /SD IDNO IDYES confirmed
    ${Else}
        MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON2 "检测到已安装版本 $1。是否原位升级到 ${PRODUCT_VERSION}？" /SD IDNO IDYES confirmed
    ${EndIf}
    Abort
fresh_install:
    StrCpy $ExistingInstall ""
confirmed:
FunctionEnd

Function SkipExistingDirectoryPage
    ${If} $ExistingInstall != ""
        Abort
    ${EndIf}
FunctionEnd

Function .onVerifyInstDir
    ; The uninstaller owns these trees. Refuse to take over an unrelated folder.
    ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager" "UninstallString"
    StrCmp $0 '$\"$INSTDIR\Uninstall.exe$\"' 0 check_empty
    IfFileExists "$INSTDIR\Uninstall.exe" done
    IfFileExists "$INSTDIR\Keyboard Manager.exe" done
check_empty:
    StrCmp $INSTDIR "$LOCALAPPDATA\Keyboard Manager" reject
    IfFileExists "$INSTDIR\*.*" 0 done
    FindFirst $0 $1 "$INSTDIR\*.*"
check_entry:
    StrCmp $1 "" close_search
    StrCmp $1 "." next_entry
    StrCmp $1 ".." next_entry
    FindClose $0
    Goto reject
next_entry:
    FindNext $0 $1
    Goto check_entry
close_search:
    FindClose $0
done:
    Return
reject:
    Abort
FunctionEnd

Section "Keyboard Manager"
    Call .onVerifyInstDir
    ; Check before extracting any files. Never terminate the running program.
    IfFileExists "$INSTDIR\Keyboard Manager.exe" 0 copy_files
    System::Call 'kernel32::CreateFileW(w "$INSTDIR\Keyboard Manager.exe", i 0x40000000, i 0, p 0, i 3, i 0x80, p 0) p .r0'
    ${If} $0 == -1
        MessageBox MB_ICONSTOP "无法写入 Keyboard Manager.exe。请从系统托盘退出 Keyboard Manager，确认安装目录可写后重新运行安装程序。" /SD IDOK
        Abort
    ${EndIf}
    System::Call 'kernel32::CloseHandle(p r0)'
copy_files:
    SetOutPath "$INSTDIR"
    File /r "${APPDIR}\*.*"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    CreateDirectory "$SMPROGRAMS\Keyboard Manager"
    CreateShortcut "$SMPROGRAMS\Keyboard Manager\Keyboard Manager.lnk" "$INSTDIR\Keyboard Manager.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager" "DisplayName" "Keyboard Manager"
    WriteRegStr HKCU "${INSTALL_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager" "DisplayIcon" "$INSTDIR\Keyboard Manager.exe"
SectionEnd

Section "Uninstall"
    Delete "$SMPROGRAMS\Keyboard Manager\Keyboard Manager.lnk"
    RMDir "$SMPROGRAMS\Keyboard Manager"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KeyboardManager"
    ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Keyboard Manager"
    StrCmp $0 '$\"$INSTDIR\Keyboard Manager.exe$\" --tray' 0 +2
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Keyboard Manager"
    Delete "$INSTDIR\Keyboard Manager.exe"
    Delete "$INSTDIR\Uninstall.exe"
    Delete "$INSTDIR\使用说明.txt"
    Delete "$INSTDIR\GPL-3.0.txt"
    RMDir /r "$INSTDIR\Licenses"
    RMDir /r "$INSTDIR\_internal"
    RMDir "$INSTDIR"
SectionEnd





