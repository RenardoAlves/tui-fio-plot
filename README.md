# FIO Plot Automation

Aplicação console em Python para gerar gráficos a partir de resultados de
benchmark FIO, reutilizando a biblioteca **fio-plot** como dependência.

A seleção de entrada é **baseada em arquivo** (via diálogo), fazendo o staging
dos arquivos escolhidos em diretórios temporários, já que o fio-plot trabalha
internamente com diretórios. O gráfico é salvo como PNG e aberto automaticamente.

## Opções disponíveis

1. **2D Chart - Compare Benchmark Results** - Compara resultados de benchmark
   (IOPS/latência) entre **múltiplos arquivos JSON** selecionados (um por run),
   a partir de `fio --output-format=json`.
2. **Line Chart - FIO Log Data** - Gráfico de linha a partir de um **único arquivo
   de log** do FIO (`--write_*_log`), formato `time,value,direction` por linha.
3. **Latency Histogram** - Histograma da distribuição de latência a partir de um
   **único arquivo JSON** do FIO.

## Como usar

Requisito: `fio-plot` como dependência.

```bash
pip install -r requirements.txt
python plot_app.py
```

O programa apresenta um menu interativo: escolha o tipo de gráfico, selecione o(s)
arquivo(s) de entrada e informe os parâmetros necessários (rw, iodepth, numjobs,
etc.). Sem necessidade de passar argumentos em linha de comando.

## Requisitos dos dados de entrada

- **JSON** (para 2D compare e histograma): precisa ser saída válida do fio
  (`fio --output-format=json`) e conter `rw`, `iodepth` e `numjobs` nas job options.
  Para o histograma, o JSON deve conter os dados de histograma de latência
  (`latency_ms`, `latency_us`, `latency_ns`).
- **Logs FIO** (para line chart): nomeados no padrão
  `[rwmode]-iodepth-[N]-numjobs-[N]_[tipo].[job].log`,
  ex.: `randwrite-iodepth-8-numjobs-8_bw.1.log`.

### 2D Chart - comparar resultados (JSON)

- Selecione **pelo menos dois** arquivos JSON (um benchmark por arquivo).
- Defina um único `iodepth` e um único `numjobs` (iguais nos JSONs).
- O gráfico compara os arquivos (runs) selecionados entre si.

### Line Chart - log data

- Selecione um **único** arquivo de log FIO.
- Informe `rw`, `iodepth` e `numjobs` que correspondam ao nome do arquivo (padrão acima).
- Informe o tipo de métrica (`bw`, `iops`, `lat`, etc.).

### Latency histogram (JSON)

- Selecione um **único** arquivo JSON contendo dados de histograma de latência.
- Informe `iodepth` e `numjobs` que correspondam às job options do JSON.
