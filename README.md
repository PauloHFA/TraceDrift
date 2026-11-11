# TraceDrift

> Gerador sintético de traces OpenTelemetry, logs correlacionados e anomalias de observabilidade.

O **TraceDrift** gera datasets sintéticos de rastreamento distribuído (spans) e logs estruturados no padrão **OpenTelemetry (OTel)**, simulando degradações realistas de microsserviços (ex.: *cascading timeouts*, *retry storms*, *database lock contention*, *cache stampede*, etc.).

Serve para testar plataformas de observabilidade (**Jaeger**, **Grafana Tempo**, **SigNoz**, **Elasticsearch**) e treinar ou avaliar detectores de anomalias sem expor dados reais (PII, credenciais, IPs internos).

---

## Principais Recursos

- **Estratégia Híbrida**: A LLM gera apenas o *blueprint* arquitetural e causal; o código determinístico em Python materializa IDs, nanosegundos e conformidade estrita de convenções semânticas.
- **Catálogo de 20+ Anomalias**: Padrões de falha distribuída reais com assinaturas estatísticas e causais.
- **Conformidade OTel Protobuf**: Saídas em OTLP/JSON aceitas diretamente por `google.protobuf.json_format` e pelo OpenTelemetry Collector.
- **Validação em 4 Camadas**: Schema Pydantic, grafo NetworkX (aciclicidade e raiz única), consistência temporal (RNF01) e varredura de PII (RFC 5737 e RFC 1918).
- **CLI Completo**: Comandos `init`, `plan`, `generate`, `validate`, `send`, `report` e `visualize`.
- **Replay em Tempo Real**: Despacho de traces para Jaeger/Tempo deslocando timestamps para o momento atual.

---

## Instalação

Com [uv](https://github.com/astral-sh/uv):

```bash
uv sync --all-extras
```

Ou com `pip`:

```bash
pip install -e ".[dev]"
```

---

## Uso Rápido

1. **Inicializar configuração padrão**:
   ```bash
   tracedrift init
   ```
2. **Visualizar plano de geração (dry-run)**:
   ```bash
   tracedrift plan --flow configs/e_commerce_flow.yaml --count 50 --dry-run
   ```
3. **Gerar dataset**:
   ```bash
   tracedrift generate --flow configs/e_commerce_flow.yaml --count 50 --output datasets/demo/
   ```
4. **Visualizar no terminal (waterfall)**:
   ```bash
   tracedrift visualize datasets/demo/traces.jsonl
   ```
5. **Enviar para coletor OTLP**:
   ```bash
   tracedrift send datasets/demo/otlp_traces.json --endpoint http://localhost:4318
   ```

---

## Licença

Distribuído sob a licença [Apache-2.0](LICENSE).
