# SQL MCP Server

輕量且可配置的 SQL MCP MCP 伺服器（Python 3.10+）

這個專案實作一個可由 AI 使用的 SQL MCP server，使用 fastmcp（MCP 伺服器）、SQLAlchemy（支援多種 DB 方言）、以及 pydantic-settings（環境設定）。已包含完整 pytest 整合測試（使用 in-memory SQLite），並強制 execute_read_only_sql 僅允許唯讀查詢。

主要功能
- list_tables(): 回傳資料庫中所有 table 與 view 名稱（排序、去重）。
- get_table_schema(table_name: str): 回傳指定 table/view 的欄位 metadata（name、type、nullable、primary_key、default）。
- execute_read_only_sql(sql_query: str): 嚴格執行唯讀查詢，只允許單一 SELECT 或 WITH 陳述式；會拒絕包含 INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/TRUNCATE/GRANT/REVOKE/MERGE 或多語句的請求。

環境變數設定（pydantic-settings）
- DB_TYPE: postgresql | mysql | mssql | sqlite （預設: sqlite）
- DB_HOST
- DB_PORT
- DB_USER
- DB_PASS
- DB_NAME （sqlite 預設為 `:memory:`）

快速開始
1. 建議建立虛擬環境並安裝相依
```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # macOS / Linux
python -m pip install -e .[postgresql,mysql,mssql]
python -m pip install pytest
```

2. 在開發或測試時使用 SQLite 範例
```bash
# 使用 in-memory SQLite
set DB_TYPE=sqlite
set DB_NAME=:memory:
python -m sql_mcp_server.server
```

啟動 MCP 伺服器
- 需安裝 fastmcp，且依 fastmcp 版本可能需微調 server 建立程式（server.build_server()）
```bash
python -m sql_mcp_server.server
```

測試
- 本專案已包含整合測試（不使用 mock/monkeypatch），皆針對 in-memory SQLite 執行：
```bash
pytest -q
```

Integration tests (Postgres)
- 用途：在本機或 CI 上以真正的 Postgres 驗證整合行為（例如 `list_tables()` 與 schema 檢索）。
- 前置條件：已安裝 Docker 與 Docker Compose（或使用 Docker 支援的 runner）。

快速在本機執行（Linux / macOS）
```bash
# 複製範例 env 檔案
cp .env.example .env

# 建立並啟動 Postgres 服務
docker compose up -d

# 等待 Postgres 健康後執行 integration tests
pytest -q -m integration

# 測試完成後清理
docker compose down
```

快速在本機執行（Windows PowerShell）
```powershell
Copy-Item .env.example .env
docker compose up -d
pytest -q -m integration
docker compose down
```

CI 行為
- 本專案的 CI 已包含一個 `integration` job（使用 GitHub Actions services postgres:15-alpine），負責啟動 Postgres、等待 pg_isready，並執行 `pytest -q -m integration`。
- 若要在 CI 中改變資料庫設定，請調整 `.github/workflows/ci.yml` 的環境變數（DB_*）。

建議
- 若要在 CI 或本機上穩定執行，請務必使用與 CI 相容的 Python 與套件版本（參考 `pyproject.toml`）。
- 若不想在本機啟用 Postgres，可暫時以 sqlite 測試：`set DB_TYPE=sqlite && pytest -q`（Windows）或 `DB_TYPE=sqlite pytest -q`（Linux/macOS）。

實作重點與安全設計
- SQL 允許性檢查：execute_read_only_sql 先移除註解、禁止多重語句（分號分隔）、確保第一個 token 為 SELECT 或 WITH，並檢查整個查詢中是否含有禁止的關鍵字（以完整單字比對）。
- 此檢查採保守策略；在高安全需求環境建議搭配完整 SQL 解析器（例如 sqlparse、或更嚴格的 AST 檢查）做二次驗證。
- 使用 SQLAlchemy 引擎並啟用 pool_pre_ping、pool_size、max_overflow 等連線池參數以提升 production 穩定性。

檔案清單（主要）
- pyproject.toml
- sql_mcp_server/
  - __init__.py
  - config.py
  - db.py
  - tools.py
  - server.py
- tests/
  - conftest.py
  - test_tools.py
- scripts/create_project.py

建議的 production 改進（建議採用）
- 為 fastmcp 的註冊程式碼加入版本相容檢查或抽象化適配器，確保不同 fastmcp 版本皆能註冊工具。
- 加入更強的 SQL 解析器（sqlparse 或類似 lib）做第二道防護。
- 增加日誌等級與結構化日誌（JSON），並加入監控/健康檢查 endpoint。
- 建立 GitHub Actions CI（跑 pytest、格式檢查、safety/依賴掃描）。
- 在 docker 映像中設定最小權限 DB 使用者、連線數限制與監控設定。

License
- MIT（可依需求更改）

若要我：我可以接著加入 CI workflow、LICENSE 檔案、或在 server 建立更完整的 fastmcp 適配層與使用範例；請回覆要我執行的下一步。
