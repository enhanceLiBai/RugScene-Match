import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, Drawer, Empty, Image, Select, Space, Table, Tag, Typography } from 'antd';
import StatisticsOverview from './StatisticsOverview';

export default function CustomerRanking({ stats, loading, period, dates, api }) {
  const [customer, setCustomer] = useState(null);
  const [page, setPage] = useState(1);
  const [personal, setPersonal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [historyId, setHistoryId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState('');
  const [sort, setSort] = useState('total_matches');
  useEffect(() => {
    let active = true;
    setPersonal(null); setError('');
    if (!customer) return;
    const params = new URLSearchParams({ period, customer_id: customer.id, history_page: page });
    if (period === 'custom') {
      if (dates?.length !== 2) return;
      params.set('start_date', dates[0].format('YYYY-MM-DD'));
      params.set('end_date', dates[1].format('YYYY-MM-DD'));
    }
    setBusy(true);
    api(`/api/admin/statistics?${params}`).then(data => { if (active) setPersonal(data); })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [customer, page, period, dates]);
  useEffect(() => {
    let active = true;
    setDetail(null); setDetailError('');
    if (!historyId) return;
    api(`/api/history/${historyId}`).then(data => { if (active) setDetail(data); })
      .catch(e => { if (active) setDetailError(e.message); });
    return () => { active = false; };
  }, [historyId]);
  const ranking = [...(stats?.ranking || [])].sort((a, b) => b[sort] - a[sort] || a.user.id - b.user.id);
  const selectCustomer = user => { setPage(1); setPersonal(null); setCustomer(user); setHistoryId(null); };
  return <>
    <Card title="客服排行" className="trend" extra={<Select aria-label="排行排序" value={sort} onChange={setSort} options={[{ value: 'total_matches', label: '按匹配次数排序' }, { value: 'converted_matches', label: '按成交次数排序' }]} />}>
      <Typography.Paragraph type="secondary">按上方日期范围统计客服账号，包含暂无匹配记录的客服。</Typography.Paragraph>
      <Table rowKey={row => row.user.id} loading={loading} dataSource={ranking} pagination={false} locale={{ emptyText: stats ? '暂无客服账号' : '请选择有效的统计范围' }} columns={[
        { title: '排名', render: (_, row, index) => index + 1 },
        { title: '客服', render: (_, row) => <>{row.user.display_name}<Typography.Text type="secondary">（{row.user.username}）</Typography.Text></> },
        { title: '匹配次数', dataIndex: 'total_matches' }, { title: '成交次数', dataIndex: 'converted_matches' },
        { title: '转化率', dataIndex: 'conversion_rate', render: v => `${v.toFixed(2)}%` },
        { title: '操作', render: (_, row) => <Button onClick={() => selectCustomer(row.user)}>查看详情</Button> },
      ]} />
    </Card>
    <Drawer title={`客服详情 · ${customer?.display_name || ''}`} open={!!customer} onClose={() => { setCustomer(null); setHistoryId(null); }} width="min(1100px, 95vw)">
      <Space className="filter-card" wrap><span>切换客服</span><Select style={{ minWidth: 200 }} value={customer?.id} onChange={id => selectCustomer(ranking.find(row => row.user.id === id).user)} options={ranking.map(row => ({ value: row.user.id, label: `${row.user.display_name}（${row.user.username}）` }))} /><Typography.Text type="secondary">沿用主页面所选日期范围</Typography.Text></Space>
      {error && <Alert type="error" showIcon message={error} />}
      <StatisticsOverview stats={personal} loading={busy} period={period} dates={dates} />
      <Card title="匹配历史" className="trend"><Table rowKey="id" loading={busy} dataSource={personal?.history.items || []} pagination={{ current: page, pageSize: 20, total: personal?.history.total || 0, showSizeChanger: false, onChange: setPage, hideOnSinglePage: true }} locale={{ emptyText: '所选范围暂无匹配历史' }} columns={[
        { title: '匹配时间', dataIndex: 'created_at', render: v => new Date(v).toLocaleString('zh-CN') },
        { title: '客户图片', dataIndex: 'query_image_url', render: v => v ? <Image width={48} height={48} style={{ objectFit: 'cover' }} src={v} /> : '未保存' },
        { title: '结果数', dataIndex: 'result_count' },
        { title: '成交状态', dataIndex: 'conversion', render: v => v ? <Tag color="green">已成交 · Top {v.rank}</Tag> : '未登记' },
        { title: '操作', render: (_, row) => <Button onClick={() => setHistoryId(row.id)}>查看匹配结果</Button> },
      ]} /></Card>
    </Drawer>
    <Drawer title="历史匹配详情" open={!!historyId} onClose={() => setHistoryId(null)} width="min(760px, 95vw)" loading={!detail && !detailError}>
      {detailError && <Alert type="error" message={detailError} />}
      {detail && <>
        <Typography.Paragraph>{detail.user?.display_name || '未知客服'} · {new Date(detail.created_at).toLocaleString('zh-CN')}</Typography.Paragraph>
        {detail.query_image_url ? <Image width={200} src={detail.query_image_url} /> : <Empty description="该历史未保存客户照片" />}
        <Typography.Paragraph>场景标签：{[['room', '空间'], ['sofa_color', '沙发颜色'], ['floor_color', '地板颜色'], ['floor_material', '地板材质']].filter(([key]) => detail.payload.query_scene?.[key]).map(([key, label]) => `${label}：${detail.payload.query_scene[key]}`).join(' / ') || '未识别'}</Typography.Paragraph>
        {!detail.payload.results?.length && detail.payload.message && <Typography.Paragraph>{detail.payload.message}</Typography.Paragraph>}
        <Table rowKey="rank" dataSource={detail.payload.results || []} pagination={false} locale={{ emptyText: '本次匹配没有结果' }} columns={[
          { title: '排名', dataIndex: 'rank', render: v => `Top ${v}` },
          { title: '匹配图片', dataIndex: 'matched_buyer_image_url', render: v => v ? <Image width={80} src={v} /> : '暂无图片' },
          { title: '商品', render: (_, row) => row.product_name || row.product_id || '未填写' },
          { title: '相似度', dataIndex: 'similarity', render: v => v == null ? '—' : `${v}%` },
        ]} />
      </>}
    </Drawer>
  </>;
}
