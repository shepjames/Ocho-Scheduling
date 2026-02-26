# Ocho Golf League Scheduler

An 8-team match play golf league scheduler. Teams input their availability, and
the app automatically generates a round-robin schedule where every team plays
every other team.

## Features

- **Team Management** — Add and manage your 8 league teams
- **Season Weeks** — Generate weekly time slots for your Jan–Sep season
- **Availability Input** — Each team marks which weeks they can play
- **Auto Scheduling** — Round-robin matchups generated based on team availability

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 in your browser.

## How It Works

1. **Add Teams** — Enter your 8 team names
2. **Generate Weeks** — Set the season date range to create weekly slots
3. **Enter Availability** — Check off which weeks each team can play
4. **Generate Schedule** — Click the button and the round-robin is built automatically

The scheduler places all 28 unique matchups (C(8,2)) into weeks where both teams
are available and neither is already booked. If availability is too limited to
place every match, it will tell you which pairings couldn't be scheduled.
