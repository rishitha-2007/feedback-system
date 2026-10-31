import os, csv, io, hashlib, random, datetime as dt
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

CATS = {"teaching_quality": "Faculty Teaching Quality", "communication": "Communication",
        "doubt_clarification": "Doubt Clarification"}
LABELS = ["Very poor", "Poor", "Good", "Very good", "Excellent"]
COURSES = [("Database Management Systems", "Faculty A"), ("Operating Systems", "Faculty B"),
           ("Computer Networks", "Faculty C"), ("Cloud Computing", "Faculty D"),
           ("Software Engineering", "Faculty A"), ("Machine Learning", "Faculty E")]
REQS = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"])


def period():
    return dt.date.today().strftime("%Y-%m")


def sid_hash(student_id):  # privacy: admins never see the student ID
    return hashlib.sha256((student_id + os.getenv("SECRET_KEY", "dev-secret")).encode()).hexdigest()


def seed(db):
    if db.users.count_documents({}) == 0:
        db.users.insert_one({"username": "admin", "role": "admin",
                             "password": generate_password_hash(os.getenv("ADMIN_PASSWORD", "admin123"))})
        for i in range(101, 106):
            db.users.insert_one({"username": f"24CSE{i}", "role": "student", "department": "CSE",
                                 "password": generate_password_hash("student123")})
    if db.courses.count_documents({}) == 0:
        db.courses.insert_many([{"subject": s, "faculty": f} for s, f in COURSES])
    if os.getenv("SEED_DEMO") == "1" and db.feedback.count_documents({}) == 0:
        today = dt.date.today()
        for n in range(120):
            s, f = random.choice(COURSES)
            d = today - dt.timedelta(days=random.randint(0, 150))
            db.feedback.insert_one({"student_hash": f"demo{n}", "subject": s, "faculty": f,
                                    "period": d.strftime("%Y-%m"), "created": d.isoformat(),
                                    **{c: random.choice([3, 4, 4, 5, 5, 5, 2, 1]) for c in CATS},
                                    "comments": random.choice(["Explains clearly", "Needs more examples", "", "Great labs"])})


def stats(db, subject="", faculty=""):
    q = {k: v for k, v in (("subject", subject), ("faculty", faculty)) if v}
    docs = list(db.feedback.find(q))
    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else 0
    row = lambda d: avg([d[c] for c in CATS])
    by_fac, by_sub, trend, dist = {}, {}, {}, {i: 0 for i in range(1, 6)}
    for d in docs:
        by_fac.setdefault(d["faculty"], []).append(row(d))
        by_sub.setdefault(d["subject"], []).append(row(d))
        trend.setdefault(d["period"], []).append(row(d))
        dist[min(5, max(1, round(row(d))))] += 1
    return {"total": len(docs), "faculty": len(by_fac), "subjects": len(by_sub),
            "overall": avg([row(d) for d in docs]),
            "cats": {CATS[c]: avg([d[c] for d in docs]) for c in CATS},
            "top": sorted(([k, avg(v), len(v)] for k, v in by_fac.items()), key=lambda x: -x[1]),
            "subject_counts": {k: len(v) for k, v in by_sub.items()},
            "trend": {k: avg(v) for k, v in sorted(trend.items())}, "dist": dist, "docs": docs}


def create_app(db=None):
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret")
    if db is None:
           uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/feedback")
           if uri == "mock":
               import mongomock
               db = mongomock.MongoClient().db
           else:
               db = MongoClient(uri).get_default_database()
    app.db = db
    seed(db)
    db.feedback.create_index([("student_hash", 1), ("faculty", 1), ("subject", 1), ("period", 1)], unique=True)

    def need(role):
        def deco(fn):
            @wraps(fn)
            def wrap(*a, **k):
                if session.get("role") != role:
                    return redirect(url_for("login_admin" if role == "admin" else "login"))
                return fn(*a, **k)
            return wrap
        return deco

    @app.after_request
    def count(resp):
        REQS.labels(request.method, request.endpoint or "none", resp.status_code).inc()
        return resp

    @app.route("/")
    def index():
        return render_template("index.html")

    def do_login(role):
        if request.method == "POST":
            u = db.users.find_one({"username": request.form.get("username", "").strip(), "role": role})
            if u and check_password_hash(u["password"], request.form.get("password", "")):
                session.clear(); session.update(user=u["username"], role=role)
                return redirect(url_for("feedback" if role == "student" else "dashboard"))
            flash("Wrong ID or password. Check both and try again.")
        return render_template("login.html", role=role)

    @app.route("/login", methods=["GET", "POST"])
    def login(): return do_login("student")

    @app.route("/admin/login", methods=["GET", "POST"])
    def login_admin(): return do_login("admin")

    @app.route("/logout")
    def logout():
        session.clear(); return redirect(url_for("index"))

    @app.route("/feedback", methods=["GET", "POST"])
    @need("student")
    def feedback():
        courses = list(db.courses.find())
        if request.method == "POST":
            subject, faculty = request.form.get("course", "|").split("|", 1)
            try:
                r = {c: int(request.form[c]) for c in CATS}
                assert all(1 <= v <= 5 for v in r.values())
                assert db.courses.find_one({"subject": subject, "faculty": faculty})
            except (KeyError, ValueError, AssertionError):
                flash("Select a course and rate all three questions from 1 to 5.")
                return render_template("feedback.html", courses=courses, cats=CATS, labels=LABELS), 400
            doc = {"student_hash": sid_hash(session["user"]), "subject": subject, "faculty": faculty,
                   "period": period(), "created": dt.date.today().isoformat(), **r,
                   "comments": request.form.get("comments", "")[:500]}
            try:
                db.feedback.insert_one(doc)
            except Exception:
                flash("You already submitted feedback for this faculty and subject this month.")
                return render_template("feedback.html", courses=courses, cats=CATS, labels=LABELS), 409
            flash("Your feedback has been submitted successfully.", "ok")
            return redirect(url_for("feedback"))
        return render_template("feedback.html", courses=courses, cats=CATS, labels=LABELS)

    @app.route("/admin")
    @need("admin")
    def dashboard():
        return render_template("dashboard.html", s=stats(db), active="dash")

    @app.route("/admin/responses")
    @need("admin")
    def responses():
        sub, fac = request.args.get("subject", ""), request.args.get("faculty", "")
        s = stats(db, sub, fac)
        return render_template("responses.html", s=s, active="resp", cats=CATS, sub=sub, fac=fac,
                               subjects=sorted({c[0] for c in COURSES}), faculty=sorted({c[1] for c in COURSES}))

    @app.route("/admin/export.csv")
    @need("admin")
    def export():
        s = stats(db, request.args.get("subject", ""), request.args.get("faculty", ""))
        out = io.StringIO(); w = csv.writer(out)
        w.writerow(["date", "subject", "faculty", *CATS, "comments"])
        for d in s["docs"]:
            w.writerow([d["created"], d["subject"], d["faculty"], *[d[c] for c in CATS], d["comments"]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=feedback.csv"})

    @app.route("/health")
    def health(): return {"status": "ok"}

    @app.route("/metrics")
    def metrics(): return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
