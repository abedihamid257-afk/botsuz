import os
import json
from pathlib import Path
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx

app = FastAPI(title="Bot Control Panel")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DATA_FILE = Path("data/bots.json")
DATA_FILE.parent.mkdir(exist_ok=True)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")

RUBIKA_API = "https://botapi.rubika.ir/v3"


def load_bots():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {}


def save_bots(bots):
    DATA_FILE.write_text(json.dumps(bots, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "رمز عبور نامعتبر است"}
        )
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("auth", ADMIN_PASSWORD, httponly=True)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if request.cookies.get("auth") != ADMIN_PASSWORD:
        return RedirectResponse(url="/", status_code=302)
    bots = load_bots()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "bots": bots}
    )


@app.post("/api/bots/add")
async def add_bot(request: Request, name: str = Form(...), token: str = Form(...)):
    if request.cookies.get("auth") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401)

    bots = load_bots()
    if name in bots:
        return JSONResponse({"ok": False, "error": "این نام قبلا ثبت شده است"})

    bots[name] = {"token": token, "status": "inactive"}
    save_bots(bots)
    return JSONResponse({"ok": True})


@app.post("/api/bots/{name}/activate")
async def activate_bot(request: Request, name: str):
    if request.cookies.get("auth") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401)

    bots = load_bots()
    if name not in bots:
        return JSONResponse({"ok": False, "error": "ربات یافت نشد"})

    token = bots[name]["token"]
    webhook_url = f"{BASE_URL}/webhook/{name}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{RUBIKA_API}/{token}/updateBotEndpoint",
                json={"endpoint": webhook_url},
                timeout=15.0
            )
            if response.status_code == 200:
                bots[name]["status"] = "active"
                save_bots(bots)
                return JSONResponse({"ok": True})
            else:
                return JSONResponse({"ok": False, "error": "خطا در اتصال به روبیکا"})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/bots/{name}/deactivate")
async def deactivate_bot(request: Request, name: str):
    if request.cookies.get("auth") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401)

    bots = load_bots()
    if name not in bots:
        return JSONResponse({"ok": False, "error": "ربات یافت نشد"})

    token = bots[name]["token"]

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{RUBIKA_API}/{token}/updateBotEndpoint",
                json={"endpoint": ""},
                timeout=15.0
            )
        except Exception:
            pass

    bots[name]["status"] = "inactive"
    save_bots(bots)
    return JSONResponse({"ok": True})


@app.post("/api/bots/{name}/delete")
async def delete_bot(request: Request, name: str):
    if request.cookies.get("auth") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401)

    bots = load_bots()
    if name in bots:
        del bots[name]
        save_bots(bots)
    return JSONResponse({"ok": True})


@app.post("/webhook/{name}")
async def webhook(name: str, request: Request):
    bots = load_bots()
    if name not in bots or bots[name]["status"] != "active":
        return JSONResponse({"ok": False}, status_code=404)

    token = bots[name]["token"]
    body = await request.json()

    if "update" in body:
        update = body["update"]
        chat_id = update.get("chat_id")
        new_message = update.get("new_message", {})
        text = new_message.get("text", "")

        if text == "/start":
            await send_message(token, chat_id, "به ربات خوش آمدید.")
        elif text == "/help":
            await send_message(token, chat_id, "دستورات موجود: start و help")

    elif "inline_message" in body:
        inline_msg = body["inline_message"]
        chat_id = inline_msg.get("chat_id")
        button_id = inline_msg.get("aux_data", {}).get("button_id")

        if button_id == "btn_info":
            await send_message(token, chat_id, "این یک ربات نمونه است.")

    return JSONResponse({"ok": True})


async def send_message(token: str, chat_id: str, text: str, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["inline_keypad"] = keyboard
    async with httpx.AsyncClient() as client:
        await client.post(f"{RUBIKA_API}/{token}/sendMessage", json=payload, timeout=10.0)


@app.get("/health")
async def health():
    return {"status": "alive"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
