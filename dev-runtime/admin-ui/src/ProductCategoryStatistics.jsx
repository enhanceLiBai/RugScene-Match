import React, { useEffect, useState } from 'react';
import { Button, Card, Col, Empty, Image, Input, Modal, Row, Select, Statistic, Table, Tag, message } from 'antd';

const COLORS = ['黑色','炭黑色','白色','奶白色','象牙白','米色','米白色','浅灰色','中灰色','深灰色','棕色','咖啡色','红色','橙色','黄色','绿色','蓝色','紫色','粉色','无法判断'];

export default function ProductCategoryStatistics({ api }) {
  const [category, setCategory] = useState('sofa_color');
  const [value, setValue] = useState('');
  const [productInput, setProductInput] = useState('');
  const [productId, setProductId] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(null);
  useEffect(() => {
    if (!productId) { setData(null); return; }
    setLoading(true);
    const params = new URLSearchParams({ category, product_query: productId, value });
    api(`/api/admin/product-category-statistics?${params}`).then(setData).catch(error => message.error(error.message)).finally(() => setLoading(false));
  }, [api, category, value, productId]);
  const removeImage = image => Modal.confirm({ title: '确认删除这张图片？', content: '删除后图片及其关联向量会从图库移除，历史匹配记录仍会保留。', okText: '删除', okType: 'danger', cancelText: '取消', onOk: async () => {
    setDeleting(image.image_id);
    try { await api(`/api/library/${image.image_id}`, { method: 'DELETE' }); setData(current => current && { ...current, items: current.items.filter(item => item.image_id !== image.image_id) }); message.success('图片已删除'); }
    catch (error) { message.error(error.message); }
    finally { setDeleting(null); }
  }});
  return <>
    <Card title="单品分类数据" className="filter-card"><Input.Search value={productInput} onChange={event => setProductInput(event.target.value)} onSearch={() => setProductId(productInput.trim())} enterButton="查看" allowClear placeholder="输入商品 ID 或商品名称" style={{ width: 300, marginRight: 12 }} /><Select value={category} onChange={next => { setCategory(next); setValue(''); }} options={[{value:'sofa_color',label:'沙发颜色'},{value:'floor_color',label:'地板颜色'}]} /><Select allowClear value={value || undefined} onChange={next => setValue(next || '')} placeholder="全部分类" options={COLORS.map(item => ({value:item,label:item}))} style={{width:140,marginLeft:8}} /></Card>
    {!productId ? <Card><Empty description="请输入商品 ID 或商品名称查看单品分类数据" /></Card> : <><Row gutter={[16, 16]}>{[['图片数量', data?.buyer_images], ['匹配成功次数', data?.total_matches], ['转化率', data ? (data.total_matches ? data.converted_matches / data.total_matches * 100 : 0) : undefined]].map(([title, number]) => <Col xs={24} sm={8} key={title}><Card loading={loading}><Statistic title={title} value={number ?? '—'} precision={title === '转化率' ? 2 : 0} suffix={title === '转化率' && data ? '%' : undefined} /></Card></Col>)}</Row><Card title="分类汇总" className="trend" loading={loading}><Table rowKey="category_value" pagination={false} dataSource={data?.groups || []} locale={{emptyText:<Empty description="暂无分类数据" />}} columns={[{title:'分类',dataIndex:'category_value',render:value=><Tag>{value}</Tag>},{title:'图片数量',dataIndex:'buyer_images'},{title:'匹配成功次数',dataIndex:'total_matches'},{title:'转化率',dataIndex:'conversion_rate',render:value=>`${value.toFixed(2)}%`}]}/></Card><Card title="组内买家秀排行" className="trend" loading={loading}><Table rowKey="image_id" dataSource={data?.items || []} pagination={{pageSize:20,showSizeChanger:false}} locale={{emptyText:<Empty description="暂无买家秀" />}} columns={[{title:'图片',dataIndex:'image_url',render:value=><Image width={64} height={64} style={{objectFit:'cover'}} src={`${value}?preview=1`} preview={{src:value}}/>},{title:'分类',dataIndex:'category_value',render:value=><Tag>{value}</Tag>},{title:'匹配成功次数',dataIndex:'total_matches'},{title:'成交次数',dataIndex:'converted_matches'},{title:'转化率',dataIndex:'conversion_rate',render:value=>`${value.toFixed(2)}%`},{title:'操作',render:(_, image)=><Button danger size="small" loading={deleting === image.image_id} onClick={() => removeImage(image)}>删除</Button>}]}/></Card></>}
  </>;
}
