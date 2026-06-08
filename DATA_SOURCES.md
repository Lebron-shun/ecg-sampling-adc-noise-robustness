# Data Sources and Reproduction

The raw ECG databases are not redistributed in the final project package.
They can be downloaded reproducibly with:

```powershell
python src/download_data.py
python src/validate_data.py
```

## MIT-BIH Arrhythmia Database

- Official page: https://physionet.org/content/mitdb/1.0.0/
- Use in this project: clean-condition full-factorial evaluation
- Records used: all 48 records listed by the official `RECORDS` file
- Original specification used by this project: 360 Hz, 11-bit, 10 mV range

## MIT-BIH Noise Stress Test Database

- Official page: https://physionet.org/content/nstdb/1.0.0/
- Use in this project: standardized electrode-motion artifact evaluation
- Records used: `118e*` and `119e*` at 24, 18, 12, 6, 0, and -6 dB

## Attribution

1. Moody GB, Mark RG. The impact of the MIT-BIH Arrhythmia Database.
   IEEE Engineering in Medicine and Biology Magazine. 2001;20(3):45-50.
2. Goldberger AL, et al. PhysioBank, PhysioToolkit, and PhysioNet.
   Circulation. 2000;101(23):e215-e220.

The locally generated `data/data_manifest.csv` contains file sizes, SHA-256
hashes, and official download URLs. The final package includes the manifest
without including raw signal files.
