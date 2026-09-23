"""客服接口可经公网隧道访问；管理功能仅接受本机或内网直连。"""

from ipaddress import ip_address, ip_network
import re

from fastapi import Request
from fastapi.responses import JSONResponse


LOCAL_NETWORKS = tuple(ip_network(value) for value in (
    '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
    '::1/128', 'fc00::/7', 'fe80::/10',
))
PUBLIC_ASSETS = {'/', '/app.js', '/api-client.js', '/matcher-core.js', '/styles.css',
                 '/login', '/login.js', '/auth-client.js', '/api/auth/me', '/orders.js'}
PROXY_HEADERS = ('cf-connecting-ip', 'cf-ray', 'forwarded', 'x-forwarded-for')


def is_customer_request(method: str, path: str) -> bool:
    path = path.rstrip('/') or '/'
    if method in ('GET', 'HEAD'):
        return path in PUBLIC_ASSETS or re.fullmatch(r'/api/images/[0-9]+', path) is not None or re.fullmatch(r'/api/my-history(?:/[0-9]+(?:/image)?)?', path) is not None
    return method == 'POST' and path in ('/api/search', '/api/conversions', '/api/auth/login', '/api/auth/logout')


async def restrict_management_access(request: Request, call_next):
    if not is_customer_request(request.method, request.url.path):
        # cloudflared 连接本机时也会携带这些标记，不能把代理当作本机管理员。
        direct = not any(header in request.headers for header in PROXY_HEADERS)
        try:
            address = ip_address(request.client.host if request.client else '')
            address = getattr(address, 'ipv4_mapped', None) or address
            local = any(address in network for network in LOCAL_NETWORKS)
        except ValueError:
            local = False
        if not direct or not local:
            return JSONResponse(status_code=403, content={'detail': '管理后台仅允许本机或局域网直连访问。'},
                                headers={'Cache-Control': 'no-store'})
    response = await call_next(request)
    if not is_customer_request(request.method, request.url.path):
        response.headers['Cache-Control'] = 'no-store'
    return response
