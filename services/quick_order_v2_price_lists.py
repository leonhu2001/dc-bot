from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import discord

from services import quick_order_v2 as quick


_PRICE_LIST_LABEL_BY_CHANNEL_ID = {
    int(quick.QUICK_ORDER_V2_CHANNELS["delta"]): "三角洲行動",
    int(quick.QUICK_ORDER_V2_CHANNELS["valorant"]): "VALORANT",
    int(quick.QUICK_ORDER_V2_CHANNELS["lol"]): "英雄聯盟",
    int(quick.QUICK_ORDER_V2_CHANNELS["apex"]): "APEX",
    int(quick.QUICK_ORDER_V2_CHANNELS["steam"]): "STEAM",
}

_ROOT_DIR = Path(__file__).resolve().parents[1]
_PUBLIC_BASE_URL = "https://mowanentertainment.com/static"
_DELTA_FARM_3X3_ASSET = "order_panels/delta_farm_3x3.png"
_DELTA_FUN_RUSSIAN_ROULETTE_ASSET = "price_lists/delta_fun_russian_roulette.jpg"
_DELTA_FUN_RICH_ENOUGH_ASSET = "price_lists/delta_fun_hao_dao_ni_le_ma.jpg"


def _display_width(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        for char in str(value)
    )


def _aligned_code_block(rows: tuple[tuple[str, str], ...]) -> str:
    """Render two-column Discord price rows with CJK-aware spacing."""
    if not rows:
        return "```text\n```"
    label_width = max(_display_width(label) for label, _ in rows)
    lines = []
    for label, value in rows:
        padding = " " * (label_width - _display_width(label) + 4)
        lines.append(f"{label}{padding}{value}")
    return "```text\n" + "\n".join(lines) + "\n```"


def _static_asset_url(relative_path: str) -> str:
    """Return a cache-busted public static URL based on the deployed file contents."""
    clean = str(relative_path or "").strip().lstrip("/")
    local_path = _ROOT_DIR / "web" / "app" / "static" / clean
    version = "missing"
    try:
        version = hashlib.sha256(local_path.read_bytes()).hexdigest()[:16]
    except OSError:
        pass
    return f"{_PUBLIC_BASE_URL}/{clean}?v={version}"


DELTA_PRICE_LIST_CATEGORIES = (
    ("desktop", "端遊", "🖥️"),
    ("mobile", "手遊", "📱"),
    ("farm", "代肝代解", "🛠️"),
    ("fun", "趣味單", "🎉"),
)

