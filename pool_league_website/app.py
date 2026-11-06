from __future__ import annotations

import csv
import hmac
import io
import os
import secrets
import sqlite3
from datetime import date
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
DATABASE = Path(os.environ.get("POOL_LEAGUE_DATABASE", INSTANCE_DIR / "pool_league.db"))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "admin123"),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            name TEXT NOT NULL COLLATE NOCASE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(team_id, name)
        );

        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            roster_player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
            actual_player_name TEXT NOT NULL COLLATE NOCASE,
            is_substitution INTEGER NOT NULL DEFAULT 0 CHECK(is_substitution IN (0, 1)),
            league_date TEXT NOT NULL,
            game_number INTEGER NOT NULL,
            balls_pocketed INTEGER NOT NULL CHECK(balls_pocketed BETWEEN 0 AND 7),
            eight_ball INTEGER NOT NULL DEFAULT 0 CHECK(eight_ball IN (0, 1)),
            points INTEGER NOT NULL CHECK(points BETWEEN 0 AND 10),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(eight_ball = 0 OR balls_pocketed = 7)
        );

        CREATE INDEX IF NOT EXISTS idx_scores_date_team ON scores(league_date, team_id);
        CREATE INDEX IF NOT EXISTS idx_scores_player_date ON scores(team_id, league_date, actual_player_name);
        """
    )
    db.commit()


with app.app_context():
    init_db()


def csrf_token() -> str:
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(24)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_template_helpers():
    return {"csrf_token": csrf_token, "current_year": date.today().year}


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            return "The form expired. Go back, refresh the page, and try again.", 400


def player_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        player_id = session.get("player_id")
        if not player_id:
            flash("Choose your player profile to continue.", "error")
            return redirect(url_for("player_portal"))
        player = get_db().execute(
            """SELECT players.*, teams.name AS team_name
               FROM players JOIN teams ON teams.id = players.team_id
               WHERE players.id = ?""",
            (player_id,),
        ).fetchone()
        if player is None:
            session.pop("player_id", None)
            session.pop("team_id", None)
            return redirect(url_for("player_portal"))
        g.player = player
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin sign-in is required.", "error")
            return redirect(url_for("admin_portal"))
        return view(*args, **kwargs)

    return wrapped


def clean_text(value: str | None, maximum: int = 60) -> str:
    return " ".join((value or "").strip().split())[:maximum]


def valid_league_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def points_for_game(balls_pocketed: int, eight_ball: bool) -> int:
    # Seven object balls are worth one point each; a legal 8-ball is worth three.
    return balls_pocketed + (3 if eight_ball else 0)


def get_team_standings(db: sqlite3.Connection):
    return db.execute(
        """SELECT t.id, t.name,
                  COUNT(s.id) AS games,
                  COALESCE(SUM(s.points), 0) AS points,
                  COALESCE(ROUND(AVG(s.points), 2), 0) AS average
           FROM teams t
           LEFT JOIN scores s ON s.team_id = t.id
           GROUP BY t.id
           ORDER BY points DESC, games DESC, t.name COLLATE NOCASE"""
    ).fetchall()


def get_player_rankings(db: sqlite3.Connection):
    return db.execute(
        """SELECT s.actual_player_name AS player_name, t.name AS team_name,
                  COUNT(s.id) AS games,
                  SUM(s.points) AS points,
                  ROUND(AVG(s.points), 2) AS average
           FROM scores s JOIN teams t ON t.id = s.team_id
           GROUP BY s.team_id, s.actual_player_name COLLATE NOCASE
           ORDER BY points DESC, average DESC, games DESC, player_name COLLATE NOCASE"""
    ).fetchall()


@app.get("/")
def home():
    db = get_db()
    stats = {
        "teams": db.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
        "players": db.execute("SELECT COUNT(*) FROM players").fetchone()[0],
        "games": db.execute("SELECT COUNT(*) FROM scores").fetchone()[0],
    }
    standings = get_team_standings(db)[:4]
    return render_template("home.html", stats=stats, standings=standings)


@app.get("/player")
def player_portal():
    if session.get("player_id"):
        return redirect(url_for("player_dashboard"))
    teams = get_db().execute(
        """SELECT t.id, t.name, COUNT(p.id) AS player_count
           FROM teams t LEFT JOIN players p ON p.team_id = t.id
           GROUP BY t.id ORDER BY t.name COLLATE NOCASE"""
    ).fetchall()
    return render_template("player_join.html", teams=teams)


@app.post("/player/join")
def player_join():
    name = clean_text(request.form.get("player_name"), 40)
    team_name = clean_text(request.form.get("team_name"), 40)
    selected_team_id = request.form.get("team_id", "").strip()

    if not name:
        flash("Enter your player name.", "error")
        return redirect(url_for("player_portal"))

    db = get_db()
    team = None
    if selected_team_id:
        team = db.execute("SELECT * FROM teams WHERE id = ?", (selected_team_id,)).fetchone()
        if team is None:
            flash("That team could not be found.", "error")
            return redirect(url_for("player_portal"))
    elif team_name:
        team = db.execute("SELECT * FROM teams WHERE name = ? COLLATE NOCASE", (team_name,)).fetchone()
        if team is None:
            try:
                cursor = db.execute("INSERT INTO teams (name) VALUES (?)", (team_name,))
                team = db.execute("SELECT * FROM teams WHERE id = ?", (cursor.lastrowid,)).fetchone()
            except sqlite3.IntegrityError:
                team = db.execute("SELECT * FROM teams WHERE name = ? COLLATE NOCASE", (team_name,)).fetchone()
    else:
        flash("Choose an existing team or enter a new team name.", "error")
        return redirect(url_for("player_portal"))

    existing = db.execute(
        "SELECT * FROM players WHERE team_id = ? AND name = ? COLLATE NOCASE",
        (team["id"], name),
    ).fetchone()
    if existing:
        player = existing
    else:
        count = db.execute("SELECT COUNT(*) FROM players WHERE team_id = ?", (team["id"],)).fetchone()[0]
        if count >= 4:
            flash("That team already has four roster players. Use the substitution option when entering a sub's game.", "error")
            return redirect(url_for("player_portal"))
        try:
            cursor = db.execute(
                "INSERT INTO players (team_id, name) VALUES (?, ?)", (team["id"], name)
            )
            player = db.execute("SELECT * FROM players WHERE id = ?", (cursor.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            player = db.execute(
                "SELECT * FROM players WHERE team_id = ? AND name = ? COLLATE NOCASE",
                (team["id"], name),
            ).fetchone()

    db.commit()
    session.clear()
    session["player_id"] = player["id"]
    session["team_id"] = team["id"]
    flash(f"You're in, {player['name']}.", "success")
    return redirect(url_for("player_dashboard"))


@app.get("/player/dashboard")
@player_required
def player_dashboard():
    db = get_db()
    league_date = request.args.get("date", date.today().isoformat())
    if not valid_league_date(league_date):
        league_date = date.today().isoformat()
    player = g.player
    team_id = player["team_id"]

    roster = db.execute(
        """SELECT p.id, p.name, COUNT(s.id) AS games, COALESCE(SUM(s.points), 0) AS points
           FROM players p LEFT JOIN scores s
             ON s.roster_player_id = p.id AND s.league_date = ?
           WHERE p.team_id = ? GROUP BY p.id ORDER BY p.name COLLATE NOCASE""",
        (league_date, team_id),
    ).fetchall()
    own_games = db.execute(
        """SELECT COUNT(*) FROM scores
           WHERE team_id = ? AND league_date = ? AND actual_player_name = ? COLLATE NOCASE""",
        (team_id, league_date, player["name"]),
    ).fetchone()[0]
    team_games = db.execute(
        "SELECT COUNT(*) FROM scores WHERE team_id = ? AND league_date = ?",
        (team_id, league_date),
    ).fetchone()[0]
    team_points = db.execute(
        "SELECT COALESCE(SUM(points), 0) FROM scores WHERE team_id = ? AND league_date = ?",
        (team_id, league_date),
    ).fetchone()[0]
    recent_scores = db.execute(
        """SELECT s.*, p.name AS roster_name FROM scores s
           JOIN players p ON p.id = s.roster_player_id
           WHERE s.team_id = ? ORDER BY s.created_at DESC, s.id DESC LIMIT 8""",
        (team_id,),
    ).fetchall()
    rankings = db.execute(
        """SELECT actual_player_name AS player_name, COUNT(*) AS games,
                  SUM(points) AS points, ROUND(AVG(points), 2) AS average
           FROM scores WHERE team_id = ?
           GROUP BY actual_player_name COLLATE NOCASE
           ORDER BY points DESC, average DESC, games DESC""",
        (team_id,),
    ).fetchall()
    return render_template(
        "player_dashboard.html",
        player=player,
        roster=roster,
        league_date=league_date,
        own_games=own_games,
        team_games=team_games,
        team_points=team_points,
        recent_scores=recent_scores,
        rankings=rankings,
    )


@app.post("/player/score")
@player_required
def submit_score():
    db = get_db()
    player = g.player
    league_date = request.form.get("league_date", "")
    if not valid_league_date(league_date):
        flash("Enter a valid league-night date.", "error")
        return redirect(url_for("player_dashboard"))

    try:
        balls = int(request.form.get("balls_pocketed", ""))
    except ValueError:
        balls = -1
    if not 0 <= balls <= 7:
        flash("Balls pocketed must be between 0 and 7.", "error")
        return redirect(url_for("player_dashboard", date=league_date))

    eight_ball = request.form.get("eight_ball") == "on"
    if eight_ball and balls != 7:
        flash("The 8-ball bonus is available only after all seven of your balls are pocketed.", "error")
        return redirect(url_for("player_dashboard", date=league_date))

    is_substitution = request.form.get("is_substitution") == "on"
    substitute_name = clean_text(request.form.get("substitute_name"), 40)
    if is_substitution and not substitute_name:
        flash("Enter the substitute's name.", "error")
        return redirect(url_for("player_dashboard", date=league_date))

    actual_name = substitute_name if is_substitution else player["name"]
    team_id = player["team_id"]

    team_games = db.execute(
        "SELECT COUNT(*) FROM scores WHERE team_id = ? AND league_date = ?",
        (team_id, league_date),
    ).fetchone()[0]
    if team_games >= 16:
        flash("This team has reached the 16-game limit for that league night.", "error")
        return redirect(url_for("player_dashboard", date=league_date))

    player_games = db.execute(
        """SELECT COUNT(*) FROM scores WHERE team_id = ? AND league_date = ?
           AND actual_player_name = ? COLLATE NOCASE""",
        (team_id, league_date, actual_name),
    ).fetchone()[0]
    if player_games >= 4:
        flash(f"{actual_name} has already reached the four-game limit for that league night.", "error")
        return redirect(url_for("player_dashboard", date=league_date))

    points = points_for_game(balls, eight_ball)
    try:
        db.execute(
            """INSERT INTO scores
               (team_id, roster_player_id, actual_player_name, is_substitution,
                league_date, game_number, balls_pocketed, eight_ball, points)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                team_id,
                player["id"],
                actual_name,
                int(is_substitution),
                league_date,
                player_games + 1,
                balls,
                int(eight_ball),
                points,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash("That game could not be saved. Refresh the page and try again.", "error")
        return redirect(url_for("player_dashboard", date=league_date))

    flash(f"Game saved: {points} points for {actual_name}.", "success")
    return redirect(url_for("player_dashboard", date=league_date))


