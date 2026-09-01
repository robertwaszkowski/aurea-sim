#!/bin/bash

echo "=========================================="
echo "      AureaSim Startup Environment"
echo "=========================================="

# Check if running in container / Code Ocean
IS_CONTAINER=false
if [ -f /.dockerenv ] || [ -d /codeocean ]; then
    IS_CONTAINER=true
fi

if [ "$IS_CONTAINER" = "true" ]; then
    echo "[INFO] Container/CodeOcean environment detected. Skipping Conda environment isolation..."
else
    # 1. Find Conda
    CONDA_ACTIVATE=""

    if [ -f "$HOME/miniconda3/bin/activate" ]; then
        CONDA_ACTIVATE="$HOME/miniconda3/bin/activate"
    elif [ -f "$HOME/anaconda3/bin/activate" ]; then
        CONDA_ACTIVATE="$HOME/anaconda3/bin/activate"
    elif [ -f "/opt/anaconda3/bin/activate" ]; then
        CONDA_ACTIVATE="/opt/anaconda3/bin/activate"
    elif [ -f "/opt/miniconda3/bin/activate" ]; then
        CONDA_ACTIVATE="/opt/miniconda3/bin/activate"
    elif command -v conda &> /dev/null; then
        CONDA_ACTIVATE="conda"
    fi

    if [ -z "$CONDA_ACTIVATE" ]; then
        echo "[WARNING] Conda is not installed or not found."
        read -p "Would you like to automatically download and install Miniconda? (Y/N): " INSTALL_CONDA
        if [[ "$INSTALL_CONDA" =~ ^[Yy]$ ]]; then
            echo "Downloading Miniconda..."
            OS="$(uname -s)"
            ARCH="$(uname -m)"
            if [ "$OS" = "Darwin" ]; then
                if [ "$ARCH" = "arm64" ]; then
                    INSTALLER="Miniconda3-latest-MacOSX-arm64.sh"
                else
                    INSTALLER="Miniconda3-latest-MacOSX-x86_64.sh"
                fi
            else
                if [ "$ARCH" = "aarch64" ]; then
                    INSTALLER="Miniconda3-latest-Linux-aarch64.sh"
                else
                    INSTALLER="Miniconda3-latest-Linux-x86_64.sh"
                fi
            fi
            
            curl -o "/tmp/$INSTALLER" "https://repo.anaconda.com/miniconda/$INSTALLER"
            echo "Installing Miniconda..."
            bash "/tmp/$INSTALLER" -b -p "$HOME/miniconda3"
            CONDA_ACTIVATE="$HOME/miniconda3/bin/activate"
        else
            echo "[ERROR] Conda is required to run this application. Exiting..."
            exit 1
        fi
    fi

    # 2. Source conda
    if [ "$CONDA_ACTIVATE" = "conda" ]; then
        eval "$(conda shell.bash hook)"
    else
        source "$CONDA_ACTIVATE" base
    fi

    # 3. Check if environment exists
    echo "Checking for aureasim environment..."
    if ! conda env list | grep -q "\baureasim\b"; then
        echo "[INFO] Environment 'aureasim' not found. Creating it now..."
        conda env create -f environment.yml
    fi

    # 4. Activate environment
    conda activate aureasim
fi

# 5. Ask for run mode
echo ""
python -c '
import questionary, sys
custom_style = questionary.Style([
    ("qmark", "fg:ansicyan bold"),
    ("question", "bold"),
    ("pointer", "fg:ansicyan bold"),
    ("highlighted", "fg:ansicyan bold noreverse")
])
choice = questionary.select(
    "Please select the mode you want to run AureaSim in:",
    choices=[
        "Interactive Terminal Wizard (CLI)",
        "Web Dashboard (GUI)"
    ],
    style=custom_style
).ask()
if choice == "Interactive Terminal Wizard (CLI)": sys.exit(1)
elif choice == "Web Dashboard (GUI)": sys.exit(2)
else: sys.exit(0)
'
RUN_MODE=$?

if [ "$RUN_MODE" -eq 1 ]; then
    echo ""
    echo "Starting Terminal Wizard..."
    python wizard.py
    echo ""
    read -p "Press any key to close..." -n 1 -s
    echo ""
elif [ "$RUN_MODE" -eq 2 ]; then
    echo ""
    echo "Starting Web Dashboard (GUI)..."
    
    # Set trap to kill backend if script exits
    trap "kill 0" EXIT
    
    echo "- Launching Backend Server in background..."
    if ! python -c "import multipart" 2>/dev/null; then
        echo "  Installing python-multipart..."
        pip install python-multipart -q
    fi
    if ! python -c "import openpyxl" 2>/dev/null; then
        echo "  Installing openpyxl..."
        pip install openpyxl -q
    fi

    echo "- Checking Frontend Dependencies..."
    cd frontend
    if [ ! -d "node_modules" ] || [ ! -f "node_modules/.bin/vite" ]; then
        echo "  Installing NPM dependencies..."
        npm install --silent
    fi

    if [ -f /.dockerenv ] || [ -d /codeocean ]; then
        echo "- Building Frontend for production (Code Ocean mode)..."
        if [ -n "$CO_COMPUTATION_ID" ]; then
            export VITE_BASE="/cw/${CO_COMPUTATION_ID}/proxy/8000/"
            echo "  Using base path: $VITE_BASE"
        fi
        npm run build
        if [ $? -ne 0 ]; then
            echo "[ERROR] Frontend build failed. Aborting."
            exit 1
        fi
        cd ..
        echo ""
        echo "=========================================================================="
        echo " 🌟 AureaSim Web Dashboard is now running!"
        echo " 👉 Click 'Open in Browser' for port 8000 in the VS Code Ports panel"
        echo "=========================================================================="
        echo ""
        python server.py
    else
        cd ..
        VITE_LOG="/tmp/aureasim_vite_$$.log"
        echo "- Launching Frontend Server..."
        (
            sleep 4
            echo ""
            echo "=========================================================================="
            echo " 🌟 AureaSim Web Dashboard is now running!"
            VITE_URL=$(grep -o "http://localhost:[0-9]*/" "$VITE_LOG" 2>/dev/null | head -n 1)
            if [ -n "$VITE_URL" ]; then
                ESC=$'\033'
                LINK="${ESC}]8;;${VITE_URL}${ESC}\\${ESC}[4;34m${VITE_URL}${ESC}[0m${ESC}]8;;${ESC}\\"
                echo " 👉 Please open your browser and navigate to: $LINK"
            else
                echo " 👉 Please open your browser and navigate to the Local VITE URL above"
            fi
            echo "=========================================================================="
            echo ""
            rm -f "$VITE_LOG"
        ) &
        cd frontend && npm run dev 2>&1 | tee "$VITE_LOG"
    fi
else
    echo "Cancelled."
    exit 0
fi
