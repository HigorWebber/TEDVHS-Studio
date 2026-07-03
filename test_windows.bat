@echo off
REM Script para executar testes do TEDVHS Studio no Windows
REM Cria venv se não existir, ativa, instala dependências, testes e cobertura

setlocal enabledelayedexpansion

echo ========================================
echo TEDVHS Studio - Executor de Testes
echo ========================================
echo.

REM Verificar se Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python não encontrado!
    echo Instale Python 3.9+ e adicione ao PATH
    pause
    exit /b 1
)

echo [✓] Python encontrado

REM Verificar se .venv existe
if not exist ".venv" (
    echo.
    echo [*] Criando ambiente virtual...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar ambiente virtual
        pause
        exit /b 1
    )
    echo [✓] Ambiente virtual criado
) else (
    echo [✓] Ambiente virtual já existe
)

echo.
echo [*] Ativando ambiente virtual...
call .venv\Scripts\activate.bat

REM Verificar se pip é capaz de instalar
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] pip não funcionou após ativar venv
    pause
    exit /b 1
)
echo [✓] Pip ativado

REM Instalar dependências
if exist "requirements.txt" (
    echo.
    echo [*] Instalando dependências de requirements.txt...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependências
        pause
        exit /b 1
    )
    echo [✓] Dependências instaladas
) else (
    echo.
    echo [*] requirements.txt não encontrado
    echo [*] Instalando dependências padrão...
    pip install PySide6>=6.5.0
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar PySide6
        pause
        exit /b 1
    )
    echo [✓] Dependências instaladas
)

REM Instalar ferramentas de teste
echo.
echo [*] Verificando ferramentas de teste...
pip install pytest>=7.0.0 pytest-cov>=4.0.0
if errorlevel 1 (
    echo [ERRO] Falha ao instalar ferramentas de teste
    pause
    exit /b 1
)
echo [✓] Ferramentas de teste instaladas

REM Verificar se diretório de testes existe
if not exist "tests" (
    echo.
    echo [AVISO] Diretório 'tests' não encontrado
    echo [*] Criando diretório vazio de testes...
    mkdir tests
    echo. > tests\__init__.py
)

REM Executar testes
echo.
echo [*] Executando testes com pytest...
echo ========================================
echo.

pytest tests/ -v --tb=short
set PYTEST_EXIT_CODE=!errorlevel!

REM Gerar relatório de cobertura
echo.
echo ========================================
echo [*] Gerando relatório de cobertura...
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
if !PYTEST_EXIT_CODE! equ 0 (
    echo [✓] Testes executados com sucesso
) else (
    echo [ERRO] Alguns testes falharam (código: !PYTEST_EXIT_CODE!)
)

if !COVERAGE_EXIT_CODE! equ 0 (
    echo [✓] Cobertura gerada com sucesso
    echo [*] Abra htmlcov\index.html no navegador para ver o relatório
) else (
    echo [AVISO] Cobertura não foi gerada (código: !COVERAGE_EXIT_CODE!)
)

echo ========================================
echo.

pause
exit /b !PYTEST_EXIT_CODE!
