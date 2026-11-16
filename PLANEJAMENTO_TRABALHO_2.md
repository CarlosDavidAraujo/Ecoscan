# Planejamento Técnico — Trabalho Prático 2 (Docker, Docker Compose & Kubernetes)

**Projeto:** EcoScan — Sistema Inteligente de Identificação Botânica e Catálogo de Plantas  
**Disciplina:** Desenvolvimento de Software para Nuvem  
**Professores:** Dr. Paulo A. L. Rego e Dr. Fernando Antonio Mota Trinta

---

## 1. Visão Geral da Migração (Trabalho 1 $\rightarrow$ Trabalho 2)

O objetivo do **Trabalho Prático 2** é substituir os serviços gerenciados de armazenamento, banco relacional e mensageria da AWS por containers locais orquestrados via **Docker Compose**, mantendo apenas o **Amazon DynamoDB** na nuvem AWS para os registros não-relacionais (trilha de auditoria CRUD).

| Camada / Requisito           | Trabalho 1 (AWS Nuvem)                 | Trabalho 2 (Containers Docker)                                        | Pontuação                                          |
| ---------------------------- | -------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------- |
| **Armazenamento de Objetos** | Amazon S3 (`amz-ecoscan-bucket`)       | **MinIO** (`minio/minio`)                                             | **1,5 pts** (0,5 container + 1,0 leitura/escrita)  |
| **Banco de Dados NoSQL**     | Amazon DynamoDB (`ecoscan_audit_logs`) | **Amazon DynamoDB** _(Mantido na AWS)_                                | **1,0 pt** (armazenamento e consulta)              |
| **Banco Relacional**         | Amazon RDS PostgreSQL                  | **PostgreSQL 15** (`postgres:15-alpine`)                              | **1,5 pts** (0,5 container + 1,0 persistência)     |
| **Fila de Mensagens**        | Amazon SNS + SQS                       | **RabbitMQ** (`rabbitmq:3-management-alpine`)                         | **1,5 pts** (0,5 container + 1,0 pub/sub)          |
| **Imagens da Aplicação**     | Backend + Worker                       | **Dockerfiles** (Backend, Worker e Frontend Web)                      | **1,5 pts**                                        |
| **Orquestração**             | `docker-compose.aws.yml` parcial       | **Docker Compose Completo** (1 comando, redes e `depends_on`)         | **1,5 pts** (0,75 comando único + 0,75 redes/deps) |
| **Documentação**             | `README.md`                            | **README.md atualizado** (instruções + evidências/prints)             | **1,5 pts** (1,0 instruções + 0,5 evidências)      |
| **Extra (Bônus)**            | —                                      | **Kubernetes (K8s)** (`Deployment`, `Service`, `Secret`, `ConfigMap`) | **+1,0 pt extra**                                  |

---

## 2. Arquitetura Proposta (Trabalho 2)

```mermaid
flowchart TB
    subgraph Client ["Acesso do Usuário"]
        Browser["Navegador Web\n(http://localhost:3000)"]
    end

    subgraph Docker_Network ["Rede Docker: ecoscan_network (Bridge)"]
        Frontend["Container: ecoscan_frontend\n(Nginx / Web SPA - Porta 3000:80)"]
        API["Container: ecoscan_api\n(FastAPI + Uvicorn - Porta 8000:8000)"]
        Worker["Container: ecoscan_worker\n(Python Worker: Pillow + YOLO11)"]

        subgraph Infra_Containers ["Serviços de Infraestrutura Containerizados"]
            Postgres[("Container: ecoscan_db\nPostgreSQL 15\n(Porta 5432)")]
            MinIO["Container: ecoscan_minio\nMinIO Object Storage\n(API: 9000 | Console: 9001)"]
            RabbitMQ["Container: ecoscan_rabbitmq\nRabbitMQ Broker\n(AMQP: 5672 | UI: 15672)"]
            Redis[("Container: ecoscan_redis\nRedis Cache (Opcional)\n(Porta 6379)")]
        end
    end

    subgraph AWS_Cloud ["Nuvem AWS (Serviço Mantido)"]
        DynamoDB[("Amazon DynamoDB\nTabela: ecoscan_audit_logs\n(Auditoria NoSQL CRUD)")]
    end

    Browser -->|HTTP :3000| Frontend
    Browser -->|REST API :8000| API
    Frontend -->|Consome API| API

    API -->|SQLAlchemy / Alembic| Postgres
    API -->|Upload / Download S3 API| MinIO
    API -->|Publica Tarefa (AMQP)| RabbitMQ
    API -->|Registra & Consulta Logs CRUD| DynamoDB
    API -.->|Cache de Consultas| Redis

    RabbitMQ -->|Consome Fila: image_processing_queue| Worker
    Worker -->|Baixa Original & Salva Thumbnail| MinIO
    Worker -->|Atualiza Resultado IA| Postgres
    Worker -->|Registra Log de Processamento| DynamoDB
```

