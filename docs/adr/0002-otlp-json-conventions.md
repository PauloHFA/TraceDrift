# ADR 0002: Adoção do Padrão Canônico OTLP/JSON e Atualização de Convenções Semânticas

## Status
Aceito

## Contexto
O padrão OpenTelemetry evoluiu significativamente, estabilizando novas convenções semânticas (SemConv v1.25.0+). Atributos legados como `http.method` e `http.status_code` foram substituídos por `http.request.method` e `http.response.status_code`. Além disso, para que os datasets sejam ingeridos sem erros pelo OpenTelemetry Collector, Jaeger e Tempo, o JSON de exportação deve respeitar estritamente o layout do protobuf oficial do OTel (`resourceSpans -> scopeSpans -> spans`, com atributos tipados em `AnyValue` e timestamps inteiros de 64 bits serializados como strings numéricas).

## Decisão
1. Fixar a versão das convenções semânticas em `1.25.0` e declará-la nos metadados de cada trace.
2. O normalizer converte automaticamente chaves legadas para as vigentes.
3. A exportação OTLP gera a estrutura canônica validada através de `google.protobuf.json_format.Parse`.
4. Todos os recursos exportados incluem atributos obrigatórios de identificação: `deployment.environment = "synthetic"` e `tracedrift.generated = true`.

## Consequências
- **Positivas**: Compatibilidade direta e transparente com Jaeger, Grafana Tempo e coletores modernos.
- **Negativas**: Requer conversão cuidadosa de dicionários Python simples para o formato `key: value: { stringValue: ... }`.