DELTA_DESKTOP_PRICE_LISTS = {
    "entertainment": {
        "label": "娛樂陪",
        "text": f"""**娛樂陪**
{_aligned_code_block((("單陪", "320T / H"), ("雙陪", "600T / H")))}
⚠️ **不保撤、無保底**

🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計時", "累積 10 小時 → 贈送 1 小時券"),))}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 以上免指定費**""",
    },
    "one_guard": {
        "label": "一陪一護",
        "text": f"""**一陪一護**
{_aligned_code_block((("機密", "720T / H"), ("絕密", "770T / H")))}

🛡️ **護航保證**
{_aligned_code_block((("機密", "1 小時內 8 殺"), ("絕密", "1 小時內 6 殺")))}

📌 **指定打手**
{_aligned_code_block((("指定打手", "每人 +100T"),))}
⚠️ **2H 以上免指定費**""",
    },
    "trial": {
        "label": "體驗單",
        "text": f"""**體驗單**
{_aligned_code_block((("普通體驗單", "450T　保底 777W"), ("尊爵體驗單", "900T　保底 1688W")))}

⚠️ **普通體驗單每週限一次**
⚠️ **尊爵體驗單每月限一次；金級以上每週限一次**
⚠️ **不適用任何折扣、加碼活動**
⚠️ **此單為打手選圖**""",
    },
    "technical": {
        "label": "技術陪",
        "text": f"""**機密／絕密技術陪**
{_aligned_code_block((("機密單護", "400T / H"), ("機密雙護", "750T / H"), ("絕密單護", "450T / H"), ("絕密雙護", "850T / H")))}

🛡️ **保證／保底**
{_aligned_code_block((("機密單護", "1 小時內 8 殺"), ("機密雙護", "666W 保底"), ("絕密單護", "1 小時內 6 殺"), ("絕密雙護", "800W 保底")))}

📌 **指定打手**
{_aligned_code_block((("指定打手", "每人 +100T"),))}
⚠️ **2H 以上免指定費**""",
    },
    "babel_technical": {
        "label": "絕巴技術陪",
        "text": f"""**絕巴技術陪**
{_aligned_code_block((("價格", "1000T / H"),))}

🛡️ **保底三選一**
{_aligned_code_block((("方案 1", "800W"), ("方案 2", "500W + 2 沙保"), ("方案 3", "4 沙保")))}

📌 **指定打手**
{_aligned_code_block((("指定打手", "每人 +100T"),))}
⚠️ **2H 以上免指定費**""",
    },
    "bet": {
        "label": "賭約單",
        "text": f"""**賭約單**
{_aligned_code_block((("800T", "單局 800W"), ("1200T", "單局 1000W"), ("1500T", "單局 1200W")))}

⚠️ **未達指定金額不結單**
⚠️ **此單為打手選圖**""",
    },
    "oil": {
        "label": "油鍋單",
        "text": f"""**油鍋單**
{_aligned_code_block((("火箭燃油", "2600T　保底 2000W"), ("GT 衛星通信天線", "1800T　保底 1500W"), ("全包", "4000T　保底 3500W")))}

⚠️ **此單限制「航天基地」**
⚠️ **撤離時帶出即結單**
⚠️ **已過保底仍未出貨，下場會改以撞場形式交貨**""",
    },
    "black_tide": {
        "label": "黑潮爆破",
        "text": f"""**黑潮爆破**

**娛樂陪**
{_aligned_code_block((("單陪", "320T / H"), ("雙／四陪", "每人 300T / H")))}

**技術陪**
{_aligned_code_block((("單陪", "400T / H"), ("雙／四陪", "每人 380T / H")))}

🎁 **累積回饋**
{_aligned_code_block((("計時", "累積 10 小時 → 贈送 30 分鐘券"),))}""",
    },
    "sweet": {
        "label": "甜蜜單",
        "text": f"""**甜蜜單**
{_aligned_code_block((("單陪", "520T / H"), ("雙陪", "1314T / H")))}
⚠️ **不保撤、無保底**

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 以上免指定費**

💗 **互動說明**
可設定專屬暱稱（例如：寶寶／寶貝）。
以提供情緒價值及情侶般互動為主。
⚠️ 如接單過程有任何讓陪玩感到不適的情況，管理層有權直接暫停服務。""",
    },
    "teaching": {
        "label": "教學單",
        "text": f"""**1 對 1 教學**
{_aligned_code_block((("最高段位導師", "500T / H"),))}
由對應遊戲最高段位的導師進行教學。

⚠️ **為確保教學品質，此單 3H 起標**

✨ **教學重點**
1. 地圖理解
2. 幹員定位
3. 實戰
4. 復盤
5. 總結""",
    },
}


DELTA_MOBILE_PRICE_LISTS = {
    "trial": {
        "label": "體驗單",
        "text": f"""**體驗單**
{_aligned_code_block((("777W", "400T"), ("1688W", "800T")))}""",
    },
    "guarantee": {
        "label": "保底單",
        "text": f"""**累積保底**
{_aligned_code_block((("1500W", "600T"), ("4200W", "2000T"), ("110M", "4000T"), ("300M", "10000T")))}""",
    },
    "big_red": {
        "label": "大紅單",
        "text": f"""**累積帶出**
{_aligned_code_block((("1 大紅", "1000T"), ("5 大紅", "4000T"), ("10 大紅", "7000T")))}
📌 **大紅定義**
價值 **100萬以上** 的紅色物資即計為大紅。""",
    },
    "babel": {
        "label": "絕巴保底單",
        "text": f"""**絕巴保底方案**
{_aligned_code_block((("基礎方案", "600T"), ("進階方案", "3000T"), ("最強方案", "5000T"), ("三幻神挑戰", "5000T")))}
**基礎方案**
2 個沙色保險 ＋ 800W 保底

**進階方案**
累積 10 個沙色保險 ＋ 6000W 保底

**最強方案**
累積 20 個沙色保險 ＋ 100M 保底

**三幻神挑戰**
三幻神任一出現即完成
⚠️ **不出不結單**""",
    },
    "entertainment": {
        "label": "娛樂陪",
        "text": f"""**娛樂陪**
{_aligned_code_block((("單陪", "320T / H"), ("雙陪", "600T / H")))}
🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計時", "累積 10 小時 → 贈送 1 小時券"),))}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**""",
    },
    "sweet": {
        "label": "甜蜜單",
        "text": f"""**甜蜜單**
{_aligned_code_block((("單陪", "520T / H"), ("雙陪", "1314T / H")))}
📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**""",
    },
    "teaching": {
        "label": "教學單",
        "text": f"""**1對1教學**
{_aligned_code_block((("每人", "500T / H"),))}
📌 **指定人員**
{_aligned_code_block((("指定打手／教學人員", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**""",
    },
}

