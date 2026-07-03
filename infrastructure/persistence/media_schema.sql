-- Schema para Media Library Engine
-- Tabelas para persistência de arquivos de mídia importados

-- Tabela de sessões de importação
CREATE TABLE IF NOT EXISTS import_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    folder_path TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT DEFAULT 'IN_PROGRESS',
    total_files_found INTEGER DEFAULT 0,
    total_files_valid INTEGER DEFAULT 0,
    total_files_imported INTEGER DEFAULT 0,
    total_files_failed INTEGER DEFAULT 0,
    total_duration_seconds REAL DEFAULT 0,
    total_size_bytes INTEGER DEFAULT 0
);

-- Tabela de arquivos de mídia
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_session_id TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_extension TEXT,
    file_size_bytes INTEGER,
    file_hash TEXT UNIQUE NOT NULL,
    is_duplicate BOOLEAN DEFAULT 0,
    duplicate_of_hash TEXT,
    duration_seconds REAL,
    fps REAL,
    width INTEGER,
    height INTEGER,
    resolution TEXT,
    codec_video TEXT,
    codec_audio TEXT,
    audio_channels INTEGER,
    status TEXT DEFAULT 'PENDING',
    import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata_version INTEGER DEFAULT 1,
    processing_attempts INTEGER DEFAULT 0,
    last_error TEXT,
    FOREIGN KEY (import_session_id) REFERENCES import_sessions(session_id)
);

-- Índices para otimização de queries
CREATE INDEX IF NOT EXISTS idx_media_import_session ON media_files(import_session_id);
CREATE INDEX IF NOT EXISTS idx_media_file_hash ON media_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_media_status ON media_files(status);
CREATE INDEX IF NOT EXISTS idx_media_import_date ON media_files(import_date);
CREATE INDEX IF NOT EXISTS idx_media_is_duplicate ON media_files(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON import_sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON import_sessions(started_at);