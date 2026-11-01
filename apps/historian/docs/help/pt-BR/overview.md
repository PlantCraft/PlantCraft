# Visão geral

A página de visão geral diz se o Historian está coletando e quanto ele guarda.

- **Coletor**: rodando ou parado, com a hora do seu último sinal de vida (heartbeat). O Historian
  arquiva uma lacuna para cada sinal quando o coletor para, para que as tendências nunca tracem
  uma linha atravessando o tempo fora do ar.
- **Sinais**: quantos estão coletando, esperando, falhando ou desabilitados.
- **Arquivo**: valores arquivados, bytes em disco e a taxa de compressão (valores lidos por valor
  guardado).
- **Fontes**: cada servidor OPC UA, seu estado e seu último erro.
