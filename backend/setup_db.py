import sqlite3

# Connect to database (this creates the file if it doesn't exist)
conn = sqlite3.connect('plant_readings.db')
cursor = conn.cursor()

# Create the readings table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        moisture INTEGER NOT NULL,
        temperature REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')

# Save the changes
conn.commit()

print("Database created successfully!")
print("Table 'readings' is ready to store sensor data")

# verify by checking the table structure
cursor.execute("PRAGMA table_info(readings)")
columns = cursor.fetchall()

print("\nTable structure:")
for col in columns:
    print(f"  {col[1]} - {col[2]}")  # name - type

conn.close()
