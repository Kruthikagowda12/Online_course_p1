from app import app, db
from sqlalchemy import text

with app.app_context():
    db.session.execute(text('ALTER TABLE courses ADD COLUMN IF NOT EXISTS content TEXT'))
    db.session.commit()
    print('✓ Content column added to courses table successfully')
