from flask import Flask, render_template, request, redirect
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask import flash



app = Flask(__name__)
app.secret_key = 'secret123'
app.config['SQLALCHEMY_DATABASE_URI'] = \
'postgresql://postgres:postgres123@localhost:5432/online_course'
# app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:password@localhost/online_course'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


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
    teacher_id = db.Column(db.Integer)


class Enrollment(db.Model):
    __tablename__ = 'enrollments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer)
    course_id = db.Column(db.Integer)


# Home
@app.route('/')
def home():
    return render_template('templates/index.html')

@app.route('/register', methods=['POST'])
def register():
    email = request.form['email']

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
         return render_template(
            'templates/index.html',
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
        'templates/index.html',
        message='Registration successful! You can now login.'
    
    )

@app.route('/login', methods=['POST'])
def login():
    user = User.query.filter_by(
    email=request.form['email'],
    password=request.form['password']
    ).first()


    if not user:
        return 'Invalid login'
    if user.role == 'student':
        return redirect(f'/student/{user.id}')
    else:
        return redirect(f'/teacher/{user.id}')
    
# @app.route('/teacher/<int:id>')
# def teacher_dashboard(id):
#     teacher_courses = Course.query.filter_by(teacher_id=id).all()
#     return render_template('templates/teacher.html', teacher_id=id, courses=teacher_courses)
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
 
# @app.route('/teacher/<int:id>/create', methods=['POST'])
# def create_course(id):
#     course = Course(
#         title=request.form['title'],
#         description=request.form.get('description', ''),
#         teacher_id=id   # ✅ ALWAYS integer
#         course = Course(
#         title=title,
#         description=description,
#         teacher_id=teacher_id
#     )
#     db.session.add(course)
#     db.session.commit()
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

    # courses student already enrolled in
    enrolled_courses = (
        db.session.query(Course)
        .join(Enrollment, Course.id == Enrollment.course_id)
        .filter(Enrollment.student_id == id)
        .all()
        )

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
