from flask import Flask, render_template, request, redirect, jsonify, flash, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os
from dotenv import load_dotenv
import json
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets
from datetime import datetime, timedelta
import stripe

load_dotenv()
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'secret123')


db_url = os.getenv('DATABASE_URL')
is_vercel = os.getenv('VERCEL') == '1'

if not db_url:
    if is_vercel:  
        db_url = 'sqlite:///:memory:'
        print("Warning: DATABASE_URL not found in Vercel environment. Using in-memory Safe Mode.")
    else:
        db_url = 'sqlite:///local.db'
        print("Warning: DATABASE_URL not found, falling back to local sqlite.")
elif db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

@app.route('/health')
def health_check():
    """Health check endpoint to verify environment variables"""
    db_status = "ok"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
        
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "env": {
            "vercel": is_vercel,
            "db_configured": bool(os.getenv('DATABASE_URL')),
            "cloudinary_configured": bool(os.getenv('CLOUDINARY_CLOUD_NAME')),
            "razorpay_configured": bool(os.getenv('RAZORPAY_KEY_ID')),
            "smtp_configured": bool(os.getenv('SMTP_SERVER'))
        },
        "db_connection": db_status
    })

@app.errorhandler(500)
def internal_error(error):
    import traceback
    print("500 ERROR OCCURRED:")
    print(traceback.format_exc())
    return f"Internal Server Error: {str(error)}", 500

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
stripe_publishable_key = os.getenv('STRIPE_PUBLISHABLE_KEY')

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'mp4', 'avi', 'mov', 'mkv', 'txt', 'doc', 'docx', 'ppt', 'pptx', 'zip'}
try:
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
except Exception as e:
    print(f"Warning: Could not create upload folder: {e}. This is expected on Vercel.")

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.template_filter('from_json')
def from_json(value):
    return json.loads(value) if value else []

@app.template_filter('sanitize_url')
def sanitize_url(value):
    return value.replace('\\', '/') if value else value


db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    role = db.Column(db.String(20))
    email_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)


class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    content = db.Column(db.Text)
    materials = db.Column(db.Text, default='')  # JSON string of uploaded files
    teacher_id = db.Column(db.Integer)
    price = db.Column(db.Numeric(10, 2), default=0.00)  # Course price
    currency = db.Column(db.String(3), default='INR')  # Currency code


class Enrollment(db.Model):
    __tablename__ = 'enrollments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer)
    course_id = db.Column(db.Integer)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)


class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'))
    amount = db.Column(db.Numeric(10, 2))
    currency = db.Column(db.String(3), default='INR')
    payment_gateway = db.Column(db.String(20), default='razorpay')
    transaction_id = db.Column(db.String(100), unique=True, nullable=True)
    order_id = db.Column(db.String(100))
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed, refunded
    payment_method = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Quiz(db.Model):
    __tablename__ = 'quizzes'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'))
    title = db.Column(db.String(200))
    description = db.Column(db.Text, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)  # Optional time limit
    passing_score = db.Column(db.Integer, default=60)  # Percentage
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'))
    question_text = db.Column(db.Text)
    question_type = db.Column(db.String(20), default='multiple_choice')  # multiple_choice, true_false
    options = db.Column(db.Text)  # JSON array of options
    correct_answer = db.Column(db.String(200))  # The correct option
    points = db.Column(db.Integer, default=1)
    order = db.Column(db.Integer, default=0)


class QuizAttempt(db.Model):
    __tablename__ = 'quiz_attempts'
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'))
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    answers = db.Column(db.Text)  # JSON of question_id: answer
    score = db.Column(db.Numeric(5, 2))
    max_score = db.Column(db.Numeric(5, 2))
    percentage = db.Column(db.Numeric(5, 2))
    passed = db.Column(db.Boolean)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)


def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'id' not in session:
                return redirect(url_for('login_page'))
            user_role = session.get('role')
        
            if user_role == 'admin':
                return f(*args, **kwargs)
            if allowed_roles and user_role not in allowed_roles:
                flash('You do not have permission to access this page')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

