# Guia de Validacao Sprint 2.5 - Media Library UI

**Status**: Sprint 2.5 implementada, mas aguardando validacao real no ambiente local.

Este documento fornece instrucoes passo a passo para validar a Sprint 2.5 no Windows.

---

## IMPORTANTE: Status Atual

- **Codigo criado**: SIM
- **Integracao com MainWindow**: SIM (necessario validar manualmente)
- **Interface em PT-BR**: SIM (necessario validar manualmente)
- **Testes executados**: NAO - Aguardando execucao local
- **Cobertura medida**: NAO - Aguardando execucao local
- **App aberto manualmente**: NAO - Aguardando execucao local
- **Fluxo end-to-end validado**: NAO - Aguardando execucao local

---

## Requisitos

- Python 3.9+
- Windows 10/11
- Git

---

## Passo 1: Preparar o Ambiente

### 1.1 Clonar/Atualizar o Repositorio

```bash
git clone https://github.com/HigorWebber/TEDVHS-Studio.git
cd TEDVHS-Studio
git checkout feature/sprint-2-5-media-library-ui
```

### 1.2 Executar Scripts Facilitadores (Recomendado)

Use os arquivos `.bat` fornecidos para automatizar tudo:

Para abrir a aplicacao:

```cmd
run_windows.bat
```

Para executar testes:

```cmd
test_windows.bat
```

Os scripts irao:
- Verificar se ambiente virtual existe
- Criar ambiente virtual se necessario
- Ativar ambiente virtual
- Instalar dependencias
- Executar a tarefa (app ou testes)
- Manter terminal aberto em caso de erro

---

## Passo 2: Configuracao Manual (Alternativa)

Se preferir nao usar os scripts `.bat`, siga este passo.

### 2.1 Criar Ambiente Virtual

PowerShell:

```powershell
python -m venv .venv
.\.
venv\Scripts\Activate.ps1
```

CMD:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### 2.2 Instalar Dependencias

```cmd
pip install -r requirements.txt
```

Se `requirements.txt` nao existir, instale manualmente:

```cmd
pip install "PySide6>=6.5.0"
```

---

## Passo 3: Validar Imports e Estrutura

### 3.1 Testar Imports Manualmente

Execute os seguintes comandos para validar que todos os modulos podem ser importados:

```cmd
python -c "from ui.views.main_window import MainWindow; print('[OK] MainWindow importado')"
```

```cmd
python -c "from application.media.import_orchestrator import ImportOrchestrator; print('[OK] ImportOrchestrator importado')"
```

```cmd
python -c "from presentation.dialogs.import_library_dialog import ImportLibraryDialog; print('[OK] ImportLibraryDialog importado')"
```

```cmd
python -c "from presentation.views.media_library_view import MediaLibraryView; print('[OK] MediaLibraryView importado')"
```

```cmd
python -c "from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository; print('[OK] SQLiteMediaRepository importado')"
```

Esperado: Se todos os imports funcionarem, voce vera:

```
[OK] MainWindow importado
[OK] ImportOrchestrator importado
[OK] ImportLibraryDialog importado
[OK] MediaLibraryView importado
[OK] SQLiteMediaRepository importado
```

### 3.2 Verificar Arquivos `__init__.py`

Confirme que todos os arquivos `__init__.py` existem:

PowerShell:

```powershell
Get-Item infrastructure\__init__.py
Get-Item infrastructure\persistence\__init__.py
Get-Item infrastructure\media\__init__.py
Get-Item application\__init__.py
Get-Item application\media\__init__.py
Get-Item application\task_management\__init__.py
Get-Item presentation\__init__.py
Get-Item presentation\dialogs\__init__.py
Get-Item presentation\views\__init__.py
```

CMD:

```cmd
dir infrastructure\__init__.py
dir infrastructure\persistence\__init__.py
dir infrastructure\media\__init__.py
dir application\__init__.py
dir application\media\__init__.py
dir application\task_management\__init__.py
dir presentation\__init__.py
dir presentation\dialogs\__init__.py
dir presentation\views\__init__.py
```

Esperado: Todos os arquivos devem existir (sem mensagens de erro).

---

## Passo 4: Executar Testes

### 4.1 Usar Script Automatico (Recomendado)

```cmd
test_windows.bat
```

O script executara automaticamente:
- Testes com pytest
- Medicao de cobertura
- Geracao de relatorio HTML

Nota: A pasta `tests/` deve existir no projeto. Se nao existir, o script falhara (isso e intencional para evitar criar pastas vazias).

### 4.2 Executar Testes Manualmente

Ativar ambiente virtual primeiro:

PowerShell:

```powershell
.\.
venv\Scripts\Activate.ps1
```

CMD:

```cmd
.venv\Scripts\activate.bat
```

Executar testes:

```cmd
pytest tests/ -v --tb=short
```