DELTA_FARM_PRICE_LISTS = {
    "aw_collision": {
        "label": "AW子彈代撞",
        "text": f"""**AW子彈代撞**
{_aligned_code_block((("1～100 發", "每發 5T"), ("101～500 發", "每發 4.5T"), ("501 發以上", "每發 4T")))}""",
    },
    "ammo_dump": {
        "label": "倒子彈代肝",
        "text": f"""**倒子彈代肝**
{_aligned_code_block((("100M", "800T"), ("200M", "1,500T"), ("300M", "2,100T"), ("500M", "3,300T"), ("1000M", "6,400T"), ("2000M", "11,500T")))}
📌 按 M 數選擇固定方案；可選 **加急 +280T**（全額給接單打手，不增加店抽）。""",
    },
    "car_crash": {
        "label": "撞車代肝",
        "text": f"""**撞車代肝**
{_aligned_code_block((("100M", "700T"), ("200M", "1,400T"), ("500M", "3,250T"), ("1000M", "6,100T")))}
📌 按 M 數選擇固定方案；可選 **加急 +280T**（全額給接單打手，不增加店抽）。""",
    },
    "department_mission": {
        "label": "代解部門任務",
        "text": f"""**代解部門任務**
{_aligned_code_block((("等級 1～3", "25T / 聲望"), ("等級 3～4", "40T / 聲望")))}
📌 **各等級所需聲望**
{_aligned_code_block((("等級 1→2", "20 聲望"), ("等級 2→3", "30 聲望"), ("等級 3→4", "30 聲望")))}
⚠️ **作業時間最久兩週內結單**
⚠️ **包損耗 +500T**""",
    },
    "safe_box_3x3": {
        "label": "3×3安全箱",
        "text": "**三角洲行動 S12｜3×3安全箱**\n安全箱 5500T｜安全箱＋外觀 8000T\n包損＋500T｜賽前預約 −500T｜命運契約 600T／個\n詳細規則請見下圖。",
        "image": _DELTA_FARM_3X3_ASSET,
    },
}

DELTA_FUN_PRICE_LISTS = {
    "russian_roulette": {
        "label": "俄羅斯輪盤",
        "text": f"""**俄羅斯輪盤**
{_aligned_code_block((("價格", "1000T"),))}
📌 **玩法說明**
老闆前往本店提供的輪盤網站進行抽選保底。
抽選完成後，由機器人自動記錄於票口。""",
        "image": _DELTA_FUN_RUSSIAN_ROULETTE_ASSET,
    },
    "love_delta": {
        "label": "戀與三角洲",
        "text": f"""**戀與三角洲**
{_aligned_code_block((("基礎", "1688T    基礎好感度 30"), ("標準", "2688T    基礎好感度 0"), ("困難", "4688T    基礎好感度 -30"), ("地獄", "6688T    基礎好感度 -80")))}
🎯 **結單條件**
好感度達 **100** 結單。

💗 **好感度加分**
{_aligned_code_block((("金色物資／紫卡", "+3"), ("小紅（200W以下）／金卡", "+8"), ("大紅（200W以上）／紅卡", "+15"), ("心／淚", "+30"), ("女陪第一次救起老闆", "+5"), ("女陪與老闆撤離成功", "+5"), ("女陪打三滅隊", "+10"), ("300W以上撤離", "+4"), ("600W以上撤離", "+8"), ("900W以上撤離", "+12")))}
📌 **互動規則**
老闆可設定 **3 種不同禁語**；女陪每次講到，好感度 **-2**，撤離成功後可更換。
禁語不可與自訂句末助詞、暱稱重複。

女陪每局開始前，可從上架物資中猜一樣老闆最想要的東西；猜中該局分數 **×1.2**。可提示物資類別及品質，兩位女陪需統一答案。

✨ **好感度解鎖**
好感度 **30**：可設定一句句末助詞，漏說一次 **-2**。
好感度 **60**：解鎖女陪對老闆的特殊稱呼，由老闆自訂。

單局摸出 **4 個同樣小金／紅**，老闆可指定下局女陪使用的幹員及槍械。
撤離失敗仍會計算安全箱內價值。""",
    },
    "watch_your_words": {
        "label": "謹言慎行",
        "text": f"""**謹言慎行**
{_aligned_code_block((("價格", "2500T"), ("基礎保底", "1888W")))}
📌 **規則**
開局由老闆決定 **3 個禁詞**。

在原保底內，打手每次講到禁詞，額外保底 **+50W**。
禁詞被打手猜到後，老闆可更換禁詞，最多更換 **2 次**。

打滿原保底後，結束猜禁詞環節並結算額外保底。
打手進入額外保底期間，不需再猜禁詞。""",
    },
    "eat_yourself": {
        "label": "想吃自己打",
        "text": f"""**想吃自己打**
{_aligned_code_block((("價格", "13888T"),))}
📌 **挑戰規則**
需連續撤離 **5 把**，且每把都需達 **1000W**，本方案無保底。

若連撤中斷，全部重新開始。
若連撤過程中有場次未達 1000W，需補場次，但不會中斷連撤紀錄。
補場次過程中若撤離失敗，累計場次歸零。

🔴 **大紅可折抵 1 個場次**""",
    },
    "rich_enough": {
        "label": "豪到你了嗎",
        "text": f"""**豪到你了嗎**
{_aligned_code_block((("價格", "2000T"), ("基礎保底", "1200W")))}
⚠️ **開打前檢查**
打手必須威龍
必須防爆頭+老賽甲
語音英文

⚠️ **只能使用下列槍枝**
AS VAL、M7、M14

📌 **規則**
僅能拉閘禁止飛升
全程禁止靜步，必須歐美
打贏說 \"豪到你了嗎，妹妹?\"，打輸說 \"卡了\"
丟C4前要說 \"一個吸Four\"，噴氣前要說 \"一個氣\"，丟虎蹲前要說 \"一個炮\"
遇到人說 \"窩累同雷碗\"
出貨要說 \"有感覺了嗎，妹妹\"
少說以上任一句保底 **+30W**""",
        "image": _DELTA_FUN_RICH_ENOUGH_ASSET,
    },
    "lovebirds": {
        "label": "比翼雙飛",
        "text": f"""**比翼雙飛**
{_aligned_code_block((("價格", "2000T"), ("基礎保底", "1314W")))}
📌 **規則**
由老闆指定一個打手給對方的愛稱，並在開局說出指定情話。
忘記一次，保底 **+50W**。

⚠️ **打手任何決策都必須開麥溝通**""",
    },
}


