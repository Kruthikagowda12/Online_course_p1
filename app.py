from flask import Flask, render_template, request, redirect
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask import flash
from flask import session, redirect, url_for
from sqlalchemy import text
import os
from dotenv import load_dotenv
import json
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = 'secret123'
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
# app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:password@localhost/online_course'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# File upload config
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'mp4', 'avi', 'mov', 'mkv', 'txt', 'doc', 'docx', 'ppt', 'pptx', 'zip'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Custom Jinja2 filter to parse JSON
@app.template_filter('from_json')
def from_json(value):
    return json.loads(value) if value else []


db = SQLAlchemy(app)


# Models
class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    role = db.Column(db.String(20))


class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    content = db.Column(db.Text)
    materials = db.Column(db.Text, default='')  # JSON string of uploaded files
    teacher_id = db.Column(db.Integer)


class Enrollment(db.Model):
    __tablename__ = 'enrollments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer)
    course_id = db.Column(db.Integer)


# Home
@app.route('/')
def home():
    return render_template('templates/register.html')


# Serve separate registration page (GET)
@app.route('/register', methods=['GET'])
def register_page():
    return render_template('templates/register.html')


# Serve separate login page (GET)
@app.route('/login', methods=['GET'])
def login_page():
    return render_template('templates/login.html')

@app.route('/register', methods=['POST'])
def register():
    email = request.form['email']

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
         return render_template(
            'templates/login.html',
            message='Email already registered. Please login.'
        )

        # return 'Email already registered. Please login.'

    user = User(
        name=request.form['name'],
        email=email,
        password=request.form['password'],
        role=request.form['role']
    )

    db.session.add(user)
    db.session.commit()
    return render_template(
        'templates/login.html',
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
    
    if user:
        session['id'] = user.id       
        session['name'] = user.name   
        session['role'] = user.role
        
        if user.role == 'student':
            return redirect(url_for('student_dashboard', id=user.id))
        else:
            return redirect(url_for('teacher_dashboard', id=user.id))
    
    return "Invalid Login"

    # if not user:
    #     return 'Invalid login'
    # session['name'] = user.name
    #   # Store the name in the session
    # if user.role == 'student':
        
    #     return redirect(f'/student/{user.id}')
        
    # else:
    #     return redirect(f'/teacher/{user.id}')
    
    
@app.route('/teacher/<int:id>')
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
        'templates/teacher.html',
        course_data=course_data,
        teacher_id=id   # ✅ IMPORTANT
    )


@app.route('/teacher/<int:id>/students')
def teacher_students(id):
    # Get all students enrolled in any course by this teacher
    teacher_courses = Course.query.filter_by(teacher_id=id).all()
    course_ids = [c.id for c in teacher_courses]

    students = []
    if course_ids:
        enrolled = (
            db.session.query(User)
            .join(Enrollment, User.id == Enrollment.student_id)
            .filter(Enrollment.course_id.in_(course_ids))
            .all()
        )

        # dedupe by id
        seen = set()
        for s in enrolled:
            if s.id not in seen:
                seen.add(s.id)
                students.append(s)

    return render_template('templates/teacher-students.html', students=students, teacher_id=id)

@app.route('/teacher/<int:teacher_id>/student/<int:student_id>')
def teacher_student_detail(teacher_id, student_id):
    # show a focused view of a student and the courses they are enrolled in
    student = User.query.get_or_404(student_id)

    enrolled_courses = (
        db.session.query(Course)
        .join(Enrollment, Course.id == Enrollment.course_id)
        .filter(Enrollment.student_id == student_id)
        .all()
    )

    # annotate courses with teacher relation and teacher name
    for c in enrolled_courses:
        c.is_teacher_course = (c.teacher_id == teacher_id)
        teacher = User.query.get(c.teacher_id) if c.teacher_id else None
        c.teacher_name = teacher.name if teacher else 'Unknown'

    return render_template('templates/teacher-student-detail.html',
                           student=student,
                           enrolled_courses=enrolled_courses,
                           teacher_id=teacher_id)


