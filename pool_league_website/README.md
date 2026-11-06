# RackRun — Pool League Website

An English-language, left-to-right, mobile-first Flask + SQLite website with separate player and admin dashboards.

## Features

### Player dashboard
- Join an existing team or create a team by entering its name.
- Teams have up to four roster players.
- Record game results for a selected league-night date.
- Toggle **Substitution** and enter the substitute's name. Scores and individual rankings are credited to the substitute; the roster player who submitted the score is also retained in the database.
- Enforces up to four games per actual player per league night and 16 games per team per night.
- Displays team points, roster activity, player rankings, and recent scores.

### Scoring rules implemented
- Each of the seven object balls is worth one point.
- A legally pocketed 8-ball adds three points.
- Maximum score: **10 points per game**.
- Pocketing all seven object balls without the 8-ball is **7 points**.
- The 8-ball checkbox is enabled only when all seven object balls are selected, and the server validates this rule too.

### Admin dashboard
- Password-protected admin portal.
- Team standings and individual player rankings.
- Filter by league-night date or view all-time totals.
- Review recent score submissions and delete an incorrect entry.
- Export all recorded scores to CSV for spreadsheets and further analysis.

## Run in VS Code (Windows / PowerShell)

Open this folder in VS Code, then open **Terminal → New Terminal**.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```

Open <http://127.0.0.1:5000> in your browser. The SQLite database is created automatically at `instance/pool_league.db` the first time the app runs.

If PowerShell blocks virtual-environment activation, run this once in the terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Admin password and deployment settings

The local development admin password is `admin123`.

Set a different password before using this with a real league. In PowerShell, for the current terminal session:

```powershell
$env:ADMIN_PASSWORD = "choose-a-strong-password"
$env:SECRET_KEY = "replace-with-a-long-random-secret"
py app.py
```

You can also set `POOL_LEAGUE_DATABASE` to choose a different SQLite file path.

## Project structure

```text
pool_league_website/
├── app.py
├── requirements.txt
├── README.md
├── instance/                 # database is created here automatically
├── static/
│   ├── app.js
│   └── style.css
└── templates/
    ├── base.html
    ├── home.html
    ├── player_join.html
    ├── player_dashboard.html
    ├── admin_login.html
    └── admin_dashboard.html
```

## Important notes before public deployment

This is a functional local starter project. Player access is name/team based rather than individual password accounts, so it is intended for a trusted league environment during initial testing. Before putting it on the public internet, add individual player authentication, HTTPS, stronger session-secret management, backups, and an explicit league policy for score corrections. The admin area is password protected; change the development password before deployment.

The current implementation treats a substitute as the person who actually played, credits their individual ranking, and enforces the same four-game cap for that player. The team is capped at 16 recorded games per league night.
