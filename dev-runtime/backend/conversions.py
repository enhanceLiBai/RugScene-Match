"""成功转化登记及客服个人查询记录。"""
import json

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, and_
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.exc import SQLAlchemyError

from backend.auth import public_user
from backend.models import ImageRecord, MatchHistory, MatchHistoryImage, MatchConversion, ProductImage, SceneLabel, UserAccount


class ConversionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    history_id: int = Field(gt=0)
    rank: int = Field(gt=0, le=50)


def conversion_data(row):
    return {'id': row.id, 'history_id': row.history_id, 'rank': row.rank,
            'product_id': row.product_id, 'created_at': row.created_at.isoformat()}


def install_conversions(app, factory):
    def require_admin(request: Request):
        if request.state.user['role'] != 'admin':
            raise HTTPException(403, '仅管理员可查看统计数据。')
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

    @app.get('/api/admin/statistics')
    def admin_statistics(request: Request, period: str = '7d', customer_id: int | None = Query(None, ge=1), start_date: date | None = None, end_date: date | None = None, history_page: int = Query(1, ge=1)):
        require_admin(request)
        periods = {'today': 1, 'week': None, 'month': None, '7d': 7, '30d': 30, 'all': None, 'custom': None}
        if period not in periods:
            raise HTTPException(422, '请选择有效的统计范围。')
        try:
            with factory() as session:
                today = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
                start = None
                end = today + timedelta(days=1)
                if period == 'custom':
                    if start_date is None or end_date is None:
                        raise HTTPException(422, '请选择开始和结束日期。')
                    if start_date > end_date:
                        raise HTTPException(422, '开始日期不能晚于结束日期。')
                    if end_date > today.date():
                        raise HTTPException(422, '不能选择未来日期。')
                    start = datetime.combine(start_date, datetime.min.time(), tzinfo=today.tzinfo)
                    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=today.tzinfo)
                elif period == 'week':
                    start = today - timedelta(days=today.weekday())
                elif period == 'month':
                    start = today.replace(day=1)
                elif periods[period] is not None:
                    start = today - timedelta(days=periods[period] - 1)
                conditions = [MatchHistory.user_id.is_not(None), MatchHistory.created_at < end]
                if customer_id is not None:
                    conditions.append(MatchHistory.user_id == customer_id)
                if start is not None:
                    conditions.append(MatchHistory.created_at >= start)
                histories = list(session.scalars(select(MatchHistory).where(and_(*conditions)).order_by(MatchHistory.created_at)))
                ids = [row.id for row in histories]
                conversions = list(session.scalars(select(MatchConversion).where(MatchConversion.history_id.in_(ids)))) if ids else []
                converted_ids = {row.history_id for row in conversions}
                trend = {}
                for row in histories:
                    key = row.created_at.astimezone(timezone(timedelta(hours=8))).date().isoformat()
                    bucket = trend.setdefault(key, {'date': key, 'matches': 0, 'conversions': 0})
                    bucket['matches'] += 1
                    if row.id in converted_ids:
                        bucket['conversions'] += 1
                customers = list(session.scalars(select(UserAccount).where(UserAccount.role == 'customer_service').order_by(UserAccount.id)))
                ranking = {user.id: {'user': public_user(user), 'total_matches': 0, 'converted_matches': 0, 'conversion_rate': 0} for user in customers}
                for row in histories:
                    if row.user_id in ranking:
                        ranking[row.user_id]['total_matches'] += 1
                        ranking[row.user_id]['converted_matches'] += int(row.id in converted_ids)
                for item in ranking.values():
                    if item['total_matches']:
                        item['conversion_rate'] = round(item['converted_matches'] / item['total_matches'] * 100, 2)
                history_items = []
                if customer_id is not None:
                    selected_user = session.get(UserAccount, customer_id)
                    if selected_user is None or selected_user.role != 'customer_service':
                        raise HTTPException(404, '客服账号不存在。')
                    page_rows = sorted(histories, key=lambda row: (row.created_at, row.id), reverse=True)[(history_page - 1) * 20:history_page * 20]
                    image_ids = set(session.scalars(select(MatchHistoryImage.history_id).where(MatchHistoryImage.history_id.in_([row.id for row in page_rows]))))
                    conversion_map = {row.history_id: conversion_data(row) for row in conversions}
                    history_items = [{'id': row.id, 'created_at': row.created_at.isoformat(),
                                      'result_count': len(json.loads(row.payload_json).get('results', [])),
                                      'query_image_url': f'/api/history/{row.id}/image' if row.id in image_ids else None,
                                      'conversion': conversion_map.get(row.id)} for row in page_rows]
                total = len(histories)
                converted = len(converted_ids)
                return {'period': period, 'customer_id': customer_id, 'total_matches': total,
                        'converted_matches': converted, 'conversion_rate': round(converted / total * 100, 2) if total else 0,
                        'trend': list(trend.values()),
                        'ranking': sorted(ranking.values(), key=lambda item: (-item['total_matches'], item['user']['id'])),
                        'history': {'items': history_items, 'page': history_page, 'page_size': 20, 'total': total if customer_id is not None else 0}}
        except SQLAlchemyError:
            raise HTTPException(503, '统计数据暂不可用，请重试。') from None

    @app.get('/api/admin/product-statistics')
    def product_statistics(request: Request, period: str = '7d', search: str = '',
                           start_date: date | None = None, end_date: date | None = None):
        require_admin(request)
        periods = {'today': 1, 'week': None, 'month': None, '7d': 7, '30d': 30, 'all': None, 'custom': None}
        if period not in periods:
            raise HTTPException(422, '请选择有效的统计范围。')
        try:
            with factory() as session:
                today = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
                start = None
                end = today + timedelta(days=1)
                if period == 'custom':
                    if start_date is None or end_date is None:
                        raise HTTPException(422, '请选择开始和结束日期。')
                    if start_date > end_date:
                        raise HTTPException(422, '开始日期不能晚于结束日期。')
                    if end_date > today.date():
                        raise HTTPException(422, '不能选择未来日期。')
                    start = datetime.combine(start_date, datetime.min.time(), tzinfo=today.tzinfo)
                    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=today.tzinfo)
                elif period == 'week':
                    start = today - timedelta(days=today.weekday())
                elif period == 'month':
                    start = today.replace(day=1)
                elif periods[period] is not None:
                    start = today - timedelta(days=periods[period] - 1)

                conditions = [MatchHistory.created_at < end]
                if start is not None:
                    conditions.append(MatchHistory.created_at >= start)
                histories = list(session.scalars(select(MatchHistory).where(and_(*conditions))))
                history_ids = [row.id for row in histories]
                conversions = list(session.scalars(select(MatchConversion).where(
                    MatchConversion.history_id.in_(history_ids)))) if history_ids else []

                images = {}
                image_rows = session.execute(
                    select(ProductImage.product_id, ImageRecord.id, ImageRecord.product_name, ImageRecord.style)
                    .join(ImageRecord, ImageRecord.id == ProductImage.image_id)
                    .where(ProductImage.image_role == 'buyer_sofa', ProductImage.is_active.is_(True))
                )
                for product_id, image_id, product_name, style in image_rows:
                    images[image_id] = {'image_id': image_id, 'product_id': product_id,
                                        'product_name': product_name or style,
                                        'matched_history_ids': set(), 'converted_matches': 0}

                for history in histories:
                    for result in json.loads(history.payload_json).get('results', []):
                        if not isinstance(result, dict):
                            continue
                        image_id = result.get('buyer_image_id')
                        if image_id is not None and int(image_id) in images:
                            images[int(image_id)]['matched_history_ids'].add(history.id)
                for conversion in conversions:
                    history = next((row for row in histories if row.id == conversion.history_id), None)
                    if history is None:
                        continue
                    result = next((row for row in json.loads(history.payload_json).get('results', [])
                                   if isinstance(row, dict) and row.get('rank') == conversion.rank), None)
                    image_id = result.get('buyer_image_id') if result else None
                    if image_id is not None and int(image_id) in images:
                        images[int(image_id)]['converted_matches'] += 1

                needle = search.strip().casefold()
                items = []
                for item in images.values():
                    if needle and needle not in item['product_id'].casefold() and needle not in (item['product_name'] or '').casefold():
                        continue
                    matches = len(item['matched_history_ids'])
                    converted = item['converted_matches']
                    items.append({'image_id': item['image_id'], 'product_id': item['product_id'],
                                  'product_name': item['product_name'],
                                  'image_url': f"/api/images/{item['image_id']}", 'buyer_images': 1,
                                  'converted_matches': converted, 'conversion_rate': round(converted / matches * 100, 2) if matches else 0})
                    items[-1]['total_matches'] = matches
                items.sort(key=lambda item: (-item['total_matches'], item['image_id']))
                total_matches = sum(item['total_matches'] for item in items)
                converted_matches = sum(item['converted_matches'] for item in items)
                return {'period': period, 'search': search.strip(), 'buyer_images': sum(item['buyer_images'] for item in items),
                        'total_matches': total_matches, 'converted_matches': converted_matches,
                        'conversion_rate': round(converted_matches / total_matches * 100, 2) if total_matches else 0,
                        'items': items}
        except SQLAlchemyError:
            raise HTTPException(503, '商品统计暂不可用，请重试。') from None

    @app.get('/api/admin/product-category-statistics')
    def product_category_statistics(request: Request, category: str = 'sofa_color', value: str = '', product_id: str = '', product_query: str = '', period: str = '7d',
                                    start_date: date | None = None, end_date: date | None = None):
        require_admin(request)
        if category not in {'sofa_color', 'floor_color', 'floor_type'}:
            raise HTTPException(422, '请选择有效的分类。')
        if period not in {'today', 'week', 'month', '7d', '30d', 'all', 'custom'}:
            raise HTTPException(422, '请选择有效的统计范围。')
        try:
            with factory() as session:
                today = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
                end = today + timedelta(days=1); start = None
                if period == 'custom':
                    if start_date is None or end_date is None or start_date > end_date or end_date > today.date():
                        raise HTTPException(422, '自定义日期范围无效。')
                    start = datetime.combine(start_date, datetime.min.time(), tzinfo=today.tzinfo)
                    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=today.tzinfo)
                elif period == 'week': start = today - timedelta(days=today.weekday())
                elif period == 'month': start = today.replace(day=1)
                elif period != 'all': start = today - timedelta(days={'today': 1, '7d': 7, '30d': 30}[period] - 1)
                images = list(session.execute(select(ProductImage, ImageRecord, SceneLabel).join(ImageRecord, ImageRecord.id == ProductImage.image_id).outerjoin(SceneLabel, SceneLabel.image_id == ImageRecord.id).where(ProductImage.image_role == 'buyer_sofa', ProductImage.is_active.is_(True))))
                selected = []
                for link, image, label in images:
                    tags = json.loads(label.labels_json) if label and label.labels_json else {}
                    label_value = tags.get(category)
                    if product_id and str(link.product_id) != product_id: continue
                    if product_query and product_query.casefold() not in str(link.product_id).casefold() and product_query.casefold() not in (image.product_name or image.style or '').casefold(): continue
                    if value and label_value != value: continue
                    selected.append((link.product_id, image, label_value or '未识别'))
                histories = list(session.scalars(select(MatchHistory).where(and_(MatchHistory.created_at < end, *( [MatchHistory.created_at >= start] if start else [])))))
                counts = {}; converted = {}
                for history in histories:
                    for result in json.loads(history.payload_json).get('results', []):
                        image_id = result.get('buyer_image_id')
                        if image_id is not None: counts[int(image_id)] = counts.get(int(image_id), 0) + 1
                for row in session.scalars(select(MatchConversion).where(MatchConversion.history_id.in_([h.id for h in histories])) if histories else select(MatchConversion).where(False)):
                    history = next((h for h in histories if h.id == row.history_id), None)
                    result = next((r for r in json.loads(history.payload_json).get('results', []) if isinstance(r, dict) and r.get('rank') == row.rank), None) if history else None
                    image_id = result.get('buyer_image_id') if result else None
                    if image_id is not None: converted[int(image_id)] = converted.get(int(image_id), 0) + 1
                items = [{'product_id': pid, 'image_id': image.id, 'image_url': f'/api/images/{image.id}', 'category_value': val,
                          'product_name': image.product_name or image.style, 'total_matches': counts.get(image.id, 0),
                          'converted_matches': converted.get(image.id, 0), 'conversion_rate': round(converted.get(image.id, 0) / counts.get(image.id, 1) * 100, 2) if counts.get(image.id) else 0}
                         for pid, image, val in selected]
                items.sort(key=lambda x: (-x['total_matches'], x['product_id'], x['image_id']))
                groups = {}
                for item in items:
                    group = groups.setdefault(item['category_value'], {'category_value': item['category_value'], 'buyer_images': 0, 'total_matches': 0, 'converted_matches': 0})
                    group['buyer_images'] += 1
                    group['total_matches'] += item['total_matches']
                    group['converted_matches'] += item['converted_matches']
                for group in groups.values():
                    group['conversion_rate'] = round(group['converted_matches'] / group['total_matches'] * 100, 2) if group['total_matches'] else 0
                return {'category': category, 'value': value, 'product_id': product_id, 'product_query': product_query, 'period': period,
                        'values': sorted(groups), 'groups': sorted(groups.values(), key=lambda x: (-x['total_matches'], x['category_value'])), 'items': items,
                        'buyer_images': len(items), 'total_matches': sum(x['total_matches'] for x in items), 'converted_matches': sum(x['converted_matches'] for x in items)}
        except SQLAlchemyError:
            raise HTTPException(503, '分类统计暂不可用，请重试。') from None