def _normalise_emoji_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _guild_emoji(interaction: discord.Interaction, token: str) -> str:
    """Resolve a server custom emoji by the shortcode the owner uses in Discord."""
    guild = interaction.guild
    if guild is None:
        return ""

    raw = str(token or "").strip().strip(":")
    if not raw:
        return ""

    full_key = _normalise_emoji_name(raw)
    exact = [emoji for emoji in guild.emojis if _normalise_emoji_name(emoji.name) == full_key]
    if exact:
        return str(exact[0])

    duplicate_index: int | None = None
    base = raw
    if "~" in raw:
        candidate, suffix = raw.rsplit("~", 1)
        if suffix.isdigit():
            base = candidate
            duplicate_index = int(suffix)

    base_key = _normalise_emoji_name(base)
    matches = [emoji for emoji in guild.emojis if _normalise_emoji_name(emoji.name) == base_key]
    if not matches:
        return ""

    if duplicate_index is not None and duplicate_index < len(matches):
        return str(matches[duplicate_index])
    return str(matches[0])


def _rank_heading(interaction: discord.Interaction, emoji_token: str, label: str) -> str:
    emoji = _guild_emoji(interaction, emoji_token)
    return f"{emoji} **{label}**" if emoji else f"**{label}**"


# Strong, readable dividers for the four single-page non-Delta price lists only.
# Keep the Delta category pages unchanged.
_GAME_PRICE_SECTION_DIVIDER = "━━━━━━━━━━━━━━━━━━"


def _shared_special_service_copy(game: str) -> str:
    """Display existing sweet/teaching offers below each normal game price list."""
    teaching = {
        "valorant": ("輻能導師", "地圖觀念、技能搭配、槍線、實戰與復盤"),
        "lol": ("菁英導師", "對線與兵線、地圖資源、團戰決策、實戰與復盤"),
        "apex": ("頂獵導師", "落點與轉點、跑圈觀念、交戰配合、實戰與復盤"),
    }
    sweet_copy = f"""💗 **甜蜜單**
{_aligned_code_block((("單陪", "520T / H"), ("雙陪", "1314T / H")))}
可選女陪／男陪／不限，以互動陪玩及情緒價值為主。
可設定專屬暱稱；互動須尊重彼此意願。

📌 **甜蜜單指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 以上免指定費**"""

    if game == "steam":
        # Steam has sweet-companion rules but no teaching self-service rule.
        teaching_copy = """📚 **教學單**
依指定遊戲及教學需求，由客服確認可接單內容與報價。
⚠️ **STEAM 教學單尚未開放自助下單**"""
    else:
        teacher, topics = teaching[game]
        teaching_copy = f"""📚 **教學單（1 對 1）**
{_aligned_code_block(((teacher, "500T / H"),))}
✨ **教學重點**
{topics}
⚠️ **為確保教學品質，3H 起標**"""

    return f"{sweet_copy}\n\n{_GAME_PRICE_SECTION_DIVIDER}\n\n{teaching_copy}"


