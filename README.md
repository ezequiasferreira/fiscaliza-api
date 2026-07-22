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
```

### Análise e geração do PDF

```http
POST /analisar-processo
```

Exemplo de requisição:

```json
{
  "link_processo_url": "https://sei.rr.gov.br/sei/processo_acesso_externo_consulta.php?id_acesso_externo=EXEMPLO&infra_hash=EXEMPLO"
}
```

### Download do PDF

```http
GET /downloads/{nome_arquivo}
```

## Execução local

Crie e ative o ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
playwright install chromium
```

Inicie a API:

```bash
uvicorn main:app --reload
```

A documentação interativa estará disponível em:

```text
http://127.0.0.1:8000/docs
```

## Execução com Docker

Construa a imagem:

```bash
docker build -t fiscaliza-api .
```

Execute o contêiner:

```bash
docker run --rm -p 8080:8080 fiscaliza-api
```

A documentação estará disponível em:

```text
http://127.0.0.1:8080/docs
```

## Planejamento por MVP

### MVP 1 — Acesso ao SEI e geração do PDF

- [x] receber o link público;
- [x] abrir o processo com Playwright;
- [x] listar os documentos;
- [x] selecionar os documentos;
- [x] gerar o PDF consolidado;
- [x] disponibilizar o PDF por endpoint;
- [x] executar a aplicação em Docker.

### MVP 2 — Robustez e implantação no GCP

- [ ] tratar processos com grande quantidade de documentos;
- [ ] aumentar e configurar o tempo limite;
- [ ] capturar alertas e mensagens do SEI;
- [ ] registrar erros e logs;
- [ ] armazenar PDFs no Google Cloud Storage;
- [ ] publicar a API no Google Cloud Run;
- [ ] proteger a API com autenticação.

### MVP 3 — Análise por inteligência artificial

- [ ] enviar o PDF à OpenAI API;
- [ ] gerar resumo executivo;
- [ ] identificar empenhos;
- [ ] identificar liquidações;
- [ ] identificar pagamentos;
- [ ] identificar favorecidos;
- [ ] montar cronologia financeira;
- [ ] gerar alertas e inconsistências;
- [ ] devolver resultado estruturado em JSON.

### MVP 4 — PostgreSQL e Looker Studio

- [ ] modelar as tabelas de análise;
- [ ] gravar resultados no PostgreSQL;
- [ ] relacionar processo, emenda e plano de ação;
- [ ] criar views para o Looker Studio;
- [ ] exibir situação da análise;
- [ ] exibir resumo, valores, alertas e nível de risco;
- [ ] integrar filtros do painel.

### MVP 5 — Integração com GPT personalizado

- [ ] criar contrato OpenAPI;
- [ ] publicar endpoint compatível com GPT Actions;
- [ ] configurar autenticação;
- [ ] conectar a API ao GPT Fiscaliza Dados Públicos;
- [ ] testar o fluxo completo;
- [ ] documentar a utilização.

## Arquitetura planejada

```text
Looker Studio / GPT personalizado
              |
              v
       Fiscaliza API
              |
              v
       Playwright + SEI
              |
              v
      PDF consolidado
              |
              v
        OpenAI API
              |
              v
         PostgreSQL
              |
              v
       Painéis e relatórios
```

## Segurança

Não devem ser enviados ao GitHub:

- chaves da OpenAI;
- senhas;
- tokens;
- arquivos `.env`;
- credenciais do Google Cloud;
- PDFs de processos;
- arquivos temporários.

Esses itens estão previstos no `.gitignore`.

## Autor

Projeto desenvolvido por Ezequias Carlos Ferreira da Silva.

Tribunal de Contas do Estado de Roraima — TCERR.
