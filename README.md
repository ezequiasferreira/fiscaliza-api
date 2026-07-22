# Fiscaliza Dados Públicos API

API para acesso automatizado a processos públicos do SEI, geração de PDF consolidado e futura análise da execução financeira com inteligência artificial.

## Objetivo

A solução recebe um link público de processo do SEI estadual e executa automaticamente as seguintes etapas:

1. acessa a página pública do processo;
2. identifica os documentos disponíveis;
3. seleciona todos os documentos;
4. aciona a geração do PDF consolidado;
5. disponibiliza o arquivo por meio de um endpoint da API.

O projeto será evoluído para realizar resumo, rastreabilidade da execução financeira, identificação de empenhos, liquidações, pagamentos, favorecidos e possíveis inconsistências.

## Tecnologias

- Python
- FastAPI
- Playwright
- Chromium
- Docker
- PostgreSQL
- Google Cloud Run
- Google Cloud Storage
- OpenAI API
- Looker Studio

## Situação atual

O MVP 1 está funcional e validado localmente e em contêiner Docker.

### Funcionalidades concluídas

- recebimento de link público do SEI;
- validação da página;
- identificação dos documentos;
- seleção automática dos documentos;
- geração do PDF consolidado;
- armazenamento temporário do PDF;
- disponibilização do arquivo por endpoint;
- execução local;
- execução em contêiner Docker.

## Endpoints

### Verificação da API

```http
GET /
