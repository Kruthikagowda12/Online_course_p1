#!/usr/bin/env python
"""
Migration script to add materials column to courses table
"""
from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            # Add materials column if it doesn't exist
            db.session.execute(text('''
                ALTER TABLE courses 
                ADD COLUMN IF NOT EXISTS materials TEXT DEFAULT '';
            '''))
            db.session.commit()
            print("✅ Migration successful: materials column added to courses table")
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            db.session.rollback()

if __name__ == '__main__':
    migrate()
