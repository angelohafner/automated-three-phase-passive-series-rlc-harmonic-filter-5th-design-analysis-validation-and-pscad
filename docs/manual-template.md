# Alternativa com projeto-base montado no PSCAD

Esta alternativa usa a mesma rotina `configure_case()`, o mesmo leitor de saida
e a mesma analise, mas nao chama `CircuitBuilder.build()`. O Python copia o projeto
original para a pasta da execucao, altera os parametros da copia e salva um projeto
para cada caso. A configuracao de harmônicas do template deve coincidir com a do
JSON, inclusive as ordens desativadas. Nomes ausentes ou duplicados causam erro.

## Uso de um projeto-base existente

Pode-se usar `projects/HarmonicBase.pscx` produzido pela montagem automatica como
base editavel. A sintaxe tambem se aplica a um projeto criado inteiramente a mao:

```powershell
.\.venv\Scripts\python.exe run_study.py --config study_config.json --template C:\Studies\HarmonicBase.pscx
```

O modo template pressupoe componentes Master em `Main`, sem bibliotecas externas,
resources ou submodulos personalizados. A copia nao transporta dependencias
externas de outros tipos de projeto.

## Criacao manual

1. Crie uma workspace e um projeto chamado `HarmonicBase` no PSCAD 5.1.
2. Monte os tres circuitos de fase descritos no README, em estrela aterrada.
3. Use componentes da tabela abaixo e atribua os nomes exatos.
4. Insira os controles senoidais, somadores e labels de dados.
5. Insira os canais de saida e confira suas escalas.
6. Configure o projeto para salvar canais em OUT, execute manualmente um caso
   e confira os sentidos dos amperimetros. Salve o arquivo `.pscx`.
7. Execute o comando acima. O script redimensiona o filtro, reconfigura as
   harmonicas e executa os casos selecionados.

## Contrato de componentes

Substitua `{p}` por A, B ou C, e `{h}` pela ordem inteira (1, 5, 7, 11 ou 13).
Os parametros numericos sao reescritos pelo Python. Escolhas topologicas como
fonte ideal, controle externo e polaridade devem estar corretas no template.

| Definicao real | Nome no projeto | Parametros essenciais |
| --- | --- | --- |
| master:source_1 | GridSource_{p} | Type=Ideal; Grnd=Yes; Spec=Behind; Cntrl=Internal; AC=AC; Vm em kV RMS fase-neutro; f em Hz; Ph em graus; Tc=0.02 s |
| master:resistor | GridR_{p} | R em ohm |
| master:inductor | GridL_{p} | L em H |
| master:src_ccin_1 | HarmonicSource_{p} | Cntrl=Yes; Mag ligado ao sinal CurrentCommand_{p} em kA instantaneos |
| master:ammeter | Iload_{p} | N1 no lado da fonte de corrente, N2 no PCC |
| master:ammeter | Isystem_{p} | N1 no PCC, N2 na rede |
| master:ammeter | Ifilter_{p} | N1 no PCC, N2 no filtro |
| master:voltmetergnd | Vpcc_{p} | N1 no PCC |
| master:breaker1 | NAME=FilterState | RON=1e-6 ohm; ROFF=1e12 ohm; ENAB=No; OPCUR=No |
| master:resistor | FilterR_{p} | R em ohm |
| master:inductor | FilterL_{p} | L em H |
| master:capacitor | FilterC_{p} | C em uF |
| master:const | FilterEnabled | Value=0 conectado; Value=1 desconectado; OUT com label FilterState |
| master:const | Zero | Value=0; OUT com label ZeroSignal |
| master:time-sig | sem nome exigido | OUT com label SimulationTime |
| master:gain | Omega_{p}_{h} | G=2*pi*h*f1; IN=SimulationTime |
| master:const | Phase_{p}_{h} | Value=(phi_h+h*theta_p) em radianos |
| master:sumjct | Angle_{p}_{h} | D=add, F=add, demais entradas disable |
| master:trig | Sine_{p}_{h} | Type=Sin; Mode=Radians; const=False |
| master:gain | Amplitude_{p}_{h} | G=sqrt(2)*Ih/1000, ou 0 se desativada |
| master:gain | Command_{p} | G=1; OUT com label CurrentCommand_{p} |

O nome de controle `NAME` do disjuntor e uma referencia ao sinal `FilterState`.
Nao e um numero de porta. Os tres disjuntores usam esse mesmo sinal. `BOpen` e
uma indicacao grafica e nao substitui o comando de abertura.

Conecte cada `Omega.OUT` a `Angle.IND`, `Phase.OUT` a `Angle.INF`, `Angle.OUT` a
`Sine.IN` e `Sine.OUT` a `Amplitude.IN`. Combine todos os `Amplitude.OUT` usando
somadores de duas entradas configurados para soma. Ligue o ultimo resultado a
`Command.IN`. Labels de dados podem substituir fios de controle longos.

A fonte de corrente tem corrente positiva do terminal B para A. Ligue B ao
neutro e A ao lado N1 de Iload. A fonte de tensao tem terminal NA ativo e NB de
referencia. As portas foram verificadas no XML da Master Library e pela API.

## Canais de saida

Insira 15 componentes `master:pgb`, um por nome abaixo, e ligue a entrada `Signl`
ao respectivo sinal medido usando `master:datalabel`:

```text
Iload_A    Isystem_A    Ifilter_A    Ilinear_A    Vpcc_A
Iload_B    Isystem_B    Ifilter_B    Ilinear_B    Vpcc_B
Iload_C    Isystem_C    Ifilter_C    Ilinear_C    Vpcc_C
```

Em cada PGB: `Name` igual ao nome acima, `UseSignalName=No`, `Scale=1000`,
`Units=A` para correntes e `Units=V` para tensoes. A escala converte as grandezas
internas em kA/kV para SI no arquivo gravado. O leitor Python nao converte outra vez.

Sem carga linear, conecte os PGB `Ilinear_{p}` ao sinal `ZeroSignal`. Com carga
linear, monte `Ilinear_{p}` como amperimetro e `LinearR_{p}` como resistor por fase.
O script rejeita um template com resistores lineares quando o JSON pede carga
linear desativada. Use um template com topologia compativel.

## Inspecao antes de executar

Use `project.find_all("master:gain")` para listar os ganhos e
`project.find("master:gain", "Amplitude_A_5").parameters()` para confirmar nomes.
`component.ports()` retorna apenas portas ativas apos configurar as escolhas.
Nao use coordenadas em pixels extraidas do XML como unidades do canvas: as
coordenadas retornadas pela API ja estao em unidades de grade.

As entradas do projeto `time_step` e `sample_step` sao em microssegundos;
`time_duration` e em segundos. `PlotType="OUT"` produz INF e blocos OUT.
As medicões de todas as fases, os testes de KCL e a comparacao fasorial continuam
obrigatorios no modo template. Ter os nomes corretos nao prova que os fios estejam
conectados corretamente.