def send_verification_email(user_email, user_name, token):
    """Send email verification link to user"""
    try:
        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')
        from_email = os.getenv('SMTP_FROM_EMAIL')
        from_name = os.getenv('SMTP_FROM_NAME', 'Online Course Platform')
        
        verification_link = url_for('verify_email', token=token, _external=True)
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Verify Your Email - Online Course Platform'
        msg['From'] = f'{from_name} <{from_email}>'
        msg['To'] = user_email
        
    
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px;">
              <h2 style="color: #4CAF50;">Welcome to Online Course Platform!</h2>
              <p>Hi {user_name},</p>
              <p>Thank you for registering! Please verify your email address to complete your registration.</p>
              <p style="margin: 30px 0;">
                <a href="{verification_link}" 
                   style="background-color: #4CAF50; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
                  Verify Email Address
                </a>
              </p>
              <p>Or copy and paste this link into your browser:</p>
              <p style="color: #666; font-size: 12px; word-break: break-all;">{verification_link}</p>
              <p style="margin-top: 30px; color: #666; font-size: 12px;">
                This link will expire in 24 hours. If you didn't create an account, please ignore this email.
              </p>
            </div>
          </body>
        </html>
        """
            
        text = f"""
        Welcome to Online Course Platform!
        
        Hi {user_name},
        
        Thank you for registering! Please verify your email address by clicking the link below:
        
        {verification_link}
        
        This link will expire in 24 hours. If you didn't create an account, please ignore this email.
        """
        
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def send_assignment_email(teacher_email, teacher_name, course_title):
    """Notify teacher that they have been assigned a course by Admin/HR"""
    try:
        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')
        from_email = os.getenv('SMTP_FROM_EMAIL')
        from_name = os.getenv('SMTP_FROM_NAME', 'EduStream Admin')
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'New Course Assigned: {course_title}'
        msg['From'] = f'{from_name} <{from_email}>'
        msg['To'] = teacher_email
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px;">
              <h2 style="color: #6366f1;">New Course Assignment</h2>
              <p>Hi {teacher_name},</p>
              <p>You have been assigned a new course by the <strong>Admin/HR Department</strong>.</p>
              <div style="background: #f8fafc; padding: 15px; border-left: 4px solid #6366f1; margin: 20px 0;">
                <strong>Course Title:</strong> {course_title}
              </div>
              <p>You can now log in to your dashboard to add course materials, quizzes, and manage students.</p>
              <p style="margin-top: 30px; color: #666; font-size: 12px;">
                This is an automated notification from the EduStream Platform.
              </p>
            </div>
          </body>
        </html>
        """
        
        part1 = MIMEText(f"Hi {teacher_name},\n\nYou have been assigned a new course: {course_title}. Please log in to your dashboard to manage it.", 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
    
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        return True
    except Exception as e:
        print(f"Error sending assignment email: {e}")
        return False

def generate_verification_token():
    """Generate a secure random token for email verification"""
    return secrets.token_urlsafe(32)


@app.route('/')
def home():
    return render_template('register.html')


@app.route('/register', methods=['GET'])
def register_page():
    return render_template('register.html')


@app.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html', role=None)


@app.route('/login/<string:role>', methods=['GET'])
def login_page_role(role):
    role = role.lower()
    if role not in ('student', 'teacher', 'admin'):
        return redirect(url_for('login_page'))
    return render_template('login.html', role=role)

@app.route('/register', methods=['POST'])
def register():
    email = request.form['email']
    name = request.form['name']
    password = request.form['password']
    role = request.form['role']

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
         return render_template(
            'login.html',
            message='Email already registered. Please login.'
        )

    if role == 'student':
        token = generate_verification_token()
        token_expiry = datetime.utcnow() + timedelta(hours=24)
        
        user = User(
            name=name,
            email=email,
            password=password,
            role=role,
            email_verified=False,
            verification_token=token,
            token_expiry=token_expiry
        )
        
        db.session.add(user)
        db.session.commit()
        
        email_sent = send_verification_email(email, name, token)
        
        if email_sent:
            return render_template(
                'login.html',
                message='Registration successful! Please check your email to verify your account before logging in.',
                show_resend=True,
                user_email=email
            )
        else:
            return render_template(
                'login.html',
                message='Registration successful but email could not be sent. Please contact support.',
                error=True
            )
    else:
        user = User(
            name=name,
            email=email,
            password=password,
            role=role,
            email_verified=True  
        )
        
        db.session.add(user)
        db.session.commit()
        
        return render_template(
            'login.html',
            message='Registration successful! You can now login.'
        )
@app.route("/db-test")
def db_test():
    row = db.session.execute(text("SELECT version()")).fetchone()
    return str(row)




@app.route('/login', methods=['POST'])
def login():
    user = User.query.filter_by(
        email=request.form['email'],
        password=request.form['password']
    ).first()
    
    if not user:
        return render_template('login.html', message='Invalid login credentials', role=request.form.get('role'))

    if user.role == 'student' and not user.email_verified:
        return render_template(
            'login.html', 
            message='Please verify your email before logging in. Check your inbox for the verification link.',
            show_resend=True,
            user_email=user.email,
            role=request.form.get('role')
        )

    session['id'] = user.id
    session['name'] = user.name
    session['role'] = user.role

    expected_role = request.form.get('role')
    if expected_role and expected_role != user.role:
        session.clear()
        return render_template('login.html', message='Role mismatch - use correct login flow', role=expected_role)

    if user.role == 'student':
        return redirect(url_for('student_dashboard', id=user.id))
    if user.role == 'teacher':
        return redirect(url_for('teacher_dashboard', id=user.id))
    if user.role == 'admin':
        return redirect(url_for('admin_dashboard'))

    return redirect(url_for('home'))


@app.route('/verify-email/<string:token>', methods=['GET'])
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    
    if not user:
        return render_template('login.html', message='Invalid verification token.', error=True)
    
    if user.token_expiry and user.token_expiry < datetime.utcnow():
        return render_template('login.html', message='Verification token has expired. Please request a new one.', error=True)
    
    user.email_verified = True
    user.verification_token = None
    user.token_expiry = None
    db.session.commit()
    
    return render_template('login.html', message='Email verified successfully! You can now login.')


@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()
    
    if not user:
        return render_template('login.html', message='Email not found.', error=True)
    
    if user.email_verified:
        return render_template('login.html', message='Email is already verified. Please login.')
    
    
    token = generate_verification_token()
    user.verification_token = token
    user.token_expiry = datetime.utcnow() + timedelta(hours=24)
    db.session.commit()
   
    if send_verification_email(user.email, user.name, token):
        return render_template('login.html', message='Verification email resent! Please check your inbox.')
    else:
        return render_template('login.html', message='Error sending email. Please try again later.', error=True)
  
@app.route('/admin/assign-course', methods=['POST'])
@role_required('admin')
def admin_assign_course():
    course_id = request.form.get('course_id')
    teacher_id = request.form.get('teacher_id')

    course = Course.query.get(course_id)
    teacher = User.query.get(teacher_id)

    if not course or not teacher or teacher.role != 'teacher':
        flash('Invalid course or teacher selection')
        return redirect(url_for('admin_dashboard'))

    course.teacher_id = teacher_id
    db.session.commit()

    send_assignment_email(teacher.email, teacher.name, course.title)

    flash(f'Course "{course.title}" successfully assigned to {teacher.name}')
    return redirect(url_for('admin_dashboard'))


@app.route('/teacher/<int:id>')
@role_required('teacher')
def teacher_dashboard(id):

    teacher_courses = Course.query.filter_by(teacher_id=id).all()
    
    course_data = []
    for course in teacher_courses:
        students = (
            db.session.query(User)
            .join(Enrollment, User.id == Enrollment.student_id)
            .filter(Enrollment.course_id == course.id)
            .all()
        )
        course_data.append({
            'course': course,
            'students': students,
            'count': len(students)
        })

    return render_template(
        'teacher.html',
        course_data=course_data,
        teacher_id=id
    )


@app.route('/teacher/<int:id>/students')
@role_required('teacher')
def teacher_students(id):
    return redirect(url_for('teacher_dashboard', id=id) + '#studentsModal')


@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    users = User.query.all()
    payments = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()
    courses = Course.query.all()
    teachers = User.query.filter_by(role='teacher').all()
    
           
    total_revenue = db.session.query(db.func.sum(Payment.amount)).filter(Payment.status == 'completed').scalar() or 0
    total_courses = Course.query.count()

    
    teacher_map = {t.id: t.name for t in teachers}

    stats = {
        'total_users': len(users),
        'students': len([u for u in users if u.role == 'student']),
        'teachers': len(teachers),
        'admins': len([u for u in users if u.role == 'admin']),
        'total_revenue': total_revenue,
        'total_courses': total_courses
    }
    return render_template('admin.html', 
                          users=users, 
                          stats=stats, 
                          payments=payments, 
                          courses=courses, 
                          teachers=teachers,
                          teacher_map=teacher_map)


@app.route('/admin/create-user', methods=['POST'])
@role_required('admin')
def admin_create_user():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'student').strip()

    if not name or not email or not password:
        users = User.query.all()
        return render_template('admin.html',
                             users=users,
                             stats={
                                 'total_users': len(users),
                                 'students': len([u for u in users if u.role == 'student']),
                                 'teachers': len([u for u in users if u.role == 'teacher']),
                                 'admins': len([u for u in users if u.role == 'admin']),
                                 'total_revenue': 0, # Simplified for error case
                                 'total_courses': 0
                             },
                             error='All fields are required')

    if User.query.filter_by(email=email).first():
        return render_template('admin.html',
                             users=User.query.all(),
                             stats={
                                 'total_users': len(User.query.all()),
                                 'students': len([u for u in User.query.all() if u.role == 'student']),
                                 'teachers': len([u for u in User.query.all() if u.role == 'teacher']),
                                 'admins': len([u for u in User.query.all() if u.role == 'admin'])
                             },
                             error='Email already exists')

    user = User(name=name, email=email, password=password, role=role)
    db.session.add(user)
    db.session.commit()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@role_required('admin')