def _valorant_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
{_aligned_code_block((("NG", "每人 350T / H"), ("積分（白金以下）", "每人 280T / 局")))}
積分段位加價：鑽石 +50T、超凡 +100T、神話 +150T、輻能 +200T（每人每局）。

**娛樂陪無賠付**

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Ascendant", "超凡陪")}
{_aligned_code_block((("NG", "每人 330T / H"), ("積分（白金以下）", "每人 300T / 局")))}
積分段位加價：鑽石 +50T、超凡 +100T、神話 +150T、輻能 +200T（每人每局）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Immortal", "神話陪")}
{_aligned_code_block((("NG", "每人 350T / H"), ("積分（白金以下）", "每人 330T / 局")))}
積分段位加價：鑽石 +50T、超凡 +100T、神話 +150T、輻能 +200T（每人每局）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Radiant", "輻能陪")}
{_aligned_code_block((("NG", "每人 380T / H"), ("積分（白金以下）", "每人 370T / 局")))}
積分段位加價：鑽石 +50T、超凡 +100T、神話 +150T、輻能 +200T（每人每局）。

🛡️ **技術陪賠付規則**
超凡／神話／輻能陪 2 位以上，若該局未獲勝或未進前三，將補打一把（由客服確認）。

{_GAME_PRICE_SECTION_DIVIDER}

🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計局", "累積 15 局 → 贈送 1 局券"), ("計時", "累積 10 小時 → 贈送 1 小時券")))}

{_GAME_PRICE_SECTION_DIVIDER}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**

{_GAME_PRICE_SECTION_DIVIDER}

{_shared_special_service_copy("valorant")}"""


def _apex_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
{_aligned_code_block((("NG", "每人 320T / H"), ("積分（白金以下）", "每人 350T / H")))}
積分段位加價：鑽石 +50T、大師 +100T、頂獵 +150T（每人每小時）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Diamond", "鑽石陪")}
{_aligned_code_block((("NG", "每人 380T / H"), ("積分（白金以下）", "每人 400T / H")))}
積分段位加價：鑽石 +50T、大師 +100T、頂獵 +150T（每人每小時）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Master~1", "大師陪")}
{_aligned_code_block((("NG", "每人 400T / H"), ("積分（白金以下）", "每人 450T / H")))}
積分段位加價：鑽石 +50T、大師 +100T、頂獵 +150T（每人每小時）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Predator", "頂獵陪")}
{_aligned_code_block((("NG", "每人 500T / H"), ("積分（白金以下）", "每人 550T / H")))}
積分段位加價：鑽石 +50T、大師 +100T、頂獵 +150T（每人每小時）。

{_GAME_PRICE_SECTION_DIVIDER}

🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計時", "累積 10 小時 → 贈送 1 小時券"),))}

{_GAME_PRICE_SECTION_DIVIDER}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 以上免指定費**

{_GAME_PRICE_SECTION_DIVIDER}

{_shared_special_service_copy("apex")}"""


def _lol_price_list(interaction: discord.Interaction) -> str:
    return f"""**娛樂陪**
{_aligned_code_block((("ARAM", "每人 350T / H"), ("NG", "每人 350T / H"), ("積分（白金以下）", "每人 280T / 局")))}
積分段位加價：翡翠 +50T、鑽石 +100T、大師 +150T、宗師 +200T、菁英 +250T（每人每局）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Master", "大師陪")}
{_aligned_code_block((("NG", "每人 380T / H"), ("積分（白金以下）", "每人 300T / 局")))}
積分段位加價：翡翠 +50T、鑽石 +100T、大師 +150T、宗師 +200T、菁英 +250T（每人每局）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Grandmaster", "宗師陪")}
{_aligned_code_block((("NG", "每人 390T / H"), ("積分（白金以下）", "每人 350T / 局")))}
積分段位加價：翡翠 +50T、鑽石 +100T、大師 +150T、宗師 +200T、菁英 +250T（每人每局）。

{_GAME_PRICE_SECTION_DIVIDER}

{_rank_heading(interaction, "Challenger", "菁英陪")}
{_aligned_code_block((("NG", "每人 400T / H"), ("積分（白金以下）", "每人 430T / 局")))}
積分段位加價：翡翠 +50T、鑽石 +100T、大師 +150T、宗師 +200T、菁英 +250T（每人每局）。

{_GAME_PRICE_SECTION_DIVIDER}

🎁 **娛樂陪累積回饋**
{_aligned_code_block((("計局", "累積 15 局 → 贈送 1 局券"), ("計時", "累積 10 小時 → 贈送 1 小時券")))}

{_GAME_PRICE_SECTION_DIVIDER}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 或 2局以上免指定費**

{_GAME_PRICE_SECTION_DIVIDER}

{_shared_special_service_copy("lol")}"""