@app.post("/player/logout")
def player_logout():
    session.clear()
    flash("You have left the player dashboard.", "success")
    return redirect(url_for("home"))


@app.get("/admin")
def admin_portal():
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html")


@app.post("/admin/login")
def admin_login():
    password = request.form.get("password", "")
    configured = app.config["ADMIN_PASSWORD"]
    if hmac.compare_digest(password.encode("utf-8"), configured.encode("utf-8")):
        session.clear()
        session["is_admin"] = True
        flash("Admin access granted.", "success")
        return redirect(url_for("admin_dashboard"))
    flash("The admin password was not correct.", "error")
    return redirect(url_for("admin_portal"))


@app.get("/admin/dashboard")
@admin_required
def admin_dashboard():
    db = get_db()
    selected_date = request.args.get("date", "")
    date_filter = selected_date if valid_league_date(selected_date) else ""
    where = "WHERE s.league_date = ?" if date_filter else ""
    params = (date_filter,) if date_filter else ()

    summary = db.execute(
        f"""SELECT COUNT(*) AS games, COALESCE(SUM(s.points), 0) AS points,
                   COUNT(DISTINCT s.team_id) AS active_teams
            FROM scores s {where}""",
        params,
    ).fetchone()
    total_teams = db.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    total_players = db.execute("SELECT COUNT(*) FROM players").fetchone()[0]

    if date_filter:
        standings = db.execute(
            """SELECT t.id, t.name, COUNT(s.id) AS games,
                      COALESCE(SUM(s.points), 0) AS points,
                      COALESCE(ROUND(AVG(s.points), 2), 0) AS average
               FROM teams t LEFT JOIN scores s ON s.team_id = t.id AND s.league_date = ?
               GROUP BY t.id ORDER BY points DESC, games DESC, t.name COLLATE NOCASE""",
            (date_filter,),
        ).fetchall()
        rankings = db.execute(
            """SELECT s.actual_player_name AS player_name, t.name AS team_name,
                      COUNT(*) AS games, SUM(s.points) AS points,
                      ROUND(AVG(s.points), 2) AS average
               FROM scores s JOIN teams t ON t.id = s.team_id
               WHERE s.league_date = ?
               GROUP BY s.team_id, s.actual_player_name COLLATE NOCASE
               ORDER BY points DESC, average DESC, games DESC""",
            (date_filter,),
        ).fetchall()
    else:
        standings = get_team_standings(db)
        rankings = get_player_rankings(db)

    recent_scores = db.execute(
        f"""SELECT s.*, t.name AS team_name, p.name AS roster_name
            FROM scores s JOIN teams t ON t.id = s.team_id
            JOIN players p ON p.id = s.roster_player_id
            {where}
            ORDER BY s.created_at DESC, s.id DESC LIMIT 60""",
        params,
    ).fetchall()

    return render_template(
        "admin_dashboard.html",
        summary=summary,
        total_teams=total_teams,
        total_players=total_players,
        standings=standings,
        rankings=rankings,
        recent_scores=recent_scores,
        selected_date=date_filter,
    )