@app.route('/course/<int:course_id>/material/delete/<int:material_index>', methods=['POST'])
def delete_material(course_id, material_index):
    course = Course.query.get(course_id)
    if not course:
        flash('Course not found')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    # Check if user is the teacher of this course
    if course.teacher_id != session.get('id'):
        flash('You do not have permission to edit this course')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    # Parse materials and remove the specified one
    materials_list = []
    if course.materials:
        try:
            materials_list = json.loads(course.materials)
        except:
            materials_list = []
    
    if 0 <= material_index < len(materials_list):
        # Delete file from disk if it exists
        material = materials_list[material_index]
        try:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], material['path'].split('/')[-1])
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"Error deleting file: {e}")
        
        # Remove from list
        materials_list.pop(material_index)
        course.materials = json.dumps(materials_list)
        db.session.commit()
        flash('Material deleted successfully!')
    
    return redirect(url_for('edit_course_materials', course_id=course_id))


@app.route('/teacher/create', methods=['POST'])
def create_course():
    title = request.form['title']
    description = request.form['description']
    teacher_id = request.form['teacher_id']

    course = Course(
        title=title,
        description=description,
        teacher_id=teacher_id
    )

    db.session.add(course)
    db.session.commit()
    # flash('Course created successfully!')
    return redirect(f'/teacher/{teacher_id}')

    

@app.route('/student/<int:id>')
def student_dashboard(id):

    # all courses (for enrollment)
    all_courses = Course.query.all()
    # attach teacher name to each course for template display
    for c in all_courses:
        teacher = User.query.get(c.teacher_id) if c.teacher_id else None
        c.teacher_name = teacher.name if teacher else 'Unknown'

    # courses student already enrolled in
    enrolled_courses = (
        db.session.query(Course)
        .join(Enrollment, Course.id == Enrollment.course_id)
        .filter(Enrollment.student_id == id)
        .all()
        )

    # attach teacher name to enrolled courses as well
    for c in enrolled_courses:
        teacher = User.query.get(c.teacher_id) if c.teacher_id else None
        c.teacher_name = teacher.name if teacher else 'Unknown'

    return render_template(
        'templates/student.html',
        # courses=courses,
        student_id=id,
        all_courses=all_courses,
        enrolled_courses=enrolled_courses
    )


@app.route('/enroll', methods=['POST'])
def enroll():
    student_id = request.form['student_id']
    course_id = request.form['course_id']

    # prevent duplicate enrollment
    existing = Enrollment.query.filter_by(
        student_id=student_id,
        course_id=course_id
    ).first()

    if not existing:
        enroll = Enrollment(
            student_id=student_id,
            course_id=course_id
        )
        db.session.add(enroll)
        db.session.commit()

    # 🔁 redirect back to student dashboard
    flash('Enrolled successfully!')
# return redirect(f'/student/{student_id}')
    return redirect(f'/student/{student_id}')


@app.route('/teacher/delete/<int:course_id>/<int:teacher_id>', methods=['POST'])
def delete_course(course_id, teacher_id):

    # delete enrollments first (important)
    Enrollment.query.filter_by(course_id=course_id).delete()

    # delete course
    course = Course.query.get(course_id)
    if course:
        db.session.delete(course)
        db.session.commit()

    return redirect(f'/teacher/{teacher_id}')

@app.route('/course/<int:course_id>/edit', methods=['GET'])
def edit_course_materials(course_id):
    course = Course.query.get(course_id)
    if not course:
        flash('Course not found')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    # Check if user is the teacher of this course
    if course.teacher_id != session.get('id'):
        flash('You do not have permission to edit this course')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    return render_template(
        'templates/edit-course.html',
        course=course,
        teacher_id=session.get('id')
    )

@app.route('/course/<int:course_id>/update-materials', methods=['POST'])
def update_course_materials(course_id):
    course = Course.query.get(course_id)
    if not course:
        flash('Course not found')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    # Check if user is the teacher of this course
    if course.teacher_id != session.get('id'):
        flash('You do not have permission to edit this course')
        return redirect(url_for('teacher_dashboard', id=session.get('id')))
    
    course.content = request.form.get('content', '')
    
    # Handle file uploads
    materials_list = []
    if course.materials:
        try:
            materials_list = json.loads(course.materials)
        except:
            materials_list = []
    
    # Process uploaded files
    if 'materials' in request.files:
        files = request.files.getlist('materials')
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to avoid conflicts
                import time
                filename = f"{int(time.time())}_{filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                materials_list.append({
                    'name': file.filename,
                    'path': f'uploads/{filename}',
                    'type': 'file'
                })
    
    course.materials = json.dumps(materials_list)
    db.session.commit()
    flash('Course materials updated successfully!')
    return redirect(url_for('teacher_dashboard', id=session.get('id')))

@app.route('/unenroll', methods=['POST'])
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
    return render_template('templates/course-view.html', 
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
