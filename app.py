import os
import secrets
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, g, redirect, render_template, request,
    send_from_directory, session, url_for
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", DATA_DIR / "uploads"))
PASSPORT_DIR = UPLOAD_ROOT / "passports"
MATERIALS_DIR = UPLOAD_ROOT / "materials"
PASSPORT_DIR.mkdir(parents=True, exist_ok=True)
MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'wasko.db'}")
# Render/Postgres and some other providers may return postgres://.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY")
if not secret_key and os.environ.get("FLASK_ENV") == "production":
    raise RuntimeError("SECRET_KEY must be set in production.")
app.config.update(
    SECRET_KEY=secret_key or "wasko-local-development-only",
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=15 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)

db = SQLAlchemy(app)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")
if not ADMIN_PASSWORD_HASH:
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_password:
        ADMIN_PASSWORD_HASH = generate_password_hash(admin_password)
    elif os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Set ADMIN_PASSWORD_HASH (preferred) or ADMIN_PASSWORD in production.")
    else:
        ADMIN_PASSWORD_HASH = generate_password_hash("Admin@1984")

COURSES = [
    "AI Automation",
    "Computer Studies",
    "Cybersecurity",
    "Digital Forensics",
    "Digital Marketing",
    "Web Design",
    "Software Development",
]
ALLOWED_PASSPORT_EXT = {"png", "jpg", "jpeg", "pdf"}
ALLOWED_MATERIAL_EXT = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
    "zip", "mp4", "mp3", "png", "jpg", "jpeg", "txt",
}

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    reg_code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(40), nullable=False)
    passport_filename = db.Column(db.String(255), nullable=False)
    course = db.Column(db.String(80), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class CourseMaterial(db.Model):
    __tablename__ = "course_materials"
    id = db.Column(db.Integer, primary_key=True)
    course = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), unique=True, nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

