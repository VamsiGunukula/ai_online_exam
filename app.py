import json
import random
import uuid
from datetime import datetime, timezone, timedelta

def get_running_exam():
    """Get the currently running exam based on time window"""
    try:
        # Use naive datetime to match database storage format
        now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        
        # Get all exams and check each one manually
        all_exams = ExamHistory.query.all()
        running_exams = []
        
        for exam in all_exams:
            try:
                start_time = exam.start_time
                end_time = exam.end_time
                
                if start_time and end_time:
                    # Debug output
                    print(f"Exam {exam.subject_name}:")
                    print(f"  Start: {start_time} (type: {type(start_time)})")
                    print(f"  End: {end_time} (type: {type(end_time)})")
                    print(f"  Now: {now} (type: {type(now)})")
                    
                    # Convert to naive datetime if needed
                    if hasattr(start_time, 'tzinfo') and start_time.tzinfo:
                        start_time = start_time.replace(tzinfo=None)
                    if hasattr(end_time, 'tzinfo') and end_time.tzinfo:
                        end_time = end_time.replace(tzinfo=None)
                    
                    # Check if exam is currently running
                    if start_time <= now <= end_time:
                        running_exams.append(exam)
                        print(f"  ✓ RUNNING: {exam.subject_name}")
                    else:
                        print(f"  ✗ Not running")
                        
            except Exception as e:
                print(f"Error checking exam {exam.id}: {e}")
                continue
        
        # Safety: ensure only one exam is active
        if len(running_exams) == 1:
            print(f"✓ Found single running exam: {running_exams[0].subject_name}")
            return running_exams[0]
        elif len(running_exams) == 0:
            print("✗ No exams currently running")
            return None
        else:
            # Multiple exams running - fail safely
            print(f"⚠ WARNING: Multiple exams running: {len(running_exams)}")
            return None
            
    except Exception as e:
        print(f"Critical error in get_running_exam: {e}")
        return None
from functools import wraps

from flask import (
    Flask,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash


def to_ist(dt):
    if not dt:
        return None
    return dt.astimezone(timezone(timedelta(hours=5, minutes=30)))

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key-in-production"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///exam.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Test mode for forcing all correct answers to option "C"
TEST_MODE = True

db = SQLAlchemy(app)

EXAM_TIME_SECONDS = 30 * 60
QUESTIONS_PER_EXAM = 10

TOPIC_SUGGESTIONS = {
    "DBMS": "Practice more questions on DBMS. Revise SQL basics, keys, and relational terminology.",
    "Web & Networking": "Practice more questions on Web & Networking. Review HTTP, HTTPS, and protocols.",
    "Data Structures & Algorithms": "Practice more questions on Arrays and DSA. Drill complexity and structures.",
    "Tools & APIs": "Practice more questions on Git and APIs. Spend time on workflows and REST concepts.",
    "Programming Basics": "Practice more fundamentals: hardware, languages, and runtimes.",
    "General CS": "Practice mixed CS questions to strengthen weak areas.",
}

LEARNING_RESOURCES = {
    "DBMS": {
        "youtube": "https://www.youtube.com/results?search_query=dbms+full+course",
        "website": "https://www.geeksforgeeks.org/dbms/",
    },
    "Web & Networking": {
        "youtube": "https://www.youtube.com/results?search_query=computer+networking+full+course",
        "website": "https://www.geeksforgeeks.org/computer-network-tutorials/",
    },
    "Data Structures & Algorithms": {
        "youtube": "https://www.youtube.com/results?search_query=data+structures+and+algorithms+full+course",
        "website": "https://www.geeksforgeeks.org/data-structures/",
    },
    "Tools & APIs": {
        "youtube": "https://www.youtube.com/results?search_query=rest+api+and+git+tutorial",
        "website": "https://www.geeksforgeeks.org/rest-api-introduction/",
    },
    "Programming Basics": {
        "youtube": "https://www.youtube.com/results?search_query=programming+fundamentals+course",
        "website": "https://www.geeksforgeeks.org/fundamentals-of-algorithms/",
    },
    "General CS": {
        "youtube": "https://www.youtube.com/results?search_query=computer+science+fundamentals",
        "website": "https://www.geeksforgeeks.org/computer-science-fundamentals/",
    },
}

MAX_WARNINGS = 5
PASS_SCORE_THRESHOLD = 75.0


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_admin = db.Column(db.Boolean, default=False)
    allow_reattempt = db.Column(db.Boolean, default=False)
    exam_access_enabled = db.Column(db.Boolean, default=True)
    exam_completed = db.Column(db.Boolean, default=False)
    admin_role = db.Column(db.String(20), nullable=True)
    is_blocked = db.Column(db.Boolean, default=False)
    block_reason = db.Column(db.String(255))

    attempts = db.relationship("Attempt", backref="user", lazy=True)


class BlockedRoll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=True)
    username = db.Column(db.String(100), nullable=True)
    reason = db.Column(db.String(255))


class ExamSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    exam_token = db.Column(db.String(255), unique=True)


class ExamHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_name = db.Column(db.String(100), nullable=False, default="General Exam")
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Question(db.Model):
    __tablename__ = "questions"
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(500), nullable=False)
    option_b = db.Column(db.String(500), nullable=False)
    option_c = db.Column(db.String(500), nullable=False)
    option_d = db.Column(db.String(500), nullable=False)
    correct_answer = db.Column(db.String(1), nullable=False)
    topic = db.Column(db.String(80), default="General CS")


class Attempt(db.Model):
    __tablename__ = "attempts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam_history.id'), nullable=True)
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default="in_progress")
    score = db.Column(db.Float, nullable=True)
    question_ids_json = db.Column(db.Text, nullable=False)
    current_index = db.Column(db.Integer, default=0)
    time_limit_seconds = db.Column(db.Integer, default=EXAM_TIME_SECONDS)
    tab_switch_count = db.Column(db.Integer, default=0)
    face_missing_warnings = db.Column(db.Integer, default=0)
    warning_count = db.Column(db.Integer, default=0)
    warning_details_json = db.Column(db.Text, nullable=False, default="[]")
    timeline_json = db.Column(db.Text, nullable=False, default="[]")
    student_profile_json = db.Column(db.Text, nullable=False, default="{}")
    cheating_risk = db.Column(db.String(20), nullable=True)


class Answer(db.Model):
    __tablename__ = "answers"
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("attempts.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    selected = db.Column(db.String(1), nullable=True)
    confidence = db.Column(db.String(20), default="medium")
    flagged = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    attempt = db.relationship("Attempt", backref=db.backref("answers", lazy=True))
    question = db.relationship("Question")

    __table_args__ = (db.UniqueConstraint("attempt_id", "question_id", name="uq_attempt_question"),)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("admin_login_page"))
        u = db.session.get(User, session["user_id"])
        if not u or not u.is_admin:
            flash("Admin access required.", "error")
            session.pop("user_id", None)
            session.pop("username", None)
            session.pop("is_admin", None)
            session.pop("admin_role", None)
            return redirect(url_for("admin_login_page"))
        return f(*args, **kwargs)

    return decorated


def is_super_admin_user(user):
    return (
        user
        and user.is_admin
        and getattr(user, "admin_role", None) == "super_admin"
    )


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("admin_login_page"))
        u = db.session.get(User, session["user_id"])
        if not is_super_admin_user(u):
            flash("Super administrator permission required.", "error")
            return redirect(url_for("admin_dashboard"))
        return f(*args, **kwargs)

    return decorated


def ensure_bootstrap_admin():
    """One default admin account (change password in production)."""
    if User.query.filter_by(username="admin").first():
        return
    db.session.add(
        User(
            username="admin",
            email="admin@system.local",
            password_hash=generate_password_hash("admin123"),
            is_admin=True,
            allow_reattempt=True,
            exam_access_enabled=True,
            exam_completed=False,
            admin_role="super_admin",
        )
    )
    db.session.commit()


def is_passing_score(score):
    return score is not None and float(score) >= PASS_SCORE_THRESHOLD


