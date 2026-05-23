from pathlib import Path

path = Path("web/app/templates/order_history.html")
text = path.read_text(encoding="utf-8")

replacements = {
    "{{ order.status }}": "{{ {'stored': '存單', 'closed': '結單', 'active': '可接單'}.get(order.status, order.status) }}",
    "{{ item.status }}": "{{ {'stored': '存單', 'closed': '結單', 'active': '可接單'}.get(item.status, item.status) }}",
}

for old, new in replacements.items():
    text = text.replace(old, new)

# 如果模板是直接寫 status badge 文字，也順手替換常見英文
text = text.replace(">stored<", ">存單<")
text = text.replace(">closed<", ">結單<")
text = text.replace(">active<", ">可接單<")

path.write_text(text, encoding="utf-8")
print("patched order history status labels")