def allowed_file(filename, allowed_set):
    return bool(filename and "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set)

def gen_reg_code():
    return "WV" + secrets.token_hex(4).upper()

def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token

app.jinja_env.globals["csrf_token"] = csrf_token

@app.before_request
def protect_post_requests():
    if request.method == "POST":
        sent = request.form.get("_csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not expected or not secrets.compare_digest(sent, expected):
            abort(400, description="Invalid or missing security token. Please refresh and try again.")

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

@app.context_processor
def inject_year():
    return {"current_year": datetime.now(timezone.utc).year}

@app.teardown_appcontext
def cleanup(_exception=None):
    pass

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped

def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        student_id = session.get("student_id")
        if not student_id:
            flash("Please verify your enrolment first.", "error")
            return redirect(url_for("status"))
        student = db.session.get(Student, student_id)
        if not student or student.status != "approved":
            session.pop("student_id", None)
            flash("Your approved student session is no longer valid.", "error")
            return redirect(url_for("status"))
        g.student = student
        return view(*args, **kwargs)
    return wrapped

@app.route("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "database": "ok"}, 200
    except Exception:
        return {"status": "degraded", "database": "unavailable"}, 503

@app.route("/")
def index():
    return render_template("index.html", courses=COURSES)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        course = request.form.get("course", "").strip()
        passport = request.files.get("passport")
        errors = []

        if len(full_name) < 2 or len(full_name) > 160:
            errors.append("Enter your full name.")
        if not email or "@" not in email or len(email) > 255:
            errors.append("Enter a valid email address.")
        if not phone or len(phone) > 40:
            errors.append("Enter a valid phone number.")
        if course not in COURSES:
            errors.append("Please select a valid course.")
        if not passport or not passport.filename:
            errors.append("Passport photograph or ID is required.")
        elif not allowed_file(passport.filename, ALLOWED_PASSPORT_EXT):
            errors.append("Passport file must be a PNG, JPG, JPEG, or PDF.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("register.html", courses=COURSES, form=request.form), 400

        stored_name = f"{uuid.uuid4().hex}.{passport.filename.rsplit('.', 1)[1].lower()}"
        passport.save(PASSPORT_DIR / stored_name)

        for _ in range(5):
            reg_code = gen_reg_code()
            if not db.session.scalar(db.select(Student).filter_by(reg_code=reg_code)):
                break

        student = Student(
            reg_code=reg_code,
            full_name=full_name,
            email=email,
            phone=phone,
            passport_filename=stored_name,
            course=course,
            status="pending",
        )
        try:
            db.session.add(student)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            (PASSPORT_DIR / stored_name).unlink(missing_ok=True)
            flash("Registration could not be completed. Please try again.", "error")
            return render_template("register.html", courses=COURSES, form=request.form), 500

        return render_template("registered.html", student=student)

    return render_template("register.html", courses=COURSES, form={})

@app.route("/status", methods=["GET", "POST"])
def status():
    student = None
    searched = False
    materials = []
    if request.method == "POST":
        searched = True
        reg_code = request.form.get("reg_code", "").strip().upper()
        email = request.form.get("email", "").strip().lower()
        student = db.session.scalar(
            db.select(Student).where(
                func.upper(Student.reg_code) == reg_code,
                func.lower(Student.email) == email,
            )
        )
        session.pop("student_id", None)
        if student and student.status == "approved":
            session["student_id"] = student.id
            materials = db.session.scalars(
                db.select(CourseMaterial)
                .where(CourseMaterial.course == student.course)
                .order_by(CourseMaterial.uploaded_at.desc())
            ).all()
    return render_template("status.html", student=student, searched=searched, materials=materials)

@app.route("/materials/<path:filename>")
@student_required
def download_material(filename):
    safe_name = Path(filename).name
    material = db.session.scalar(db.select(CourseMaterial).where(CourseMaterial.filename == safe_name))
    if not material or material.course != g.student.course:
        abort(404)
    path = MATERIALS_DIR / material.filename
    if not path.is_file():
        abort(404)
    return send_from_directory(MATERIALS_DIR, material.filename, as_attachment=True, download_name=material.original_filename)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear()
            session["is_admin"] = True
            session["admin_user"] = username
            flash("Welcome back.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout", methods=["GET"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    course_filter = request.args.get("course", "")
    query = db.select(Student).order_by(Student.created_at.desc())
    if course_filter in COURSES:
        query = query.where(Student.course == course_filter)
    students = db.session.scalars(query).all()
    counts = {
        c: db.session.scalar(db.select(func.count()).select_from(Student).where(Student.course == c)) or 0
        for c in COURSES
    }
    total = db.session.scalar(db.select(func.count()).select_from(Student)) or 0
    pending = db.session.scalar(db.select(func.count()).select_from(Student).where(Student.status == "pending")) or 0
    return render_template(
        "admin_dashboard.html", courses=COURSES, students=students,
        counts=counts, course_filter=course_filter if course_filter in COURSES else "",
        total=total, pending=pending, active="dashboard"
    )

@app.route("/admin/student/<int:student_id>/approve", methods=["POST"])
@admin_required
def approve_student(student_id):
    student = db.session.get(Student, student_id)
    if not student:
        flash("Registration not found.", "error")
        return redirect(url_for("admin_dashboard"))
    student.status = "approved"
    db.session.commit()
    flash(f"{student.full_name} approved for {student.course}.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))

@app.route("/admin/student/<int:student_id>/delete", methods=["POST"])
@admin_required
def delete_student(student_id):
    student = db.session.get(Student, student_id)
    if not student:
        flash("Registration not found.", "error")
        return redirect(url_for("admin_dashboard"))
    (PASSPORT_DIR / Path(student.passport_filename).name).unlink(missing_ok=True)
    db.session.delete(student)
    db.session.commit()
    flash("Registration removed.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))

@app.route("/admin/passport/<path:filename>")
@admin_required
def admin_passport(filename):
    safe_name = Path(filename).name
    if not (PASSPORT_DIR / safe_name).is_file():
        abort(404)
    return send_from_directory(PASSPORT_DIR, safe_name)

@app.route("/admin/materials", methods=["GET", "POST"])
@admin_required
def admin_materials():
    if request.method == "POST":
        course = request.form.get("course", "")
        title = request.form.get("title", "").strip()
        file = request.files.get("material")
        if course not in COURSES:
            flash("Select a valid course.", "error")
        elif not title or len(title) > 200:
            flash("Give the material a valid title.", "error")
        elif not file or not file.filename:
            flash("Choose a file to upload.", "error")
        elif not allowed_file(file.filename, ALLOWED_MATERIAL_EXT):
            flash("That file type isn't supported.", "error")
        else:
            original = secure_filename(file.filename)
            ext = original.rsplit(".", 1)[1].lower()
            stored_name = f"{uuid.uuid4().hex}.{ext}"
            file.save(MATERIALS_DIR / stored_name)
            material = CourseMaterial(
                course=course, title=title, filename=stored_name,
                original_filename=original
            )
            db.session.add(material)
            db.session.commit()
            flash(f"Material uploaded for {course}.", "success")
        return redirect(url_for("admin_materials"))

    materials = db.session.scalars(
        db.select(CourseMaterial).order_by(CourseMaterial.uploaded_at.desc())
    ).all()
    return render_template("admin_materials.html", courses=COURSES, materials=materials, active="materials")

@app.route("/admin/materials/<int:material_id>/delete", methods=["POST"])
@admin_required
def delete_material(material_id):
    material = db.session.get(CourseMaterial, material_id)
    if not material:
        flash("Material not found.", "error")
        return redirect(url_for("admin_materials"))
    (MATERIALS_DIR / Path(material.filename).name).unlink(missing_ok=True)
    db.session.delete(material)
    db.session.commit()
    flash("Material removed.", "success")
    return redirect(url_for("admin_materials"))

@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404

@app.errorhandler(413)
def too_large(_error):
    return render_template("413.html"), 413

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
