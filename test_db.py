import psycopg2

conn = psycopg2.connect(
    dbname="online_course",
    user="PostgreSQL",
    password="postgres123",
    host="localhost",
    port="5432"
)

print("Connected successfully")
