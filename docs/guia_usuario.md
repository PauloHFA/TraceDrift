# Guia do Usuário — TraceDrift

Bem-vindo ao **TraceDrift**, o gerador sintético de traces OpenTelemetry e logs correlacionados com simulação de anomalias distribuídas.

---

## 1. Primeiros Passos

### Inicialização do Projeto
Para começar em um novo diretório de trabalho:
```bash
tracedrift init
```
Este comando cria o arquivo de topologia `flow.yaml` e o modelo de configuração de credenciais `.env.example`.

### Configuração de Credenciais
Copie o `.env.example` para `.env` e configure seu provedor preferido compatível com OpenAI:
```bash
OPENAI_API_KEY=sua_chave_aqui
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```
*(Para usar com Ollama local, defina `OPENAI_BASE_URL=http://localhost:11434/v1`)*.

---

## 2. Fluxo de Trabalho

### Passo 1: Pré-visualizar o Plano de Geração (`plan`)
Antes de gastar tokens ou chamar modelos, visualize o planejamento estatístico:
```bash
tracedrift plan --flow configs/e_commerce_flow.yaml --count 100 --anomaly-ratio 0.2 --dry-run
```

### Passo 2: Gerar os Datasets (`generate`)
Execute a geração em lote assíncrona:
```bash
tracedrift generate --flow configs/e_commerce_flow.yaml --count 50 --output datasets/demo/
```
Arquivos gerados:
- `traces.jsonl`: Formato interno legível e enriquecido.
- `labels.jsonl`: Rótulos de verdade-terreno para treinamento/avaliação de Machine Learning.
- `otlp_traces.json`: Formato canônico OTLP/JSON aceito pelo OpenTelemetry Collector.
- `otlp_logs.json`: Logs OTLP correlacionados por trace e span ID.

### Passo 3: Visualizar Traces no Terminal (`visualize`)
Renderize as árvores e gráficos de cascata (waterfall) coloridos:
```bash
tracedrift visualize datasets/demo/traces.jsonl --count 3
```

### Passo 4: Subir Ambiente de Demonstração e Enviar Traces (`send`)
Suba o OpenTelemetry Collector e o Jaeger:
```bash
docker compose -f deploy/docker-compose.yml up -d
```
Envie os traces gerados com ajuste em tempo real:
```bash
tracedrift send datasets/demo/otlp_traces.json --endpoint http://localhost:4318/v1/traces --replay-realtime
```
Abra a interface web do Jaeger em `http://localhost:16686` para navegar pelos traces e analisar as causas-raiz!
