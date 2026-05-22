cd "D:\DC bot"

git status
git add shared/db.py shared/staff_models.py web/app/config.py web/.env.example web/app/services/staff_service.py web/app/routers/admin.py web/app/templates/admin.html scripts/sync_staff_members.py cogs/staff_sync.py scripts/install_staff_sync_cog.py bot.py
git commit -m "Add staff sync and dashboard dropdowns"
git push origin web-dashboard

ssh root@178.128.85.16 "cd /opt/dc-bot && git fetch origin web-dashboard && git checkout web-dashboard && git pull origin web-dashboard && /opt/dc-bot/venv/bin/python -m pip install -r requirements.txt && /opt/dc-bot/venv/bin/python -m pip install -r web/requirements-web.txt && /opt/dc-bot/venv/bin/python -c 'from shared.db import create_all_tables; create_all_tables(); print(\"tables created\")' && systemctl restart dc-bot.service && systemctl restart dc-bot-dashboard.service && systemctl status dc-bot-dashboard.service --no-pager -l"