def infer_topic_from_text(qtext):
    t = (qtext or "").lower()
    if "sql" in t or "primary key" in t or "relational" in t:
        return "DBMS"
    if "http" in t or "tls" in t or "https" in t or "port is" in t:
        return "Web & Networking"
    if "array" in t or "stack" in t or "queue" in t or "complexity" in t or "binary search" in t or "lifo" in t:
        return "Data Structures & Algorithms"
    if "git" in t or "api stand" in t:
        return "Tools & APIs"
    if "cpu" in t or "browser" in t or "javascript" in t:
        return "Programming Basics"
    return "General CS"


def _add_column_if_missing(table, column, ddl):
    insp = inspect(db.engine)
    names = {c["name"] for c in insp.get_columns(table)}
    if column in names:
        return
    try:
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        db.session.commit()
    except Exception:
        db.session.rollback()

def ensure_block_columns():
    """Ensure block columns exist before using them."""
    from sqlalchemy import text

    try:
        db.session.execute(text("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT 0"))
    except:
        pass

    try:
        db.session.execute(text("ALTER TABLE users ADD COLUMN block_reason TEXT"))
    except:
        pass

    db.session.commit()


def migrate_schema():
    """Add new columns to existing SQLite DBs without breaking data."""
    _add_column_if_missing("questions", "topic", "VARCHAR(80)")
    _add_column_if_missing("attempts", "tab_switch_count", "INTEGER")
    _add_column_if_missing("attempts", "face_missing_warnings", "INTEGER")
    _add_column_if_missing("attempts", "warning_count", "INTEGER")
    _add_column_if_missing("attempts", "timeline_json", 'TEXT DEFAULT "[]"')
    _add_column_if_missing("attempts", "student_profile_json", 'TEXT DEFAULT "{}"')
    _add_column_if_missing("attempts", "cheating_risk", "VARCHAR(20)")
    _add_column_if_missing("answers", "confidence", "VARCHAR(20)")
    _add_column_if_missing("users", "is_admin", "BOOLEAN")
    _add_column_if_missing("users", "allow_reattempt", "BOOLEAN")
    _add_column_if_missing("users", "exam_access_enabled", "BOOLEAN")
    _add_column_if_missing("users", "exam_completed", "BOOLEAN")
    _add_column_if_missing("users", "admin_role", "VARCHAR(20)")
    _add_column_if_missing("users", "roll_number", "VARCHAR(50)")
    _add_column_if_missing("answers", "flagged", "BOOLEAN")

    # Backfill topics
    for q in Question.query.all():
        if not q.topic or q.topic.strip() == "":
            q.topic = infer_topic_from_text(q.text)
    for att in Attempt.query.all():
        if att.tab_switch_count is None:
            att.tab_switch_count = 0
        if att.face_missing_warnings is None:
            att.face_missing_warnings = 0
        if att.warning_count is None:
            att.warning_count = 0
        if not att.timeline_json:
            att.timeline_json = "[]"
        if not att.student_profile_json:
            att.student_profile_json = "{}"
    for a in Answer.query.all():
        if not a.confidence:
            a.confidence = "medium"
        if getattr(a, "flagged", None) is None:
            a.flagged = False

    # Set all questions correct_answer to "C"
    for q in Question.query.all():
        if q.correct_answer != "C":
            q.correct_answer = "C"
            print(f"Updated question {q.id}: correct_answer set to 'C'")

    db.session.commit()
    print("Database migration completed. All questions now have correct_answer = 'C'")

    for u in User.query.all():
        if u.is_admin is None:
            u.is_admin = False
        if u.allow_reattempt is None:
            u.allow_reattempt = False
        if u.exam_access_enabled is None:
            u.exam_access_enabled = True
        if u.is_admin and not getattr(u, "admin_role", None):
            u.admin_role = "super_admin" if u.username == "admin" else "admin"
    for u in User.query.filter_by(is_admin=False).all():
        has_done = Attempt.query.filter_by(user_id=u.id, status="completed").first()
        if has_done:
            u.exam_completed = True
        else:
            u.exam_completed = False
    db.session.commit()
    ensure_bootstrap_admin()


def seed_questions():
    if Question.query.first():
        return
    samples = [
        (
            "What does CPU stand for?",
            "Central Process Unit",
            "Central Processing Unit",
            "Computer Personal Unit",
            "Central Processor Utility",
            "B",
            "Programming Basics",
        ),
        (
            "Which HTTP method is idempotent for updates?",
            "POST",
            "PATCH",
            "GET",
            "CONNECT",
            "C",
            "Web & Networking",
        ),
        (
            "What is 2^10 in decimal?",
            "512",
            "1024",
            "2048",
            "256",
            "B",
            "Data Structures & Algorithms",
        ),
        (
            "Which language runs in a web browser?",
            "Java",
            "C",
            "JavaScript",
            "Python",
            "C",
            "Programming Basics",
        ),
        (
            "What does SQL stand for?",
            "Structured Query Language",
            "Simple Query Language",
            "Standard Query Logic",
            "Sequential Query Layer",
            "A",
            "DBMS",
        ),
        (
            "Which data structure is LIFO?",
            "Queue",
            "Stack",
            "Array",
            "Heap",
            "B",
            "Data Structures & Algorithms",
        ),
        (
            "What is the primary key in a relational table?",
            "A foreign reference",
            "A unique identifier for a row",
            "A column that can be null",
            "An index only",
            "B",
            "DBMS",
        ),
        (
            "Which protocol secures HTTP traffic?",
            "FTP",
            "SMTP",
            "TLS",
            "DNS",
            "C",
            "Web & Networking",
        ),
        (
            "What does API stand for?",
            "Application Programming Interface",
            "Advanced Program Integration",
            "Automated Processing Input",
            "Abstract Protocol Instance",
            "A",
            "Tools & APIs",
        ),
        (
            "Which complexity is typical for binary search on a sorted array?",
            "O(n)",
            "O(log n)",
            "O(n^2)",
            "O(1)",
            "B",
            "Data Structures & Algorithms",
        ),
        (
            "What is Git primarily used for?",
            "Spreadsheets",
            "Version control",
            "Image editing",
            "Email",
            "B",
            "Tools & APIs",
        ),
        (
            "Which port is commonly used for HTTPS?",
            "80",
            "443",
            "22",
            "3306",
            "B",
            "Web & Networking",
        ),
    ]
    for row in samples:
        q = Question(
            text=row[0],
            option_a=row[1],
            option_b=row[2],
            option_c=row[3],
            option_d=row[4],
            correct_answer=row[5],
            topic=row[6],
        )
        db.session.add(q)
    db.session.commit()


def get_attempt_for_user(attempt_id, user_id):
    return Attempt.query.filter_by(id=attempt_id, user_id=user_id).first()


def exam_api_access_guard(user, attempt=None):
    """Exam API: one attempt unless reattempt; exam must be enabled."""
    if not user:
        return ({"error": "not_found"}, 404)

    # Allow current in-progress attempt
    if attempt and attempt.status == "in_progress":
        return (None, None)

    # Check if user already completed this specific exam
    current_exam_id = session.get("exam_id")
    
    if current_exam_id:
        existing_attempt = Attempt.query.filter_by(
            user_id=user.id,
            exam_id=current_exam_id,
            status="completed"
        ).first()
        
        if existing_attempt and not user.allow_reattempt:
            return (
                {
                    "error": "already_completed",
                    "message": "You have already completed this exam.",
                    "dashboard_url": url_for("dashboard"),
                },
                403,
            )

    if not getattr(user, "exam_access_enabled", True):
        return (
            {
                "error": "access_denied",
                "message": "Exam access is disabled.",
            },
            403,
        )

    return (None, None)


def exam_api_reattempt_guard(user, attempt):
    """Block extra in-progress sessions when a completed attempt exists without reattempt."""
    if not attempt or attempt.status != "in_progress":
        return (None, None)
    # Check if user already completed this specific exam
    current_exam_id = session.get("exam_id")
    
    if current_exam_id:
        done = Attempt.query.filter_by(
            user_id=user.id,
            exam_id=current_exam_id,
            status="completed"
        ).first()
        
        if done and not user.allow_reattempt and done.id != attempt.id:
            return (
                {
                    "error": "already_completed",
                    "message": "You have already completed this exam.",
                    "dashboard_url": url_for("dashboard"),
                },
                403,
            )
    return (None, None)


