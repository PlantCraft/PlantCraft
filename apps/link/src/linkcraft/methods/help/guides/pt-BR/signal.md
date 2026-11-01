# Um sinal

Os dados de um sinal na janela do algoritmo, com os eventos que cada verificação encontrou
desenhados no gráfico (lacunas, trechos congelados, picos, valores fora dos limites), o resultado
de cada verificação e o histórico da qualidade.

Os editores podem:

- **Verificar agora**: julgar o sinal de novo na janela do algoritmo (salvo), ou em outra janela
  (não salvo).
- **Alterar as configurações**: limites que substituem os do PlantCraft, um sinal de referência
  para a verificação de deriva, verificações desativadas ou ativadas para este sinal, e parâmetros
  das suas verificações.
- **Desativá-lo**: o algoritmo o ignora.

Sinais com o papel de setpoint, modo ou saída do controlador em um ativo do PlantCraft não passam
pela verificação de valor congelado: um setpoint e um modo são constantes por projeto, e uma saída
parada é o estado da malha (uma válvula saturada, modo manual), que os métodos de malha julgam.
Ative-a para um sinal se quiser.

## Análises de laboratório

Um sinal de uma fonte de arquivo (CSV: análises de laboratório, entradas manuais) é **amostrado** e
não é julgado como um sinal de processo. Seu valor se repete até a próxima análise, e amostras com
horas de intervalo são normais, então ele não passa pelas verificações de valor congelado, ruído e
resolução. O frescor e as lacunas são medidos contra o intervalo de amostragem: atenção quando uma
análise atrasa meio intervalo, ruim com três intervalos sem nenhuma. Faixa, picos (saltos entre
amostras) e deriva ainda o julgam. O intervalo é lido das próprias amostras (4 h quando há poucas);
defina-o em **Intervalo de amostragem**. **Amostragem** marca qualquer sinal como de laboratório ou
como contínuo, qualquer que seja sua fonte.
