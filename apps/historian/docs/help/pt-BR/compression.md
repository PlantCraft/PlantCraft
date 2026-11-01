# Compressão

O Historian usa a compressão **swinging-door** (Bristol, 1990), o método dos historiadores desta
categoria.

1. Cada valor lido é mantido como o *snapshot*: as leituras sempre o incluem, para que as
   tendências cheguem até o presente.
2. Um valor mantido só é arquivado quando o valor seguinte mostra que uma reta a partir do último
   valor arquivado já não consegue passar dentro do *desvio* de cada valor lido no meio.
3. Um valor é arquivado pelo menos a cada *intervalo máximo*, mesmo em um sinal constante.
4. Os sinais de degrau e de texto arquivam cada mudança, com o valor mantido logo antes dela,
   para que um degrau reconstruído seja exato.
5. Qualidade ruim ou conexão perdida arquiva um marcador de lacuna; o próximo valor bom começa
   uma nova linha.
6. Um valor que se mantém e depois salta mais do que o desvio é arquivado na sua última leitura
   antes do salto (um *marcador de degrau*), para que a tendência desenhe um degrau, e não uma
   rampa a partir do último valor arquivado.
7. Um sinal numérico pode definir um *menor intervalo entre valores arquivados* (vazio: nenhum,
   como o CompMin do PI): uma mudança mais rápida fica retida até lá, e a compressão continua a
   partir dela. Lacunas, mudanças de qualidade e sinais de degrau ou de texto nunca ficam retidos.

Uma tendência reconstruída ligando os valores arquivados com retas nunca fica mais longe do que
o desvio de qualquer valor lido. As médias sobre uma grade são integrais exatas, ponderadas no
tempo, dessa tendência reconstruída.