def parse_question_ids(attempt):
    return json.loads(attempt.question_ids_json)


def build_nav_status(attempt):
    qids = parse_question_ids(attempt)
    out = []
    for qid in qids:
        ans = Answer.query.filter_by(attempt_id=attempt.id, question_id=qid).first()
        answered = bool(ans and ans.selected)
        flagged = bool(ans and getattr(ans, "flagged", False))
        out.append({"answered": answered, "flagged": flagged})
    return out


def utc_timestamp(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def remaining_seconds(attempt):
    if attempt.status != "in_progress":
        return 0
    deadline = utc_timestamp(attempt.started_at) + attempt.time_limit_seconds
    now = datetime.now(timezone.utc).timestamp()
    return max(0, int(deadline - now))


def compute_cheating_risk_from_warnings(w):
    """0–1 Low, 2–3 Medium, 4–5 High (based on global warning count)."""
    w = w or 0
    if w <= 1:
        return "Low"
    if w <= 3:
        return "Medium"
    return "High"


def compute_cheating_risk(attempt):
    return compute_cheating_risk_from_warnings(attempt.warning_count)


def parse_warning_details(attempt):
    raw = attempt.warning_details_json or "[]"
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def parse_timeline(attempt):
    raw = attempt.timeline_json or "[]"
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def parse_student_profile(attempt):
    raw = attempt.student_profile_json or "{}"
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def append_warning_detail(attempt, warning_type, reason, question_number):
    details = parse_warning_details(attempt)
    details.append(
        {
            "type": warning_type or "General",
            "message": reason or "Policy violation detected",
            "question": int(question_number or 0),
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        }
    )
    attempt.warning_details_json = json.dumps(details[-50:])


def append_timeline_event(attempt, event_name, question_number):
    timeline = parse_timeline(attempt)
    timeline.append(
        {
            "event": event_name or "Event",
            "question": int(question_number or 0),
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        }
    )
    attempt.timeline_json = json.dumps(timeline[-200:])


def normalize_confidence(val):
    v = (val or "medium").lower()
    if v in ("low", "medium", "high"):
        return v
    return "medium"


def finalize_attempt(attempt):
    if attempt.status != "in_progress":
        return
    qids = parse_question_ids(attempt)
    correct = 0
    total = len(qids)
    
    print(f"=== Backend Scoring Debug ===")
    print(f"TEST_MODE: {TEST_MODE}")
    print(f"Total questions: {total}")
    
    for qid in qids:
        ans = Answer.query.filter_by(attempt_id=attempt.id, question_id=qid).first()
        q = db.session.get(Question, qid)
        
        print(f"Question {qid}:")
        print(f"  Answer exists: {ans is not None}")
        print(f"  Question exists: {q is not None}")
        
        if q and ans and ans.selected:
            print(f"  Selected: '{ans.selected}' (type: {type(ans.selected)})")
            print(f"  Selected upper: '{ans.selected.upper()}'")
            
            if TEST_MODE:
                # In test mode, treat "C" as correct answer for all questions
                expected = "C"
                is_correct = ans.selected.upper() == "C"
                print(f"  TEST_MODE - Expected: '{expected}'")
            else:
                # Normal mode: compare with actual correct answer
                expected = q.correct_answer.upper()
                is_correct = ans.selected.upper() == q.correct_answer.upper()
                print(f"  NORMAL MODE - Expected: '{expected}'")
                print(f"  Actual correct_answer: '{q.correct_answer}' (type: {type(q.correct_answer)})")
            
            print(f"  Comparison: '{ans.selected.upper()}' == '{expected}' = {is_correct}")
            
            if is_correct:
                correct += 1
                print(f"  -> CORRECT! Total correct: {correct}")
            else:
                print(f"  -> INCORRECT")
        else:
            print(f"  -> NO ANSWER or MISSING QUESTION")
    
    print(f"Final backend score: {correct}/{total}")
    print("==============================")
    attempt.score = round(100.0 * correct / total, 1) if total else 0.0
    attempt.cheating_risk = compute_cheating_risk(attempt)
    attempt.status = "completed"
    attempt.ended_at = datetime.now(timezone.utc)
    db.session.commit()


def build_report_data(attempt):
    """Topic stats, suggestions, confidence insights."""
    qids = parse_question_ids(attempt)
    by_topic = {}
    overconfident_wrong = 0
    underconfident_right = 0
    calibrated_high = 0

    for qid in qids:
        q = db.session.get(Question, qid)
        if not q:
            continue
        ans = Answer.query.filter_by(attempt_id=attempt.id, question_id=qid).first()
        topic = (q.topic or "General CS").strip()
        if topic not in by_topic:
            by_topic[topic] = {"correct": 0, "total": 0}
        by_topic[topic]["total"] += 1
        selected = (ans.selected or "").upper() if ans else ""
        
        if TEST_MODE:
            # In test mode, treat "C" as correct answer for all questions
            is_correct = selected == "C"
        else:
            # Normal mode: compare with actual correct answer
            is_correct = bool(selected and selected == q.correct_answer.upper())
            
        if is_correct:
            by_topic[topic]["correct"] += 1

        conf = normalize_confidence(ans.confidence if ans else "medium")
        if is_correct and conf == "low":
            underconfident_right += 1
        if not is_correct and conf == "high":
            overconfident_wrong += 1
        if is_correct and conf == "high":
            calibrated_high += 1

    topic_rows = []
    for name, st in by_topic.items():
        tot = st["total"]
        acc = round(100.0 * st["correct"] / tot, 1) if tot else 0.0
        topic_rows.append({"name": name, "accuracy": acc, "correct": st["correct"], "total": tot})

    topic_rows.sort(key=lambda x: x["accuracy"])
    weak = [r for r in topic_rows if r["accuracy"] < 70.0]
    strong = [r for r in topic_rows if r["accuracy"] >= 70.0]

    suggestions = []
    seen = set()
    for r in weak:
        t = r["name"]
        if t in TOPIC_SUGGESTIONS and t not in seen:
            suggestions.append(TOPIC_SUGGESTIONS[t])
            seen.add(t)
        elif t not in seen:
            suggestions.append("Practice more questions on " + t + ".")
            seen.add(t)
    if not suggestions and topic_rows:
        suggestions.append("Keep practicing mixed topics to stay balanced.")

    conf_insights = {
        "overconfident_wrong": overconfident_wrong,
        "underconfident_right": underconfident_right,
        "calibrated_high": calibrated_high,
    }

    return {
        "topic_rows": topic_rows,
        "weak_topics": weak,
        "strong_topics": strong,
        "suggestions": suggestions,
        "confidence_insights": conf_insights,
    }


def report_url_for_attempt(attempt_id):
    return url_for("exam_report", attempt_id=attempt_id)


@app.route("/")
def home():
    return render_template("welcome.html")


@app.route("/models/<path:filename>")
def face_models(filename):
    return send_from_directory("static/models", filename)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        roll_number = request.form.get("roll_number", "").strip()
        password = request.form.get("password", "")
        
        if not roll_number:
            last_user = User.query.order_by(User.id.desc()).first()
            next_id = last_user.id + 1 if last_user else 1
            roll_number = str(next_id)
        if not username or not email or not password:
            flash("All fields are required.", "error")
        elif User.query.filter_by(username=username).first():
            flash("Username already taken.", "error")
        elif User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
        elif User.query.filter_by(roll_number=roll_number).first():
            flash("Roll number already exists.", "error")
        else:
            user = User(
                username=username,
                email=email,
                roll_number=roll_number,
                password_hash=generate_password_hash(password),
                is_admin=False,
                allow_reattempt=False,
                exam_completed=False,
                exam_access_enabled=True,
            )
            db.session.add(user)
            db.session.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        roll_number = request.form.get("roll_number", "").strip()
        password = request.form.get("password", "")
        roll = request.form.get("roll_number", "").strip()
        
        blocked = BlockedRoll.query.filter(
            (BlockedRoll.roll_number == roll) |
            (BlockedRoll.username == username)
        ).first()
        
        if blocked:
            flash("You are blocked by admin", "error")
            return redirect(url_for("login"))
        
        user = User.query.filter(
            (User.username == username) |
            (User.roll_number == roll_number)
        ).first()
        
        if user:
            if user.is_blocked is None:
                user.is_blocked = False
            if user.is_blocked is True:
                flash("Your account is blocked by admin", "error")
                return redirect(url_for("login"))
            
        if user and check_password_hash(user.password_hash, password):
            if getattr(user, "is_admin", False):
                flash("Use the admin sign-in page for staff accounts.", "info")
                return redirect(url_for("admin_login_page"))
            session["user_id"] = user.id
            session["username"] = user.username
            session["is_admin"] = False
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")
def logout():
    session.clear()

@app.route('/exam_rules')
@login_required
def exam_rules():
    # Safety check: ensure user has exam_id in session
    if "exam_id" not in session:
        # Try to auto-assign running exam
        running_exam = get_running_exam()
        if running_exam:
            session["exam_id"] = running_exam.id
        else:
            flash("No exam is running right now.", "error")
            return redirect(url_for("dashboard"))
    
    # Verify exam still exists and is running
    exam = ExamHistory.query.get(session["exam_id"])
    if not exam:
        flash("Exam not found.", "error")
        session.pop("exam_id", None)
        return redirect(url_for("dashboard"))
    
    exams = ExamHistory.query.order_by(ExamHistory.start_time.desc()).all()
    now = datetime.utcnow().replace(tzinfo=None)
    return render_template('exam_rules.html', exams=exams, now=now)

@app.route('/start_exam', methods=['POST'])
@login_required
def start_exam():
    # Check if user has access to start exam
    user = User.query.get(session['user_id'])
    if not user.exam_access_enabled:
        flash("Exam access is disabled", "error")
        return redirect(url_for('dashboard'))
    
    # Check if user already has an in-progress attempt
    existing_attempt = Attempt.query.filter_by(
        user_id=user.id,
        status='in_progress'
    ).first()
    
    if existing_attempt:
        return redirect(url_for('exam', attempt_id=existing_attempt.id))
    
    # Check if user already completed and no reattempt allowed
    completed_attempt = Attempt.query.filter_by(
        user_id=user.id,
        status='completed'
    ).first()
    
    if completed_attempt and not user.allow_reattempt:
        flash("You have already completed the exam", "error")
        return redirect(url_for('dashboard'))
    
    # Get running exam
    running_exam = get_running_exam()
    if not running_exam:
        flash("No exam is currently running", "error")
        return redirect(url_for('dashboard'))
    
    # Get random questions
    import json
    questions = Question.query.order_by(db.func.random()).limit(10).all()
    
    # Extract question IDs
    question_ids = [q.id for q in questions]
    
    # Convert to JSON
    question_ids_json = json.dumps(question_ids)
    
    # Create new attempt
    attempt = Attempt(
        user_id=user.id,
        exam_id=running_exam.id,
        question_ids_json=question_ids_json,
        current_index=0,
        status='in_progress',
        time_limit_seconds=1800,
        started_at=datetime.utcnow()
    )
    db.session.add(attempt)
    db.session.commit()
    
    return redirect(url_for('exam', attempt_id=attempt.id))

@app.route('/exam/<int:attempt_id>')
@login_required
def exam(attempt_id):
    # Get the attempt
    attempt = Attempt.query.get(attempt_id)
    if not attempt:
        flash("Exam not found", "error")
        return redirect(url_for('dashboard'))
    
    # Verify user owns this attempt
    if attempt.user_id != session['user_id']:
        flash("Access denied", "error")
        return redirect(url_for('dashboard'))
    
    # Check if attempt is in progress
    if attempt.status != 'in_progress':
        flash("Exam is not in progress", "error")
        return redirect(url_for('dashboard'))
    
    # Check if time has expired
    if remaining_seconds(attempt) <= 0:
        finalize_attempt(attempt)
        flash("Exam time has expired", "error")
        return redirect(url_for('dashboard'))
    
    return render_template('exam.html', attempt=attempt)

@app.route("/admin")
@admin_required
def admin_dashboard():
    students = User.query.filter_by(is_admin=False).order_by(User.username).all()
    rows = []
    for u in students:
        attempt_count = Attempt.query.filter_by(user_id=u.id).count()
        latest = (
            Attempt.query.filter_by(user_id=u.id, status="completed")
            .order_by(Attempt.ended_at.desc())
            .first()
        )
        rep = build_report_data(latest) if latest else None
        sc = latest.score if latest and latest.score is not None else None
        rows.append(
            {
                "user": u,
                "latest_attempt": latest,
                "attempt_count": attempt_count,
                "score": sc,
                "passed": is_passing_score(latest.score) if latest else None,
                "weak": rep["weak_topics"] if rep else [],
                "strong": rep["strong_topics"] if rep else [],
                "warnings": int(latest.warning_count or 0) if latest else 0,
            }
        )
    with_score = [r for r in rows if r["score"] is not None]
    without_score = [r for r in rows if r["score"] is None]
    top_rows = sorted(with_score, key=lambda r: float(r["score"]), reverse=True) + sorted(
        without_score, key=lambda r: r["user"].username.lower()
    )
    failed_rows = [
        r
        for r in rows
        if r["latest_attempt"] is not None and not is_passing_score(r["latest_attempt"].score)
    ]
    failed_rows.sort(key=lambda r: float(r["latest_attempt"].score or 0.0))
    recent_attempts = Attempt.query.order_by(Attempt.started_at.desc()).limit(40).all()
    completed_attempts = Attempt.query.filter_by(status="completed").all()
    all_scores = [a.score for a in completed_attempts if a.score is not None]
    avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
    weak_topic_counts = {}
    high_warning_users = 0
    for row in rows:
        for t in row["weak"]:
            weak_topic_counts[t["name"]] = weak_topic_counts.get(t["name"], 0) + 1
        if row["latest_attempt"] and int(row.get("warnings") or 0) >= 4:
            high_warning_users += 1
    most_weak_topic = None
    if weak_topic_counts:
        most_weak_topic = max(weak_topic_counts.items(), key=lambda kv: kv[1])[0]
    cur = db.session.get(User, session["user_id"])
    is_super = is_super_admin_user(cur)
    admin_accounts = (
        User.query.filter_by(is_admin=True).order_by(User.username.asc()).all()
    )
    
    return render_template(
        "admin/dashboard.html",
        rows=top_rows,
        failed_rows=failed_rows,
        recent_attempts=recent_attempts,
        pass_threshold=PASS_SCORE_THRESHOLD,
        avg_score=avg_score,
        most_weak_topic=most_weak_topic,
        high_warning_users=high_warning_users,
        is_super=is_super,
        admin_accounts=admin_accounts,
        schedule=ExamSchedule.query.first(),
        latest_exam=ExamSchedule.query.order_by(ExamSchedule.start_time.desc()).first(),
        current_time=datetime.utcnow() + timedelta(hours=5, minutes=30),
    )

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    if "user_id" in session:
        u = db.session.get(User, session["user_id"])
        if u and u.is_admin:
            return redirect(url_for("admin_dashboard"))
        if u and not u.is_admin:
            session.pop("user_id", None)
            session.pop("username", None)
            session.pop("is_admin", None)
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.is_admin and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["is_admin"] = True
            session["admin_role"] = user.admin_role or "admin"
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials.", "error")
    return render_template("admin/login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login_page"))