def admin_delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        flash('User not found.')
        return redirect(url_for('admin_dashboard'))

    try:
        # 1. Delete Student Data (if user acted as student)
        Enrollment.query.filter_by(student_id=user_id).delete()
        Payment.query.filter_by(student_id=user_id).delete()
        QuizAttempt.query.filter_by(student_id=user_id).delete()

        # 2. Delete Teacher Data (if user acted as teacher)
        # Find all courses by this teacher
        teacher_courses = Course.query.filter_by(teacher_id=user_id).all()
        for course in teacher_courses:
            # Delete enrollments for this course
            Enrollment.query.filter_by(course_id=course.id).delete()
            # Delete payments for this course
            Payment.query.filter_by(course_id=course.id).delete()
            # Delete quizzes for this course (and questions)
            quizzes = Quiz.query.filter_by(course_id=course.id).all()
            for quiz in quizzes:
                Question.query.filter_by(quiz_id=quiz.id).delete()
                QuizAttempt.query.filter_by(quiz_id=quiz.id).delete()
                db.session.delete(quiz)
            
            # Delete the course itself
            db.session.delete(course)
        
        # Delete any standalone quizzes created by this user
        other_quizzes = Quiz.query.filter_by(created_by=user_id).all()
        for quiz in other_quizzes:
             Question.query.filter_by(quiz_id=quiz.id).delete()
             QuizAttempt.query.filter_by(quiz_id=quiz.id).delete()
             db.session.delete(quiz)

        # 3. Delete the User
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.email} and all associated data deleted successfully!')

    except Exception as e:
        db.session.rollback()
        print(f"Error deleting user: {e}")
        flash('Error deleting user. Please check server logs.')

    return redirect(url_for('admin_dashboard'))

