@echo off
REM Script para executar testes do TEDVHS Studio no Windows
REM Cria venv se nao existir, ativa, instala dependencias, testes e cobertura

setlocal enabledelayedexpansion

echo ========================================
echo TEDVHS Studio - Executor de Testes
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

REM Verificar se diretorio de testes existe
if not exist "tests" (
    echo.
    echo [ERRO] Diretorio 'tests' nao encontrado
    echo [ERRO] Por favor, crie a pasta 'tests' com os arquivos de teste
    pause
    exit /b 1
)
echo [OK] Diretorio de testes encontrado

REM Instalar ferramentas de teste
echo.
echo [INFO] Verificando ferramentas de teste...
pip install "pytest>=7.0.0" "pytest-cov>=4.0.0"
if errorlevel 1 (
    echo [ERRO] Falha ao instalar ferramentas de teste
    pause
    exit /b 1
)
echo [OK] Ferramentas de teste instaladas

REM Executar testes
echo.
echo [INFO] Executando testes com pytest...
echo ========================================
echo.

pytest tests/ -v --tb=short
set PYTEST_EXIT_CODE=!errorlevel!

echo.
echo ========================================

REM Gerar relatorio de cobertura
echo [INFO] Gerando relatorio de cobertura...
echo ========================================
echo.

pytest tests/ ^
  --cov=infrastructure.persistence ^
  --cov=application.media ^
  --cov=presentation ^
  --cov-report=term-missing ^
  --cov-report=html:htmlcov

set COVERAGE_EXIT_CODE=!errorlevel!

REM Mostrar resultado
echo.
echo ========================================

REM Verificar se ambos passaram
set FINAL_EXIT_CODE=0

if !PYTEST_EXIT_CODE! equ 0 (
    echo [OK] Testes executados com sucesso
) else (
    echo [ERRO] Alguns testes falharam (codigo: !PYTEST_EXIT_CODE!)
    set FINAL_EXIT_CODE=1
)

if !COVERAGE_EXIT_CODE! equ 0 (
    echo [OK] Cobertura gerada com sucesso
    echo [INFO] Abra htmlcov\index.html no navegador para ver o relatorio
) else (
    echo [ERRO] Cobertura nao foi gerada (codigo: !COVERAGE_EXIT_CODE!)
    set FINAL_EXIT_CODE=1
)

echo ========================================
echo.

pause
exit /b !FINAL_EXIT_CODE!