@app.post("/admin/score/<int:score_id>/delete")
@admin_required
def delete_score(score_id: int):
    db = get_db()
    row = db.execute("SELECT league_date FROM scores WHERE id = ?", (score_id,)).fetchone()
    if row is None:
        flash("That score entry no longer exists.", "error")
    else:
        db.execute("DELETE FROM scores WHERE id = ?", (score_id,))
        db.commit()
        flash("Score entry deleted.", "success")
    return redirect(url_for("admin_dashboard", date=row["league_date"] if row else ""))


@app.get("/admin/export.csv")
@admin_required
def export_scores():
    db = get_db()
    rows = db.execute(
        """SELECT s.league_date, t.name AS team, p.name AS roster_player,
                  s.actual_player_name AS player_who_played,
                  CASE WHEN s.is_substitution = 1 THEN 'Yes' ELSE 'No' END AS substitution,
                  s.game_number, s.balls_pocketed, s.eight_ball, s.points, s.created_at
           FROM scores s JOIN teams t ON t.id = s.team_id
           JOIN players p ON p.id = s.roster_player_id
           ORDER BY s.league_date DESC, t.name, s.actual_player_name, s.game_number"""
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "League date", "Team", "Roster player", "Player who played", "Substitution",
        "Game number", "Balls pocketed", "8-ball made", "Points", "Submitted at",
    ])
    for row in rows:
        writer.writerow(list(row))
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=pool-league-scores.csv"
    return response


@app.post("/admin/logout")
def admin_logout():
    session.clear()
    flash("Admin signed out.", "success")
    return redirect(url_for("home"))


@app.errorhandler(413)
def request_too_large(_error):
    return "The submitted form was too large.", 413


if __name__ == "__main__":
    app.run(debug=True)
