# Especificação do Trabalho Prático 2

**Disciplina:** Desenvolvimento de Software para Nuvem  
**Professores:** Dr. Paulo A. L. Rego e Dr. Fernando Antonio Mota Trinta

---

## Objetivo

Fazer a implantação da aplicação desenvolvida no Trabalho 1 utilizando **Docker** e **Docker Compose**.

---

## Imposições sobre o Trabalho

1. A aplicação deve:
   - **a.** Continuar usando o serviço de banco de dados não-relacional da AWS (**DynamoDB** ou **Amazon DocumentDB**) para armazenar e consultar as informações necessárias para a sua aplicação;
   - **b.** Usar um serviço de banco de dados relacional gerenciado por você (**Postgres** ou **MySQL**) para persistir os dados antes armazenados no Amazon RDS;
   - **c.** Usar o serviço **MinIO** para armazenar os arquivos antes armazenados no S3;
   - **d.** Usar o **RabbitMQ** ou **Kafka** para substituir o SNS/SQS.
2. Usar `Dockerfile` para criar a imagem do **backend** da aplicação;
3. Usar `Dockerfile` para criar a imagem do **frontend** da aplicação;
4. Usar imagem do **Postgres** ou **MySQL** para executar o banco de dados relacional;
5. Usar imagem do **MinIO** para executar o serviço de armazenamento de arquivos;
6. Usar a imagem do **RabbitMQ** ou **Kafka** para executar o serviço de fila de mensagens;
7. Usar **Docker Compose** para configurar a execução e iniciar os serviços de backend, frontend, banco de dados relacional, serviço de fila de mensagens e armazenamento de arquivos.

---

## Algumas Ponderações

1. Subir código no GitHub (ou outro repositório) e preparar `README` com os passos necessários para baixar o código, gerar as imagens e iniciar os serviços.
2. **Opcionalmente:** pode-se iniciar os serviços em uma máquina virtual da AWS para possibilitar a correção online.

---

## Pontuação (Total: 10,0 pontos)

- **Usar o MinIO para escrita e leitura de arquivos (1,5 pontos):**
  - 0,5 ponto: container executando;
  - 1,0 ponto: upload/download de arquivos funcionando na aplicação.
- **Usar o banco de dados NoSQL (AWS DynamoDB/DocumentDB) para armazenamento e consulta (1,0 ponto).**
- **Usar o banco de dados relacional gerenciado pela equipe (1,5 pontos):**
  - 0,5 ponto: container do Postgres/MySQL executando;
  - 1,0 ponto: aplicação se conectar e persistir dados.
- **Usar o RabbitMQ ou Kafka para fila de mensagens (1,5 pontos):**
  - 0,5 ponto: container executando corretamente;
  - 1,0 ponto: produção e consumo de mensagens funcionando.
- **Usar `Dockerfile` corretamente para criar as imagens do backend, worker e frontend da aplicação (1,5 pontos).**
- **Usar `Docker Compose` corretamente para configurar a execução de todos os serviços (1,5 pontos):**
  - 0,75 ponto: todos os serviços sobem via um único comando (`docker compose up`);
  - 0,75 ponto: redes e dependências configuradas corretamente.
- **Documentação de uso no `README` do repositório (1,5 pontos):**
  - 1,0 ponto: instruções claras para executar o `docker compose up`;
  - 0,5 ponto: prints ou evidências de funcionamento.

### Penalidades / Critérios Adicionais

- **Atraso na entrega:** -1,0 ponto por dia.
- **Qualidade da apresentação (slides, figuras, diagramas) e clareza na apresentação e resposta às perguntas:** 0 a -3,0 pontos.

---

## Pontuação Extra (+1,0 ponto)

- Subir o mesmo serviço no **Kubernetes**, utilizando `Deployment` e `Services` (`NodePort` e `ClusterIP`).
- Configurar variáveis de ambiente e usar credenciais/`Secrets` no K8s de forma segura.