@app.route('/teacher/<int:teacher_id>/student/<int:student_id>')
@role_required('teacher')
def teacher_student_detail(teacher_id, student_id):
    return redirect(url_for('teacher_dashboard', id=teacher_id) + '#studentsModal')


@app.route('/course/<int:course_id>/material/delete/<int:material_index>', methods=['POST'])
@role_required('teacher')
def delete_material(course_id, material_index):
    course = Course.query.get(course_id)
    if not course:
        flash('Course not found')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    materials_list = []
    materials_list = []
    if course.materials:
        try:
            materials_list = json.loads(course.materials)
        except:
            materials_list = []
    
    if 0 <= material_index < len(materials_list):
        
        material = materials_list[material_index]
        if material.get('type') == 'file':
            try:
                
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], material['path'].split('/')[-1])
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"Error deleting file: {e}")
        
        
        materials_list.pop(material_index)
        course.materials = json.dumps(materials_list)
        db.session.add(course)
        db.session.commit()
        flash('Material deleted successfully!', 'success')
    
    return redirect(url_for('edit_course_materials', course_id=course_id))


@app.route('/admin/create-course', methods=['POST'])
@role_required('admin')
def create_course():
    title = request.form['title']
    description = request.form['description']
    teacher_id = request.form.get('teacher_id')
    price = request.form.get('price', 0)

    course = Course(
        title=title,
        description=description,
        teacher_id=teacher_id if teacher_id and teacher_id != '0' else None,
        price=price
    )

    db.session.add(course)
    db.session.commit()

    if course.teacher_id:
        teacher = User.query.get(course.teacher_id)
        if teacher:
            send_assignment_email(teacher.email, teacher.name, course.title)

    flash('Course created successfully!')
    return redirect(url_for('admin_dashboard'))


