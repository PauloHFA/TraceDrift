# Dataset Card — TraceDrift Synthetic Dataset

## Visão Geral
Este dataset foi gerado de forma **100% sintética** pelo **TraceDrift**, uma ferramenta para simulação realista de rastreamento distribuído (OpenTelemetry spans) e logs correlacionados com padrões de falha e degradações de microsserviços.

- **Natureza dos Dados**: Sintético (Livre de PII, senhas ou credenciais de produção).
- **Modelo Gerador**: `gpt-4o-mini`
- **Semente Aleatória**: `42`
- **Convenções Semânticas OTel**: `1.25.0`
- **Licença**: [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0)

---

## Estatísticas do Dataset

| Métrica | Valor |
| :--- | :--- |
| **Total de Traces** | 100 |
| **Traces Normais (Linha de Base)** | 0 (0.0%) |
| **Traces Anômalos** | 100 (100.0%) |
| **Total de Spans** | 310 |
| **Média de Spans por Trace** | 3.10 |
| **Total de Logs Correlacionados** | 120 |
| **Spans com Erro** | 45 (14.52%) |
| **Traces Rejeitados na Validação** | 0 |

### Percentis de Duração dos Traces
- **P50 (Mediana)**: 350.00 ms
- **P90**: 350.00 ms
- **P95**: 350.00 ms
- **P99**: 350.00 ms

---

## Distribuição de Anomalias

| Padrão de Anomalia | Contagem de Traces |
| :--- | :--- |
| `thundering_herd` | 5 |
| `database_lock_contention` | 5 |
| `circuit_breaker_tripping` | 5 |
| `downstream_network_partition` | 5 |
| `retry_storm` | 5 |
| `thread_pool_exhaustion` | 5 |
| `slow_consumer` | 5 |
| `n_plus_one_query` | 5 |
| `cache_stampede` | 5 |
| `partial_db_failure` | 5 |
| `cascading_timeout` | 5 |
| `connection_pool_starvation` | 5 |
| `dns_resolution_delay` | 5 |
| `garbage_collection_pause` | 5 |
| `rate_limiter_throttling` | 5 |
| `deadlock_abort` | 5 |
| `asynchronous_queue_overflow` | 5 |
| `microservice_fallback_degradation` | 5 |
| `hotspot_partition` | 5 |
| `memory_leak_latency_drift` | 5 |

---

## Limitações e Uso Recomendado
1. **Treinamento e Avaliação**: Indicado para treino supervisionado ou não supervisionado de detectores de anomalias em observabilidade.
2. **Testes de Plataforma**: Indicado para validação de ingestão em Jaeger, Tempo, SigNoz e OpenTelemetry Collector.
3. **Não utilizar para dimensionamento físico direto**: Os dados representam simulações probabilísticas e estruturadas, e não captura de profiling em nível de CPU/kernel.