---

## 3. Planejamento Detalhado por Etapas

### Etapa 1: Adaptação do Armazenamento para o MinIO (1,5 pontos)

O **MinIO** implementa a API compatível com o Amazon S3. Assim, podemos continuar usando `boto3`, apontando para o container do MinIO.

1. **Ajustes em `api/ecoscan/settings.py`:**
   - Adicionar configurações dedicadas para o MinIO/S3 local:
     - `S3_ENDPOINT_URL` (ex: `http://minio:9000` internamente no Docker).
     - `S3_PUBLIC_URL` (ex: `http://localhost:9000` para o navegador exibir as imagens diretamente).
     - `S3_ACCESS_KEY` (`minioadmin`) e `S3_SECRET_KEY` (`minioadmin123`).
     - `S3_BUCKET_NAME` (`ecoscan-images`).
2. **Refatoração em `api/ecoscan/aws/s3.py`:**
   - Criar função `ensure_bucket_exists()` chamada no startup da API e do Worker:
     - Verifica se o bucket `ecoscan-images` existe no MinIO; caso não exista, cria automaticamente (`create_bucket`) e aplica política pública de leitura (`put_bucket_policy`) para que as fotos e thumbnails possam ser abertas pelo Frontend.
   - Atualizar `get_s3_url()` e `upload_to_s3()` para montar a URL usando `S3_PUBLIC_URL` (`http://localhost:9000/ecoscan-images/{key}`) quando estiver usando MinIO.
   - Garantir que `download_from_s3()` no Worker baixe usando o endpoint interno `http://minio:9000`.

---

### Etapa 2: Substituição do SNS/SQS pelo RabbitMQ (1,5 pontos)

Escolhemos o **RabbitMQ** (`rabbitmq:3-management-alpine`) por ser leve, ter inicialização rápida em container e possuir o painel administrativo web na porta `15672` (excelente para demonstrar as filas ao professor durante a apresentação).

1. **Dependências (`api/ecoscan/requirements.txt`):**
   - Adicionar a biblioteca `pika` para comunicação via protocolo AMQP com o RabbitMQ.
2. **Ajustes em `api/ecoscan/settings.py`:**
   - Adicionar variáveis:
     - `RABBITMQ_URL: str = "amqp://guest:guest@rabbitmq:5672/"`
     - `RABBITMQ_QUEUE_NAME: str = "ecoscan_image_queue"`
3. **Refatoração do Produtor (`api/ecoscan/aws/messaging.py`):**
   - Substituir a publicação SNS/SQS por publicação direta na fila durável (`durable=True`) do RabbitMQ via `pika`:
     - Conecta ao broker RabbitMQ, declara a fila `ecoscan_image_queue` e publica o payload JSON (`job_id`, `user_id`, `s3_key`, `confidence_threshold`, `top_k`) com `delivery_mode=2` (mensagem persistente).
4. **Refatoração do Consumidor (`api/ecoscan/worker.py`):**
   - Substituir o polling do SQS por consumo via `pika` (`basic_consume` ou loop resiliente com reconexão automática):
     - Lê a mensagem da fila `ecoscan_image_queue` no RabbitMQ;
     - Baixa a imagem original do **MinIO**;
     - Faz o _rescaling_ com Pillow (gera thumbnail 300x300 e imagem normalizada 640x640);
     - Faz upload do thumbnail no **MinIO**;
     - Executa a inferência com o modelo **YOLO11 (`best.pt`)**;
     - Atualiza o status para `COMPLETED` e salva os metadados no **PostgreSQL**;
     - Registra o evento de auditoria no **Amazon DynamoDB**;
     - Envia o `basic_ack` para o RabbitMQ removendo a mensagem da fila.