@app.route('/admin/create-exam', methods=['GET', 'POST'])
@admin_required
def create_exam_page():
    if request.method == 'POST':
        start_time = datetime.fromisoformat(request.form["start_time"])
        end_time = datetime.fromisoformat(request.form["end_time"])

        now = datetime.utcnow() + timedelta(hours=5, minutes=30)

        # Check if start time is in past
        if start_time <= now:
            flash("Cannot schedule exam in past time", "danger")
            return redirect(url_for("create_exam_page"))

        # Check if end time is in past
        if end_time <= now:
            flash("End time must be in future", "danger")
            return redirect(url_for("create_exam_page"))

        # Check start < end
        if start_time >= end_time:
            flash("End time must be after start time", "danger")
            return redirect(url_for("create_exam_page"))

        existing_exam = ExamSchedule.query.order_by(ExamSchedule.id.desc()).first()

        if existing_exam:
            if start_time < existing_exam.end_time and end_time > existing_exam.start_time:
                flash(
                    f"⚠️ Exam already scheduled from "
                    f"{existing_exam.start_time.strftime('%H:%M')} to "
                    f"{existing_exam.end_time.strftime('%H:%M')}",
                    "error"
                )
                return redirect(url_for("create_exam_page"))

        # Delete old schedule ONLY
        old_schedule = ExamSchedule.query.first()
        if old_schedule:
            db.session.delete(old_schedule)
        exam_token = str(uuid.uuid4())
        
        new_exam = ExamSchedule(
            start_time=start_time,
            end_time=end_time,
            exam_token=exam_token
        )

        db.session.add(new_exam)
        
        # Get exam name from form
        subject_name = request.form.get('subject_name', '').strip() or "General Exam"
        
        # Save exam history
        exam_history = ExamHistory(
            subject_name=subject_name,
            start_time=start_time,
            end_time=end_time
        )
        
        db.session.add(exam_history)
        db.session.commit()

        flash("✅ Exam scheduled successfully!", "success")

        return redirect(url_for("admin_dashboard"))

    # For GET request, always return the create exam page
    return render_template(
        'create_exam.html',
        now=datetime.utcnow().strftime('%Y-%m-%dT%H:%M')
    )

