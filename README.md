# Archive Studio 檔案工具

Windows 10 / 11 64 位元桌面程式。支援壓縮包與照片轉檔。繁體中文介面，所有檔案在本機處理，不需登入或上傳。

[下載 Windows 可攜版](https://github.com/charlesjian95-source/archive-studio/releases/latest) · [原始碼](https://github.com/charlesjian95-source/archive-studio)

## 開啟程式

到 Releases 下載 Windows 可攜版 ZIP，將整個 ZIP 解壓縮後，開啟 ArchiveStudio.exe。
如果是從原始碼下載的專案，請依下方「從原始碼執行與打包」操作；本機最新建置路徑記錄在 dist\latest.json。
請保留同層的 _internal 資料夾；若要搬移程式，請搬移整個 ArchiveStudio 資料夾。
使用打包完成的程式不需要另外安裝 Python。

如果拿到 ArchiveStudio-Windows-x64.zip，請先將整個壓縮包解壓縮，再開啟裡面的 ArchiveStudio.exe。

## 1.3：外觀更新

- 統一淺色底、圓角卡片、字體層級與間距。
- 功能切換加入圖示與明確選取狀態。
- 加入檔案、一般操作、主要開始按鈕以不同層級呈現。
- 照片頁改為左側清單／設定，右側獨立大預覽。
- 透明照片用棋盤格顯示，方便辨識透明區域與輸出背景。
- 清單改為簡潔表頭與交錯底色。
- 小視窗收起輔助說明，保留清單、設定及預覽空間。
- 更新程式圖示、欄位焦點提示與下拉清單樣式。

## 1.2：照片轉檔與操作體驗

新增「照片轉檔」頁面，支援一次加入多張照片或整個資料夾（含子資料夾）。

- 讀取 JPG/JPEG、PNG、WebP、HEIC/HEIF、AVIF、BMP、TIFF，以及單張 GIF。
- 輸出 JPG、PNG、WebP、AVIF、TIFF、BMP。
- 選取照片後，可切換原圖與轉檔預覽，看到原始尺寸、預計輸出尺寸及估計檔案大小。
- 按「放大」可同時查看原圖與轉檔結果。
- 內建高畫質 JPG、網頁 WebP、透明 PNG、分享用 JPG 快速預設。
- 品質 1–100；可保留原尺寸或限制最長邊，保持比例且不放大小照片。
- JPG/BMP 的透明區域可選白底或黑底；其他支援透明的格式保留透明。
- 依 EXIF 自動校正直向／橫向照片。可選擇保留拍攝資訊（包含位置）；預設不保留拍攝資訊。
- 批次中單張失敗會繼續其他照片，完成後可以查看逐張結果及失敗原因。
- 每批輸出另建新資料夾，同名自動編號；資料夾來源保留原有子資料夾結構。
- 記住照片格式、品質、尺寸、拍攝資訊選項、上次加入的位置與已存在的輸出資料夾。
- Ctrl+O 加入檔案，Ctrl+Shift+O 加入資料夾，Ctrl+Enter 開始，Esc 取消工作。
- 清單中的 Delete 與移出按鈕只移出選取項目；實際檔案保留。
- 開始按鈕只在已有可處理項目時啟用；切換頁面可重新開啟該頁上次完成的輸出。
- 照片與資料夾右鍵加入「使用 Archive Studio 轉換照片」。
- 開始功能表新增「Archive Studio 照片轉檔」，可直接搜尋「照片轉檔」。

單批最多 10,000 張照片；單張最多 6,000 萬像素。
本功能處理單張、標準 8 位元照片；動畫 GIF/WebP、連拍多張 HEIF 與多頁 TIFF 會顯示失敗原因，不會靜默只保留第一張。RAW、SVG、PDF 不在照片轉檔範圍。
若保留 EXIF，JPG、PNG、WebP、AVIF、TIFF 可保存支援的拍攝資訊；BMP 不支援這項資訊。
品質調整適用 JPG/WebP/AVIF；PNG/TIFF 使用無損壓縮，BMP 為未壓縮輸出。

操作設計參考官方介紹：
- XnConvert 的批次轉換、可重用預設與尺寸轉換：https://www.xnview.com/en/xnconvert/
- PowerToys Image Resizer 的快速尺寸、等比例縮放與照片右鍵入口：https://learn.microsoft.com/en-us/windows/powertoys/image-resizer

## 1.1 更新

- 介面改為上方功能切換，尺寸、字型與間距隨 Windows DPI 調整。
- 檔案清單會隨視窗伸展；小視窗自動收起輔助說明，保留操作空間。
- 加入空清單提示。
- 對檔案／資料夾按右鍵可以「使用 Archive Studio 壓縮」。
- 對支援的壓縮包按右鍵可以解壓縮或轉換格式，選取內容會自動帶入。
- 透過「開啟方式」啟動支援的壓縮包時，預設進入解壓縮頁面。
- 本程式可加入「開啟方式」清單；不會自動取代既有的預設開啟程式。

首次搬到其他電腦時，開啟程式後按右上方「Windows 整合」，或執行同資料夾的「加入右鍵選單.cmd」。
Windows 11 的舊式右鍵功能可能位於「顯示其他選項」中。
右鍵選單一次帶入一個檔案／資料夾；多個項目可在程式內加入或一起拖入。

## 使用方法

1. 在上方選「壓縮檔案」、「解壓縮」、「壓縮包互轉」或「照片轉檔」。
2. 加入檔案／資料夾，或將檔案拖進視窗。
3. 選擇名稱、格式、壓縮程度與儲存位置，按下開始。
4. 完成後按「開啟輸出位置」。

壓縮可以同時加入多個檔案與資料夾；解壓縮、轉換一次處理一個壓縮包。
「移出清單」及「清空清單」只調整選取項目，不會刪除實際檔案。

## 支援格式

| 操作 | 支援格式 |
| --- | --- |
| 建立壓縮包 | ZIP、TAR、TAR.GZ |
| 解壓縮 | ZIP、TAR、TAR.GZ，另可讀取 TAR.BZ2、TAR.XZ |
| 格式互轉 | 上述可讀格式轉成 ZIP、TAR 或 TAR.GZ |

ZIP 適合 Windows 分享。TAR 只有打包、不壓縮；TAR.GZ 同時打包與壓縮。
「壓縮包互轉」處理壓縮包格式；照片內容格式請使用獨立的「照片轉檔」頁面。
不支援 RAR、7Z、分卷壓縮、加密 ZIP，或寫入密碼。
JPG、MP4、現有壓縮檔等內容可能無法再顯著縮小。

## 檔案保護與限制

- 原始檔保留；遇到同名輸出會自動加上編號。
- 解壓縮永遠另建新資料夾；格式互轉採串流處理，不需先解壓到暫存資料夾。
- 取消或失敗的內容會標記為 .partial 並保留，不會自動清除；介面會顯示位置。
- 不接受壓縮包內的絕對路徑、上層跳轉、符號連結、硬連結、裝置檔、Windows 保留檔名、重複檔名和大小寫衝突。
- 單次未壓縮內容上限 20 GB、最多 100,000 個項目。程式會先檢查磁碟空間。
- 保留一般檔案內容、結構與檔案修改時間；不保留 NTFS 權限、替代資料串流、檔案擁有者或連結。
- 請避免在執行期間修改來源或輸出資料夾。

## 從原始碼執行與打包

建議使用 Python 3.10。先在 PowerShell 建立獨立環境，再安裝依賴：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe archive_studio.py
```

測試（介面測試需要可開啟視窗的 Windows 環境）：

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_archive_engine test_launch test_photo_engine
.\.venv\Scripts\python.exe layout_regression.py
.\.venv\Scripts\python.exe gui_smoke_test.py
.\.venv\Scripts\python.exe photo_ui_regression.py
```

打包 Windows 可攜版：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe build.py
.\.venv\Scripts\python.exe verify_release.py
.\.venv\Scripts\python.exe test_packaged_launch.py
```

若自行建立環境，先安裝 requirements-build.txt。
build.py 若遇到既有輸出，會建立新版本資料夾，不會清除舊版本。
.test-runs 與 .build 是保留的測試／建置資料，不需要隨程式散布。

主要檔案：
- archive_studio.py：視窗介面
- archive_engine.py：壓縮、解壓與串流轉換
- photo_engine.py：照片格式轉換、拍攝方向、色彩、尺寸與批次處理
- photo_panel.py：照片清單、預覽、快速預設與逐張結果
- photo_workspace.py：照片頁左右分區配置
- visual_theme.py：共用配色、圓角卡片、按鈕與圖示
- test_archive_engine.py：核心整合測試
- gui_smoke_test.py：介面流程與配置檢查
- build.py：Windows 可攜版打包

本程式使用 Python 的 zipfile、tarfile、tkinter，加上 Pillow 與 pi-heif（僅讀取 HEIC）；EXE 以 PyInstaller 打包。
Python、Tcl/Tk、PyInstaller、Pillow、pi-heif 及其附帶影像編解碼器的授權資訊見 LICENSES。

Windows 整合參考：
https://learn.microsoft.com/en-us/windows/win32/shell/context
https://learn.microsoft.com/en-us/windows/win32/shell/app-registration