---

### Etapa 3: Manutenção do NoSQL na AWS — Amazon DynamoDB (1,0 ponto)

Conforme exigido no item `1.a` da especificação, o banco não-relacional deve continuar sendo o serviço da AWS.

1. **Verificação em `api/ecoscan/aws/dynamodb.py`:**
   - Manter a gravação de logs de auditoria em todas as ações CRUD (criação de usuário, login, identificação síncrona/assíncrona, adição/remoção do jardim e exclusão de histórico).
   - Manter a rota `GET /audit/logs` que consulta em tempo real os itens armazenados na tabela `ecoscan_audit_logs` no DynamoDB da AWS.
   - Separar claramente no `.env` as credenciais da AWS (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`) usadas exclusivamente pelo cliente do DynamoDB, para que não conflitem com as credenciais locais do MinIO.

---

### Etapa 4: Banco de Dados Relacional Containerizado — PostgreSQL (1,5 pontos)

Conforme exigido nos itens `1.b` e `4`, o banco relacional antes no RDS passa a rodar em container gerenciado pela equipe.

1. **Configuração do Container PostgreSQL:**
   - Imagem: `postgres:15-alpine`.
   - Volume nomeado `postgres_data:/var/lib/postgresql/data` para garantir que os dados persistam mesmo se o container for reiniciado.
   - `healthcheck` com `pg_isready -U postgres -d ecoscan`.
2. **Migrações Automáticas:**
   - O `entrypoint.sh` da API já executa `alembic -c ecoscan/alembic.ini upgrade head` antes de iniciar o servidor Uvicorn, criando todas as tabelas automaticamente na primeira execução do `docker compose up`.

---

### Etapa 5: Criação do Frontend Web e seu Dockerfile (1,5 pontos)

A especificação exige um `Dockerfile` para o **frontend** e que ele suba junto no `docker-compose.yml`.

1. **Desenvolvimento da Interface Web (`web/`):**
   - Criar uma aplicação Web moderna, responsiva e intuitiva conectada à API (`http://localhost:8000`), contendo:
     - **Autenticação:** Tela de Login e Cadastro de Usuário;
     - **Identificação de Plantas (Síncrona e Assíncrona via RabbitMQ + MinIO):** Upload de foto da planta, barra de status do processamento em fila, exibição da foto/thumbnail servida diretamente do **MinIO**, grau de confiança e guia de cuidados botânicos;
     - **Meu Jardim & Histórico (PostgreSQL):** Listagem das plantas identificadas, botão para salvar/remover do Jardim e exclusão de registros;
     - **Painel de Auditoria NoSQL (AWS DynamoDB) & Status da Infraestrutura:** Aba exibindo em tempo real os logs vindos do DynamoDB na AWS e o status dos containers.
2. **Criação do `web/Dockerfile`:**
   - Imagem baseada em `nginx:alpine` (ou build multi-stage Node $\rightarrow$ Nginx) expondo a porta `80` (mapeada para `3000:80` no host) para servir a aplicação de forma leve e instantânea.

---

### Etapa 6: Dockerfiles (Backend, Worker e Frontend) e Docker Compose Unificado (3,0 pontos)

Atende aos itens `2`, `3`, `4`, `5`, `6` e `7` da especificação.

1. **`api/ecoscan/Dockerfile` (Backend e Worker):**
   - Revisar para garantir que todas as dependências (`pika`, `boto3`, `psycopg`, `ultralytics`, `pillow`, `fastapi`, `uvicorn`, `alembic`) estejam instaladas e que o modelo `best.pt` seja empacotado ou montado automaticamente sem passos manuais.
2. **`docker-compose.yml` na Raiz do Projeto:**
   - Configurar todos os **6 containers** na mesma rede bridge (`ecoscan_net`) subindo com um único comando `docker compose up -d --build`:
     1. `db` (`postgres:15-alpine`) — com `healthcheck` e volume persistente;
     2. `minio` (`minio/minio:latest`) — portas `9000` (API S3) e `9001` (Console Web), com `healthcheck` e volume `minio_data`;
     3. `rabbitmq` (`rabbitmq:3-management-alpine`) — portas `5672` (AMQP) e `15672` (Painel Web), com `healthcheck` e volume `rabbitmq_data`;
     4. `api` (Backend FastAPI) — porta `8000:8000`, `depends_on` aguardando `db`, `minio` e `rabbitmq` ficarem `service_healthy`;
     5. `worker` (Worker IA/Pillow) — compartilha a imagem do backend com comando `python -m ecoscan.worker`, `depends_on` aguardando `db`, `minio` e `rabbitmq` saudáveis;
     6. `frontend` (Interface Web) — porta `3000:80`, `depends_on` da `api`.

---

### Etapa 7: Documentação Completa no `README.md` (1,5 pontos)

1. Atualizar o `README.md` principal com:
   - Diagrama da arquitetura em containers + integração com DynamoDB na AWS;
   - Pré-requisitos (Docker, Docker Compose e variáveis AWS para o DynamoDB no `.env`);
   - Passo a passo claro para clonar o repositório, configurar o `.env` e subir tudo com **um único comando**:
     ```bash
     docker compose up -d --build
     ```
   - Tabela com as URLs e portas de acesso de cada serviço:
     - Frontend Web: `http://localhost:3000`
     - Backend API / Swagger: `http://localhost:8000/docs`
     - Console MinIO: `http://localhost:9001`
     - Painel RabbitMQ: `http://localhost:15672`
   - Seção de evidências/comandos de teste comprovando o funcionamento de ponta a ponta.

---

### Etapa 8 (Bônus +1,0 ponto): Manifestos Kubernetes (`k8s/`)

Para garantir o **1,0 ponto extra** da especificação:

1. Criar diretório `k8s/` contendo os manifestos YAML prontos para `kubectl apply -f k8s/`:
   - `01-secrets-configmap.yaml`: `Secret` (credenciais do Postgres, MinIO, RabbitMQ e AWS DynamoDB) e `ConfigMap` (URLs de conexão e nomes de filas/buckets);
   - `02-postgres.yaml`: `Deployment` + `Service (ClusterIP)` + `PersistentVolumeClaim` para o PostgreSQL;
   - `03-minio.yaml`: `Deployment` + `Service (ClusterIP e NodePort)` para o MinIO;
   - `04-rabbitmq.yaml`: `Deployment` + `Service (ClusterIP e NodePort)` para o RabbitMQ;
   - `05-backend-worker.yaml`: `Deployment` para a `api` + `Service (NodePort)` e `Deployment` para o `worker`;
   - `06-frontend.yaml`: `Deployment` para o `frontend` + `Service (NodePort)`.
2. Adicionar no `README.md` a seção de como subir no Kubernetes (Minikube / Docker Desktop K8s / Kind).

---

## 4. Checklist de Execução e Validação (Critérios de Correção)

- [ ] **Etapa 1 (MinIO - 1,5 pts):** Container MinIO subindo, bucket criado automaticamente e fotos/thumbnails sendo enviadas e lidas pela aplicação.
- [ ] **Etapa 2 (RabbitMQ - 1,5 pts):** Container RabbitMQ subindo, rota `/plants/identify-async` publicando mensagens na fila e `worker` consumindo e processando com IA.
- [ ] **Etapa 3 (DynamoDB AWS - 1,0 pt):** Operações de CRUD gravando logs na tabela `ecoscan_audit_logs` na AWS e rota `/audit/logs` consultando os dados.
- [ ] **Etapa 4 (PostgreSQL - 1,5 pts):** Container do Postgres executando, migrações Alembic aplicadas automaticamente e dados de usuários/plantas persistidos.
- [ ] **Etapa 5 & 6 (Dockerfiles & Docker Compose - 3,0 pts):** Dockerfiles de Backend, Worker e Frontend funcionando; `docker compose up -d --build` na raiz subindo toda a stack com redes e `depends_on` configurados.
- [ ] **Etapa 7 (README - 1,5 pts):** Instruções passo a passo claras e roteiro de validação documentado.
- [ ] **Etapa 8 (Extra Kubernetes - +1,0 pt):** Manifestos `Deployment`, `Service (ClusterIP / NodePort)`, `ConfigMap` e `Secret` criados em `k8s/`.
