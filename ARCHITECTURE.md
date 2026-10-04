# 魔丸娛樂 DC Bot 架構整理筆記

## 目前原則

bot.py 仍是主入口，但大型已驗證 runtime 會依責任區塊搬出；每次搬移必須保留原行為並由 CI / regression 驗證。

之後新增功能時，優先放到以下區域：

## Cogs

- cogs/orders/：訂單 slash 指令
- cogs/tickets/：客服 ticket / 開單流程
- cogs/dispatch/：派單、接單、取消接單
- cogs/vip/：VIP、會員、權限相關指令

## Services

- services/order_flow/：訂單流程、付款、結單、存單
- services/acceptance/runtime.py：付款前接單 Discord runtime、panel reconcile、sync worker 與付款 panel 修復；不直接 import bot.py
- services/web_sync/：Discord 與接單網頁同步
  - event_store.py：Web→Bot sync event 的 atomic claim、stale recovery、完成/失敗狀態、接單人查詢，以及 `order_created` 的資料庫讀寫
  - presentation.py：Web sync 的純資料解析與顯示文字組裝，不直接呼叫 Discord API
  - discord_helpers.py：Web sync 的低階 Discord member/channel/ticket/footer 與派單 embed helper
  - runtime.py：網站訂單建立、客服確認、網站訂單 runtime 與相關 persistent views；透過啟動時 adapter 綁定尚未拆出的 legacy bot 依賴

## Views

- views/orders/：訂單面板、付款面板
- views/dispatch/：派單面板、接單按鈕
- views/tickets/：客服 ticket 面板

## 修改規則

1. 新功能不要再直接塞進 bot.py。
2. 一次性 patch 成功後要刪除。
3. 正式設定與 token 不進 Git。
4. 每次部署前都要 py_compile。
5. 部署後要看 systemctl status 與 journalctl。
6. Web→Bot 同步的資料庫存取集中在 services/web_sync/event_store.py；Web 訂單高階 runtime 集中在 services/web_sync/runtime.py。
7. 付款前接單的 Discord runtime 集中在 services/acceptance/runtime.py；shared/order_acceptance.py 繼續負責 canonical acceptance business state。
8. runtime adapter 只能作為拆分過渡層，不允許新功能再依賴 bot.py globals；新功能必須直接使用 service/view 的明確 API。
