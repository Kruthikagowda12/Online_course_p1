from app import app, db
from sqlalchemy import text

with app.app_context():
    # Ensure all tables from models are created
    db.create_all()

    # Add the `content` column to courses if it doesn't exist
    db.session.execute(text('ALTER TABLE courses ADD COLUMN IF NOT EXISTS content TEXT'))
    db.session.commit()
    print('✓ Database tables ensured and content column added to courses table successfully')