Esperado: Todos os testes devem passar (ou indicar quantos passaram/falharam).

### 4.3 Medir Cobertura

```cmd
pytest tests/ --cov=infrastructure.persistence --cov=application.media --cov=presentation --cov-report=term-missing --cov-report=html:htmlcov
```

Resultado: Abra `htmlcov/index.html` no navegador para ver cobertura detalhada.

### 4.4 Registrar Resultados

Apos executar, anote:
- Quantos testes passaram
- Quantos falharam
- Percentual de cobertura

---

## Passo 5: Validar Interface

### 5.1 Iniciar Aplicacao

Usar script automatico:

```cmd
run_windows.bat
```

Ou manualmente:

Ativar venv e executar:

```cmd
python app.py
```

### 5.2 Verificar Textos em PT-BR

Quando a janela abrir, procure por:

Menu File:
- [PROCURE] "Importar Biblioteca" (botao/opcao para importar)
- [PROCURE] "Biblioteca de Midia" (aba/secao principal)
- [PROCURE] Textos em portugues

Caixa de Dialogo de Importacao:
- [PROCURE] "Selecionar Pasta"
- [PROCURE] "Importar"
- [PROCURE] "Cancelar"

Status Bar:
- [PROCURE] "Pronto" ou "Processando"

Se encontrar textos em ingles:
- "New Project"
- "Open Project"
- "Exit"

Reporte como erro de traducao.

### 5.3 Teste de Fluxo End-to-End

1. **Abrir aplicacao**: `python app.py` ou `run_windows.bat`

2. **Clicar em "Importar Biblioteca"**:
   - Deve abrir caixa de dialogo
   - Selecionar uma pasta com midia

3. **Verificar se a importacao comeca**:
   - Status bar deve mudar para "Processando"
   - Deve haver feedback visual

4. **Verificar se os dados foram salvos**:
   - Fechar aplicacao
   - Verificar se `tedvhs_studio.db` foi criado na raiz do projeto

PowerShell:

```powershell
Test-Path tedvhs_studio.db
```

CMD:

```cmd
dir tedvhs_studio.db
```

---

## Passo 6: Verificar Banco de Dados

### 6.1 Localizar Banco de Dados

PowerShell:

```powershell
Get-Item tedvhs_studio.db
```

CMD:

```cmd
dir tedvhs_studio.db
```

Esperado: O arquivo deve existir apos a primeira execucao da app.

### 6.2 Inspecionar Tabelas

Execute o seguinte comando Python para listar as tabelas:

```cmd
python -c "import sqlite3; conn = sqlite3.connect('tedvhs_studio.db'); cursor = conn.cursor(); cursor.execute('SELECT name FROM sqlite_master WHERE type=''table'''); tables = cursor.fetchall(); print('Tabelas encontradas:'); [print(f'  - {table[0]}') for table in tables]"
```

Esperado:

```
Tabelas encontradas:
  - import_sessions
  - media_files
```

### 6.3 Verificar Dados Importados

Para verificar quantos arquivos foram importados:

```cmd
python -c "import sqlite3; conn = sqlite3.connect('tedvhs_studio.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM media_files'); count = cursor.fetchone()[0]; print(f'Total de arquivos importados: {count}')"
```

### 6.4 Entender o Schema

O banco de dados possui as seguintes tabelas:

**import_sessions** - Rastreia sessoes de importacao:
- `session_id`: ID unico da sessao
- `folder_path`: Pasta importada
- `started_at`: Data/hora de inicio
- `completed_at`: Data/hora de conclusao
- `status`: 'IN_PROGRESS', 'COMPLETED', ou 'FAILED'
- `total_files_found`: Arquivos detectados
- `total_files_valid`: Arquivos validos
- `total_files_imported`: Arquivos importados com sucesso
- `total_files_failed`: Arquivos que falharam

**media_files** - Detalhes dos arquivos de midia:
- `file_path`: Caminho completo do arquivo
- `file_name`: Nome do arquivo
- `file_extension`: Extensao (mp4, mkv, etc)
- `file_size_bytes`: Tamanho em bytes
- `file_hash`: Hash do arquivo (para detectar duplicatas)
- `is_duplicate`: Se e duplicata
- `duration_seconds`: Duracao em segundos
- `fps`: Frames por segundo
- `width` / `height`: Resolucao
- `resolution`: String de resolucao (ex: "1920x1080")
- `codec_video` / `codec_audio`: Codecs utilizados
- `status`: Status de processamento
- `import_date`: Data de importacao

---

## Passo 7: Analise Estatica (Ja Realizada)

A analise estatica foi realizada no servidor. Pontos verificados:

### Validacoes Ja Concluidas

- Arquivos `__init__.py` em todas as camadas: SIM
- Estrutura de pacotes (infrastructure, application, presentation): SIM
- Imports basicos de PySide6: SIM
- Integracao com MainWindow: SIM (estruturalmente)
- Caminhos Windows usando `pathlib.Path`: SIM

