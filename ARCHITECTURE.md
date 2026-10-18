# 魔丸娛樂 DC Bot 架構整理筆記

## 目前原則

`bot.py` 仍是主入口，但大型已驗證 runtime 會依責任區塊搬出；每次搬移必須保留原行為並由 CI / regression 驗證。

Runtime 與主入口之間使用明確 dependency API 綁定。已完成 explicit configuration 的 runtime 不得退回 `globals()` / namespace 注入。

之後新增功能時，優先放到以下區域：

## Cogs

- `cogs/orders/`：訂單 slash 指令
- `cogs/tickets/`：客服 ticket / 開單流程
- `cogs/dispatch/`：派單、接單、取消接單
- `cogs/vip/`：VIP、會員、權限相關指令

## Services

- `services/order_flow.py`：付款方式 embed 與基礎付款資訊
- `services/order_runtime.py`：訂單 runtime 的薄協調層，透過 `configure_order_runtime_explicit(...)` 接收 entrypoint 依賴；付款、storage、dispatch、credential、點數兌換等責任已分散到對應 service
- `services/order_payment_runtime.py`：付款流程 runtime
- `services/order_storage_runtime.py`：存單 / 恢復相關 runtime
- `services/order_dispatch_runtime.py`：派單相關 runtime
- `services/order_credential_runtime.py`：Discord 訂單憑證 UI/runtime；憑證 persistence 由 `services/order_credentials.py` 負責
- `services/order_point_redemption.py`：點數福利付款兌換
- `services/self_service_runtime.py`：自助下單 runtime 的薄協調層，透過 `configure_self_service_runtime_explicit(...)` 接收明確依賴
- `services/self_service_financials.py`：自助下單報價、手動調整、VIP 折扣與點數福利財務計算
- `services/self_service_selection_runtime.py`：自助下單指定人員 / 選擇 UI runtime
- `services/self_service_reorder.py`：reorder 流程
- `services/acceptance/runtime.py`：付款前接單 Discord runtime、panel reconcile、sync worker 與付款 panel 修復；透過 `configure_acceptance_runtime_explicit(...)` 綁定依賴，不直接 import `bot.py`
- `services/web_sync/`：Discord 與接單網頁同步
  - `event_store.py`：Web→Bot sync event 的 atomic claim、stale recovery、完成/失敗狀態、接單人查詢，以及 `order_created` 的資料庫讀寫
  - `presentation.py`：Web sync 的純資料解析與顯示文字組裝，不直接呼叫 Discord API
  - `discord_helpers.py`：Web sync 的低階 Discord member/channel/ticket/footer 與派單 embed helper
  - `self_service_bridge.py`：網站訂單與自助下單 panel/state 的 bridge
  - `cs_review.py`：網站訂單客服確認、待確認取消與相關 persistent views
  - `runtime.py`：網站訂單建立與 Web Sync 高階 orchestration；透過 `configure_web_sync_runtime_explicit(...)` 接收 entrypoint-owned state

## Views

- `views/orders/`：訂單面板、付款面板
- `views/dispatch/`：派單面板、接單按鈕
- `views/tickets/`：客服 ticket 面板

## 修改規則

1. 新功能不要再直接塞進 `bot.py`。
2. 一次性 patch / repair 不得掛在 Web 或 Bot 的正常 startup；需要保留的歷史修復放在 `scripts/run_data_repairs.py` 顯式執行，完成且不再需要後應刪除。
3. 正式設定與 token 不進 Git。
4. 每次部署前都要做 Python compile check。
5. 部署後要確認 Bot / Web / Nginx service 狀態、HTTP smoke 與 restart stability。
6. Web→Bot 同步的資料庫存取集中在 `services/web_sync/event_store.py`；網站訂單高階 runtime 集中在 `services/web_sync/runtime.py`，客服審核與 self-service bridge 各自留在專用模組。
7. 付款前接單的 Discord runtime 集中在 `services/acceptance/runtime.py`；`shared/order_acceptance.py` 繼續負責 canonical acceptance business state。
8. Runtime configuration 必須使用明確 dependency API；禁止 `configure_*runtime(globals())`、廣泛 namespace 注入，以及 service 反向 import `bot.py`。
9. `bot.py` 只保留啟動、事件註冊、管理指令與尚未拆出的薄 orchestration；自助下單與訂單 runtime 不再新增實作到 `bot.py`。
10. 修改 `order_runtime.py`、`self_service_runtime.py`、`acceptance/runtime.py` 或 `web_sync/runtime.py` 時，優先縮小責任與依賴面，不得重新建立 legacy namespace adapter。
11. `bot.py`、主要 order/self-service runtime、Web Sync、Web admin、`views/review.py` 等大型模組都有 regression growth budget；新功能若撞到上限，必須先抽出責任區塊而不是提高上限。
12. Architecture regression 會阻止 `services/` import `bot.py`，並阻止 runtime configurator 使用 `globals()`；這些 guard 不得為了新功能移除或放寬。
13. Python regression 之外，公開首頁與點單流程必須通過 Playwright browser smoke；至少驗證頁面可載入、點單 Dialog 可操作，以及 390px 手機寬度不產生水平溢出。
14. 前端臨時 `*_fix.js` / runtime CSS injection 不作為新功能的落點；碰到既有 patch 時優先把行為移回正式 controller / stylesheet，再刪除 patch。

## Phase 2 extraction boundaries (2026-10-13 起，持續收斂)

- Discord order credential UI/runtime lives in `services/order_credential_runtime.py`; credential persistence remains in `services/order_credentials.py`.
- Point-benefit payment redemption lives in `services/order_point_redemption.py`.
- Self-service pricing, manual adjustment, VIP discount, and point-benefit financial calculation live in `services/self_service_financials.py`.
- Ticket naming/topic identity helpers live in `services/ticket_identity.py`, not the `bot.py` entrypoint.
- Admin dashboard and order workspace are separate routers; `web/app/routers/admin.py` is a thin action/router composition layer.
- Patch-style frontend assets (`*_fix.js` / `*_fix.css`) have no allow-list. Additions must be implemented in canonical controllers/styles instead.
- Wallet persistence is canonical in `services/wallet_service.py`; Discord/Web layers may adapt identities or presentation, but must not open or mutate wallet tables directly.
- Persistent VIP voice lifecycle behavior is owned by `services/vip_voice_runtime.py`; `bot.py` keeps Discord event/command registration and explicit dependency binding only.
- Order, Self Service, Acceptance 與 Web Sync runtime 均已改為 explicit configuration；後續工作是繼續縮小 `bot.py` 與各 runtime 的責任面，而不是再做 namespace-based adapter migration。
