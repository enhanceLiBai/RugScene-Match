"""账号、密码和数据库会话；不依赖图片匹配实现。"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from backend.access import is_customer_request
from backend.models import LoginSession, UserAccount

COOKIE = 'rugscene_session'
SESSION_SECONDS = 7 * 24 * 3600


def hash_password(password):
    if not 6 <= len(password) <= 128:
        raise ValueError('密码长度须为 6–128 个字符。')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f'scrypt${salt.hex()}${digest.hex()}'


def verify_password(password, stored):
    try:
        _, salt, expected = stored.split('$')
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(user):
    return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'role': user.role}


def create_user(session, username, display_name, password, role):
    username = username.strip().lower()
    display_name = display_name.strip()
    if not re.fullmatch(r'[\u3400-\u4dbf\u4e00-\u9fffa-z0-9_.-]{2,40}', username):
        raise ValueError('账号须为 2–40 个中文、英文字母、数字、点、横线或下划线，不含空格。')
    if not display_name or len(display_name) > 60:
        raise ValueError('姓名须为 1–60 个字符。')
    if role not in ('admin', 'customer_service'):
        raise ValueError('账号角色无效。')
    user = UserAccount(username=username, display_name=display_name, password_hash=hash_password(password), role=role)
    session.add(user)
    session.flush()
    return user


def resolve_user(factory, token):
    if not token:
        return None
    with factory() as session:
        user = session.scalar(select(UserAccount).join(LoginSession, LoginSession.user_id == UserAccount.id).where(
            LoginSession.token_hash == token_hash(token), LoginSession.expires_at > datetime.now(timezone.utc)))
        return public_user(user) if user else None


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class NewAccount(BaseModel):
    username: str = Field(max_length=40)
    display_name: str = Field(max_length=60)
    password: str = Field(min_length=6, max_length=128)


def install_auth(app, factory, frontend_root):
    # 静态脚本不含业务数据；客户图片与所有业务接口仍要求有效会话。
    anonymous = {'/login', '/admin/login', '/login.js', '/auth-client.js', '/styles.css',
                 '/app.js', '/api-client.js', '/matcher-core.js', '/api/auth/login', '/api/auth/admin-login', '/health'}

    @app.middleware('http')
    async def authentication(request: Request, call_next):
        path = request.url.path.rstrip('/') or '/'
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            # 同源 Cookie 会话：拒绝跨站表单及跨站 fetch 写入。
            from urllib.parse import urlsplit
            if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and urlsplit(origin).netloc != request.headers.get('host')):
                return JSONResponse({'detail': '请在系统页面内操作。'}, status_code=403)
        if path not in anonymous:
            try:
                user = await run_in_threadpool(resolve_user, factory, request.cookies.get(COOKIE))
            except SQLAlchemyError:
                return JSONResponse({'detail': '登录状态暂不可用，请稍后重试。'}, status_code=503)
            if not user:
                if path in ('/', '/admin', '/feedback', '/admin/library'):
                    return RedirectResponse('/login' if path == '/' else '/admin/login', status_code=303)
                return JSONResponse({'detail': '登录已过期，请重新登录。'}, status_code=401)
            request.state.user = user
            shared = path in ('/api/auth/me', '/api/auth/logout', '/auth-client.js')
            if not shared and not is_customer_request(request.method, path) and user['role'] != 'admin':
                return JSONResponse({'detail': '仅管理员可访问。'}, status_code=403)
        response = await call_next(request)
        if path not in {'/styles.css', '/app.js', '/api-client.js', '/matcher-core.js', '/login.js', '/auth-client.js'}:
            response.headers['Cache-Control'] = 'no-store'
        return response

    def login(body, request, admin_only):
        try:
            with factory() as session:
                user = session.scalar(select(UserAccount).where(UserAccount.username == body.username.strip().lower()).with_for_update())
                if not user or not verify_password(body.password, user.password_hash) or (admin_only and user.role != 'admin'):
                    raise HTTPException(401, '账号或密码错误，或账号不属于此登录入口。')
                token = secrets.token_urlsafe(32)
                now = datetime.now(timezone.utc)
                session.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
                if user.role == 'customer_service':
                    session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
                session.add(LoginSession(token_hash=token_hash(token), user_id=user.id, expires_at=now + timedelta(seconds=SESSION_SECONDS)))
                result = public_user(user)
                session.commit()
            response = JSONResponse({'user': result})
            secure = request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https'
            response.set_cookie(COOKIE, token, httponly=True, secure=secure, samesite='lax', max_age=SESSION_SECONDS, path='/')
            return response
        except SQLAlchemyError:
            raise HTTPException(503, '登录服务暂不可用，请稍后重试。') from None

    @app.post('/api/auth/login')
    def customer_login(body: LoginBody, request: Request):
        return login(body, request, False)

    @app.post('/api/auth/admin-login')
    def admin_login(body: LoginBody, request: Request):
        return login(body, request, True)

    @app.get('/api/auth/me')
    def me(request: Request):
        return {'user': request.state.user}

    @app.post('/api/auth/logout')
    def logout(request: Request):
        try:
            with factory() as session:
                session.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(request.cookies.get(COOKIE, ''))))
                session.commit()
        except SQLAlchemyError:
            raise HTTPException(503, '退出失败，请重试。') from None
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.get('/api/accounts')
    def accounts():
        try:
            with factory() as session:
                return {'items': [public_user(user) for user in session.scalars(select(UserAccount).order_by(UserAccount.id))]}
        except SQLAlchemyError:
            raise HTTPException(503, '账号列表暂不可用。') from None

    @app.post('/api/accounts', status_code=201)
    def new_customer(body: NewAccount):
        try:
            with factory() as session:
                user = create_user(session, body.username, body.display_name, body.password, 'customer_service')
                result = public_user(user)
                session.commit()
                return {'user': result}
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except IntegrityError:
            raise HTTPException(409, '账号已存在，请换一个账号。') from None
        except SQLAlchemyError:
            raise HTTPException(503, '开通账号失败，请稍后重试。') from None

    @app.get('/login', include_in_schema=False)
    @app.get('/admin/login', include_in_schema=False)
    def login_page():
        return FileResponse(frontend_root / 'login.html', media_type='text/html')

    @app.get('/login.js', include_in_schema=False)
    def login_script():
        return FileResponse(frontend_root / 'login.js', media_type='text/javascript')

    @app.get('/auth-client.js', include_in_schema=False)
    def auth_script():
        return FileResponse(frontend_root / 'auth-client.js', media_type='text/javascript')