def _steam_price_list(_: discord.Interaction) -> str:
    return f"""**娛樂陪**
{_aligned_code_block((("一般陪玩", "每人 350T / H"),))}

{_GAME_PRICE_SECTION_DIVIDER}

📌 **指定陪玩**
{_aligned_code_block((("指定打手／陪玩", "每人 +100T"),))}
⚠️ **2H 以上免指定費**

{_GAME_PRICE_SECTION_DIVIDER}

{_shared_special_service_copy("steam")}"""


def _price_list_text(interaction: discord.Interaction, channel_id: int) -> str:
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["valorant"]):
        return _valorant_price_list(interaction)
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["lol"]):
        return _lol_price_list(interaction)
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["apex"]):
        return _apex_price_list(interaction)
    if int(channel_id) == int(quick.QUICK_ORDER_V2_CHANNELS["steam"]):
        return _steam_price_list(interaction)
    return "價目表內容整理中，稍後更新。"



# The four non-Delta games use the same one-select price-list interaction as
# Delta's plan selector. Each option displays only the selected service.
GAME_PRICE_LIST_OPTIONS = {
    "valorant": (("entertainment", "娛樂陪"), ("technical", "技術陪"), ("sweet", "甜蜜單"), ("teaching", "教學單")),
    "lol": (("entertainment", "娛樂陪"), ("technical", "技術陪"), ("sweet", "甜蜜單"), ("teaching", "教學單")),
    "apex": (("entertainment", "娛樂陪"), ("technical", "技術陪"), ("sweet", "甜蜜單"), ("teaching", "教學單")),
    "steam": (("entertainment", "娛樂陪"), ("sweet", "甜蜜單")),
}

_GAME_BY_CHANNEL_ID = {
    int(quick.QUICK_ORDER_V2_CHANNELS[game]): game for game in GAME_PRICE_LIST_OPTIONS
}


def _game_price_list_options(channel_id: int) -> tuple[tuple[str, str], ...]:
    return GAME_PRICE_LIST_OPTIONS[_GAME_BY_CHANNEL_ID[int(channel_id)]]


def _game_price_list_sections(
    interaction: discord.Interaction, channel_id: int
) -> dict[str, str]:
    """Reuse the existing approved price copy, displaying one service at a time.

    The existing single-page builders stay as the sole source of amounts and
    rule text. A fixed separator marks each segment; never show it to customers.
    Check the segment count to prevent silent pricing omissions after copy edits.
    """
    game = _GAME_BY_CHANNEL_ID[int(channel_id)]
    full = _price_list_text(interaction, channel_id)
    blocks = full.split(f"\n\n{_GAME_PRICE_SECTION_DIVIDER}\n\n")
    expected = 4 if game == "steam" else 8
    if len(blocks) != expected:
        raise ValueError(f"unexpected {game} price list layout: {len(blocks)} segments")

    if game == "steam":
        return {
            "entertainment": "\n\n".join(blocks[:2]),
            "sweet": blocks[2],
        }

    # Normal play owns loyalty rewards; rank-based play is technical.
    # Both keep the existing specify-fee rules.
    return {
        "entertainment": "\n\n".join((blocks[0], blocks[4], blocks[5])),
        "technical": "\n\n".join((*blocks[1:4], blocks[5])),
        "sweet": blocks[6],
        "teaching": blocks[7],
    }


def _game_root_embed(channel_id: int) -> discord.Embed:
    label = _PRICE_LIST_LABEL_BY_CHANNEL_ID[int(channel_id)]
    return discord.Embed(
        title=f"📋 {label}・陪玩價目",
        description="請選擇要查看的服務分類。",
        color=discord.Color.blurple(),
    )


def _game_plan_embed(
    interaction: discord.Interaction, channel_id: int, plan_key: str
) -> discord.Embed:
    options = dict(_game_price_list_options(channel_id))
    if plan_key not in options:
        raise ValueError(f"unknown game price list service: {plan_key}")
    label = _PRICE_LIST_LABEL_BY_CHANNEL_ID[int(channel_id)]
    text = _game_price_list_sections(interaction, channel_id)[plan_key]
    return discord.Embed(
        title=f"📋 {label}・{options[plan_key]}",
        description=text,
        color=discord.Color.blurple(),
    )


