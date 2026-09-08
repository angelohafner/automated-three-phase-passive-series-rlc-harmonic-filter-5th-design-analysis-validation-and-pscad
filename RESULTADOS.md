# Resultados executados no PSCAD 5.1

Execucao principal: **PSCAD 5.1.0 + mhi.pscad 3.1.2 + GFortran 8.1 (64-bit)**,
em 8 de setembro de 2026. Os valores abaixo vieram dos arquivos INF/OUT do EMTDC.
As seis simulacoes e as 964 verificacoes da analise principal passaram.

- [Relatorio completo, tabelas fasoriais e graficos](results/20260908_162820_819432_pscad/report.md)
- [Workspace para abrir no PSCAD](results/20260908_162820_819432_pscad/HarmonicFilter.pswx)
- [Projeto-base editavel](results/20260908_162820_819432_pscad/projects/HarmonicBase.pscx)
- [Projeto do filtro sintonizado](results/20260908_162820_819432_pscad/projects/tuned_5th.pscx)
- [Configuracao efetivamente executada](results/20260908_162820_819432_pscad/config.json)
- [CSV de todas as harmonicas e fases](results/20260908_162820_819432_pscad/comparison_harmonics.csv)
- [CSV de RMS, THD e validacao numerica](results/20260908_162820_819432_pscad/comparison_metrics.csv)
- [Convergencia com passo de 5 us](results/20260908_162820_819432_pscad/convergence.json)
- [Validacao adicional de carga linear e sequencia zero](results/20260908_163936_202713_pscad/report.md)

## Comparacao

Valores da fase A; as outras fases possuem os mesmos modulos, respeitando a
sequencia de cada ordem.

| Caso | THD corrente da rede | THD tensao no PCC |
| --- | ---: | ---: |
| Sem filtro | 26,9444% | 5,3222% |
| Sintonizado em 300 Hz | 12,1419% | 3,3632% |
| Dessintonizado em 285 Hz | 13,9126% | 3,5858% |
| Rede forte, Zg x 0,5 | 14,4075% | 1,9383% |
| Rede fraca, Zg x 2 | 9,3835% | 5,3537% |
| Fator de qualidade 20 | 12,6113% | 3,4024% |

As comparacoes de rede forte/fraca incluem mudanca de impedancia da rede, nao
apenas o efeito de conectar o filtro.

## Filtro sintonizado

R=0,03199944 ohm; L=0,84881163 mH; C=331,57855458 uF por fase, em estrela
aterrada. Fasores em A RMS / graus, com referencia em seno e t=0.

| Ordem | Frequencia | Iload | Isystem | Ifilter | Modulo no filtro | Modulo na rede |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 60 Hz | 100,0000 / 180,00 | 107,5066 / -160,34 | 36,1926 / 88,04 | 36,19% | 107,51% |
| 5 | 300 Hz | 20,0000 / 0,00 | 1,6812 / -81,98 | 19,8354 / 4,81 | 99,18% | 8,41% |
| 7 | 420 Hz | 14,0000 / 20,00 | 9,4522 / 20,16 | 4,5479 / 19,66 | 32,49% | 67,52% |
| 11 | 660 Hz | 9,0000 / -10,00 | 6,9390 / -9,83 | 2,0611 / -10,56 | 22,90% | 77,10% |
| 13 | 780 Hz | 7,0000 / 30,00 | 5,4836 / 30,14 | 1,5165 / 29,49 | 21,66% | 78,34% |

Na quinta ordem, por exemplo, as partes imaginarias das duas correntes de saida
se cancelam. Por isso 99,18% + 8,41% nao precisa resultar em 100%. O CSV tambem
fornece partes reais/imaginarias e as projecoes aditivas das razoes complexas.
O erro relativo maximo de KCL harmonica nos seis casos foi inferior a 1,1e-12%.

O RMS total da corrente da rede subiu de 103,5664 A para 108,2962 A, embora as
correntes harmonicas tenham diminuido. A fundamental subiu de 100 A para
107,5066 A devido a corrente capacitiva do filtro. Essa sobrecompensacao e
coerente com a carga fundamental inicial, proxima de fator de potencia unitario.

## Evidencias de validacao

- 14 testes unitarios de fasores, sequencias, dimensionamento, KCL e leitura OUT.
- Seis casos reais com verificacoes temporal e fasorial aprovadas.
- Maior erro por fasor versus referencia continua: aproximadamente 0,295%.
- Maior variacao entre janelas consecutivas: inferior a 0,000007%.
- Repeticao de `tuned_5th` com 5 us de integracao e gravacao: maior diferenca
  complexa em relacao a 10 us igual a 0,2201%, abaixo da tolerancia de 1%.
- Execucao adicional com carga linear de 20 kW: 184 verificacoes aprovadas.
  A 3a ordem mediu 5 A / 15 graus de sequencia zero; a 5a mediu 20 A / -25 graus
  de sequencia negativa; a 11a desativada ficou abaixo de 3e-11 A. A corrente
  linear fundamental da fase A foi 24,085 A e a KCL incluiu esse quarto ramo.

Ha um pequeno residuo numerico de alta frequencia na tensao, associado ao circuito
ideal e a inicializacao. Na gravacao a cada dois passos, ele aparece como um
pequeno desvio DC amostrado. Na verificacao a cada passo de 5 us, a DC da tensao
da fase A caiu para aproximadamente zero e o residuo nao harmonico foi 0,0831 V
RMS, ou 0,0299% da fundamental. Isso nao foi ocultado: DC, residuo e variacao do
passo estao explicitamente registrados e testados.

Os CSV completos conservam maior precisao que as tabelas arredondadas deste
resumo. O modo `--analytical` e uma referencia distinta, identificada nos seus
proprios arquivos, e nao foi usado para substituir resultados do PSCAD.

## Reproduzir

```powershell
python -m pip install -r requirements.txt
python run_study.py --config study_config.json
```

O [README](README.md) contem instalacao, equacoes, explicacao do circuito,
parametros, limites das edicoes e procedimento de validacao. A alternativa
sem montagem automatica esta em [projeto-base manual](docs/manual-template.md).
