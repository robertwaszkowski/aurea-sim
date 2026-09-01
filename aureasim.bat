@echo off
setlocal EnableDelayedExpansion

echo ==========================================
echo       AureaSim Startup Environment
echo ==========================================

REM 1. Find Conda
set "CONDA_ACTIVATE="

if exist "%USERPROFILE%\miniconda3\Scripts\activate.bat" (
    set "CONDA_ACTIVATE=%USERPROFILE%\miniconda3\Scripts\activate.bat"
) else if exist "%USERPROFILE%\Anaconda3\Scripts\activate.bat" (
    set "CONDA_ACTIVATE=%USERPROFILE%\Anaconda3\Scripts\activate.bat"
) else if exist "%ALLUSERSPROFILE%\Miniconda3\Scripts\activate.bat" (
    set "CONDA_ACTIVATE=%ALLUSERSPROFILE%\Miniconda3\Scripts\activate.bat"
) else if exist "%ALLUSERSPROFILE%\Anaconda3\Scripts\activate.bat" (
    set "CONDA_ACTIVATE=%ALLUSERSPROFILE%\Anaconda3\Scripts\activate.bat"
) else (
    REM Check if conda is in PATH
    where conda >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "CONDA_ACTIVATE=conda"
    )
)

if "%CONDA_ACTIVATE%"=="" (
    echo [WARNING] Conda is not installed or not found.
    set /p INSTALL_CONDA="Would you like to automatically download and install Miniconda? (Y/N): "
    if /I "!INSTALL_CONDA!"=="Y" (
        echo Downloading Miniconda...
        powershell -Command "Invoke-WebRequest -Uri https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe -OutFile %TEMP%\miniconda_installer.exe"
        echo Installing Miniconda...
        start /wait "" "%TEMP%\miniconda_installer.exe" /InstallationType=JustMe /RegisterPython=0 /S /D="%USERPROFILE%\miniconda3"
        set "CONDA_ACTIVATE=%USERPROFILE%\miniconda3\Scripts\activate.bat"
    ) else (
        echo [ERROR] Conda is required to run this application. Exiting...
        pause
        exit /b 1
    )
)

REM 2. Activate base Conda to run conda commands reliably
if "%CONDA_ACTIVATE%"=="conda" (
    REM We rely on conda being in PATH
) else (
    call "%CONDA_ACTIVATE%" base
)

REM 3. Check if aureasim environment exists
echo Checking for aureasim environment...
call conda env list | findstr /R /C:"\baureasim\b" >nul
if !ERRORLEVEL! NEQ 0 (
    echo [INFO] Environment 'aureasim' not found. Creating it now...
    call conda env create -f environment.yml
)

REM 4. Activate environment
if "%CONDA_ACTIVATE%"=="conda" (
    call conda activate aureasim
) else (
    call "%CONDA_ACTIVATE%" aureasim
)

REM 5. Ask for run mode
echo.
python -c "import questionary, sys; custom_style = questionary.Style([('qmark', 'fg:ansicyan bold'), ('question', 'bold'), ('pointer', 'fg:ansicyan bold'), ('highlighted', 'fg:ansicyan bold noreverse')]); choice = questionary.select('Please select the mode you want to run AureaSim in:', choices=['Interactive Terminal Wizard (CLI)', 'Web Dashboard (GUI)'], style=custom_style).ask(); sys.exit(1 if choice == 'Interactive Terminal Wizard (CLI)' else 2 if choice == 'Web Dashboard (GUI)' else 0)"
set RUN_MODE=!ERRORLEVEL!

if "!RUN_MODE!"=="1" (
    echo.
    echo Starting Terminal Wizard...
    python wizard.py
    echo.
    pause
) else if "!RUN_MODE!"=="2" (
    echo.
    echo Starting Web Dashboard (GUI)...
    echo - Launching Backend Server...
    start "AureaSim Backend" cmd /k "python server.py"
    
    echo - Checking Frontend Dependencies...
    cd frontend
    if not exist "node_modules\" (
        echo Installing NPM dependencies...
        call npm install
    )
    
    echo - Launching Frontend Server...
    start "AureaSim Frontend" cmd /k "npm run dev"
) else (
    echo Cancelled.
    exit /b 0
)
