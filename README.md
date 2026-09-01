# FIO Plot Automation

Aplicação console em Python para gerar gráficos a partir de resultados de
benchmark FIO, reutilizando a biblioteca **fio-plot** como dependência.

A seleção de entrada é **baseada em diretório**: cada pastas corresponde a um
run de benchmark (um disco/sistema testado) e contém os arquivos gerados pela
ferramenta:
- `resultado.json` — saída JSON completa do fio (`--output-format=json`);
- `*.N.log` — arquivos de log de IOPS/latência por job (`--write_*_log`).

Os arquivos dentro de cada pasta são detectados e roteados automaticamente de
acordo com a opção de gráfico escolhida. O gráfico é salvo como PNG e aberto
automaticamente.

## Opções disponíveis

1. **2D Chart - Compare Benchmark Results** - Compara resultados de benchmark
   entre **múltiplos diretórios** (um run por pasta), usando o `resultado.json`
   de cada um.
2. **Line Chart - FIO Log Data** - Gráfico de linha a partir dos **arquivos de
   log** (`*.N.log`) de um único diretório, mostrando read/write ao longo do
   tempo.
3. **Latency Histogram** - Histograma da distribuição de latência a partir do
   `resultado.json` de um único diretório.

Ao selecionar diretórios, o programa oferece atalhos para as pastas de
benchmark padrão (HD Computador, NVME Kingston, HD Note) ou permite navegar
por uma pasta via diálogo (tecla `b`), ou usar todas (`all`).

## Como usar

Requisito: `fio-plot` como dependência.

```bash
pip install -r requirements.txt
python plot_app.py
```

O programa apresenta um menu interativo: escolha o tipo de gráfico, selecione
o(s) diretório(s) de entrada e o programa detecta automaticamente `rw`,
`iodepth` e `numjobs` a partir do `resultado.json` (sem precisar informar
manualmente). Apenas o `filter` (read/write) para dados `randrw` precisa ser
escolhido quando relevante.

## Requisitos dos dados de entrada

Cada diretório de benchmark deve conter:

- **`resultado.json`** — saída válida do fio (`fio --output-format=json`) com
  `rw`, `iodepth` e `numjobs` nas job options. Usado na comparação (opção 1) e
  no histograma (opção 3), além de fornecer o workload para os logs (opção 2).
- **Arquivos `*.N.log`** — logs FIO por job (formato `time,value,rwt,bs,offset`
  por linha), nomeados como `iops_iops.1.log`, `iops_iops.2.log`, etc. Usados
  no gráfico de linha (opção 2).

No gráfico de linha, o programa lê o tipo de métrica (`bw`, `iops`, `lat`, ...)
do nome do arquivo de log e copia/renomeia os logs para o padrão que o fio-plot
espera (`<rw>-iodepth-<N>-numjobs-<M>_<tipo>.<job>.log`), de forma automática.
