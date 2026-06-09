# ECG采样率、ADC位数与抗噪性能联合设计

这是一个面向可穿戴心电长时监护的可复现实验项目，用虚拟ECG采集链路评估采样率和ADC有效位数对R峰检测、RR间期、瞬时心率、HRV技术可用性、数据率和抗运动伪影能力的联合影响。

项目最终推荐配置仍为 **360 Hz / 6 bit**：在干净条件下合并F1为 **99.305%**，相对360 Hz / 11 bit参考配置下降 **0.086 pp**，单通道原始码率降至 **2160 bit/s**，约降低 **45.5%**。新增RR/HRV扩展分析用于说明该配置在心率与RR趋势监护中的技术适用性，并明确不做疾病诊断、心律失常分类或ST段形态判断。

## 在线/本地展示

本仓库包含一个纯静态交互展示页，适合作为课程展示入口：

- GitHub Pages: https://lebron-shun.github.io/ecg-sampling-adc-noise-robustness/
- 本地入口: [web/index.html](web/index.html)
- 完整性审核: [FINAL_AUDIT.md](FINAL_AUDIT.md)

```text
web/index.html
```

直接用浏览器打开即可查看。页面包含推荐配置卡片、医学监护场景、采样率/ADC位数交互筛选、Clean F1热力矩阵、SNR抗噪曲线、候选配置表和实验图集。

## 医学监护扩展

本项目将医学场景从“R峰检测是否稳定”扩展为“长时监护指标是否可靠”。新增 `src/monitoring_analysis.py` 对代表配置计算以下技术指标：

- RR间期绝对误差中位数与P95。
- 瞬时心率绝对误差中位数与P95。
- 连续匹配RR对比例。
- SDNN和RMSSD相对误差。
- HRV可用记录比例。

同时生成 `results/scenario_recommendations.json`，把不同监护目标映射到配置建议：HR/RR长时监护、HRV趋势观察、运动/噪声优先监护、极低数据率教学探索，以及明确不在范围内的ST/形态/临床诊断。

## 项目结构

```text
.
├── config.json                  # 实验参数
├── src/                         # 数据下载、实验、分析、报告生成和审核脚本
├── results/                     # 逐记录和聚合结果表
├── figures/                     # 自动生成的实验图
├── web/                         # 交互展示网页
├── data_manifest/               # 原始数据清单和校验信息
├── DATA_SOURCES.md              # 数据来源说明
└── FINAL_AUDIT.md               # 最终完整性审核
```

## 研究范围

- 信号：单导联ECG，使用第0通道。
- 任务：长程心率/RR监测中的R峰检测、RR间期误差、瞬时心率误差和HRV技术可用性分析。
- 采样率：360、250、180、125、100 Hz。
- ADC有效位数：11、10、9、8、7、6 bit。
- 干净数据：MIT-BIH Arrhythmia Database。
- 噪声数据：MIT-BIH Noise Stress Test Database。
- 检测器：固定参数的WFDB XQRS。

本项目不进行疾病诊断、心律失常分类、ST段分析、形态学判读、疾病风险解释或真实硬件功耗测量。原始数据库为360 Hz / 11 bit，因此本项目只研究降低采样率和降低有效位数后的表现，不外推到12 bit、16 bit或其他硬件系统。

## 复现实验

建议使用Python 3.10+。从仓库根目录执行：

```powershell
pip install -r requirements.txt
python src/download_data.py
python src/validate_data.py
python src/run_experiments.py --mode all --workers 8
python src/analyze_results.py
python src/monitoring_analysis.py
python src/build_web_data.py
python src/build_report.py
python src/build_pdf.py
python src/audit_project.py
```

所有脚本读取 `config.json`，结果表、图像和报告均由脚本生成，不需要手工改表。

## 数据说明

原始PhysioNet ECG信号文件不随仓库分发。请使用 `src/download_data.py` 重新下载，并用 `src/validate_data.py` 校验。仓库仅包含实验结果、图像、报告和数据清单。

数据来源与引用见 [DATA_SOURCES.md](DATA_SOURCES.md)。

## 主要输出

- [FINAL_AUDIT.md](FINAL_AUDIT.md)：完整性审核。
- [results/recommended_config.json](results/recommended_config.json)：推荐配置指标。
- [results/monitoring_summary.csv](results/monitoring_summary.csv)：代表配置RR/HRV监护指标。
- [results/scenario_recommendations.json](results/scenario_recommendations.json)：医学监护场景推荐。
- [figures/figure_09_monitoring_metrics.png](figures/figure_09_monitoring_metrics.png)：RR、心率和HRV指标图。
- [web/index.html](web/index.html)：交互展示页面。

课程提交用的完整报告不在公开仓库中分发，可通过 `src/build_report.py` 和 `src/build_pdf.py` 在本地生成。

## License

本项目代码以MIT License开源。数据集版权和使用条款归原始数据提供方所有。
