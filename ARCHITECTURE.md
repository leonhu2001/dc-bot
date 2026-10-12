# 魔丸娛樂 DC Bot 架構整理筆記

## 目前原則

`bot.py` 仍是實際啟動入口。大型已驗證 runtime 以 strangler 方式逐步搬出：先固定 canonical import path，再把舊實作隔離成 shrink-only legacy implementation；每次抽離必須保留原行為並由 CI / regression 驗證。

之後新增功能時，優先放到以下區域：

## Cogs

- cogs/orders/：訂單 slash 指令
- cogs/tickets/：客服 ticket / 開單流程
- cogs/dispatch/：派單、接單、取消接單
- cogs/vip/：VIP、會員、權限相關指令

## Services

- services/order_flow.py：付款方式 embed 與基礎付款資訊
- services/order_runtime.py：穩定 import facade；現有 legacy runtime 在 `services/order_runtime_legacy.py`，只允許縮小，不接受新功能
- services/self_service_runtime.py：穩定 import facade；現有 legacy runtime 在 `services/self_service_runtime_legacy.py`，只允許縮小，不接受新功能
- services/acceptance/runtime.py：付款前接單 Discord runtime、panel reconcile、sync worker 與付款 panel 修復；不直接 import bot.py
- services/web_sync/：Discord 與接單網頁同步
  - event_store.py：Web→Bot sync event 的 atomic claim、stale recovery、完成/失敗狀態、接單人查詢，以及 `order_created` 的資料庫讀寫
  - presentation.py：Web sync 的純資料解析與顯示文字組裝，不直接呼叫 Discord API
  - discord_helpers.py：Web sync 的低階 Discord member/channel/ticket/footer 與派單 embed helper
  - runtime.py：網站訂單建立、客服確認、網站訂單 runtime 與相關 persistent views；透過啟動時 adapter 綁定尚未拆出的 legacy bot 依賴

## Web Routers

- `web/app/routers/admin.py`：穩定 admin import facade
- `web/app/routers/admin_legacy.py`：既有大型 admin 實作，shrink-only；新頁面與新責任必須建立 focused router/service

## Views

- views/orders/：訂單面板、付款面板
- views/dispatch/：派單面板、接單按鈕
- views/tickets/：客服 ticket 面板

## 修改規則

1. 新功能不要再直接塞進 bot.py。
2. 一次性 patch / repair 不得掛在 Web 或 Bot 的正常 startup；需要保留的歷史修復放在 `scripts/run_data_repairs.py` 顯式執行，完成且不再需要後應刪除。
3. 正式設定與 token 不進 Git。
4. 每次部署前都要 py_compile。
5. 部署後要看 systemctl status 與 journalctl。
6. Web→Bot 同步的資料庫存取集中在 services/web_sync/event_store.py；Web 訂單高階 runtime 集中在 services/web_sync/runtime.py。
7. 付款前接單的 Discord runtime 集中在 services/acceptance/runtime.py；shared/order_acceptance.py 繼續負責 canonical acceptance business state。
8. runtime adapter 只能作為拆分過渡層，不允許新功能再依賴 bot.py globals；新功能必須直接使用 service/view 的明確 API。
9. bot.py 保留真正啟動入口、事件註冊與尚未拆出的 orchestration；不為了縮檔名使用 runpy 或另一份入口複製品。碰到其中可獨立責任時，直接抽到 service/view。
10. `order_runtime.py`、`self_service_runtime.py` 與 `admin.py` 是 canonical facade；外部程式不得直接 import 對應 `_legacy`。legacy implementation 只允許刪除/抽離，不接受新增業務功能。
11. `bot.py`、canonical facades、對應 `_legacy`、`views/review.py` 都有 regression growth budget；新功能若撞到上限，必須先抽出責任區塊而不是提高上限。
12. Python regression 之外，公開首頁與點單流程必須通過 Playwright；至少驗證頁面可載入、點單 Dialog、390px 手機寬度，以及使用真實 signed session 的 server quote → checkout → 正式建立訂單。
13. 前端臨時 `*_fix.js` / runtime CSS injection 不作為新功能的落點；碰到既有 patch 時優先把行為移回正式 controller / stylesheet，再刪除 patch。
14. CSP inline debt 採 shrink-only budget；每次把 inline style/script 外移後同步降低 ceiling，不得把 `unsafe-inline` 當永久新增功能入口。