@app.route('/admin/exam-history')
@admin_required
def exam_history():
    # Fetch all exams from exam_history table
    exams = ExamHistory.query.order_by(ExamHistory.start_time.desc()).all()
    
    # IMPORTANT FIX: Ensure exams is not None
    if exams is None:
        exams = []
    
    # Fetch latest scheduled exam (current/active exam)
    current_exam = ExamSchedule.query.first()
    
    # Add student count to current exam if it exists
    if current_exam:
        student_count = Attempt.query.filter(
            Attempt.started_at >= current_exam.start_time,
            Attempt.started_at <= current_exam.end_time,
            Attempt.status == 'completed'
        ).count()
        current_exam.total_students = student_count
    
    # Add student count and status to each exam
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    
    for exam in exams:
        # Count attempts for this exam time period
        student_count = Attempt.query.filter(
            Attempt.started_at >= exam.start_time,
            Attempt.started_at <= exam.end_time,
            Attempt.status == 'completed'
        ).count()
        exam.total_students = student_count
        
        # Calculate exam status based on real datetime comparison
        if exam.start_time <= now <= exam.end_time:
            exam.status = "RUNNING"
        elif now > exam.end_time:
            exam.status = "COMPLETED"
        else:
            exam.status = "NOT STARTED"
    
    return render_template('exam_history.html', exams=exams, now=now)

@app.route('/admin/exam/delete/<int:exam_id>', methods=['POST'])
@admin_required
def delete_exam(exam_id):
    try:
        print("Deleting exam ID:", exam_id)

        # Delete from ExamHistory
        exam = ExamHistory.query.get(exam_id)

        if not exam:
            flash("Exam not found", "danger")
            return redirect(url_for('exam_history'))

        # ALSO DELETE matching schedule (IMPORTANT FIX)
        schedule = ExamSchedule.query.filter(
            ExamSchedule.start_time == exam.start_time,
            ExamSchedule.end_time == exam.end_time
        ).first()

        if schedule:
            db.session.delete(schedule)

        db.session.delete(exam)

        db.session.commit()

        flash("Exam deleted successfully", "success")

    except Exception as e:
        db.session.rollback()
        print("DELETE ERROR:", e)
        flash("Delete failed", "danger")

    return redirect(url_for('exam_history'))

@app.route('/admin/exam/<int:exam_id>/students')
@admin_required
def admin_exam_students(exam_id):
    exam = ExamHistory.query.get_or_404(exam_id)

    print("Fetching attempts for exam:", exam_id)
    print("Exam details:", exam.subject_name)

    # Fetch attempts using both exam_id and time range fallback
    attempts = Attempt.query.filter(
        Attempt.status == "completed",
        (
            (Attempt.exam_id == exam_id) |
            (
                (Attempt.exam_id == None) &
                (Attempt.started_at >= exam.start_time) &
                (Attempt.started_at <= exam.end_time)
            )
        )
    ).all()

    print("Found attempts for exam:", len(attempts))

    students = []

    for attempt in attempts:
        user = User.query.get(attempt.user_id)
        
        if not user:
            print(f"User not found for attempt ID: {attempt.id}")
            continue

        # Build students list with required structure
        students.append({
            "name": user.username,
            "roll": user.roll_number,
            "score": attempt.score,
            "attempt_id": attempt.id,
            "status": "Pass" if attempt.score >= 75 else "Fail"
        })

    print("Final students count:", len(students))

    return render_template(
        'admin_exam_students.html',
        students=students,
        exam=exam
    )

@app.route('/admin/students', methods=['GET', 'POST'])
@admin_required
def admin_students():
    if request.method == 'POST':
        roll_no = request.form.get('roll_no')
        reason = request.form.get('reason')
        username = request.form.get('name', '')

        if not username or username.strip() == "":
            username = "Unknown"

        existing = BlockedRoll.query.filter_by(roll_number=roll_no).first()

        if existing:
            flash("Student already blocked!", "warning")
            return redirect(request.referrer)

        new_block = BlockedRoll(
            roll_number=roll_no,
            username=username,
            reason=reason
        )
        db.session.add(new_block)
        db.session.commit()

        flash("Student blocked successfully!", "success")
        return redirect(request.referrer)

    # TEMP FIX: Update existing None usernames to "Unknown"
    try:
        BlockedRoll.query.filter_by(username=None).update({"username": "Unknown"})
        db.session.commit()
    except:
        pass

    students = User.query.filter_by(is_admin=False).all()
    return render_template('block_student.html', students=students)

@app.route('/admin/below-pass')
@admin_required
def admin_below_pass():
    try:
        students = User.query.filter_by(is_admin=False).all()
        below_pass = []
        for student in students:
            latest_attempt = Attempt.query.filter_by(user_id=student.id).order_by(Attempt.started_at.desc()).first()
            if latest_attempt and latest_attempt.score is not None and latest_attempt.score < 75:
                below_pass.append({'student': student, 'attempt': latest_attempt})
        return render_template('admin/admin_below_pass.html', below_pass=below_pass)
    except Exception as e:
        return f"Error loading below pass page: {str(e)}"

@app.route('/admin/pass-rule')
@admin_required
def admin_pass_rule():
    try:
        students = User.query.filter_by(is_admin=False).all()
        pass_students = []
        for student in students:
            latest_attempt = Attempt.query.filter_by(user_id=student.id).order_by(Attempt.started_at.desc()).first()
            if latest_attempt and latest_attempt.score is not None and latest_attempt.score >= 75:
                pass_students.append({'student': student, 'attempt': latest_attempt})
        return render_template('admin/admin_pass_rule.html', pass_students=pass_students)
    except Exception as e:
        return f"Error loading pass rule page: {str(e)}"

@app.route('/admin/average-score')
@admin_required
def admin_average_score():
    try:
        attempts = Attempt.query.filter_by(status='completed').all()
        if attempts:
            scores = [a.score for a in attempts if a.score is not None]
            avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        else:
            avg_score = 0
        return render_template('admin/admin_average_score.html', avg_score=avg_score, total_attempts=len(attempts))
    except Exception as e:
        return f"Error loading average score page: {str(e)}"

