# Bundled UnRAR

Unmodified, signed **UnRAR 7.23 x64** by Alexander Roshal / win.rar GmbH.
This is the free command line reader, not WinRAR or the RAR compression program.
Archive Studio only uses its `p` (stdout) command after validating member names.

- Official stable package: https://www.rarlab.com/rar/winrar-x64-723.exe
- Official UnRAR distribution and license: https://www.rarlab.com/rar_add.htm
- Exact source package and binary SHA-256: `provenance.json`
- Redistribution terms: `license.txt` (explicitly permits inclusion in other software packages).

The Windows Authenticode signature was verified as valid for win.rar GmbH at import.
Only `UnRAR.exe` is included; the WinRAR installer was never run.
Builds verify its SHA-256 and include this notice and the license.

RAR creation is not included. The RAR compression algorithm is proprietary;
this component must not be used to recreate it.