@app.route('/course/<int:course_id>/payment/initiate', methods=['POST'])
@role_required('student')
def initiate_payment(course_id):
    student_id = session.get('id')
    course = Course.query.get_or_404(course_id)
    
    
    existing = Enrollment.query.filter_by(student_id=student_id, course_id=course_id).first()
    if existing:
        flash('You are already enrolled in this course.')
        return redirect(url_for('student_dashboard', id=student_id))
    
    try:
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': course.currency.lower() if course.currency else 'inr',
                    'product_data': {
                        'name': course.title,
                        'description': course.description[:255] if course.description else None,
                    },
                    'unit_amount': int(course.price * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('payment_cancel', _external=True),
            client_reference_id=str(student_id),
            metadata={
                'course_id': str(course_id),
                'student_id': str(student_id)
            }
        )

        payment = Payment(
            student_id=student_id,
            course_id=course_id,
            amount=course.price,
            currency=course.currency,
            payment_gateway='stripe',
            order_id=checkout_session.id,
            status='pending'
        )
        db.session.add(payment)
        db.session.commit()
        
        return redirect(checkout_session.url, code=303)
        
    except Exception as e:
        flash(f'Error initiating payment: {str(e)}')
        return redirect(url_for('student_dashboard', id=student_id))


@app.route('/payment/success', methods=['GET'])
def payment_success():
    session_id = request.args.get('session_id')
    if not session_id:
        flash('Invalid payment session.')
        return redirect(url_for('home'))
        
    try:
        
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status == 'paid':
            
            payment = Payment.query.filter_by(order_id=session_id).first()
            if payment:
                payment.status = 'completed'
                payment.transaction_id = checkout_session.payment_intent
                payment.updated_at = datetime.utcnow()
                
                
                existing_enroll = Enrollment.query.filter_by(
                    student_id=payment.student_id, 
                    course_id=payment.course_id
                ).first()
                
                if not existing_enroll:
                    enrollment = Enrollment(student_id=payment.student_id, course_id=payment.course_id)
                    db.session.add(enrollment)
                
                db.session.commit()
                
                flash('Payment successful! You are now enrolled.')
                return redirect(url_for('student_dashboard', id=payment.student_id))
            else:
                 
                 pass
        
        flash('Payment not completed.')
        return redirect(url_for('home'))
            
    except Exception as e:
        flash(f'Error verifying payment: {str(e)}')
        return redirect(url_for('home'))


@app.route('/payment/cancel', methods=['GET'])
def payment_cancel():
    return render_template('payment-cancel.html')

@app.route('/student/<int:id>')
@role_required('student')
def student_dashboard(id):

    
    all_courses = Course.query.all()
    
    for c in all_courses:
        teacher = User.query.get(c.teacher_id) if c.teacher_id else None
        c.teacher_name = teacher.name if teacher else 'Unknown'

    
    enrolled_courses = (
        db.session.query(Course)
        .join(Enrollment, Course.id == Enrollment.course_id)
        .filter(Enrollment.student_id == id)
        .all()
        )

    
    for c in enrolled_courses:
        teacher = User.query.get(c.teacher_id) if c.teacher_id else None
        c.teacher_name = teacher.name if teacher else 'Unknown'

    enrolled_course_ids = [c.id for c in enrolled_courses]

    return render_template(
        'student.html',
        student_id=id,
        all_courses=all_courses,
        enrolled_courses=enrolled_courses,
        enrolled_course_ids=enrolled_course_ids
    )


@app.route('/enroll', methods=['POST'])
@role_required('student')
def enroll():
    student_id = request.form['student_id']
    course_id = request.form['course_id']
    course = Course.query.get_or_404(course_id)

    existing = Enrollment.query.filter_by(
        student_id=student_id,
        course_id=course_id
    ).first()

    if existing:
        flash('Already enrolled!')
        return redirect(f'/student/{student_id}')

    
    payment_mode = os.getenv('PAYMENT_MODE', 'test').lower()
    
    if course.price > 0 and payment_mode != 'bypass':
        
        return initiate_payment(course_id)

    
    enroll = Enrollment(
        student_id=student_id,
        course_id=course_id
    )
    db.session.add(enroll)
    db.session.commit()

    flash('Enrolled successfully!')
    return redirect(f'/student/{student_id}')

