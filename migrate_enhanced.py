from app import app, db
from sqlalchemy import text
import os

def migrate():
    with app.app_context():
        print("Starting enhanced migration...")
        
        # 1. Create all new tables defined in models
        db.create_all()
        print("✓ Tables created (if they didn't exist)")
        
        # 2. Add columns to USERS if they don't exist
        cols_users = [
            ('email_verified', 'BOOLEAN DEFAULT FALSE'),
            ('verification_token', 'VARCHAR(100)'),
            ('token_expiry', 'TIMESTAMP')
        ]
        for col, type in cols_users:
            try:
                db.session.execute(text(f'ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {type}'))
                print(f"✓ Column {col} ensured in users table")
            except Exception as e:
                print(f"! Note for {col} in users: {e}")
                
        # 3. Add columns to COURSES if they don't exist
        cols_courses = [
            ('price', 'NUMERIC(10, 2) DEFAULT 0.00'),
            ('currency', "VARCHAR(3) DEFAULT 'INR'")
        ]
        for col, type in cols_courses:
            try:
                db.session.execute(text(f'ALTER TABLE courses ADD COLUMN IF NOT EXISTS {col} {type}'))
                print(f"✓ Column {col} ensured in courses table")
            except Exception as e:
                print(f"! Note for {col} in courses: {e}")

        # 4. Add columns to ENROLLMENTS if they don't exist
        try:
            db.session.execute(text('ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))
            print("✓ Column enrolled_at ensured in enrollments table")
        except Exception as e:
            print(f"! Note for enrolled_at in enrollments: {e}")

        db.session.commit()
        
        # 5. Pre-verify existing users (optional - skip for production but helpful for migration)
        # We'll mark existing admin and teachers as verified
        db.session.execute(text("UPDATE users SET email_verified = TRUE WHERE role IN ('admin', 'teacher')"))
        db.session.commit()
        print("✓ Existing admins and teachers marked as verified")
        
        print("\nMigration completed successfully!")

if __name__ == "__main__":
    migrate()
