# 冰箱食材與餐食規劃助手

AI Agent 課程指定作業 2。使用者登錄食材庫存，指定人數、道數、時間上限及排除或優先食材。Agent 用工具查詢庫存及食譜，檢查整份菜單的食材總量與時間，再提供菜單、缺料或無解原因。料理完成後，使用者可確認依菜單列出的用量扣除庫存。

## 快速展示

在本資料夾開啟 PowerShell。只需 Python 3.11 以上，不須安裝套件或下載模型。

```powershell
python -X utf8 -m fridge.demo --output runtime/demo-run.json
python -X utf8 -m unittest discover -s tests -v
```

第一個指令以獨立的測試庫存執行五個案例。預期看到 `S01 PASS`、`F01 PASS`、`F02 PASS`、`S02 PASS`、`F03 PASS`。已實際產生的完整輸入、工具紀錄、輸出與扣庫存結果見 [離線執行紀錄](docs/evidence/offline-run.json)。工具介面、案例原因與處置見[作業 2 說明](docs/assignment-2.md)。

## 使用自己的庫存

`set` 輸入的是現有總量。各食材單位由目錄固定，數量為 0 表示移除。以下使用獨立的示範資料庫，兩種介面也可用 `FRIDGE_DB` 指向相同檔案。

```powershell
$env:FRIDGE_DB = 'runtime/manual-demo.sqlite3'
python -X utf8 -m fridge ingredients
python -X utf8 -m fridge set 雞蛋 4
python -X utf8 -m fridge set 板豆腐 300
python -X utf8 -m fridge set 高麗菜 400
python -X utf8 -m fridge set 蒜頭 20
python -X utf8 -m fridge set 食用油 30
python -X utf8 -m fridge set 鹽 10
python -X utf8 -m fridge plan --servings 2 --dishes 2 --minutes 20 --priority 板豆腐
```

預期回傳 `ready`、豆腐炒蛋與蒜炒高麗菜、18 分鐘，以及 `meal_id`。要測試扣庫存，料理完成後以輸出的 `meal_id` 取代下例中的 `MEAL_ID`。重送同一個 ID 會回報 `already_confirmed`。

```powershell
python -X utf8 -m fridge confirm MEAL_ID
python -X utf8 -m fridge inventory
Remove-Item Env:\FRIDGE_DB
```

`--exclude` 和 `--priority` 可各自重複指定。加上 `--shopping` 可輸出採買清單。規則模式根據缺料種類數、可使用的優先食材和時間排序。Ollama 模式透過 `--ollama` 啟用，也可用 `--preference '口味清淡'` 影響候選菜單選擇。時間、排除食材和採買設定請使用明確欄位，因為程式會直接驗證這些條件。文字偏好僅供模型排序參考。

## Podman 部署

依課程規定，應用程式、Agent、工具及 SQLite 在 Podman 容器內運作。Windows 先依 [Podman 安裝說明](https://podman.io/docs/installation) 安裝並啟動 Podman machine。第一次使用才需要 `podman machine init`，既有 machine 可直接啟動或略過已完成的步驟。

```powershell
podman machine init
podman machine start
podman info
podman build -t fridge-agent:hw2 -f Containerfile .
podman run --rm -p 127.0.0.1:8501:8501 -v fridge-data:/app/data -e OLLAMA_HOST=http://host.containers.internal:11434 fridge-agent:hw2
```

開啟 [本機操作介面](http://127.0.0.1:8501)，先在「冰箱庫存」登錄食材，再到「餐食規劃」。資料存於 `fridge-data` 具名 volume，停止或重建容器時保留。首次瀏覽可選「離線規則」，不必先準備 Ollama。容器內可重跑以下檢查與展示。

```powershell
podman run --rm fridge-agent:hw2 python -m unittest discover -s tests -v
podman run --rm fridge-agent:hw2 python -m fridge.demo
```

### 真實 Ollama 模式

在 Windows 主機依 [Ollama 安裝說明](https://docs.ollama.com/windows) 啟動 Ollama 並下載模型。模型服務獨立於應用容器。若主機已有版本可先以 `ollama list` 確認。

```powershell
ollama pull qwen3:8b
ollama list
python -X utf8 -m fridge.demo --ollama --output runtime/ollama-run.json
```

容器使用 `OLLAMA_HOST` 連到可達的 Ollama 服務。容器預設範例使用 `host.containers.internal`。若主機只能從自己的回環位址連線，請先在容器內測試下列查詢，再按主機網路環境配置可供 Podman 存取的服務位址。若已另外配置 `OLLAMA_MODEL`，請將對應模型預先下載。

```powershell
podman run --rm -e OLLAMA_HOST=http://host.containers.internal:11434 fridge-agent:hw2 python -c "from urllib.request import urlopen; print(urlopen('http://host.containers.internal:11434/api/tags', timeout=5).read().decode())"
podman run --rm -e OLLAMA_HOST=http://host.containers.internal:11434 fridge-agent:hw2 python -m fridge.demo --ollama
```

`demo --ollama` 只把成功主案例 `S01` 交給真實模型，其餘保留離線以重現案例。實機若回報連線錯誤，先確認端點與模型已下載。若回報工具呼叫無效，確認模型支援工具呼叫，並查閱程式輸出的 `Error` 與 `Result`。模型選擇不保證與離線排序相同，驗證以食譜 ID、時間及庫存為準。API 參考 [Ollama Chat](https://docs.ollama.com/api/chat) 與 [Tool calling](https://docs.ollama.com/capabilities/tool-calling)。

### 直接在本機開網頁

此方式便於開發。課程的部署驗證使用前述 Podman 指令。

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address=127.0.0.1 --browser.gatherUsageStats=false
```

## 交付與執行範圍

- `fridge/` 是可共用的 Agent、工具、資料庫及命令列介面。`app.py` 是 Streamlit 介面。
- `data/recipes.json` 有 30 道一人份食譜。`data/demo_cases.json` 是展示用庫存與規劃案例。
- `tests/` 包含 6 項自動測試。`docs/` 包含工具定義、作業說明與測試證據。
- 本版接受 1～2 人、單餐、最多兩道菜。採用固定目錄、手動登錄及明確的菜單確認。菜單時間為順序料理的估計值。
- 採買清單、兩道菜總量驗證及確認扣庫存在本版可用。作業 3 可針對模型選到缺料菜單時加入自動重選，與目前的一次選擇流程比較。
- 2026 年 11 月 22 日已在 Windows／Python 3.12.2 實跑命令列、5 個展示案例、6 項自動測試。Ollama 的工具回應在單元測試以替身驗證，實際模型、Streamlit 網頁及 Podman 建置仍待有相應程式及下載權限的環境驗證。
