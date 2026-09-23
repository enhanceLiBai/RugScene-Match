import React, { useEffect, useRef, useState } from 'react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import zhCN from 'antd/locale/zh_CN';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, Layout, Menu, Card, Table, Button, Image, Drawer, Empty, Space, message, Select, DatePicker, Modal, Tag, Form, Input } from 'antd';
import 'antd/dist/reset.css';
import './style.css';
import StatisticsOverview from './StatisticsOverview';
import CustomerRanking from './CustomerRanking';
import ProductStatistics from './ProductStatistics';
import ProductCategoryStatistics from './ProductCategoryStatistics';

dayjs.locale('zh-cn');

const { Sider, Header, Content } = Layout;
async function api(url, options) { const response = await fetch(url, { credentials: 'same-origin', ...options }); const data = await response.json().catch(() => { throw Error(`服务器返回异常（${response.status}），请重试`); }); if (!response.ok) throw Error(data.detail || '请求失败'); return data; }

function App() {
  const [tab, setTab] = useState('stats'); const [period, setPeriod] = useState('7d'); const [customDates, setCustomDates] = useState(null); const [stats, setStats] = useState(null); const [exceptions, setExceptions] = useState([]); const [exceptionStatus, setExceptionStatus] = useState('open'); const [detail, setDetail] = useState(null); const [loading, setLoading] = useState(false);
  const [exceptionCustomer, setExceptionCustomer] = useState(null); const [exceptionDates, setExceptionDates] = useState(null); const [customerOptions, setCustomerOptions] = useState([]);
  const [library, setLibrary] = useState([]); const [libraryLoading, setLibraryLoading] = useState(false); const [librarySearch, setLibrarySearch] = useState('');
  const [statsLoading, setStatsLoading] = useState(false);
  const [accounts, setAccounts] = useState([]); const [accountsLoading, setAccountsLoading] = useState(false);
  const statsRequest = useRef(0);
  const loadStats = async (selected, dates) => {
    const request = ++statsRequest.current;
    setStats(null);
    setStatsLoading(false);
    if (selected === 'custom' && dates?.length !== 2) return;
    const params = new URLSearchParams({ period: selected });
    if (selected === 'custom') {
      params.set('start_date', dates[0].format('YYYY-MM-DD'));
      params.set('end_date', dates[1].format('YYYY-MM-DD'));
    }
    setStatsLoading(true);
    try {
      const data = await api(`/api/admin/statistics?${params}`);
      if (request === statsRequest.current) setStats(data);
    } catch (e) {
      if (request === statsRequest.current) message.error(e.message);
    } finally {
      if (request === statsRequest.current) setStatsLoading(false);
    }
  };
  const loadExceptions = () => {
    const params = new URLSearchParams({ status: exceptionStatus });
    if (exceptionCustomer) params.set('customer_id', exceptionCustomer);
    if (exceptionDates?.length === 2) {
      params.set('start_date', exceptionDates[0].format('YYYY-MM-DD'));
      params.set('end_date', exceptionDates[1].format('YYYY-MM-DD'));
    }
    setLoading(true);
    api(`/api/admin/exceptions?${params}`).then(d => setExceptions(d.items)).catch(e => message.error(e.message)).finally(() => setLoading(false));
  };
  useEffect(() => { loadStats(period, customDates); }, [period, customDates]);
  useEffect(() => { loadExceptions(); }, [exceptionStatus, exceptionCustomer, exceptionDates]);
  useEffect(() => { api('/api/accounts').then(d => setCustomerOptions((d.items || []).filter(user => user.role === 'customer_service').map(user => ({ value: user.id, label: user.display_name || user.username })))).catch(e => message.error(e.message)); }, []);
  const loadAccounts = () => { setAccountsLoading(true); api('/api/accounts').then(d => setAccounts(d.items || [])).catch(e => message.error(e.message)).finally(() => setAccountsLoading(false)); };
  useEffect(() => { if (tab === 'accounts') loadAccounts(); }, [tab]);
  const createAccount = async values => { try { await api('/api/accounts', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values) }); message.success('客服账号已开通'); loadAccounts(); } catch (e) { message.error(e.message); } };
  useEffect(() => { if (tab !== 'library') return; setLibraryLoading(true); api('/api/library').then(d => setLibrary(d.images || [])).catch(e => message.error(e.message)).finally(() => setLibraryLoading(false)); }, [tab]);
  const removeLibraryImage = image => { const references = image.history_reference_count || 0; Modal.confirm({ title: '确认删除这张买家秀？', content: references ? `这张图片被 ${references} 条历史匹配记录引用。删除后历史结果快照仍会保留，图库中的图片和关联向量会被删除。` : '该图片没有历史匹配引用。图库中的图片和关联向量会被删除。', okText: '删除', okType: 'danger', cancelText: '取消', onOk: async () => { try { await api('/api/library/' + image.id, {method:'DELETE'}); message.success('已删除'); setLibrary(items => items.filter(x => x.id !== image.id)); } catch (e) { message.error(e.message); } } }); };
  const changePeriod = setPeriod;
  const changeCustomDates = setCustomDates;
  const resolve = async id => { await api(`/api/admin/exceptions/${id}/resolve`, { method: 'POST' }); message.success('已标记处理'); loadExceptions(); };
  const openException = id => api(`/api/admin/exceptions/${id}`).then(setDetail).catch(e => message.error(e.message));
  const columns = [{ title: '查询时间', dataIndex: 'created_at', render: v => new Date(v).toLocaleString() }, { title: '客服', dataIndex: ['user', 'display_name'], render: v => v || '未知客服' }, { title: '客户图片', dataIndex: 'query_image_url', render: v => v ? '已保存（点击查看详情）' : '未保存' }, { title: '场景标签', dataIndex: 'query_scene', render: v => v ? Object.values(v).filter(Boolean).join(' / ') : '未识别' }, { title: '操作', render: (_, row) => <Space><Button size="small" onClick={() => openException(row.id)}>查看</Button>{row.status === 'open' && <Button size="small" type="primary" onClick={() => resolve(row.id)}>标记处理</Button>}</Space> }];
  return <Layout><Sider><div className="brand">买家秀后台</div><Menu mode="inline" theme="dark" selectedKeys={[tab]} defaultOpenKeys={["library-group", "products-group"]} onClick={e => setTab(e.key)} items={[{ key: 'stats', label: '客服数据' }, { key: 'exceptions', label: '异常待处理' }, { key: 'library-group', label: '买家秀库', children: [{ key: 'library', label: '总图库' }, { key: 'products-group', label: '商品数据', children: [{ key: 'products', label: '商品统计明细' }, { key: 'product-categories', label: '商品分类筛选' }] }] }, { key: 'accounts', label: '客服子账户' }]} /></Sider><Layout><Header className="header">管理后台</Header><Content className="content">{tab === 'stats' && <><Card title="统计范围" className="filter-card"><Space><Select value={period} onChange={changePeriod} options={[{ value: 'today', label: '今日' }, { value: 'week', label: '本周' }, { value: 'month', label: '本月' }, { value: '7d', label: '近 7 天' }, { value: '30d', label: '近 30 天' }, { value: 'all', label: '全部' }, { value: 'custom', label: '自定义' }]} /><DatePicker.RangePicker value={customDates} disabledDate={date => date.isAfter(dayjs(), 'day')} disabled={period !== 'custom'} onChange={changeCustomDates} placeholder={['开始日期', '结束日期']} /></Space></Card><StatisticsOverview stats={stats} loading={statsLoading} period={period} dates={customDates} api={api} /><CustomerRanking stats={stats} loading={statsLoading} period={period} dates={customDates} api={api} /></>}{tab === 'products' && <ProductStatistics api={api} />}{tab === 'product-categories' && <ProductCategoryStatistics api={api} />}{tab === 'exceptions' && <Card title="异常待处理" extra={<Button onClick={loadExceptions}>刷新</Button>}><Space wrap className="exception-filters"><Select value={exceptionStatus} onChange={setExceptionStatus} options={[{value:"open",label:"待处理"},{value:"resolved",label:"已处理"},{value:"all",label:"全部"}]} /><Select allowClear placeholder="全部客服" value={exceptionCustomer} onChange={setExceptionCustomer} options={customerOptions} style={{minWidth:160}} /><DatePicker.RangePicker value={exceptionDates} onChange={setExceptionDates} disabledDate={date => date.isAfter(dayjs(), 'day')} placeholder={['开始日期', '结束日期']} /></Space><Table rowKey="id" loading={loading} dataSource={exceptions} columns={columns} locale={{ emptyText: <Empty description="暂无符合条件的异常" /> }} /></Card>}{tab === 'library' && <Card title="买家秀库" extra={<Space><input className="library-search" placeholder="搜索商品或 SKU" value={librarySearch} onChange={e => setLibrarySearch(e.target.value)} /><Button onClick={() => setLibrarySearch('')}>清除</Button></Space>}><Table loading={libraryLoading} rowKey="id" dataSource={library.filter(x => !librarySearch || [x.product_id,x.sku,x.product_name].some(v => (v || '').toLowerCase().includes(librarySearch.toLowerCase())))} pagination={{pageSize:12,showSizeChanger:false}} columns={[{title:'图片',dataIndex:'image_url',render:v=><Image width={72} height={72} style={{objectFit:'cover'}} src={`${v}?preview=1`} preview={{src:v}} />},{title:'商品 ID / 名称',render:(_,r)=><>{r.product_id || r.sku || '未填写'}<br/>{r.product_name || '未填写'}</>},{title:'SKU',dataIndex:'sku',render:v=>v || '—'},{title:'尺寸',dataIndex:'size',render:v=>v || '—'},{title:'颜色',dataIndex:'color',render:v=>v || '—'},{title:'历史引用',dataIndex:'history_reference_count',render:v=>v ? <Tag color="blue">{v} 次</Tag> : '无'},{title:'操作',render:(_,r)=><Button danger onClick={()=>removeLibraryImage(r)}>删除</Button>},{title:'上传时间',dataIndex:'created_at',render:v=>v ? new Date(v).toLocaleString('zh-CN') : '—'}]} locale={{emptyText:'暂无买家秀图片'}} /></Card>}{tab === 'accounts' && <><Card title="新增客服账号" className="filter-card"><Form layout="inline" onFinish={createAccount}><Form.Item name="username" label="登录账号" rules={[{required:true,message:"请输入登录账号"}]}><Input placeholder="请输入账号" /></Form.Item><Form.Item name="display_name" label="客服姓名" rules={[{required:true,message:"请输入客服姓名"}]}><Input placeholder="请输入姓名" /></Form.Item><Form.Item name="password" label="初始密码" rules={[{required:true,min:6,message:"密码至少 6 个字符"}]}><Input.Password placeholder="至少 6 个字符" /></Form.Item><Button type="primary" htmlType="submit">开通账号</Button></Form></Card><Card title="账号列表" extra={<Button onClick={loadAccounts}>刷新</Button>}><Table rowKey="id" loading={accountsLoading} dataSource={accounts} pagination={false} locale={{emptyText:"暂无账号"}} columns={[{title:"账号",dataIndex:"username"},{title:"姓名",dataIndex:"display_name"},{title:"角色",dataIndex:"role",render:v=>v === "admin" ? <Tag color="blue">管理员</Tag> : <Tag>客服</Tag>},{title:"状态",render:()=> <Tag color="green">正常</Tag>}]} /></Card></>}<Drawer title="异常匹配详情" open={!!detail} onClose={() => setDetail(null)} width={560}>{detail && <>{detail.query_image_url ? <Image width="100%" src={detail.query_image_url} /> : <Empty description="该历史记录未保存客户图片" />}<p>客服：{detail.user?.display_name || '未知客服'}</p><p>查询时间：{new Date(detail.created_at).toLocaleString()}</p><p>状态：{detail.status === 'resolved' ? '已处理' : '待处理'}</p><p>提示：{detail.payload?.message || '无'}</p><p>场景标签：{Object.values(detail.payload?.query_scene || {}).filter(Boolean).join(' / ') || '未识别'}</p></>}</Drawer></Content></Layout></Layout>;
}
createRoot(document.getElementById('root')).render(<ConfigProvider locale={zhCN}><App /></ConfigProvider>);




