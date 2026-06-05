@echo off
:: build.bat — Compile cronet_helper.dll (MSVC cl.exe)
setlocal

set SRC=%~dp0cronet_helper_dll.cpp
set OUT=%~dp0cronet_helper.dll
set VCVARS=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat

where cl.exe >nul 2>&1
if %errorlevel% equ 0 goto :build

if not exist "%VCVARS%" (
    echo [-] vcvarsall.bat not found at: %VCVARS%
    echo     Please open a "Developer Command Prompt for VS" and re-run this script.
    exit /b 1
)
echo [*] Initializing MSVC env...
call "%VCVARS%" x64 >nul

:build
echo [*] Compiling %SRC%
cl.exe /O2 /std:c++17 /EHsc /MD /LD "%SRC%" /Fe:"%OUT%" /link Advapi32.lib /INCREMENTAL:NO

if %errorlevel% neq 0 (
    echo [-] Build FAILED.
    exit /b %errorlevel%
)
echo [+] Build succeeded: %OUT%
endlocal
