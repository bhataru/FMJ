from datetime import datetime, timedelta
import os
import shutil
from pathlib import Path
from typing import Optional
import aiomysql
import bcrypt
from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from pydantic import BaseModel

# Configuration (Reads both underscored and non-underscored Railway variables)
MYSQL_HOST = os.getenv("MYSQLHOST") or os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQLPORT") or os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQLUSER") or os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQLPASSWORD") or os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQLDATABASE") or os.getenv("MYSQL_DATABASE", "journalist_db")

SECRET_KEY = os.getenv("SECRET_KEY", "your_super_secret_jwt_key_here")
ALGORITHM = "HS256"

app = FastAPI(title="Faizan Mir Journalist Platform", version="2.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

db_pool = None

@app.on_event("startup")
async def startup_db_pool():
    global db_pool
    db_pool = await aiomysql.create_pool(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, db=MYSQL_DB, autocommit=True, minsize=2, maxsize=10
    )
    
    # Automatically create required tables if they don't exist
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS stories (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    category VARCHAR(100) DEFAULT 'General',
                    author VARCHAR(100) DEFAULT 'Faizan Mir',
                    image_url VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL
                );
            """)

@app.on_event("shutdown")
async def shutdown_db_pool():
    global db_pool
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()

class StoryCreate(BaseModel):
    title: str
    slug: str
    content: str
    category: str
    author: str
    image_url: Optional[str] = None
    created_at: Optional[str] = None  # Added to accept custom publication dates

class LoginRequest(BaseModel):
    username: str
    password: str

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=60))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_admin(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        if token.startswith("Bearer "):
            token = token.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

# ---------------------------------------------------------
# Web Page Frontend Routes
# ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    stories = []
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT id, title, slug, content, category, author, image_url, created_at FROM stories ORDER BY created_at DESC LIMIT 6"
                    )
                    stories = await cursor.fetchall()
        except Exception as e:
            print(f"Database query error: {e}")
            
    return templates.TemplateResponse("index.html", {"request": request, "stories": stories})

@app.get("/home", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/photos", response_class=HTMLResponse)
async def photos_page(request: Request):
    return templates.TemplateResponse("photos.html", {"request": request})

@app.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request):
    return templates.TemplateResponse("videos.html", {"request": request})

@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    stories = []
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT id, title, slug, content, category, author, image_url, created_at FROM stories ORDER BY created_at DESC LIMIT 6"
                    )
                    stories = await cursor.fetchall()
        except Exception as e:
            print(f"Database query error: {e}")
    return templates.TemplateResponse("index.html", {"request": request, "stories": stories})

@app.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})

@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


# ---------------------------------------------------------
# Admin Panel Routes
# ---------------------------------------------------------

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    try:
        await get_current_admin(request)
    except HTTPException:
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse("admin.html", {"request": request})


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.get("/api/stories")
async def get_stories(limit: int = 20, offset: int = 0):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, title, slug, content, category, author, image_url, created_at FROM stories ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset)
            )
            stories = await cursor.fetchall()
            return {"status": "success", "data": stories}

@app.post("/api/admin/login")
async def login(data: LoginRequest):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT password_hash FROM admins WHERE username = %s", (data.username,))
            admin = await cursor.fetchone()
            if not admin or not verify_password(data.password, admin["password_hash"]):
                raise HTTPException(status_code=400, detail="Incorrect credentials")
            access_token = create_access_token(data={"sub": data.username})
            response = JSONResponse(content={"status": "success"})
            response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True, secure=False, samesite="lax")
            return response

@app.post("/api/admin/upload")
async def upload_file(file: UploadFile = File(...), admin: str = Depends(get_current_admin)):
    file_path = UPLOAD_DIR / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "url": f"/static/uploads/{file.filename}"}

@app.post("/api/admin/stories")
async def create_story(story: StoryCreate, admin: str = Depends(get_current_admin)):
    if story.created_at:
        try:
            pub_date = datetime.fromisoformat(story.created_at.replace("Z", "+00:00"))
        except ValueError:
            pub_date = datetime.utcnow()
    else:
        pub_date = datetime.utcnow()

    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO stories (title, slug, content, category, author, image_url, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (story.title, story.slug, story.content, story.category, story.author, story.image_url, pub_date)
            )
            return {"status": "success", "message": "Story published successfully"}

@app.delete("/api/admin/stories/{story_id}")
async def delete_story(story_id: int, admin: str = Depends(get_current_admin)):
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("DELETE FROM stories WHERE id = %s", (story_id,))
            return {"status": "success", "message": "Story deleted successfully"}

@app.put("/api/admin/password")
async def change_password(data: PasswordChangeRequest, admin: str = Depends(get_current_admin)):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT password_hash FROM admins WHERE username = %s", (admin,))
            record = await cursor.fetchone()
            if not record or not verify_password(data.current_password, record["password_hash"]):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            
            new_hash = bcrypt.hashpw(data.new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            await cursor.execute("UPDATE admins SET password_hash = %s WHERE username = %s", (new_hash, admin))
            return {"status": "success", "message": "Password updated successfully in database"}