### Pontos a Validar Localmente

1. **Imports em tempo de execucao**: Confirmar que nao ha erros ao abrir a app
2. **Circular dependencies**: Nenhuma detectada, mas validar em runtime
3. **Thread safety**: PySide6 UI executa em thread principal - SIM
4. **Banco de dados**: Tabelas criadas e dados persistem

---

## Passo 8: Gerar Relatorio Final

Apos validar tudo, crie um relatorio com os resultados:

```
RELATORIO DE VALIDACAO SPRINT 2.5
=================================

Data: [data]
Executor: [seu_nome]

RESULTADOS:
-----------

1. Imports: [SIM/NAO]
   - Detalhes: [sucesso/erro]

2. Estrutura: [SIM/NAO]
   - Arquivos __init__.py: [encontrados/faltantes]

3. Testes: [X/Y passaram, Z falharam]
   - Cobertura: [%]

4. Interface: [SIM/NAO]
   - Textos em PT-BR: [SIM/NAO]
   - Traducao completa: [SIM/NAO]

5. Banco de Dados: [SIM/NAO]
   - Tabelas encontradas: import_sessions, media_files
   - Total de registros: [X]

6. Fluxo End-to-End: [SIM/NAO]
   - Importacao funciona: [SIM/NAO]
   - Dados persistem: [SIM/NAO]

PROBLEMAS ENCONTRADOS:
----------------------
[lista]

RECOMENDACOES:
---------------
[lista]

STATUS FINAL: [VALIDADA COM SUCESSO / VALIDADA COM PROBLEMAS / NAO VALIDADA]
```

---

## Troubleshooting

### Erro: `ModuleNotFoundError: No module named 'PySide6'`

Solucao:

```cmd
pip install "PySide6>=6.5.0"
```

### Erro: `No such table: media_files`

O banco nao foi criado corretamente. Execute:

```cmd
python -c "from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository; from core.database.connection import DatabaseConnection; db = DatabaseConnection(); db.connect(); repo = SQLiteMediaRepository(db); print('[OK] Schema criado com sucesso')"
```

### Erro: `File not found: app.py`

Certifique-se de estar no diretorio raiz:

PowerShell:

```powershell
Get-Item app.py
cd TEDVHS-Studio
```

CMD:

```cmd
dir app.py
cd TEDVHS-Studio
```

### Aplicacao nao abre

Ativar venv corretamente:

PowerShell:

```powershell
.\.
venv\Scripts\Activate.ps1
```

CMD:

```cmd
.venv\Scripts\activate.bat
```

Depois tente:

```cmd
python app.py
```

### Erro: `sqlite3.OperationalError`

Limpar database corrompido e recriar:

```cmd
del tedvhs_studio.db
python app.py
```

### Erro no test_windows.bat: Diretorio 'tests' nao encontrado

A pasta `tests/` e necessaria para executar os testes. Se ela nao existe:

1. Crie a pasta manualmente:

```cmd
mkdir tests
```

2. Crie um arquivo `__init__.py` dentro dela:

```cmd
echo. > tests\__init__.py
```

3. Adicione seus arquivos de teste

4. Tente rodar o script novamente:

```cmd
test_windows.bat
```

---

## Checklist Final

- [ ] Ambiente virtual criado e ativado
- [ ] Dependencias instaladas (pip install -r requirements.txt)
- [ ] Imports validados (todos passam)
- [ ] Arquivos __init__.py verificados (todos existem)
- [ ] Testes executados (via test_windows.bat ou pytest tests/)
- [ ] Cobertura medida (relatorio HTML gerado)
- [ ] Aplicacao abriu sem erros (via run_windows.bat ou python app.py)
- [ ] Textos em PT-BR encontrados na interface
- [ ] Banco de dados criado (tedvhs_studio.db existe)
- [ ] Tabelas corretas (import_sessions, media_files)
- [ ] Fluxo end-to-end testado (importacao completa)
- [ ] Relatorio criado com resultados

---

## Proximas Etapas

1. Clonar repositorio e fazer checkout da branch `feature/sprint-2-5-media-library-ui`
2. Executar `run_windows.bat` para abrir a aplicacao
3. Executar `test_windows.bat` para rodar os testes
4. Seguir os passos deste guia
5. Anotar todos os resultados
6. Criar relatorio final
7. Reportar qualquer problema encontrado

Nao invente resultados. Se algo nao funcionou, reporte como NAO e descreva o erro.

---

## Duvidas?

Se encontrar problemas:
1. Verifique o Troubleshooting acima
2. Verifique se esta na branch correta: `git branch`
3. Verifique se pip packages estao instalados: `pip list`
4. Limpe cache do Python: `del /s /q __pycache__` (CMD) ou `Get-ChildItem -Directory __pycache__ | Remove-Item` (PS)
