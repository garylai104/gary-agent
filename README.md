# gary-agent — 104 QA 的 Claude 技能包

這是一組給 **Claude Code**（AI 代理）使用的技能（skill）。
你不需要會寫程式——**打開 Claude Code，用一句話描述你要做的事**，Claude 會自己挑對的技能、跑對的指令。

裡面有 6 個技能，涵蓋：查 Jenkins、找 allure 報告、排查測試失敗、code review、填 Jira 工時、上傳 AI 使用紀錄。

---

## ⚠️ 最重要：先設定 `.env`

**整包所有功能都靠 `gary-agent/.env` 裡的金鑰運作。少了對應的那一格，那個技能就不能用。**

### 怎麼設定

1. 複製範本：把 `env.example` 複製成 `.env`（放在 `gary-agent/` 資料夾裡）。
2. 打開 `.env`，把每一格 `=` 後面填上你的實際值。
3. `.env` 不會被上傳到 git（已設定忽略），放心填。

不確定某個值去哪拿？直接問 Claude：「JIRA_API_TOKEN 要去哪裡拿？」

### 每一格是給哪個技能用的

| `.env` 欄位 | 哪裡拿 | 沒填的話，哪個技能不能用 |
|---|---|---|
| `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` | Jira → 個人設定 → API Token | 填工時、code review、排查填票 |
| `TESTRAIL_BASE_URL` / `TESTRAIL_EMAIL` / `TESTRAIL_API_KEY` | TestRail → My Settings → API Keys | code review（比對測試案例） |
| `GITHUB_TOKEN` | GitHub → Settings → Developer settings → PAT | code review（讀 PR） |
| `JENKINS_USER` | 各台 Jenkins 共用帳號 | 查 Jenkins、排查（看 console） |
| `JENKINS_URL_{末碼}` / `JENKINS_LABEL_{末碼}` / `JENKINS_TOKEN_{末碼}` | 每台一組：網址與標籤向 QA 負責人索取，token 到該台 Jenkins → 個人 → API Token | 查 Jenkins、排查（看 console） |
| `SKILLS_CRYPT_KEY` | 向 QA 負責人索取（解開 skills/ 用） | **全部技能**（沒有就解不開 skills/） |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_S3_REGION` / `AWS_REPORT_BUCKET` | 找 QA 負責人索取 S3 唯讀金鑰 | 找 allure 報告、排查（抓報告） |
| `AI_PERF_TOKEN` | 登入 ai-performance 平台，從瀏覽器 devtools Network 複製（12 小時失效） | 上傳 AI 使用紀錄 |
| `LOCAL_REPO_ROOT` | 你本機放 104qa 專案的資料夾（預設 `~/Documents/104qa`） | code review、排查（讀本機程式碼） |

> 只想用其中一兩個技能？只要填那幾個技能對應的欄位就好，其他留空沒關係。

---

## 安裝（第一次才需要）

只需要 Python 3 和兩個套件：

```bash
cd ~/Documents/104qa/gary-agent
pip3 install -r requirements.txt   # 安裝 requests、boto3
```

（填工時的網頁另有一鍵啟動腳本，見下方。）

### 解開 skills/（clone 或 pull 之後）

`skills/` 含公司內部資訊，版控裡只放加密檔 `skills.tar.gz.enc`。`.env` 填好 `SKILLS_CRYPT_KEY` 後：

```bash
python3 scripts/skills_crypt.py decrypt   # skills.tar.gz.enc → skills/
```

改了 `skills/` 要 commit 前，先跑 `python3 scripts/skills_crypt.py encrypt` 更新加密檔，否則推上去的還是舊版。

---

## 6 個技能：目標、怎麼問、怎麼用

用法一律是**在 Claude Code 裡用自然語言講**，不用背指令。以下「這樣問」給你參考句型。

### 1. jenkins-query-104 — 查 Jenkins
- **目標**：查 job 狀態、某天的建置、某次 build 的結果 / console log / 觸發參數。
- **這樣問**：「幫我查 221 上 PYTEST_CAPP_P1 今天的 build」「看 452 這次 build 的 console」
- **需要**：`JENKINS_USER` + 對應那台的 `JENKINS_TOKEN_*`

### 2. s3-allure-104 — 找 allure 報告
- **目標**：在 S3 上依「環境 / 類型 / job / build」逐層找到 allure 報告連結。手動獨立跑的報告在 `specific` 底下。
- **這樣問**：「幫我找 prod api 最新的 allure 報告」「列出 PROD_PYTEST_API 的 build」
- **需要**：`AWS_*` 四格

### 3. qa-diagnosis-104 — 排查測試失敗
- **目標**：給一個 allure 報告連結，自動抓失敗素材（錯誤、API log、截圖）、比對本機程式碼、查 Jenkins 佐證，判斷是產品 bug / 自動化 bug / 前置資料 / 環境 / Flaky，並可把結論填回 Jira 票。
- **這樣問**：「幫我排查這個 TC 失敗原因 <allure 連結>」
- **需要**：`AWS_*`（抓報告）、`JENKINS_*`（看 console）、`JIRA_*`（填票）、`LOCAL_REPO_ROOT`（讀程式碼）
- 支援 web / api / app-ios / app-android 四平台。

### 4. code-review-104 — 交叉審查
- **目標**：給 Jira 連結 + GitHub PR 連結，自動比對「需求 ↔ 程式碼變更 ↔ 測試案例」，產出 Markdown 報告，你確認後回貼到 PR。
- **這樣問**：「幫我 code review，Jira: <連結> PR: <連結>」
- **需要**：`JIRA_*` + `GITHUB_TOKEN` + `TESTRAIL_*` + `LOCAL_REPO_ROOT`

### 5. jira-worklog-104 — 填工時
- **目標**：把某天的 Claude Code 使用紀錄推算成各任務工時、依常用名單歸單，經你確認後寫入 Jira worklog。**有一個本機網頁可以一次看到所有票、手動微調再送出。**
- **這樣問**：「幫我填今天的工時」；或直接跑下方腳本開網頁。
- **需要**：`JIRA_*`

### 6. ai-usage-record-104 — 上傳 AI 使用紀錄
- **目標**：把整理好的 AI 使用紀錄批次上傳到 `AI效率追蹤` 平台。
- **這樣問**：「幫我上傳 AI 使用紀錄」
- **需要**：`AI_PERF_TOKEN`（12 小時失效，過期就重拿）

---

## 填工時網頁：一鍵啟動

不想在對話裡一來一往微調工時，可以用網頁版：一次看到所有相關票、手動改時數/內容、一鍵送出。

```bash
cd ~/Documents/104qa/gary-agent
./skills/jira-worklog-104/start.sh
```

這支腳本會**自動**：檢查 Python、裝好套件、確認 `.env` 有 Jira 設定、在背景啟動網站，並打開瀏覽器到 `http://127.0.0.1:8770`。
關閉網站：`./skills/jira-worklog-104/start.sh stop`

---

## 安全機制

這包內建三層防護，避免 AI 誤刪檔案或亂改遠端資料——詳見 [SAFETY.md](SAFETY.md)。重點：
- **讀取自由，破壞性操作受控**：AI 不會自己執行 `rm -rf`、`git push -f` 等危險指令，而是把指令列給你，由你確認後自己執行。
- **對外寫入（Jira/GitHub）只走封裝好的功能**，且送出前一定先問過你。

## 遇到問題

大多數情況直接問 Claude 最快，例如：
- 「這個技能報錯說少了 XXX，我該怎麼設定？」
- 「JENKINS_TOKEN 要去哪裡拿？」
- 「工時網頁打不開，幫我看一下。」
