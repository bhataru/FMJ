import bcrypt

# The password you want to log in with
password = b"admin123" 

# Generate the secure hash
hashed = bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')

# Print the exact SQL command to run in Railway
print("\n--- RUN THIS SQL IN RAILWAY ---")
print(f"INSERT INTO admins (username, password_hash) VALUES ('admin', '{hashed}');")
print("-------------------------------\n")