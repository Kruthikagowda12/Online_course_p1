from app import app, db, User
import os
from dotenv import load_dotenv

load_dotenv()

def create_admin():
    with app.app_context():
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@gmail.com')
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin')
        
        # Check if admin already exists
        admin = User.query.filter_by(email=admin_email).first()
        
        if not admin:
            print(f"Creating admin user: {admin_email}")
            admin = User(
                name='Admin User',
                email=admin_email,
                password=admin_password,
                role='admin',
                email_verified=True
            )
            db.session.add(admin)
            db.session.commit()
            print("Admin user created successfully.")
        else:
            print(f"Admin user {admin_email} already exists.")
            # Optional: Update password if needed, but for now just reporting
            # admin.password = admin_password
            # db.session.commit()

if __name__ == "__main__":
    create_admin()
