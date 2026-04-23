# WebSearch 流量生成工具

## 一、简介

本文件夹提供一个 **基于 WebSearch 工作负载的 HTSIM 流量生成器**，包含：

1. **Python 程序 `generate_traffic.py`**

   * 生成 HTSIM 兼容的 `.htsim` 流量文件
   * 支持任意拓扑（expander、clos、dragonfly、torus、dc、rail、zcube 等）
   * 支持灵活配置机架数量、每机架主机数、负载比例、CDF 文件等

2. **批量脚本 `batch_traffic.sh`**

   * 自动为多个拓扑、多个规模、多个负载生成所有流量组合
   * 每个拓扑自动归入独立目录
   * 支持并发控制（最大并发 8），运行稳定
   * 自动创建输出目录

---

## 二、Python 流量生成脚本：`generate_traffic.py`

### **基本用法**

```bash
python3 generate_traffic.py \
    -t 拓扑名 \
    -r 机架数 \
    -c 每机架主机数 \
    -l 负载比例 \
    -T 模拟时长(秒) \
    --coflow-window-ms 20 \
    --outdir 输出目录 \
    --workload CDF文件路径 (分布在flow_distr文件夹内)
```

### **示例**

```bash
python3 generate_traffic.py \
    -t expander \
    -r 130 \
    -c 5 \
    -l 0.10 \
    -T 1.001 \
    --coflow-window-ms 20 \
    --outdir ./flows/expander \
    --workload ./websearch.csv
```

### **输出文件格式**

输出为：

```
flows_<topo>_<R>racks_<C>c_<L>pct_<T>s.htsim
```

每行格式：

```
src_host dst_host flow_size_bytes start_time_ns group_id
```

其中 `group_id = floor(start_time_ns / (20ms))`（默认窗口 20ms，可通过 `--coflow-window-ms` 修改）。
如果要兼容旧 4 列格式，可加 `--no-group`。

---

## 三、批量生成脚本：`batch_traffic.sh`

该脚本自动遍历：

* 多个拓扑（expander / dc / dragonfly / torus / clos / rail / zcube）
* 每个拓扑的不同规模（RACKS、CVALUES）
* 多个负载比例 LOADS
* 自动创建输出目录
* 自动控制并发（最多 MAXJOBS 个任务同时运行，建议不要太多，默认8）

### **运行方式**

```bash
chmod 777 ./batch_traffic.sh
./batch_traffic.sh
```

脚本会自动生成所有 `.htsim` 文件，并按拓扑分类：

```
../tasks/websearch_traffic/expander/
../tasks/websearch_traffic/clos/
../tasks/websearch_traffic/dc/
...
```

### **并发限制（最大 8 个）**

脚本中定义：

```bash
MAXJOBS=8
```

无论你的服务器有多少核，最多只会同时运行 8 个 Python 任务。
适用于大规模并行但对 IO、CPU 有限制的环境。

---

## 四、目录结构

生成后的目录结构示例：

```
tasks/
└── websearch_traffic/
    ├── expander/
    │    ├── flows_expander_66racks_16c_1pct_1.001s.htsim
    │    ├── flows_expander_66racks_16c_5pct_1.001s.htsim
    │    └── ...
    ├── dc/
    ├── dragonfly/
    ├── torus/
    ├── clos/
    ├── rail/
    └── zcube/
```

---

## 五、WebSearch CDF 文件

`generate_traffic.py` 读取一个 CSV 文件：

```
flow_size_bytes, cdf_value
...
```

示例：`websearch.csv`

该 CDF 决定流量大小分布。

---

## 六、注意事项

* 若输出文件已存在，将被 **覆盖**（使用 write 模式写入）
* `batch_traffic.sh` 会自动创建所有输出目录
* 若要添加新拓扑，只需在脚本中配置：

```bash
RACKS_MAP[topo]="..."
CVALUES_MAP[topo]="..."
```

