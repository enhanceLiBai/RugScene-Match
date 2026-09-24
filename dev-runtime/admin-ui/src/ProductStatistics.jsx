import React, { useEffect, useRef, useState } from 'react';
import dayjs from 'dayjs';
import { Button, Card, Col, DatePicker, Empty, Image, Input, Modal, Row, Select, Space, Statistic, Table, Typography, message } from 'antd';

export default function ProductStatistics({ api }) {
  const [period, setPeriod] = useState('7d');
  const [dates, setDates] = useState(null);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const requestId = useRef(0);

  useEffect(() => {
    if (period === 'custom' && dates?.length !== 2) { setData(null); return; }
    const current = ++requestId.current;
    const params = new URLSearchParams({ period });
    if (search) params.set('search', search);
    if (period === 'custom') {
      params.set('start_date', dates[0].format('YYYY-MM-DD'));
      params.set('end_date', dates[1].format('YYYY-MM-DD'));
    }
    setLoading(true);
    api(`/api/admin/product-statistics?${params}`).then(result => {
      if (current === requestId.current) setData(result);
    }).catch(error => { if (current === requestId.current) message.error(error.message); })
      .finally(() => { if (current === requestId.current) setLoading(false); });
  }, [period, dates, search]);

  const submitSearch = () => setSearch(searchInput.trim());
  const removeImage = image => Modal.confirm({ title: '确认删除这张图片？', content: '删除后图片及其关联向量会从图库移除，历史匹配记录仍会保留。', okText: '删除', okType: 'danger', cancelText: '取消', onOk: async () => {
    setDeleting(image.image_id);
    try { await api(`/api/library/${image.image_id}`, { method: 'DELETE' }); setData(current => current && { ...current, items: current.items.filter(item => item.image_id !== image.image_id) }); message.success('图片已删除'); }
    catch (error) { message.error(error.message); }
    finally { setDeleting(null); }
  }});
  return <>
    <Card title="商品数据筛选" className="filter-card">
      <Space wrap>
        <Input.Search value={searchInput} onChange={event => setSearchInput(event.target.value)} onSearch={submitSearch} enterButton="搜索" allowClear placeholder="商品 ID 或商品名称" style={{ width: 280 }} />
        <Select value={period} onChange={setPeriod} options={[{ value: 'today', label: '今日' }, { value: 'week', label: '本周' }, { value: 'month', label: '本月' }, { value: '7d', label: '近 7 天' }, { value: '30d', label: '近 30 天' }, { value: 'all', label: '全部' }, { value: 'custom', label: '自定义' }]} />
        <DatePicker.RangePicker value={dates} disabled={period !== 'custom'} disabledDate={date => date.isAfter(dayjs(), 'day')} onChange={setDates} placeholder={['开始日期', '结束日期']} />
        {search && <Button onClick={() => { setSearchInput(''); setSearch(''); }}>清除搜索</Button>}
      </Space>
    </Card>
    <Row gutter={[16, 16]}>
      {[['买家秀数量', data?.buyer_images], ['匹配成功次数', data?.total_matches], ['成交次数', data?.converted_matches], ['转化率', data?.conversion_rate]].map(([title, value]) => <Col xs={24} sm={12} xl={6} key={title}><Card loading={loading}><Statistic title={title} value={value ?? '—'} precision={title === '转化率' && data ? 2 : 0} suffix={title === '转化率' && data ? '%' : undefined} /></Card></Col>)}
    </Row>
    <Card title="商品统计明细" className="trend">
      <Typography.Paragraph type="secondary">每张买家秀独立统计，并按匹配成功次数从高到低排列；匹配和成交按原匹配日期统计。</Typography.Paragraph>
      <Table rowKey="image_id" loading={loading} dataSource={data?.items || []} pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }} locale={{ emptyText: <Empty description={period === 'custom' && !dates ? '请选择开始和结束日期' : '暂无符合条件的商品数据'} /> }} columns={[
        { title: '买家秀', dataIndex: 'image_url', render: value => value ? <Image width={64} height={64} style={{ objectFit: 'cover' }} src={`${value}?preview=1`} preview={{ src: value }} /> : '—' },
        { title: '商品 ID', dataIndex: 'product_id' },
        { title: '商品名称', dataIndex: 'product_name', render: value => value || '未填写' },
        { title: '匹配成功次数', dataIndex: 'total_matches' },
        { title: '成交次数', dataIndex: 'converted_matches' },
        { title: '转化率', dataIndex: 'conversion_rate', render: value => `${value.toFixed(2)}%` },
        { title: '操作', render: (_, image) => <Button danger size="small" loading={deleting === image.image_id} onClick={() => removeImage(image)}>删除</Button> },
      ]} />
    </Card>
  </>;
}