class GamePriceListSelect(discord.ui.Select):
    def __init__(self, channel_id: int, selected: str | None = None):
        self.source_channel_id = int(channel_id)
        super().__init__(
            placeholder="請選擇價目表分類",
            min_values=1,
            max_values=1,
            row=0,
            custom_id=f"quick_order_v2_game_price_list_{self.source_channel_id}",
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    default=key == selected,
                )
                for key, label in _game_price_list_options(channel_id)
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Acknowledge the component immediately; avoid the Discord 3s timeout.
        await interaction.response.defer()
        plan_key = str(self.values[0])
        try:
            await interaction.edit_original_response(
                embed=_game_plan_embed(interaction, self.source_channel_id, plan_key),
                view=GamePriceListView(self.source_channel_id, selected=plan_key),
            )
        except Exception as exc:
            print(
                f"[quick-price-list] game select failed channel={self.source_channel_id} "
                f"plan={plan_key}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            try:
                await interaction.edit_original_response(
                    content="價目表暫時無法載入，請稍後重試或聯繫客服。",
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                pass


class GamePriceListView(discord.ui.View):
    def __init__(self, channel_id: int, selected: str | None = None):
        super().__init__(timeout=840)
        self.add_item(GamePriceListSelect(channel_id, selected=selected))


def _delta_category_label(value: str) -> str:
    for key, label, _ in DELTA_PRICE_LIST_CATEGORIES:
        if key == value:
            return label
    return "三角洲行動"


def _delta_root_embed() -> discord.Embed:
    return discord.Embed(
        title="📋 三角洲行動・價目表",
        description="請先選擇價目表分類。",
        color=discord.Color.blurple(),
    )


def _delta_category_embed(category: str) -> discord.Embed:
    label = _delta_category_label(category)
    description = (
        "請選擇要查看的單子。"
        if category in {"desktop", "mobile", "farm", "fun"}
        else "此分類價目表內容整理中。"
    )
    return discord.Embed(
        title=f"📋 三角洲行動・{label}價目",
        description=description,
        color=discord.Color.blurple(),
    )


def _delta_desktop_embed(plan_key: str) -> discord.Embed:
    plan = DELTA_DESKTOP_PRICE_LISTS[plan_key]
    return discord.Embed(
        title=f"📋 三角洲行動・端遊・{plan['label']}",
        description=str(plan["text"]),
        color=discord.Color.blurple(),
    )


def _delta_mobile_embed(plan_key: str) -> discord.Embed:
    plan = DELTA_MOBILE_PRICE_LISTS[plan_key]
    return discord.Embed(
        title=f"📋 三角洲行動・手遊・{plan['label']}",
        description=str(plan["text"]),
        color=discord.Color.blurple(),
    )


def _delta_farm_embed(plan_key: str) -> discord.Embed:
    plan = DELTA_FARM_PRICE_LISTS[plan_key]
    embed = discord.Embed(
        title=f"📋 三角洲行動・代肝代解・{plan['label']}",
        description=str(plan["text"]),
        color=discord.Color.blurple(),
    )
    image = str(plan.get("image") or "").strip()
    if image:
        embed.set_image(url=_static_asset_url(image))
    return embed


def _delta_fun_embed(plan_key: str) -> discord.Embed:
    plan = DELTA_FUN_PRICE_LISTS[plan_key]
    embed = discord.Embed(
        title=f"📋 三角洲行動・趣味單・{plan['label']}",
        description=str(plan["text"]),
        color=discord.Color.blurple(),
    )
    image = str(plan.get("image") or "").strip()
    if image:
        embed.set_image(url=_static_asset_url(image))
    return embed


class DeltaPriceListCategorySelect(discord.ui.Select):
    def __init__(self, selected: str | None = None):
        super().__init__(
            placeholder="請選擇價目表分類",
            min_values=1,
            max_values=1,
            row=0,
            custom_id="quick_order_v2_delta_price_list_category",
            options=[
                discord.SelectOption(
                    label=label,
                    value=value,
                    emoji=emoji,
                    default=value == selected,
                )
                for value, label, emoji in DELTA_PRICE_LIST_CATEGORIES
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        category = str(self.values[0])
        await interaction.response.edit_message(
            embed=_delta_category_embed(category),
            view=DeltaPriceListView(category=category),
        )


class DeltaDesktopPriceListSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None):
        super().__init__(
            placeholder="請選擇端遊單子",
            min_values=1,
            max_values=1,
            row=1,
            custom_id="quick_order_v2_delta_desktop_price_list",
            options=[
                discord.SelectOption(
                    label=str(plan["label"]),
                    value=key,
                    default=key == selected,
                )
                for key, plan in DELTA_DESKTOP_PRICE_LISTS.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        plan_key = str(self.values[0])
        await interaction.response.edit_message(
            embed=_delta_desktop_embed(plan_key),
            view=DeltaPriceListView(category="desktop", desktop_plan=plan_key),
        )


class DeltaMobilePriceListSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None):
        super().__init__(
            placeholder="請選擇手遊單子",
            min_values=1,
            max_values=1,
            row=1,
            custom_id="quick_order_v2_delta_mobile_price_list",
            options=[
                discord.SelectOption(
                    label=str(plan["label"]),
                    value=key,
                    default=key == selected,
                )
                for key, plan in DELTA_MOBILE_PRICE_LISTS.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        plan_key = str(self.values[0])
        await interaction.response.edit_message(
            embed=_delta_mobile_embed(plan_key),
            view=DeltaPriceListView(category="mobile", mobile_plan=plan_key),
        )


class DeltaFarmPriceListSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None):
        super().__init__(
            placeholder="請選擇代肝代解項目",
            min_values=1,
            max_values=1,
            row=1,
            custom_id="quick_order_v2_delta_farm_price_list",
            options=[
                discord.SelectOption(
                    label=str(plan["label"]),
                    value=key,
                    default=key == selected,
                )
                for key, plan in DELTA_FARM_PRICE_LISTS.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        plan_key = str(self.values[0])
        await interaction.response.edit_message(
            embed=_delta_farm_embed(plan_key),
            view=DeltaPriceListView(category="farm", farm_plan=plan_key),
        )


class DeltaFunPriceListSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None):
        super().__init__(
            placeholder="請選擇趣味單",
            min_values=1,
            max_values=1,
            row=1,
            custom_id="quick_order_v2_delta_fun_price_list",
            options=[
                discord.SelectOption(
                    label=str(plan["label"]),
                    value=key,
                    default=key == selected,
                )
                for key, plan in DELTA_FUN_PRICE_LISTS.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        plan_key = str(self.values[0])
        await interaction.response.edit_message(
            embed=_delta_fun_embed(plan_key),
            view=DeltaPriceListView(category="fun", fun_plan=plan_key),
        )


class DeltaPriceListView(discord.ui.View):
    def __init__(
        self,
        category: str | None = None,
        desktop_plan: str | None = None,
        mobile_plan: str | None = None,
        farm_plan: str | None = None,
        fun_plan: str | None = None,
    ):
        super().__init__(timeout=840)
        self.add_item(DeltaPriceListCategorySelect(selected=category))
        if category == "desktop":
            self.add_item(DeltaDesktopPriceListSelect(selected=desktop_plan))
        elif category == "mobile":
            self.add_item(DeltaMobilePriceListSelect(selected=mobile_plan))
        elif category == "farm":
            self.add_item(DeltaFarmPriceListSelect(selected=farm_plan))
        elif category == "fun":
            self.add_item(DeltaFunPriceListSelect(selected=fun_plan))


def has_price_list(channel_id: int) -> bool:
    return int(channel_id) in _PRICE_LIST_LABEL_BY_CHANNEL_ID


class QuickPriceListButton(discord.ui.Button):
    def __init__(self, channel_id: int):
        self.source_channel_id = int(channel_id)
        super().__init__(
            label="查看價目表",
            emoji="📋",
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id=f"quick_order_v2_price_list_{self.source_channel_id}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Acknowledge promptly to avoid the Discord "未及時回應" banner.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if self.source_channel_id == int(quick.QUICK_ORDER_V2_CHANNELS["delta"]):
                await interaction.edit_original_response(
                    embed=_delta_root_embed(),
                    view=DeltaPriceListView(),
                )
                return

            await interaction.edit_original_response(
                embed=_game_root_embed(self.source_channel_id),
                view=GamePriceListView(self.source_channel_id),
            )
        except Exception as exc:
            print(
                f"[quick-price-list] failed channel={self.source_channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            try:
                await interaction.edit_original_response(
                    content="價目表暫時無法載入，請稍後重試或聯繫客服。",
                    embed=None,
                    view=None,
                )
            except discord.HTTPException:
                pass


def add_price_list_control(view: discord.ui.View, channel_id: int) -> discord.ui.View:
    """Decorate a canonical public quick-order view without patching its factory."""
    if has_price_list(channel_id):
        view.add_item(QuickPriceListButton(int(channel_id)))
    return view


__all__ = [
    "DELTA_DESKTOP_PRICE_LISTS",
    "DELTA_FARM_PRICE_LISTS",
    "DELTA_FUN_PRICE_LISTS",
    "DELTA_MOBILE_PRICE_LISTS",
    "DELTA_PRICE_LIST_CATEGORIES",
    "GAME_PRICE_LIST_OPTIONS",
    "GamePriceListSelect",
    "GamePriceListView",
    "DeltaDesktopPriceListSelect",
    "DeltaFarmPriceListSelect",
    "DeltaFunPriceListSelect",
    "DeltaPriceListView",
    "QuickPriceListButton",
    "add_price_list_control",
    "has_price_list",
]
