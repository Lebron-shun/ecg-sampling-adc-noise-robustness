# ECG采样率、ADC位数与抗噪性能联合设计

这是一个面向可穿戴心电监护的可复现实验项目，用虚拟ECG采集链路评估采样率和ADC有效位数对R峰检测、数据率和抗运动伪影能力的联合影响。

项目最终推荐配置为 **360 Hz / 6 bit**：在干净条件下合并F1为 **99.305%**，相对360 Hz / 11 bit参考配置下降 **0.086 pp**，单通道原始码率降至 **2160 bit/s**，约降低 **45.5%**。最终审核结果为 **PASS，17/17项检查通过**。

## 在线/本地展示

本仓库包含一个纯静态交互展示页，适合作为课程展示入口：

- GitHub Pages: https://lebron-shun.github.io/ecg-sampling-adc-noise-robustness/
- 本地入口: [web/index.html](web/index.html)
- 最终报告: [report/final_report.pdf](report/final_report.pdf) / [report/final_report.docx](report/final_report.docx)
- 完整性审核: [FINAL_AUDIT.md](FINAL_AUDIT.md)

```text
web/index.html
```

直接用浏览器打开即可查看。页面包含推荐配置卡片、采样率/ADC位数交互筛选、Clean F1热力矩阵、SNR抗噪曲线、候选配置表和实验图集。

## 课程评分对照

| 指导书评分项 | 本项目对应材料 |
|---|---|
| 引言与医学应用背景 | 报告第1节给出可穿戴ECG监护场景、工程约束和任务边界 |
| 系统设计原理与关键技术方案 | 报告第2节给出虚拟采集链路、输入输出关系、核心参数和数据率计算 |
| 方法与实现过程 | 报告第3节说明MIT-BIH/NSTDB数据、XQRS检测器、本人实现工作和复现实验流程 |
| 结果展示与性能评价 | 报告第4节、`results/`和`figures/`给出全因子结果、抗噪分析、Pareto权衡和达标表 |
| 讨论与改进分析 | 报告第5节从医学应用、工程实现、算法和数据四类说明限制 |
| 图表质量与系统表达 | 报告统一图1-图8、表1-表8，并在正文引用；网页提供交互展示 |
| 引用、格式与语言规范 | `DATA_SOURCES.md`和报告参考文献列出PhysioNet、MIT-BIH、NSTDB、WFDB和QRS检测文献 |
| 附录资料 | 报告附录A-D给出核心参数、关键脚本、结果文件索引、GitHub和展示链接 |

## 项目结构

```text
.
├── config.json                  # 实验参数
├── src/                         # 数据下载、实验、分析、报告生成和审核脚本
├── results/                     # 逐记录和聚合结果表
├── figures/                     # 自动生成的实验图
├── report/                      # 最终课程报告 PDF / DOCX / Markdown
├── web/                         # 交互展示网页
├── data_manifest/               # 原始数据清单和校验信息
├── DATA_SOURCES.md              # 数据来源说明
└── FINAL_AUDIT.md               # 最终完整性审核
```

## 研究范围

- 信号：单导联ECG，使用第0通道。
- 任务：长程心率/RR监测中的R峰检测。
- 采样率：360、250、180、125、100 Hz。
- ADC有效位数：11、10、9、8、7、6 bit。
- 干净数据：MIT-BIH Arrhythmia Database。
- 噪声数据：MIT-BIH Noise Stress Test Database。
- 检测器：固定参数的WFDB XQRS。

本项目不进行疾病诊断、心律失常分类、ST段分析或真实硬件功耗测量。原始数据库为360 Hz / 11 bit，因此本项目只研究降低采样率和降低有效位数后的表现，不外推到12 bit、16 bit或其他硬件系统。

## 复现实验

建议使用Python 3.10+。从仓库根目录执行：

```powershell
pip install -r requirements.txt
python src/download_data.py
python src/validate_data.py
python src/run_experiments.py --mode all --workers 8
python src/analyze_results.py
python src/build_report.py
python src/build_pdf.py
python src/audit_project.py
```

所有脚本读取 `config.json`，结果表、图像和报告均由脚本生成，不需要手工改表。

## 数据说明

原始PhysioNet ECG信号文件不随仓库分发。请使用 `src/download_data.py` 重新下载，并用 `src/validate_data.py` 校验。仓库仅包含实验结果、图像、报告和数据清单。

数据来源与引用见 [DATA_SOURCES.md](DATA_SOURCES.md)。

## 主要输出

- [report/final_report.pdf](report/final_report.pdf)：最终课程报告。
- [report/final_report.docx](report/final_report.docx)：可编辑报告。
- [FINAL_AUDIT.md](FINAL_AUDIT.md)：完整性审核。
- [results/recommended_config.json](results/recommended_config.json)：推荐配置指标。
- [web/index.html](web/index.html)：交互展示页面。

## License

本项目代码以MIT License开源。数据集版权和使用条款归原始数据提供方所有。
