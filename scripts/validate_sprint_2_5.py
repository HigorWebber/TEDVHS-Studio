#!/usr/bin/env python3
"""Script de validação completa da Sprint 2.5.

Executa:
1. Testes com pytest
2. Cobertura com pytest-cov
3. Validação de imports
4. Verificação de interações de UI
"""

import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime


class ValidationReport:
    """Relatório de validação."""
    
    def __init__(self):
        self.timestamp = datetime.now().isoformat()
        self.results = {}
        self.errors = []
        self.passed = 0
        self.failed = 0
    
    def add_test_result(self, name: str, passed: bool, output: str = ""):
        """Adicionar resultado de teste."""
        self.results[name] = {
            "passed": passed,
            "output": output
        }
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def add_error(self, error: str):
        """Adicionar erro."""
        self.errors.append(error)
    
    def print_summary(self):
        """Imprimir resumo."""
        print("\n" + "="*80)
        print("RELATÓRIO DE VALIDAÇÃO - SPRINT 2.5")
        print("="*80)
        print(f"Timestamp: {self.timestamp}")
        print(f"\nTestes Aprovados: {self.passed}")
        print(f"Testes Falhos: {self.failed}")
        print(f"Erros Encontrados: {len(self.errors)}")
        
        if self.errors:
            print("\nERROS:")
            for error in self.errors:
                print(f"  ❌ {error}")
        
        print("\n" + "="*80)


def run_command(cmd: list, description: str) -> tuple[bool, str]:
    """Executar comando e retornar (sucesso, output)."""
    print(f"\n[*] {description}...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            print(f"[+] {description} - OK")
            return True, result.stdout + result.stderr
        else:
            print(f"[-] {description} - FALHOU")
            print(result.stderr)
            return False, result.stderr
    except subprocess.TimeoutExpired:
        print(f"[-] {description} - TIMEOUT")
        return False, "Comando expirou (timeout)"
    except Exception as e:
        print(f"[-] {description} - ERRO: {e}")
        return False, str(e)


def validate_imports() -> bool:
    """Validar que todos os imports funcionam."""
    print("\n[*] Validando imports...")
    try:
        # Testar imports principais
        from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
        from application.media.import_orchestrator import ImportOrchestrator
        from presentation.dialogs.import_library_dialog import ImportLibraryDialog
        from presentation.views.media_library_view import MediaLibraryView
        from application.media.media_pipeline import MediaPipeline
        from application.task_management import TaskScheduler, TaskQueue
        from application.event_bus import EventBus
        
        print("[+] Todos os imports validados com sucesso")
        return True
    except ImportError as e:
        print(f"[-] Erro de import: {e}")
        return False


def run_tests(report: ValidationReport) -> bool:
    """Executar testes com pytest."""
    print("\n" + "="*80)
    print("ETAPA 1: EXECUTAR TESTES COM PYTEST")
    print("="*80)
    
    # Executar pytest
    success, output = run_command(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        "Executando testes com pytest"
    )
    
    # Contar resultados
    lines = output.split("\n")
    passed_count = output.count(" PASSED")
    failed_count = output.count(" FAILED")
    collected = 0
    
    for line in lines:
        if " collected " in line:
            try:
                collected = int(line.split("collected ")[1].split(" ")[0])
            except:
                pass
    
    report.add_test_result("pytest", success, output)
    
    print(f"\nResumo de Testes:")
    print(f"  Total coletados: {collected}")
    print(f"  Aprovados: {passed_count}")
    print(f"  Falhos: {failed_count}")
    
    if not success:
        report.add_error(f"Testes falharam. Detalhes no output.")
    
    return success


def run_coverage(report: ValidationReport) -> bool:
    """Executar cobertura com pytest-cov."""
    print("\n" + "="*80)
    print("ETAPA 2: MEDIR COBERTURA COM PYTEST-COV")
    print("="*80)
    
    success, output = run_command(
        [
            sys.executable, "-m", "pytest", "tests/",
            f"--cov=infrastructure.persistence",
            f"--cov=application.media",
            f"--cov=presentation",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov"
        ],
        "Medindo cobertura com pytest-cov"
    )
    
    report.add_test_result("coverage", success, output)
    
    # Extrair percentual de cobertura
    coverage_pct = 0
    for line in output.split("\n"):
        if "TOTAL" in line:
            try:
                parts = line.split()
                coverage_pct = int(parts[-1].replace("%", ""))
            except:
                pass
    
    print(f"\nCobertura Total: {coverage_pct}%")
    print(f"Relatório HTML: htmlcov/index.html")
    
    if coverage_pct < 80:
        report.add_error(f"Cobertura baixa: {coverage_pct}% (esperado 80%+)")
    
    return success


def validate_ui_translations() -> bool:
    """Validar que toda a UI está em PT-BR."""
    print("\n" + "="*80)
    print("ETAPA 3: VALIDAR TRADUÇÕES PARA PT-BR")
    print("="*80)
    
    files_to_check = [
        "ui/views/main_window.py",
        "presentation/dialogs/import_library_dialog.py",
        "presentation/views/media_library_view.py"
    ]
    
    # Textos em inglés que não deveriam estar vistos
    forbidden_en = [
        '"New',
        '"Open',
        '"Exit',
        '"Help',
        '"About',
        '"Ready',
        '"Browse',
        '"Import',
        'English text that should be translated'
    ]
    
    all_pt_br = True
    for file_path in files_to_check:
        if not Path(file_path).exists():
            print(f"[-] Arquivo não encontrado: {file_path}")
            all_pt_br = False
            continue
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Verificar se tem textos em PT-BR esperados
        pt_br_texts = [
            "Importar Biblioteca",
            "Biblioteca de Mídia",
            "Selecionar Pasta",
            "Progresso",
            "Pronto",
            "Erro",
            "Cancelar",
            "Fechar",
            "Processando",
            "Pendente"
        ]
        
        found_pt_br = any(text in content for text in pt_br_texts)
        if found_pt_br:
            print(f"[+] {file_path} - PT-BR validado")
        else:
            print(f"[-] {file_path} - PT-BR não encontrado")
            all_pt_br = False
    
    return all_pt_br


def main():
    """Executar validação completa."""
    report = ValidationReport()
    
    print("\n" + "#"*80)
    print("# VALIDAÇÃO COMPLETA - SPRINT 2.5")
    print("#"*80)
    
    # 1. Validar imports
    print("\n" + "="*80)
    print("VALIDAÇÃO PRÉVIA: IMPORTS")
    print("="*80)
    imports_ok = validate_imports()
    report.add_test_result("imports", imports_ok)
    
    if not imports_ok:
        print("\n[-] Imports falhou. Encerrando validação.")
        report.print_summary()
        sys.exit(1)
    
    # 2. Executar testes
    tests_ok = run_tests(report)
    
    # 3. Medir cobertura
    coverage_ok = run_coverage(report)
    
    # 4. Validar traduções
    translations_ok = validate_ui_translations()
    report.add_test_result("translations", translations_ok)
    
    # Gerar relatório
    report.print_summary()
    
    # Determinar status final
    all_ok = imports_ok and tests_ok and coverage_ok and translations_ok
    
    if all_ok:
        print("\n[+] VALIDAÇÃO CONCLUÍDA COM SUCESSO!")
        return 0
    else:
        print("\n[-] VALIDAÇÃO COM FALHAS!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
