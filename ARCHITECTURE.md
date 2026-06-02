# 魔丸娛樂 DC Bot 架構整理筆記

## 目前原則

bot.py 仍是主入口，短期不一次大拆，避免正式營運出問題。

之後新增功能時，優先放到以下區域：

## Cogs

- cogs/orders/：訂單 slash 指令
- cogs/tickets/：客服 ticket / 開單流程
- cogs/dispatch/：派單、接單、取消接單
- cogs/vip/：VIP、會員、權限相關指令

## Services

- services/order_flow/：訂單流程、付款、結單、存單
- services/web_sync/：Discord 與接單網頁同步

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
