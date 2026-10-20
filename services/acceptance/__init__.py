"""Discord runtime helpers for the pre-payment acceptance flow."""

# VIP 自由計時仍沿用既有的接單流程，但接單滿人後不能立刻要求付款。
# 在 acceptance 子系統載入時替換付款 panel 入口：一般訂單完全照舊，
# VIP 計時單先進入計時控制，結束後才回到原本付款流程。
from services.vip_timer_runtime import install_acceptance_payment_hook

install_acceptance_payment_hook()
