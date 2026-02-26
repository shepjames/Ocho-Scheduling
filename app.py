import hashlib
import itertools
from datetime import date, timedelta

from flask import Flask, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ocho.db"
app.config["SECRET_KEY"] = "ocho-golf-league"
db = SQLAlchemy(app)

# Minimum days between matches for any single team (~1 match per month)
MIN_DAYS_BETWEEN_MATCHES = 21

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(16), nullable=False, unique=True)
    availabilities = db.relationship("Availability", backref="team", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Team {self.name}>"


def make_slug(name):
    """Generate a short unique slug from a team name."""
    return hashlib.md5(name.encode()).hexdigest()[:10]


class Week(db.Model):
    """A playable week in the season."""
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(60), nullable=False)          # e.g. "Week 1 – Jan 6"
    week_date = db.Column(db.Date, nullable=False, unique=True)
    availabilities = db.relationship("Availability", backref="week", cascade="all, delete-orphan")
    matches = db.relationship("Match", backref="week", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Week {self.label}>"


class Availability(db.Model):
    """Marks a team as available for a given week."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    week_id = db.Column(db.Integer, db.ForeignKey("week.id"), nullable=False)

    __table_args__ = (db.UniqueConstraint("team_id", "week_id"),)


class Match(db.Model):
    """A scheduled match between two teams."""
    id = db.Column(db.Integer, primary_key=True)
    week_id = db.Column(db.Integer, db.ForeignKey("week.id"), nullable=False)
    home_team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)

    home_team = db.relationship("Team", foreign_keys=[home_team_id])
    away_team = db.relationship("Team", foreign_keys=[away_team_id])

    def __repr__(self):
        return f"<Match {self.home_team_id} vs {self.away_team_id} week {self.week_id}>"


# ---------------------------------------------------------------------------
# Scheduling algorithm
# ---------------------------------------------------------------------------

def generate_schedule():
    """Generate a round-robin schedule respecting team availability.

    For 8 teams the round-robin produces 28 unique pairings (7 rounds of 4).
    The algorithm places each pairing into a week where:
      - Both teams are available
      - Neither team already has a match that week
      - Neither team has played within MIN_DAYS_BETWEEN_MATCHES days
    This spreads matches to roughly once per month per team.
    """
    teams = Team.query.order_by(Team.id).all()
    weeks = Week.query.order_by(Week.week_date).all()

    if len(teams) < 2 or len(weeks) == 0:
        return False, "Need at least 2 teams and 1 week to generate a schedule."

    # Build availability lookup
    avail_set = set()
    for a in Availability.query.all():
        avail_set.add((a.team_id, a.week_id))

    # Build week date lookup
    week_date = {w.id: w.week_date for w in weeks}

    # Generate round-robin pairings using circle method (balanced rounds)
    n = len(teams)
    fixed = teams[0]
    rotating = list(teams[1:])
    rounds = []
    for _ in range(n - 1):
        current = [fixed] + rotating
        round_pairs = []
        for i in range(n // 2):
            round_pairs.append((current[i], current[n - 1 - i]))
        rounds.append(round_pairs)
        rotating = [rotating[-1]] + rotating[:-1]

    # Track the last scheduled date for each team
    team_last_match_date = {t.id: date.min for t in teams}
    # Track which teams are booked per week
    team_booked_week = set()

    scheduled = []
    unscheduled = []

    for round_pairs in rounds:
        for t1, t2 in round_pairs:
            placed = False
            for w in weeks:
                both_available = (t1.id, w.id) in avail_set and (t2.id, w.id) in avail_set
                neither_booked = (t1.id, w.id) not in team_booked_week and (t2.id, w.id) not in team_booked_week
                t1_rested = (week_date[w.id] - team_last_match_date[t1.id]).days >= MIN_DAYS_BETWEEN_MATCHES
                t2_rested = (week_date[w.id] - team_last_match_date[t2.id]).days >= MIN_DAYS_BETWEEN_MATCHES
                if both_available and neither_booked and t1_rested and t2_rested:
                    scheduled.append((w.id, t1.id, t2.id))
                    team_booked_week.add((t1.id, w.id))
                    team_booked_week.add((t2.id, w.id))
                    team_last_match_date[t1.id] = week_date[w.id]
                    team_last_match_date[t2.id] = week_date[w.id]
                    placed = True
                    break
            if not placed:
                unscheduled.append((t1.name, t2.name))

    # Clear existing matches and write new ones
    Match.query.delete()
    for week_id, home_id, away_id in scheduled:
        db.session.add(Match(week_id=week_id, home_team_id=home_id, away_team_id=away_id))
    db.session.commit()

    if unscheduled:
        pairs_str = ", ".join(f"{a} vs {b}" for a, b in unscheduled)
        return True, f"Schedule generated with {len(scheduled)} matches. Could not place: {pairs_str}. Consider adding more available weeks."
    return True, f"Full round-robin schedule generated: {len(scheduled)} matches across {len(set(s[0] for s in scheduled))} weeks."


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    teams = Team.query.order_by(Team.name).all()
    weeks = Week.query.order_by(Week.week_date).all()
    matches = Match.query.order_by(Match.week_id).all()
    return render_template("index.html", teams=teams, weeks=weeks, matches=matches)


# ---- Teams ----

@app.route("/teams")
def teams():
    teams = Team.query.order_by(Team.name).all()
    return render_template("teams.html", teams=teams)


@app.route("/teams/add", methods=["POST"])
def add_team():
    name = request.form.get("name", "").strip()
    if name:
        existing = Team.query.filter_by(name=name).first()
        if not existing:
            db.session.add(Team(name=name, slug=make_slug(name)))
            db.session.commit()
    return redirect(url_for("teams"))


@app.route("/teams/<int:team_id>/delete", methods=["POST"])
def delete_team(team_id):
    team = Team.query.get_or_404(team_id)
    db.session.delete(team)
    db.session.commit()
    return redirect(url_for("teams"))


# ---- Weeks ----

@app.route("/weeks")
def weeks():
    weeks = Week.query.order_by(Week.week_date).all()
    return render_template("weeks.html", weeks=weeks)


@app.route("/weeks/generate", methods=["POST"])
def generate_weeks():
    """Auto-generate weekly slots from a start date to an end date."""
    start = request.form.get("start_date")
    end = request.form.get("end_date")
    if not start or not end:
        return redirect(url_for("weeks"))
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    week_num = Week.query.count() + 1
    current = start_date
    while current <= end_date:
        existing = Week.query.filter_by(week_date=current).first()
        if not existing:
            label = f"Week {week_num} \u2013 {current.strftime('%b %d')}"
            db.session.add(Week(label=label, week_date=current))
            week_num += 1
        current += timedelta(weeks=1)
    db.session.commit()
    return redirect(url_for("weeks"))


@app.route("/weeks/<int:week_id>/delete", methods=["POST"])
def delete_week(week_id):
    week = Week.query.get_or_404(week_id)
    db.session.delete(week)
    db.session.commit()
    return redirect(url_for("weeks"))


@app.route("/weeks/clear", methods=["POST"])
def clear_weeks():
    Week.query.delete()
    db.session.commit()
    return redirect(url_for("weeks"))


# ---- Availability ----

@app.route("/availability")
def availability():
    teams = Team.query.order_by(Team.name).all()
    weeks = Week.query.order_by(Week.week_date).all()
    avail_set = set()
    for a in Availability.query.all():
        avail_set.add((a.team_id, a.week_id))
    return render_template("availability.html", teams=teams, weeks=weeks, avail_set=avail_set)


@app.route("/availability/update", methods=["POST"])
def update_availability():
    teams = Team.query.all()
    weeks = Week.query.all()
    # Clear all existing availability
    Availability.query.delete()
    for team in teams:
        for week in weeks:
            key = f"avail_{team.id}_{week.id}"
            if key in request.form:
                db.session.add(Availability(team_id=team.id, week_id=week.id))
    db.session.commit()
    return redirect(url_for("availability"))


@app.route("/team/<slug>")
def team_availability(slug):
    """Per-team availability page. Each team gets a unique link."""
    team = Team.query.filter_by(slug=slug).first_or_404()
    weeks = Week.query.order_by(Week.week_date).all()
    avail_set = set()
    for a in Availability.query.filter_by(team_id=team.id).all():
        avail_set.add(a.week_id)
    return render_template("team_availability.html", team=team, weeks=weeks, avail_set=avail_set)


@app.route("/team/<slug>/update", methods=["POST"])
def update_team_availability(slug):
    """Save availability for a single team."""
    team = Team.query.filter_by(slug=slug).first_or_404()
    weeks = Week.query.all()
    # Clear this team's availability only
    Availability.query.filter_by(team_id=team.id).delete()
    for week in weeks:
        key = f"avail_{week.id}"
        if key in request.form:
            db.session.add(Availability(team_id=team.id, week_id=week.id))
    db.session.commit()
    return redirect(url_for("team_availability", slug=slug))


# ---- Schedule ----

@app.route("/schedule")
def schedule():
    weeks = Week.query.order_by(Week.week_date).all()
    schedule_data = []
    for w in weeks:
        matches = Match.query.filter_by(week_id=w.id).all()
        if matches:
            schedule_data.append({"week": w, "matches": matches})
    return render_template("schedule.html", schedule_data=schedule_data)


@app.route("/schedule/generate", methods=["POST"])
def generate():
    success, message = generate_schedule()
    weeks = Week.query.order_by(Week.week_date).all()
    schedule_data = []
    for w in weeks:
        matches = Match.query.filter_by(week_id=w.id).all()
        if matches:
            schedule_data.append({"week": w, "matches": matches})
    return render_template("schedule.html", schedule_data=schedule_data, message=message)


@app.route("/schedule/clear", methods=["POST"])
def clear_schedule():
    Match.query.delete()
    db.session.commit()
    return redirect(url_for("schedule"))


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
