# TEDVHS Studio - Anime Clip Editor

Aplicação desktop para edição e gerenciamento de clips de animes. Construída com Python, PySide6 e SQLite.

## 🎯 Características

- ✅ Gerenciamento de projetos de animes
- ✅ Criação e edição de clips de vídeo
- ✅ Sistema de tags para organização
- ✅ Histórico de buscas
- ✅ Favoritos de clips
- ✅ Interface dark theme moderna
- ✅ Banco de dados SQLite integrado

## 🏗️ Arquitetura

```
TEDVHS-Studio/
├── app.py                          # Ponto de entrada
├── config.py                       # Configurações
├── requirements.txt                # Dependências
├── core/
│   ├── logger.py                   # Sistema de logging
│   ├── database/
│   │   ├── connection.py           # Conexão com BD
│   │   ├── migrations.py           # Migrações do schema
│   │   └── repository.py           # Padrão Repository
│   ├── services/
│   │   └── project_service.py      # Lógica de projetos
│   └── entities/
│       ├── anime.py                # Entidade Anime
│       ├── episode.py              # Entidade Episode
│       ├── clip.py                 # Entidade Clip
│       └── project.py              # Entidade Project
└── ui/
    ├── theme/
    │   └── theme_manager.py        # Gerenciador de temas
    ├── controllers/
    │   └── main_controller.py      # Controlador principal
    └── views/
        ├── main_window.py          # Janela principal
        └── status_bar.py           # Barra de status
```

## 🗄️ Schema do Banco de Dados

### Tabelas

- **anime**: Informações dos animes
- **episode**: Episódios dos animes
- **clip**: Clips extraídos dos episódios
- **thumbnail**: Miniaturas dos clips
- **tag**: Tags para categorização
- **clip_tag**: Relação many-to-many entre clips e tags
- **project**: Projetos de edição
- **favorite**: Clips favoritos
- **search_history**: Histórico de buscas

## 🚀 Como Executar

### Pré-requisitos

- Python 3.10+
- pip

### Instalação

1. Clone o repositório
```bash
git clone https://github.com/HigorWebber/TEDVHS-Studio.git
cd TEDVHS-Studio
```

2. Crie um ambiente virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

3. Instale as dependências
```bash
pip install -r requirements.txt
```

### Executar a aplicação
```bash
python app.py
```

## 📦 Dependências Principais

- **PySide6**: Framework para interface gráfica
- **SQLite3**: Banco de dados (incluído no Python)

## 🏛️ Padrões Utilizados

- **MVC**: Model-View-Controller para separação de responsabilidades
- **Repository Pattern**: Abstração de acesso a dados
- **Dependency Injection**: Injeção de dependências
- **Service Layer**: Camada de serviços para lógica de negócio

## 📝 Estrutura de Código

### Camada de Apresentação (UI)
- `theme_manager.py`: Gerencia temas e estilos
- `main_controller.py`: Coordena ações da UI
- `main_window.py`: Janela principal
- `status_bar.py`: Barra de status

### Camada de Negócio (Services)
- `project_service.py`: Operações com projetos

### Camada de Dados
- `connection.py`: Gerencia conexão com BD
- `repository.py`: Operações genéricas de banco
- `migrations.py`: Criação de schema

### Modelos (Entities)
- `anime.py`: Modelo de Anime
- `episode.py`: Modelo de Episode
- `clip.py`: Modelo de Clip
- `project.py`: Modelo de Project

## 🔧 Configuração

Edite `config.py` para customizar:
- Diretórios de projetos
- Configurações de logging
- Dimensões da janela
- Outras preferências

## 📊 Logging

Logs são salvos em `logs/tedvhs.log` com informações de:
- Inicialização da aplicação
- Operações de banco de dados
- Erros e exceções
- Ações do usuário

## 🎨 Tema

A aplicação usa um tema escuro moderno com:
- Cores personalizadas
- Componentes estilizados
- Efeitos hover e transições

## 👨‍💻 Autor

**HigorWebber**

## 📄 Licença

Este projeto está sob a licença MIT.

## 🤝 Contribuições

Contribuições são bem-vindas! Por favor:

1. Faça um Fork do projeto
2. Crie uma branch para sua feature (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add some AmazingFeature'`)
4. Push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

## 📞 Contato

- GitHub: [@HigorWebber](https://github.com/HigorWebber)
- Email: higor11webber@gmail.com

---

**TEDVHS Studio** - Criado com ❤️ para editores de anime
