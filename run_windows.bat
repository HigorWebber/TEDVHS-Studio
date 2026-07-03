@echo off
REM Script para abrir TEDVHS Studio no Windows
REM Cria venv se nao existir, ativa, instala dependencias e executa

setlocal enabledelayedexpansion

echo ========================================
echo TEDVHS Studio - Executor do App
echo ========================================
echo.

REM Verificar se Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo Instale Python 3.9+ e adicione ao PATH
    pause
    exit /b 1
)

echo [OK] Python encontrado

REM Verificar se .venv existe
if not exist ".venv" (
    echo.
    echo [INFO] Criando ambiente virtual...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar ambiente virtual
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado
) else (
    echo [OK] Ambiente virtual ja existe
)

echo.
echo [INFO] Ativando ambiente virtual...
call .venv\Scripts\activate.bat

REM Verificar se pip consegue funcionar
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] pip nao funcionou apos ativar venv
    pause
    exit /b 1
)
echo [OK] Pip ativado

REM Instalar dependencias
if exist "requirements.txt" (
    echo.
    echo [INFO] Instalando dependencias de requirements.txt...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependencias
        pause
        exit /b 1
    )
    echo [OK] Dependencias instaladas
) else (
    echo.
    echo [INFO] requirements.txt nao encontrado
    echo [INFO] Instalando dependencias padrao...
    pip install "PySide6>=6.5.0"
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar PySide6
        pause
        exit /b 1
    )
    echo [OK] Dependencias instaladas
)

REM Executar aplicacao
echo.
echo [INFO] Iniciando TEDVHS Studio...
echo ========================================
echo.

python app.py
set APP_EXIT_CODE=!errorlevel!

echo.
echo ========================================
if !APP_EXIT_CODE! equ 0 (
    echo [OK] Aplicacao fechada normalmente
) else (
    echo [ERRO] Aplicacao saiu com erro (codigo: !APP_EXIT_CODE!)
)

pause
exit /b !APP_EXIT_CODE!
