"""成功转化登记及客服个人查询记录。"""
import json

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import SQLAlchemyError

from backend.auth import public_user
from backend.models import MatchHistory, MatchHistoryImage, MatchConversion, UserAccount


class ConversionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    history_id: int = Field(gt=0)
    rank: int = Field(gt=0, le=50)


def conversion_data(row):
    return {'id': row.id, 'history_id': row.history_id, 'rank': row.rank,
            'product_id': row.product_id, 'created_at': row.created_at.isoformat()}


def install_conversions(app, factory):
    def owned_history(session, history_id, user_id):
        row = session.get(MatchHistory, history_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(404, '查询记录不存在。')
        return row

    @app.post('/api/conversions')
    def register_conversion(body: ConversionRequest, request: Request):
        try:
            with factory() as session:
                # 同一记录的检查与写入在一个事务内，避免重复提交重复计数。
                history = session.scalar(select(MatchHistory).where(MatchHistory.id == body.history_id).with_for_update())
                if history is None or history.user_id != request.state.user['id']:
                    raise HTTPException(404, '查询记录不存在。')
                result = next((item for item in json.loads(history.payload_json).get('results', []) if item.get('rank') == body.rank), None)
                if result is None:
                    raise HTTPException(422, '请选择本次匹配中存在的 Top 排名。')
                existing = session.scalar(select(MatchConversion).where(MatchConversion.history_id == history.id))
                if existing:
                    if existing.rank != body.rank:
                        raise HTTPException(409, f'本次匹配已登记 Top {existing.rank}，请勿重复登记。')
                    return {'conversion': conversion_data(existing)}
                row = MatchConversion(history_id=history.id, rank=body.rank, product_id=result.get('product_id') or None,
                                      submitted_by=request.state.user['id'])
                session.add(row)
                session.flush()
                data = conversion_data(row)
                session.commit()
                return {'conversion': data}
        except SQLAlchemyError:
            raise HTTPException(503, '下单登记失败，请稍后重试。') from None

    @app.get('/api/my-history')
    def my_history(request: Request, before: int | None = Query(None, ge=1)):
        try:
            with factory() as session:
                stmt = select(MatchHistory).where(MatchHistory.user_id == request.state.user['id']).order_by(MatchHistory.id.desc()).limit(21)
                if before is not None:
                    stmt = stmt.where(MatchHistory.id < before)
                rows = list(session.scalars(stmt))
                ids = [row.id for row in rows[:20]]
                conversions = {row.history_id: conversion_data(row) for row in session.scalars(select(MatchConversion).where(MatchConversion.history_id.in_(ids)))}
                images = set(session.scalars(select(MatchHistoryImage.history_id).where(MatchHistoryImage.history_id.in_(ids))))
                items = [{'id': row.id, 'user_id': row.user_id, 'created_at': row.created_at.isoformat(), 'result_count': len(json.loads(row.payload_json).get('results', [])),
                          'query_image_url': f'/api/my-history/{row.id}/image' if row.id in images else None,
                          'conversion': conversions.get(row.id)} for row in rows[:20]]
                return {'items': items, 'next_before': items[-1]['id'] if len(rows) > 20 else None}
        except SQLAlchemyError:
            raise HTTPException(503, '查询记录暂不可用，请重试。') from None

    @app.get('/api/my-history/{history_id}')
    def my_detail(history_id: int, request: Request):
        try:
            with factory() as session:
                row = owned_history(session, history_id, request.state.user['id'])
                conversion = session.scalar(select(MatchConversion).where(MatchConversion.history_id == history_id))
                image = session.scalar(select(MatchHistoryImage.history_id).where(MatchHistoryImage.history_id == history_id))
                return {'id': row.id, 'created_at': row.created_at.isoformat(), 'payload': json.loads(row.payload_json),
                        'query_image_url': f'/api/my-history/{row.id}/image' if image else None,
                        'conversion': conversion_data(conversion) if conversion else None}
        except SQLAlchemyError:
            raise HTTPException(503, '查询详情暂不可用，请重试。') from None

    @app.get('/api/my-history/{history_id}/image')
    def my_image(history_id: int, request: Request):
        try:
            with factory() as session:
                owned_history(session, history_id, request.state.user['id'])
                image = session.get(MatchHistoryImage, history_id)
                if image is None:
                    raise HTTPException(404, '该记录未保存客户照片。')
                return Response(image.content, media_type=image.mime_type, headers={'Cache-Control': 'no-store'})
        except SQLAlchemyError:
            raise HTTPException(503, '客户照片暂不可用。') from None

    @app.get('/api/conversions')
    def list_conversions(before: int | None = Query(None, ge=1)):
        try:
            with factory() as session:
                stmt = select(MatchConversion, MatchHistory, UserAccount).join(MatchHistory, MatchConversion.history_id == MatchHistory.id).join(
                    UserAccount, MatchHistory.user_id == UserAccount.id).order_by(MatchConversion.id.desc()).limit(21)
                if before is not None:
                    stmt = stmt.where(MatchConversion.id < before)
                rows = list(session.execute(stmt))
                items = [{**conversion_data(row), 'user': public_user(user), 'matched_at': history.created_at.isoformat()} for row, history, user in rows[:20]]
                total = session.scalar(select(func.count()).select_from(MatchHistory).where(MatchHistory.user_id.is_not(None)))
                converted = session.scalar(select(func.count()).select_from(MatchConversion))
                return {'items': items, 'next_before': items[-1]['id'] if len(rows) > 20 else None,
                        'total_matches': total, 'converted_matches': converted,
                        'conversion_rate': round(converted / total * 100, 2) if total else 0}
        except SQLAlchemyError:
            raise HTTPException(503, '下单记录暂不可用，请重试。') from None

    @app.get('/api/monitor')
    def monitor(customer_id: int | None = Query(None, ge=1), period: str = '7d'):
        if period not in ('7d', 'all'):
            raise HTTPException(422, '统计范围只支持近七天或全部。')
        try:
            with factory() as session:
                users = list(session.scalars(select(UserAccount).where(UserAccount.role == 'customer_service').order_by(UserAccount.id)))
                start = None
                if period == '7d':
                    today = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
                    start = today - timedelta(days=6)
                conditions = [MatchHistory.user_id.is_not(None)]
                if customer_id is not None:
                    conditions.append(MatchHistory.user_id == customer_id)
                if start is not None:
                    conditions.append(MatchHistory.created_at >= start)
                histories = list(session.scalars(select(MatchHistory).where(and_(*conditions)).order_by(MatchHistory.id.desc()).limit(501)))
                history_ids = [row.id for row in histories]
                conversions = list(session.scalars(select(MatchConversion).where(MatchConversion.history_id.in_(history_ids)))) if history_ids else []
                conversion_by_history = {row.history_id: conversion_data(row) for row in conversions}
                items = [{'id': row.id, 'created_at': row.created_at.isoformat(), 'result_count': len(json.loads(row.payload_json).get('results', [])),
                          'conversion': conversion_by_history.get(row.id)} for row in histories[:500]]
                total = len(histories)
                converted = len(conversions)
                return {'customers': [public_user(user) for user in users], 'selected_customer_id': customer_id,
                        'period': period, 'total_matches': total, 'converted_matches': converted,
                        'conversion_rate': round(converted / total * 100, 2) if total else 0, 'items': items,
                        'truncated': len(histories) > 500}
        except SQLAlchemyError:
            raise HTTPException(503, '查询监控暂不可用，请重试。') from None
