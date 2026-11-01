# Simulando com dados da planta

Uma simulação pode tomar suas entradas do histórico da planta e ser desenhada contra os próprios
sinais da planta: o modelo está certo, e o que a planta teria feito com outra sintonia?

Na caixa de diálogo **Simular** do editor de código (**Código** na página de um modelo), marque
**Usar dados da planta**:

1. **De** e **Até**: o período do histórico da planta. A simulação o cobre, começando no tempo 0
   do modelo.
2. **Passo de amostragem**: a cada quanto tempo os sinais são lidos (em segundos). Um período pode
   ter até 100.000 amostras.
3. **Entradas da planta**: cada entrada de nível superior do modelo (um conector `RealInput`, ou
   uma variável `input Real`) pode seguir um sinal. Entre duas amostras o último valor é mantido,
   como a planta o registrou.
4. **Comparar com a planta**: uma variável do modelo (`tank.level`) e o sinal com que ela deve
   coincidir. O gráfico da simulação desenha as amostras do sinal ao lado da variável.

Os sinais são lidos pelo PlantCraft com o seu próprio acesso: você vê os sinais que o PlantCraft
lhe mostra. O gráfico de uma simulação assim fica no horário da planta.

Para acionar um modelo a partir da planta, dê entradas a ele. No exemplo `TankLevelControl`, a
carga do tanque vem de uma bomba; uma cópia com um `Modelica.Blocks.Interfaces.RealInput qin`
conectado ao `qIn` do tanque pode ser alimentada com um sinal de vazão no lugar.

A página de um ativo no Models (aberta a partir do ativo no PlantCraft) lista as simulações que
usaram os sinais dele.