# quizze
@app.route('/course/<int:course_id>/quiz/create', methods=['GET', 'POST'])
@role_required('teacher')
def create_quiz(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        duration = request.form.get('duration_minutes')
        passing_score = request.form.get('passing_score', 60)
        
        quiz = Quiz(
            course_id=course_id,
            title=title,
            description=description,
            duration_minutes=duration,
            passing_score=passing_score,
            created_by=session.get('id')
        )
        db.session.add(quiz)
        db.session.commit()
        
        if request.form.get('redirect_to') == 'manage_course_quizzes':
            flash('Quiz created successfully!')
            return redirect(url_for('manage_course_quizzes', course_id=course_id))
            
        flash('Quiz created successfully! Now add some questions.')
        return redirect(url_for('manage_quiz', quiz_id=quiz.id))
        
    return redirect(url_for('manage_course_quizzes', course_id=course_id))


@app.route('/course/<int:course_id>/manage-quizzes', methods=['GET'])
@role_required('teacher')
def manage_course_quizzes(course_id):
    course = Course.query.get_or_404(course_id)
    quizzes = Quiz.query.filter_by(course_id=course_id).all()
    # Populate questions for each quiz for modal viewing
    for quiz in quizzes:
        quiz.questions = Question.query.filter_by(quiz_id=quiz.id).order_by(Question.order).all()
    return render_template('manage-course-quizzes.html', course=course, quizzes=quizzes)


@app.route('/quiz/<int:quiz_id>/manage', methods=['GET'])
@role_required('teacher')
def manage_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    questions = Question.query.filter_by(quiz_id=quiz_id).order_by(Question.order).all()
    return redirect(url_for('manage_course_quizzes', course_id=quiz.course_id))


@app.route('/quiz/<int:quiz_id>/question/add', methods=['POST'])
@role_required('teacher')
def add_question(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    question_text = request.form.get('question_text')
    options = request.form.getlist('options[]')
    correct_answer = request.form.get('correct_answer')
    
    question = Question(
        quiz_id=quiz_id,
        question_text=question_text,
        options=json.dumps(options),
        correct_answer=correct_answer,
        order=Question.query.filter_by(quiz_id=quiz_id).count() + 1
    )
    db.session.add(question)
    db.session.commit()
    
    flash('Question added successfully!')
    if request.form.get('redirect_to') == 'manage_course_quizzes':
        # Pass a hash to open the modal back
        return redirect(url_for('manage_course_quizzes', course_id=quiz.course_id) + f'#manageQuizModal{quiz_id}')
        
    return redirect(url_for('manage_quiz', quiz_id=quiz_id))


@app.route('/course/<int:course_id>/quizzes', methods=['GET'])
@role_required('student')
def list_quizzes(course_id):
    course = Course.query.get_or_404(course_id)
    
    enrolled = Enrollment.query.filter_by(student_id=session.get('id'), course_id=course_id).first()
    if not enrolled:
        flash('You must be enrolled to access quizzes.')
        return redirect(url_for('view_course', course_id=course_id))
        
    quizzes = Quiz.query.filter_by(course_id=course_id).all()
    attempts = {a.quiz_id: a for a in QuizAttempt.query.filter_by(student_id=session.get('id')).all()}
    
    return render_template('quiz-list.html', course=course, quizzes=quizzes, attempts=attempts)


@app.route('/quiz/<int:quiz_id>/take', methods=['GET'])
@role_required('student')
def take_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    
    enrolled = Enrollment.query.filter_by(student_id=session.get('id'), course_id=quiz.course_id).first()
    if not enrolled:
        flash('You must be enrolled to take this quiz.')
        return redirect(url_for('home'))
        
    questions = Question.query.filter_by(quiz_id=quiz_id).order_by(Question.order).all()
    
    
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        student_id=session.get('id')
    )
    db.session.add(attempt)
    db.session.commit()
    
    return render_template('quiz-take.html', quiz=quiz, questions=questions, attempt_id=attempt.id)


@app.route('/quiz/<int:quiz_id>/submit/<int:attempt_id>', methods=['POST'])
@role_required('student')
def submit_quiz(quiz_id, attempt_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    
    questions = Question.query.filter_by(quiz_id=quiz_id).all()
    user_answers = {}
    score = 0
    total_points = 0
    
    for q in questions:
        total_points += q.points
        answer = request.form.get(f'question_{q.id}')
        user_answers[str(q.id)] = answer
        if answer == q.correct_answer:
            score += q.points
            
    percentage = (score / total_points * 100) if total_points > 0 else 0
    passed = percentage >= quiz.passing_score
    
    attempt.answers = json.dumps(user_answers)
    attempt.score = score
    attempt.max_score = total_points
    attempt.percentage = percentage
    attempt.passed = passed
    attempt.submitted_at = datetime.utcnow()
    
    db.session.commit()
    
    return redirect(url_for('quiz_results', attempt_id=attempt.id))


@app.route('/quiz/results/<int:attempt_id>', methods=['GET'])
@role_required('student')
def quiz_results(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    if attempt.student_id != session.get('id'):
        flash('Unauthorized.')
        return redirect(url_for('home'))
        
    quiz = Quiz.query.get(attempt.quiz_id)
    questions = Question.query.filter_by(quiz_id=quiz.id).all()
    answers = json.loads(attempt.answers) if attempt.answers else {}
    
    return render_template('quiz-results.html', attempt=attempt, quiz=quiz, questions=questions, answers=answers)


@app.route('/quiz/<int:quiz_id>/attempts', methods=['GET'])
@role_required('teacher')
def view_quiz_attempts(quiz_id):
    return redirect(url_for('teacher_quiz_tracker', id=session.get('id')))


@app.route('/quiz/attempt/<int:attempt_id>/detail', methods=['GET'])
@role_required('teacher')
def view_attempt_detail(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    quiz = Quiz.query.get(attempt.quiz_id)
    student = User.query.get(attempt.student_id)
    
    questions = Question.query.filter_by(quiz_id=quiz.id).order_by(Question.order).all()
    student_answers = json.loads(attempt.answers) if attempt.answers else {}
    
    return render_template(
        'quiz-attempt-detail-teacher.html',
        quiz=quiz,
        attempt=attempt,
        student=student,
        questions=questions,
        student_answers=student_answers
    )

@app.route('/teacher/<int:id>/quiz-tracker', methods=['GET'])
@role_required('teacher')
def teacher_quiz_tracker(id):
    if id != session.get('id'):
        flash('Unauthorized')
        return redirect(url_for('home'))
    quizzes = Quiz.query.filter_by(created_by=id).all()
    
    quiz_data = []
    for quiz in quizzes:
        
        attempts = db.session.query(QuizAttempt, User).join(
            User, QuizAttempt.student_id == User.id
        ).filter(
            QuizAttempt.quiz_id == quiz.id
        ).order_by(QuizAttempt.submitted_at.desc()).all()
        
        quiz_data.append({
            'quiz': quiz,
            'attempts': attempts,
            'attempt_count': len(attempts)
        })
        
    return render_template(
        'teacher-quiz-tracker.html',
        teacher_id=id,
        quiz_data=quiz_data
    )


@app.route('/quiz/delete/<int:quiz_id>', methods=['POST'])
@role_required('teacher')
def delete_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    
    is_admin = session.get('role') == 'admin'
    if quiz.created_by != session.get('id') and not is_admin:
        flash('You do not have permission to delete this quiz.')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    try:
        # 1. Delete associated questions
        Question.query.filter_by(quiz_id=quiz_id).delete()
        
        # 2. Delete associated quiz attempts
        QuizAttempt.query.filter_by(quiz_id=quiz_id).delete()
        
        # 3. Delete the quiz itself
        db.session.delete(quiz)
        db.session.commit()
        
        flash('Quiz and all associated data deleted successfully!')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting quiz: {str(e)}')
        
    if request.referrer and 'manage-quizzes' in request.referrer:
         return redirect(request.referrer)
         
    return redirect(url_for('teacher_dashboard', id=session.get('id')))


@app.route('/admin/delete-course/<int:course_id>', methods=['POST'])
@role_required('admin')
def admin_delete_course(course_id):
    Enrollment.query.filter_by(course_id=course_id).delete()
    course = Course.query.get(course_id)
    if course:
        title = course.title
        db.session.delete(course)
        db.session.commit()
        flash(f'Course "{title}" deleted successfully!')

    return redirect(url_for('admin_dashboard'))

@app.route('/course/<int:course_id>/edit', methods=['GET'])
@role_required('teacher')
def edit_course_materials(course_id):
    course = Course.query.get(course_id)
    if not course:
        flash('Course not found')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    
    
    return render_template(
        'edit-course.html',
        course=course,
        teacher_id=session.get('id')
    )

@app.route('/course/<int:course_id>/update-materials', methods=['POST'])
@role_required('teacher')
def update_course_materials(course_id):
    try:
        course = Course.query.get(course_id)
        if not course:
            flash('Course not found')
            return redirect(url_for('teacher_dashboard', id=session.get('id')))
        
        
        
        course.content = request.form.get('content', '')
        
        # Get existing materials
        materials_list = []
        if course.materials:
            try:
                materials_list = json.loads(course.materials)
            except:
                materials_list = []
        
        # 1. Handle YouTube Link
        youtube_link = request.form.get('youtube_link', '').strip()
        youtube_title = request.form.get('youtube_title', '').strip() or 'Video Lecture (YouTube)'
        if youtube_link:
            materials_list.append({
                'name': youtube_title,
                'path': youtube_link,
                'type': 'youtube'
            })
        
        # 2. Process uploaded files using Cloudinary
        if 'materials' in request.files:
            files = request.files.getlist('materials')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    try:
                        # Upload to Cloudinary
                        result = cloudinary.uploader.upload(
                            file,
                            folder=f"course_materials/{course_id}",
                            resource_type="auto"
                        )
                        
                        # Sanitize URL to remove any backslashes
                        secure_url = result['secure_url'].replace('\\', '/')
                        
                        materials_list.append({
                            'name': file.filename,
                            'path': secure_url,
                            'type': 'file',
                            'cloudinary_id': result['public_id']
                        })
                    except Exception as upload_error:
                        flash(f'Error uploading {file.filename}: {str(upload_error)}', 'danger')
        
        course.materials = json.dumps(materials_list)
        db.session.add(course)
        db.session.commit()
        flash('Course materials updated successfully!', 'success')
        return redirect(url_for('edit_course_materials', course_id=course_id))
    except Exception as e:
        flash(f'Error updating materials: {str(e)}', 'danger')
        return redirect(url_for('edit_course_materials', course_id=course_id))

@app.route('/unenroll', methods=['POST'])
@role_required('student')
def unenroll():
    student_id = request.form['student_id']
    course_id = request.form['course_id']

    # Find and delete the enrollment record
    Enrollment.query.filter_by(
        student_id=student_id, 
        course_id=course_id
    ).delete()
    
    db.session.commit()
    flash('Successfully un-enrolled from the course.')
    return redirect(f'/student/{student_id}')


@app.route('/course/<int:course_id>')
def view_course(course_id):
    # 1. Check if user is logged in
    if 'id' not in session:
        return redirect(url_for('login_page'))
    
    # 2. Get the course details from the database
    course = Course.query.get_or_404(course_id)
    
    # Parse materials JSON
    materials = []
    if course.materials:
        try:
            materials = json.loads(course.materials)
        except:
            materials = []
    
    # 3. Show a new page called course_detail.html
    return render_template('course-view.html', 
                           course=course,
                           materials=materials,
                           student_id=session.get('id'))
@app.route('/logout')
def logout():
    # Clears the user's session data
    session.clear() 
    # Redirect to the 'home' function instead of 'login' 
    # to show the login form again.
    return redirect(url_for('home'))


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json

    user = User.query.filter_by(
        email=data['email'],
        password=data['password']
    ).first()

    if not user:
        return jsonify({'message': 'Invalid login'}), 401

    return jsonify({
        'message': 'Login success',
        'user_id': user.id,
        'role': user.role
    })
@app.route('/api/student/<int:id>/courses')
def api_student_courses(id):

    courses = db.session.query(Course).join(
        Enrollment, Course.id == Enrollment.course_id
    ).filter(
        Enrollment.student_id == id
    ).all()

    return jsonify([
        {
            'course_id': c.id,
            'title': c.title,
            'description': c.description
        } for c in courses
    ])
@app.route('/api/enroll', methods=['POST'])
def api_enroll():
    data = request.json

    enrollment = Enrollment(
        student_id=data['student_id'],
        course_id=data['course_id']
    )
    db.session.add(enrollment)
    db.session.commit()

    return jsonify({'message': 'Enrolled successfully'})

@app.route('/api/teacher/course', methods=['POST'])
def api_create_course():
    data = request.json

    course = Course(
        title=data['title'],
        description=data['description'],
        teacher_id=data['teacher_id']
    )

    db.session.add(course)
    db.session.commit()

    return jsonify({'message': 'Course created'})

@app.route('/api/teacher/<int:id>/dashboard')
def api_teacher_dashboard(id):

    teacher_courses = Course.query.filter_by(teacher_id=id).all()
    result = []

    for course in teacher_courses:
        students = db.session.query(User).join(
            Enrollment, User.id == Enrollment.student_id
        ).filter(
            Enrollment.course_id == course.id
        ).all()

        result.append({
            'course_id': course.id,
            'title': course.title,
            'student_count': len(students),
            'students': [
                {
                    'id': s.id,
                    'name': s.name,
                    'email': s.email
                } for s in students
            ]
        })

    return jsonify(result)


if __name__ == '__main__':
    app.run(debug=True)
