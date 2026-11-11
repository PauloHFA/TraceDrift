# ADR 0003: Arquitetura Assíncrona, Escrita em Streaming e Retomada de Execução

## Status
Aceito

## Contexto
A geração de grandes volumes de traces (até 100.000 requisições) impõe dois grandes desafios: controle de concorrência com chamadas de I/O intensivo para provedores de LLM e consumo de memória RAM (< 1 GB) durante a exportação para o disco. Adicionalmente, falhas de rede ou interrupções manuais (Ctrl+C) não devem perder o progresso já gerado.

## Decisão
1. Utilizar `asyncio` e semáforos (`asyncio.Semaphore(concurrency)`) para controlar rigorosamente a vazão de chamadas simultâneas à API.
2. Adotar escrita em streaming assíncrono com `aiofiles` (`append` contínuo em `traces.jsonl` e `labels.jsonl`), evitando acumular centenas de milhares de traces em memória.
3. Manter arquivo de checkpoint de estado (`.tracedrift_state.json`) contendo os índices de traces já finalizados, viabilizando retomada imediata com `--resume`.

## Consequências
- **Positivas**: Baixo uso de memória (< 1 GB), resiliência a quedas e interrupções, vazão escalável de acordo com o limite do provedor LLM.
