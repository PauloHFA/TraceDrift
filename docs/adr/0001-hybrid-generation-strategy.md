# ADR 0001: Estratégia Híbrida de Geração (LLM + Normalizer Determinístico)

## Status
Aceito

## Contexto
A geração sintética de traces de microsserviços exige estrita conformidade com identificadores hexadecimais únicos (`trace_id` de 32 chars, `span_id` de 16 chars), relações pai-filho acíclicas e precisão temporal em nanossegundos (`start_time_unix_nano` e `end_time_unix_nano`). Modelos de linguagem (LLMs) frequentemente cometem alucinações na aritmética de inteiros de 64 bits, geram timestamps incoerentes onde spans filhos terminam após o span pai, e falham na consistência de hashes hexadecimais entre spans.

## Decisão
Adotar a **estratégia híbrida** dividida em duas etapas complementares:
1. **LLM (Blueprint)**: Gera exclusivamente um esquema simbólico simplificado com rótulos (`s1`, `s2`), relações pai-filho (`parent_ref`), deslocamentos relativos em milissegundos (`offset_ms`) e durações (`duration_ms`), além de narrativas causais e mensagens de erro semânticas.
2. **Normalizer (Código Python Determinístico)**: Recebe o blueprint e a semente aleatória (`--seed`), atribuindo IDs hexadecimais reproduzíveis, convertendo milissegundos relativos para nanossegundos absolutos Unix, ajustando pequenas tolerâncias temporais (`--auto-fix` até 5%) e validando conformidade temporal (RNF01).

## Consequências
- **Positivas**: 100% de consistência temporal, reprodutibilidade perfeita via semente, redução drástica no consumo de tokens de saída da LLM (~60% de economia), eliminação de alucinações matemáticas.
- **Negativas**: Exige uma camada extra de serialização e validação interna no código.
