# Acompanhando um modelo contra a planta

Um acompanhamento fica verificando sozinho um modelo contra a planta. De forma agendada, ele simula
o modelo sobre a última janela de dados da planta (como **Usar dados da planta** faz na caixa de
diálogo Simular), grava **modelo menos planta** para cada variável comparada como um sinal no
PlantCraft e, quando há um limite definido, gera **Modelo afastado da planta** enquanto o erro
ficar acima dele.

Abra **Acompanhamento** e clique em **Novo acompanhamento**:

1. **Modelo**: o modelo a simular. As configurações dele (solver, parâmetros) são as que ele tem
   quando cada execução começa.
2. **Janela** e **A cada**: cada execução cobre os últimos *janela* minutos até agora, e uma
   execução começa a cada *a cada* minutos (no mínimo 5 minutos para os dois).
3. **Comparar com a planta**: uma linha por variável, `variable = signal`, por exemplo
   `tank.level = plant:LT-101`. Cada uma ganha um sinal de erro,
   `app-modelcraft:tracking-<id>.<variable>.error`, gravado nos instantes de amostragem da planta
   dentro da janela. Veja a tendência dele no View, use-o no Analytics ou configure alarmes sobre
   ele como qualquer sinal.
4. **Entradas da planta** (opcional): linhas `input = signal` alimentam as entradas do modelo a
   partir da planta, mantendo o último valor entre as amostras.
5. **Limites de alarme** (opcional): `variable = number`, o erro absoluto médio acima do qual a
   variável está afastada da planta. O evento abre quando uma execução termina acima do limite e
   fecha quando uma termina abaixo dele; ele vai para o responsável pelo acompanhamento quando
   fica aberto por 30 minutos.

Cada execução é uma simulação comum entre as simulações rápidas do modelo, com o nome do
acompanhamento como rótulo; as últimas 20 de cada acompanhamento são guardadas. A tabela mostra o
erro absoluto médio e o viés de cada variável na última execução, a própria execução e o motivo da
falha quando ela falhou (um sinal que não pôde ser lido, um modelo que não compila). **Executar
agora** inicia uma na hora; desmarque um acompanhamento para pausá-lo.

Os acompanhamentos leem a planta com o acesso do próprio Models (a conta de serviço da suíte), não
com o da pessoa que os criou: eles continuam rodando quando ninguém está conectado.