@app.route('/admin/high-warnings')
@admin_required
def admin_high_warnings():
    try:
        attempts = Attempt.query.filter(
        Attempt.warning_count > 0
    ).order_by(
        Attempt.warning_count.desc()
    ).all()
        high_warning_users = []
        for attempt in attempts:
            if attempt.warning_count > 0:
                high_warning_users.append({'user': attempt.user, 'attempt': attempt, 'warnings': attempt.warning_count})
        return render_template('admin/admin_high_warnings.html', high_warning_users=high_warning_users)
    except Exception as e:
        return f"Error loading high warnings page: {str(e)}"

@app.route('/admin/weak-topics')
@admin_required
def admin_weak_topics():
    try:
        # Simple implementation - show all attempts with weak topics
        attempts = Attempt.query.filter_by(status='completed').all()
        weak_topics_data = []
        for attempt in attempts:
            # Get weak topics from existing data structure if available
            if hasattr(attempt, 'weak_topics') and attempt.weak_topics:
                weak_topics_data.append({'user': attempt.user, 'weak_topics': attempt.weak_topics})
        return render_template('admin/admin_weak_topics.html', weak_topics_data=weak_topics_data)
    except Exception as e:
        return f"Error loading weak topics page: {str(e)}"


@app.route('/admin/report/<int:attempt_id>')
@admin_required
def admin_view_report(attempt_id):
    try:
        # Get the attempt
        attempt = Attempt.query.get(attempt_id)
        if not attempt:
            flash("Report not found.", "error")
            return redirect(url_for('admin_students'))
        
        original_user_id = session.get('user_id')
        session['user_id'] = attempt.user_id
        
        try:
            # Redirect to existing exam_report function
            return redirect(url_for('exam_report', attempt_id=attempt_id))
        finally:
            # Restore original admin session
            session['user_id'] = original_user_id
            
    except Exception as e:
        flash(f"Error loading report: {str(e)}", "error")
        return redirect(url_for('admin_students'))


@app.route('/admin/reattempt/<int:attempt_id>')
@admin_required
def admin_reattempt(attempt_id):
    old_attempt = Attempt.query.get(attempt_id)
    
    if not old_attempt:
        return "Attempt not found", 404
    
    user = db.session.get(User, old_attempt.user_id)
    if not user:
        flash("Invalid student", "error")
        return redirect(url_for("admin_dashboard"))
    
    # RESET USER FLAGS (IMPORTANT)
    user.allow_reattempt = True
    user.exam_completed = False
    user.exam_access_enabled = True
    
    # DELETE OLD IN-PROGRESS ATTEMPTS (SAFE CLEANUP)
    Attempt.query.filter_by(user_id=user.id, status="in_progress").delete()
    
    db.session.commit()
    
    flash("Reattempt enabled successfully", "success")
    return redirect(url_for('admin_exam_students', exam_id=old_attempt.exam_id))

@app.route("/admin/block_student", methods=["GET", "POST"])
def block_student():
    if request.method == "POST":
        name = request.form.get("name")
        roll = request.form.get("roll")
        reason = request.form.get("reason") or ""

        if not name or not roll:
            flash("Name and Roll No required", "error")
            return redirect("/admin/block_student")

        # save into blocked table (or your logic)
        try:
            new_block = BlockedRoll(
                roll_number=roll,
                username=name,
                reason=reason
            )
            db.session.add(new_block)
            db.session.commit()
            flash("Student blocked successfully", "success")
        except Exception as e:
            db.session.rollback()
            flash("Already blocked or error occurred", "error")

        return redirect("/admin")

    return render_template("admin/block_student.html")


@app.route("/admin/blocked_students")
def blocked_students():
    blocked_students = BlockedRoll.query.all()
    total_blocked = len(blocked_students)
    return render_template(
        "blocked_students.html",
        blocked_students=blocked_students,
        total_blocked=total_blocked
    )


@app.route("/admin/unblock_student/<int:id>", methods=["POST"])
def unblock_student(id):
    record = BlockedRoll.query.get(id)
    if record:
        db.session.delete(record)
        db.session.commit()
        flash("Student unblocked successfully", "success")
    return redirect("/admin/blocked_students")


@app.route("/admin/all-students")
@admin_required
def all_students():
    students = User.query.filter_by(is_admin=False).all()
    return render_template("admin/all_students.html", students=students)

@app.route('/admin/student/<id>')
@admin_required
def admin_student_detail(id):
    student = None
    try:
        # Try to get student from existing data if available
        student = User.query.get(int(id)) if id.isdigit() else None
    except:
        student = None
    
    return render_template('admin/student_detail.html', student=student)

@app.route('/admin/toggle_exam_access/<int:user_id>', methods=['POST'])
@admin_required
def admin_toggle_exam_access(user_id):
    user = User.query.get(user_id)
    if not user:
        flash("Student not found", "error")
        return redirect(url_for('admin_dashboard'))
    
    # Toggle exam access
    user.exam_access_enabled = not user.exam_access_enabled
    db.session.commit()
    
    status = "enabled" if user.exam_access_enabled else "disabled"
    flash(f"Exam access {status} for {user.username}", "success")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/grant_reattempt/<int:user_id>', methods=['POST'])
