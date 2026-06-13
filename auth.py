from fastapi import Request, Response, HTTPException
from database import create_user, get_user, get_user_plan
import secrets

sessions = {}

def register_user(email: str, password: str):
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Senha muito curta")
    success = create_user(email, password)
    if not success:
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    return {"message": "Usuário criado com sucesso"}

def login_user(email: str, password: str, response: Response):
    user = get_user(email, password)
    if not user:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")
    token = secrets.token_hex(32)
    sessions[token] = {"email": email, "plan": get_user_plan(email)}
    response.set_cookie(key="session", value=token, httponly=True, max_age=86400)
    return {"message": "Login realizado", "plan": get_user_plan(email)}

def logout_user(response: Response, request: Request):
    token = request.cookies.get("session")
    if token in sessions:
        del sessions[token]
    response.delete_cookie("session")
    return {"message": "Logout realizado"}

def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token or token not in sessions:
        return None
    return sessions[token]

def require_pro(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login necessário")
    if user["plan"] == "free":
        raise HTTPException(status_code=403, detail="Plano Pro necessário")
    return user
