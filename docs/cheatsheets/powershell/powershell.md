# PowerShell Cheatsheet (ta_lab2)

## Git basics

```powershell
# Show status
git status

# Stage everything
git add .

# Commit
git commit -m "message"

# Push
git push

#$env:TARGET_DB_URL
postgresql+psycopg2://postgres:3400@localhost:5432/marketdata