@admin_required
def admin_grant_reattempt(user_id):
    user = User.query.get(user_id)
    if not user:
        flash("Student not found", "error")
        return redirect(url_for('admin_dashboard'))
    
    # Grant reattempt permission
    user.allow_reattempt = True
    user.exam_completed = False
    user.exam_access_enabled = True
    db.session.commit()
    
    flash(f"Reattempt granted for {user.username}", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_admin_user/<int:admin_id>', methods=['POST'])
@admin_required
def admin_delete_admin_user(admin_id):
    admin = User.query.get(admin_id)
    if not admin:
        flash("Admin not found", "error")
        return redirect(url_for('admin_dashboard'))
    
    # Don't allow deleting super admin or yourself
    current_user = db.session.get(User, session["user_id"])
    if admin.id == current_user.id:
        flash("Cannot delete your own admin account", "error")
        return redirect(url_for('admin_dashboard'))
    
    if getattr(admin, 'admin_role', None) == 'super_admin':
        flash("Cannot delete super admin account", "error")
        return redirect(url_for('admin_dashboard'))
    
    # Delete the admin
    db.session.delete(admin)
    db.session.commit()
    
    flash(f"Admin {admin.username} removed successfully", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/create_admin', methods=['POST'])
@admin_required
def admin_create_admin():
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    
    if not username or not email or not password:
        flash("All fields are required", "error")
        return redirect(url_for('admin_dashboard'))
    
    # Check if user already exists
    if User.query.filter_by(username=username).first():
        flash("Username already exists", "error")
        return redirect(url_for('admin_dashboard'))
    
    if User.query.filter_by(email=email).first():
        flash("Email already registered", "error")
        return redirect(url_for('admin_dashboard'))
    
    # Create new admin user
    admin = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        is_admin=True,
        allow_reattempt=True,
        exam_completed=False,
        exam_access_enabled=True,
        admin_role="admin"
    )
    
    db.session.add(admin)
    db.session.commit()
    
    flash(f"Admin {username} created successfully", "success")
    return redirect(url_for('admin_dashboard'))


@app.route('/exams')
@login_required
def exam_list_page():
    attempts = Attempt.query.filter_by(user_id=session['user_id']).order_by(Attempt.started_at.desc()).all()
    return render_template('exams.html', attempts=attempts)


@app.route('/scores')
@login_required
def score_page():
    attempts = Attempt.query.filter_by(user_id=session['user_id'], status='completed').order_by(Attempt.started_at.desc()).all()
    return render_template('scores.html', attempts=attempts)


@app.route('/history')
@login_required
def history_page():
    attempts = Attempt.query.filter_by(user_id=session['user_id']).order_by(Attempt.started_at.desc()).all()
    return render_template('history.html', attempts=attempts)


@app.route('/exam-report/<int:attempt_id>')
@login_required
def exam_report(attempt_id):
    # Get the attempt
    attempt = Attempt.query.get(attempt_id)
    if not attempt:
        flash("Report not found", "error")
        return redirect(url_for('dashboard'))
    
    # Verify user owns this attempt
    if attempt.user_id != session['user_id']:
        flash("Access denied", "error")
        return redirect(url_for('dashboard'))
    
    # Get user info
    user = User.query.get(attempt.user_id)
    
    # Build report data
    report_data = build_report_data(attempt) if attempt.status == 'completed' else None
    
    return render_template('report.html', 
                      attempt=attempt, 
                      user=user, 
                      report_data=report_data)


@app.route('/dashboard')
@login_required
def dashboard():
    # Get user's exam attempts
    attempts = Attempt.query.filter_by(user_id=session['user_id']).order_by(Attempt.started_at.desc()).all()
    
    # Calculate statistics
    completed_attempts = [a for a in attempts if a.status == 'completed']
    total_attempts = len(attempts)
    completed_count = len(completed_attempts)
    
    # Calculate average score
    scores = [a.score for a in completed_attempts if a.score is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0
    
    # Get latest attempt
    latest_attempt = attempts[0] if attempts else None
    
    # Add exam schedule and time variables
    schedule = ExamSchedule.query.first()
    current_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
    
    user = User.query.get(session['user_id'])
    
    can_start_exam = True
    is_currently_completed = False
    
    if not user.exam_access_enabled:
        can_start_exam = False
    
    # Check if user already completed exam
    completed_attempt = Attempt.query.filter_by(
        user_id=user.id,
        status='completed'
    ).first()
    
    if completed_attempt and not user.allow_reattempt:
        can_start_exam = False
        is_currently_completed = True
    
    return render_template('dashboard.html', 
                      attempts=attempts,
                      total_attempts=total_attempts,
                      completed_attempts=completed_count,
                      avg_score=avg_score,
                      latest_attempt=latest_attempt,
                      pass_threshold=PASS_SCORE_THRESHOLD,
                      schedule=schedule,
                      current_time=current_time,
                      can_start_exam=can_start_exam,
                      is_currently_completed=is_currently_completed)


def _increment_global_warning(attempt):
    """Single counter for tab, face, and voice events."""
    attempt.warning_count = min(MAX_WARNINGS, (attempt.warning_count or 0) + 1)


@app.route("/api/exam/<int:attempt_id>/telemetry", methods=["POST"])
@login_required
def api_telemetry(attempt_id):
    uid = session["user_id"]
    user = db.session.get(User, uid)
    err, code = exam_api_access_guard(user)
    if err:
        return jsonify(err), code
    attempt = get_attempt_for_user(attempt_id, uid)
    err, code = exam_api_reattempt_guard(user, attempt)
    if err:
        return jsonify(err), code
    if not attempt or attempt.status != "in_progress":
        return jsonify({"error": "invalid"}), 400
    if remaining_seconds(attempt) <= 0:
        finalize_attempt(attempt)
        return jsonify({"error": "time_up", "report_url": report_url_for_attempt(attempt.id)}), 400
    data = request.get_json(silent=True) or {}
    warning_type = data.get("warning_type")
    warning_reason = data.get("warning_reason")
    question_number = data.get("question_number", 0)
    if data.get("timeline_event"):
        append_timeline_event(attempt, data.get("timeline_event"), question_number)

    if data.get("tab_switch"):
        attempt.tab_switch_count = min(100, (attempt.tab_switch_count or 0) + 1)
        _increment_global_warning(attempt)
        append_warning_detail(
            attempt,
            warning_type or "Tab",
            warning_reason or "Tab switched",
            question_number,
        )
    elif data.get("face_warning"):
        attempt.face_missing_warnings = min(200, (attempt.face_missing_warnings or 0) + 1)
        _increment_global_warning(attempt)
        append_warning_detail(
            attempt,
            warning_type or "Face",
            warning_reason or "Face not detected",
            question_number,
        )
    elif data.get("voice_warning"):
        _increment_global_warning(attempt)
        append_warning_detail(
            attempt,
            warning_type or "Voice",
            warning_reason or "Voice detected",
            question_number,
        )
    elif data.get("multiple_faces"):
        _increment_global_warning(attempt)
        append_warning_detail(
            attempt,
            warning_type or "Face",
            warning_reason or "Multiple faces detected",
            question_number,
        )
    elif data.get("multiple_voices"):
        _increment_global_warning(attempt)
        append_warning_detail(
            attempt,
            warning_type or "Voice",
            warning_reason or "Multiple voices detected",
            question_number,
        )
    elif data.get("screenshot"):
        _increment_global_warning(attempt)
        append_warning_detail(
            attempt,
            warning_type or "Screenshot",
            warning_reason or "Screenshot detected",
            question_number,
        )
    db.session.commit()

    wc = attempt.warning_count or 0
    if wc >= MAX_WARNINGS:
        finalize_attempt(attempt)
        return jsonify(
            {
                "ok": True,
                "warning_count": wc,
                "max_warnings": MAX_WARNINGS,
                "submitted": True,
                "report_url": report_url_for_attempt(attempt.id),
                "score": attempt.score,
            }
        )
    return jsonify(
        {
            "ok": True,
            "warning_count": wc,
            "max_warnings": MAX_WARNINGS,
            "submitted": False,
        }
    )


@app.route("/api/exam/<int:attempt_id>/state", methods=["GET"])
@login_required
def api_exam_state(attempt_id):
    uid = session["user_id"]
    user = db.session.get(User, uid)
    err, code = exam_api_access_guard(user)
    if err:
        return jsonify(err), code
    attempt = get_attempt_for_user(attempt_id, uid)
    if not attempt:
        return jsonify({"error": "not_found"}), 404
    err, code = exam_api_reattempt_guard(user, attempt)
    if err:
        return jsonify(err), code
    rem = remaining_seconds(attempt)
    if attempt.status == "in_progress" and rem <= 0:
        finalize_attempt(attempt)
        return jsonify(
            {
                "status": attempt.status,
                "remaining_seconds": 0,
                "finished": True,
                "score": attempt.score,
                "report_url": report_url_for_attempt(attempt.id),
            }
        )
    qids = parse_question_ids(attempt)
    total = len(qids)
    idx = min(attempt.current_index, max(0, total - 1))
    if total == 0:
        return jsonify({"error": "empty"}), 400
    qid = qids[idx]
    q = db.session.get(Question, qid)
    if not q:
        return jsonify({"error": "missing_question"}), 500
    ans = Answer.query.filter_by(attempt_id=attempt.id, question_id=qid).first()
    selected = ans.selected if ans else None
    return jsonify(
        {
            "status": attempt.status,
            "remaining_seconds": rem,
            "current_index": idx,
            "total": total,
            "question": {
                "id": q.id,
                "text": q.text,
                "topic": q.topic or "General CS",
                "correct_answer": "C",
                "options": {
                    "A": q.option_a,
                    "B": q.option_b,
                    "C": q.option_c,
                    "D": q.option_d,
                },
            },
            "selected": selected,
            "finished": False,
            "warning_count": attempt.warning_count or 0,
            "max_warnings": MAX_WARNINGS,
            "nav_status": build_nav_status(attempt),
            "student_profile": parse_student_profile(attempt),
        }
    )


@app.route("/api/exam/<int:attempt_id>/profile", methods=["POST"])
@login_required
def api_exam_profile(attempt_id):
    uid = session["user_id"]
    user = db.session.get(User, uid)
    err, code = exam_api_access_guard(user)
    if err:
        return jsonify(err), code
    attempt = get_attempt_for_user(attempt_id, uid)
    err, code = exam_api_reattempt_guard(user, attempt)
    if err:
        return jsonify(err), code
    if not attempt or attempt.status != "in_progress":
        return jsonify({"error": "invalid"}), 400

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not name or not email:
        return jsonify({"error": "name_email_required"}), 400

    profile = {
        "name": name,
        "email": email,
        "examId": int(data.get("examId") or attempt.id),
        "date": data.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    attempt.student_profile_json = json.dumps(profile)
    append_timeline_event(attempt, "Exam started", int(data.get("question_number") or 1))
    db.session.commit()
    return jsonify({"ok": True, "student_profile": profile})


@app.route("/api/exam/<int:attempt_id>/answer", methods=["POST"])
@login_required
def api_save_answer(attempt_id):
    uid = session["user_id"]
    user = db.session.get(User, uid)
    err, code = exam_api_access_guard(user)
    if err:
        return jsonify(err), code
    attempt = get_attempt_for_user(attempt_id, uid)
    err, code = exam_api_reattempt_guard(user, attempt)
    if err:
        return jsonify(err), code
    if not attempt or attempt.status != "in_progress":
        return jsonify({"error": "invalid"}), 400
    if remaining_seconds(attempt) <= 0:
        finalize_attempt(attempt)
        return jsonify(
            {"error": "time_up", "score": attempt.score, "report_url": report_url_for_attempt(attempt.id)}
        ), 400
    data = request.get_json(silent=True) or {}
    qid = data.get("question_id")
    selected = (data.get("selected") or "").upper()[:1] or None
    if selected and selected not in "ABCD":
        selected = None
    qids = parse_question_ids(attempt)
    if qid not in qids:
        return jsonify({"error": "bad_question"}), 400
    ans = Answer.query.filter_by(attempt_id=attempt.id, question_id=qid).first()
    if not ans:
        ans = Answer(
            attempt_id=attempt.id,
            question_id=qid,
            selected=selected,
            confidence="medium",
        )
        db.session.add(ans)
    else:
        ans.selected = selected
        ans.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/exam/<int:attempt_id>/flag", methods=["POST"])
@login_required
def api_toggle_flag(attempt_id):
    uid = session["user_id"]
    user = db.session.get(User, uid)
    err, code = exam_api_access_guard(user)
    if err:
        return jsonify(err), code
    attempt = get_attempt_for_user(attempt_id, uid)
    err, code = exam_api_reattempt_guard(user, attempt)
    if err:
        return jsonify(err), code
    if not attempt or attempt.status != "in_progress":
        return jsonify({"error": "invalid"}), 400
    if remaining_seconds(attempt) <= 0:
        finalize_attempt(attempt)
        return jsonify(
            {"error": "time_up", "score": attempt.score, "report_url": report_url_for_attempt(attempt.id)}
        ), 400
    data = request.get_json(silent=True) or {}
    qid = data.get("question_id")
    qids = parse_question_ids(attempt)
    if qid not in qids:
        return jsonify({"error": "bad_question"}), 400
    ans = Answer.query.filter_by(attempt_id=attempt.id, question_id=qid).first()
    if not ans:
        ans = Answer(
            attempt_id=attempt.id,
            question_id=qid,
            selected=None,
            confidence="medium",
            flagged=True,
        )
        db.session.add(ans)
    else:
        ans.flagged = not bool(getattr(ans, "flagged", False))
        ans.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True, "flagged": bool(ans.flagged)})


@app.route("/api/exam/<int:attempt_id>/navigate", methods=["POST"])
@login_required
def api_navigate(attempt_id):
    uid = session["user_id"]
    user = db.session.get(User, uid)
    
    # For navigation, allow access even if exam_completed is set, as long as:
    # 1. User exists
    # 2. Exam access is enabled
    # 3. They have a valid in-progress attempt
    if not user:
        return jsonify({"error": "not_found"}), 404
    if not getattr(user, "exam_access_enabled", True):
        return (
            {
                "error": "access_denied",
                "message": "Exam access is disabled. Contact your administrator.",
            },
            403,
        )
    
    attempt = get_attempt_for_user(attempt_id, uid)
    
    # Allow navigation for in-progress attempts even if user has exam_completed flag
    # This prevents blocking navigation due to anti-cheating flags while preserving security
    # Only apply reattempt guard for submission, not navigation
    # This allows users to navigate in their current attempt even if they have completed attempts
    if not attempt or attempt.status != "in_progress":
        return jsonify({"error": "invalid"}), 400
    if remaining_seconds(attempt) <= 0:
        finalize_attempt(attempt)
        return jsonify(
            {"error": "time_up", "score": attempt.score, "report_url": report_url_for_attempt(attempt.id)}
        ), 400
    data = request.get_json(silent=True) or {}
    qids = parse_question_ids(attempt)
    total = len(qids)
    if total == 0:
        return jsonify({"error": "empty"}), 400
    idx = attempt.current_index
    if data.get("jump_to_index") is not None:
        try:
            idx = int(data["jump_to_index"])
        except (TypeError, ValueError):
            return jsonify({"error": "bad_index"}), 400
        idx = max(0, min(total - 1, idx))
    else:
        direction = data.get("direction", "next")
        if direction == "prev":
            idx = max(0, idx - 1)
        else:
            idx = min(total - 1, idx + 1)
    attempt.current_index = idx
    db.session.commit()
    return jsonify({"ok": True, "current_index": idx})


@app.route("/api/exam/<int:attempt_id>/submit", methods=["POST"])
@login_required
def api_submit(attempt_id):
    uid = session["user_id"]
    user = db.session.get(User, uid)
    attempt = get_attempt_for_user(attempt_id, uid)
    err, code = exam_api_access_guard(user, attempt)
    if err:
        return jsonify(err), code
    err, code = exam_api_reattempt_guard(user, attempt)
    if err:
        return jsonify(err), code
    if not attempt or attempt.status != "in_progress":
        return jsonify({"error": "invalid"}), 400
    append_timeline_event(attempt, "Exam ended", int((attempt.current_index or 0) + 1))
    finalize_attempt(attempt)
    return jsonify(
        {
            "ok": True,
            "score": attempt.score,
            "status": attempt.status,
            "report_url": report_url_for_attempt(attempt.id),
        }
    )


with app.app_context():
    db.create_all()
    ensure_block_columns()
    migrate_schema()
    seed_questions()

# TEMPORARY: Add username column to blocked_roll table (RUN ONCE, THEN REMOVE)
with app.app_context():
    try:
        from sqlalchemy import text
        db.session.commit()
        print("username column added successfully")
    except Exception as e:
        print("Column may already exist:", e)
        # Check if username column already exists in blocked_roll table
        result = db.session.execute(text("PRAGMA table_info(blocked_roll)")).fetchall()
        columns = [row[1] for row in result if row[0] == 'column']
        username_exists = 'username' in columns
        
        if not username_exists:
            db.session.execute(text("ALTER TABLE blocked_roll ADD COLUMN username TEXT"))
            db.session.commit()
            print("username column added successfully")
        else:
            print("username column already exists in blocked_roll table")
    except Exception as e:
        print("Error checking/adding column:", e)

# TEMPORARY: Update missing roll numbers for existing students
# RUN ONCE, THEN REMOVE THIS CODE
with app.app_context():
    users = User.query.all()
    for i, u in enumerate(users, start=1):
        if not u.roll_number:
            u.roll_number = f"RN{i:03}"
    
    db.session.commit()
    print("Roll numbers updated successfully")

# TEMPORARY: Clean existing roll numbers from RN012 format to 12
# RUN ONCE, THEN REMOVE THIS CODE
with app.app_context():
    users = User.query.order_by(User.id).all()
    for u in users:
        if u.roll_number and u.roll_number.startswith("RN"):
            # remove "RN" and convert to number
            clean = u.roll_number.replace("RN", "")
            u.roll_number = str(int(clean))  # removes leading zeros
    
    db.session.commit()
    print("Roll numbers cleaned")


@app.route("/api/add_warning", methods=["POST"])
def add_warning():
    if "user_id" not in session:
        return {"error": "unauthorized"}, 401

    attempt = Attempt.query.filter_by(
        user_id=session["user_id"],
        status="in_progress"
    ).order_by(Attempt.id.desc()).first()

    if not attempt:
        return {"error": "no active attempt"}, 400

    attempt.warning_count += 1

    if attempt.warning_count >= 5:
        finalize_attempt(attempt)
        return {"status": "submitted"}

    db.session.commit()
    return {"status": "ok", "warnings": attempt.warning_count}


if __name__ == "__main__":
    app.run(debug=True, port=5000)