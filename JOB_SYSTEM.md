# Job System

## Visão Geral

O **Job System** é uma arquitetura para gerenciar tarefas de longa duração de forma robusta, com suporte para:

- Pausa/resume
- Cancelamento
- Priorização
- Monitoramento de progresso
- Tratamento de erros

## Arquitetura

### JobStatus

```python
class JobStatus(Enum):
    PENDING = "pending"        # Aguardando execução
    RUNNING = "running"        # Executando
    PAUSED = "paused"          # Pausado pelo usuário
    COMPLETED = "completed"    # Concluído com sucesso
    FAILED = "failed"          # Falhou
    CANCELLED = "cancelled"    # Cancelado
```

### JobPriority

```python
class JobPriority(Enum):
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0
```

### IJob Interface

```python
class IJob(ABC):
    @property
    def job_id(self) -> str:
        """ID único do job."""

    @property
    def status(self) -> JobStatus:
        """Status atual."""

    @property
    def progress(self) -> JobProgress:
        """Progresso da execução."""

    def execute(self) -> Dict[str, Any]:
        """Executar job."""

    def pause(self) -> bool:
        """Pausar execução."""

    def resume(self) -> bool:
        """Retomar execução."""

    def cancel(self) -> bool:
        """Cancelar job."""

    def get_result(self) -> Optional[Dict[str, Any]]:
        """Obter resultado."""
```

## Uso Básico

### Criar um Job

```python
from domain.jobs.interfaces import BaseJob, JobStatus

class ImportLibraryJob(BaseJob):
    """Job para importar biblioteca."""
    
    def __init__(self, folder_path: str, priority=JobPriority.NORMAL):
        super().__init__(job_id=str(uuid4()), priority=priority)
        self.folder_path = folder_path
        self.pipeline = None
    
    def execute(self) -> Dict[str, Any]:
        self._mark_started()
        
        try:
            # Processar
            stats = self.pipeline.process_directory(
                self.folder_path,
                progress_callback=self._update_progress
            )
            
            # Marcar como completo
            self._mark_completed(stats)
            return stats
        
        except Exception as e:
            self._mark_failed(str(e))
            raise
    
    def _update_progress(self, stage: str, current: int, total: int = None):
        """Atualizar progresso."""
        if total:
            self._progress.update(current, total, f"{stage}: {current}/{total}")
```

### Executar Job

```python
# Criar job
job = ImportLibraryJob("/path/to/anime", priority=JobPriority.HIGH)

# Executar
try:
    result = job.execute()
    print(f"Job concluído: {result}")
except Exception as e:
    print(f"Job falhou: {e}")

# Verificar resultado
if job.status == JobStatus.COMPLETED:
    stats = job.get_result()
    print(f"Importados: {stats['files_imported']}")
```

### Controlar Job

```python
# Pausar
if job.pause():
    print("Job pausado")

# Retomar
if job.resume():
    print("Job retomado")

# Cancelar
if job.cancel():
    print("Job cancelado")

# Verificar progresso
print(f"Progresso: {job.progress.percentage:.1f}%")
print(f"Mensagem: {job.progress.message}")
```

## JobManager

### Responsabilidades (Futuro)

O JobManager será implementado em Sprint 3.0 com:

- Fila de jobs
- Priorização
- Scheduling
- Execução paralela (com controle)
- Persistência de estado
- Retomada após shutdown

### Interface Planejada

```python
class JobManager:
    """Gerenciador de jobs."""
    
    def submit(self, job: IJob) -> str:
        """Submeter job para execução.
        Retorna: job_id
        """
    
    def pause(self, job_id: str) -> bool:
        """Pausar job."""
    
    def resume(self, job_id: str) -> bool:
        """Retomar job."""
    
    def cancel(self, job_id: str) -> bool:
        """Cancelar job."""
    
    def get_status(self, job_id: str) -> JobStatus:
        """Obter status do job."""
    
    def get_progress(self, job_id: str) -> JobProgress:
        """Obter progresso do job."""
    
    def list_jobs(self, status: Optional[JobStatus] = None) -> List[str]:
        """Listar job IDs."""
```

## Fluxo Típico (v1.0)

```
UI: Usuário clica "Importar"
    ↓
Application: Criar ImportLibraryJob
    ↓
UI: Mostrar dialog de progresso
    ↓
Application: job.execute()
    ├─ Scanner.scan()
    ├─ Validator.validate()
    ├─ Hash.calculate()
    ├─ Analyzer.analyze()
    └─ Repository.save()
    ↓
UI: Atualizar progresso via callback
    ↓
Job: COMPLETED
    ↓
UI: Mostrar resumo e fechar dialog
```

## Fluxo Avançado (v2.0+)

```
JobManager
    ├─ Job 1: Scan (CRITICAL)
    │   └─ RUNNING → COMPLETED
    ├─ Job 2: Import (HIGH)
    │   └─ PENDING → RUNNING
    ├─ Job 3: Scene Detect (NORMAL)
    │   └─ PENDING
    └─ Job 4: AI Analysis (LOW)
        └─ PENDING

JobManager coordena:
- Execução paralela (4 workers)
- Pausa/resume de jobs
- Erro handling
- Persistência de estado
```

## Integração com Media Pipeline

```python
# Uma importação é um Job
import_job = ImportLibraryJob(
    folder_path="/anime/biblioteca",
    priority=JobPriority.HIGH
)

# UI conecta callback de progresso
def on_progress(stage, current, total):
    update_ui_progress_bar(current / total * 100)

import_job._progress_callback = on_progress

# Task Manager executa
task_scheduler.submit_task(import_job)

# Usuário pode pausar durante import
if user_clicked_pause:
    import_job.pause()

# E retomar depois
if user_clicked_resume:
    import_job.resume()
```

## Persistência de Estado (v2.0)

Os jobs podem ser persistidos para retomada após shutdown:

```python
# Antes de encerrar
job_state = {
    "job_id": job.job_id,
    "status": job.status.value,
    "progress": job.progress.to_dict(),
    "result": job.get_result()
}
save_to_database(job_state)

# Ao reiniciar
recovered_job = load_from_database(job_id)
if recovered_job.status in (PAUSED, RUNNING):
    show_dialog(
        "Processamento interrompido. Retomar?"
    )
    if user_confirms:
        recovered_job.resume()
```

## Error Handling

```python
try:
    job.execute()
except Exception as e:
    # Job automaticamente marcado como FAILED
    assert job.status == JobStatus.FAILED
    
    # Error armazenado
    error_msg = job._error
    
    # Usuário pode tentar novamente
    job.retry()  # Reset para PENDING
    job.execute()
```

## Monitoramento

```python
# Real-time monitoring
while job.status != JobStatus.COMPLETED:
    print(f"Progresso: {job.progress.percentage:.1f}%")
    print(f"Mensagem: {job.progress.message}")
    time.sleep(0.5)

if job.status == JobStatus.COMPLETED:
    print("Sucesso!")
    print(job.get_result())
elif job.status == JobStatus.FAILED:
    print(f"Erro: {job._error}")
```

---

**Status**: ✅ Base implementation ready (JobManager em v2.0)
**Próximas etapas**: JobManager com queue e scheduling
