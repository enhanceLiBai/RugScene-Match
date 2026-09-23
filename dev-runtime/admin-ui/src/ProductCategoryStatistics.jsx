import React, { useEffect, useState } from 'react';
import { Card, Empty, Select, Table, Tag } from 'antd';

const COLORS = ['黑色','炭黑色','白色','奶白色','象牙白','暖白色','冷白色','米色','米白色','米黄色','奶油色','浅灰色','中灰色','深灰色','银灰色','暖灰色','冷灰色','棕色','浅棕色','深棕色','咖啡色','浅咖色','奶咖色','灰棕色','驼色','卡其色','巧克力色','浅木色','深木色','胡桃木色','红色','酒红色','砖红色','枣红色','橙色','橘色','铁锈橙','黄色','浅黄色','姜黄色','芥末黄','金黄色','绿色','浅绿色','深绿色','灰绿色','橄榄绿','墨绿色','鼠尾草绿','蓝色','浅蓝色','深蓝色','灰蓝色','藏蓝色','孔雀蓝','紫色','浅紫色','灰紫色','深紫色','粉色','浅粉色','藕粉色','灰粉色','豆沙粉','无法判断'];

export default function ProductCategoryStatistics({ api }) {
  const [category, setCategory] = useState('sofa_color');
  const [value, setValue] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => { setLoading(true); api(`/api/admin/product-category-statistics?category=${category}&value=${encodeURIComponent(value)}`)
    .then(setData).finally(() => setLoading(false)); }, [category, value]);
  return <Card title="商品分类筛选" className="trend" extra={<><Select value={category} onChange={v => { setCategory(v); setValue(''); }} options={[{value:'sofa_color',label:'沙发颜色'},{value:'floor_color',label:'地板颜色'}]} /> <Select allowClear value={value || undefined} onChange={v => setValue(v || '')} placeholder="全部颜色" options={COLORS.map(v => ({value:v,label:v}))} style={{width:140,marginLeft:8}} /></>}>
    <Table rowKey="image_id" loading={loading} dataSource={data?.items || []} pagination={{pageSize:20,showSizeChanger:false}} locale={{emptyText:<Empty description="暂无符合条件的分类图片" />}} columns={[
      {title:'图片',dataIndex:'image_url',render:v=><img src={v} style={{width:64,height:64,objectFit:'cover'}} />}, {title:'分类',dataIndex:'category_value',render:v=><Tag>{v}</Tag>}, {title:'商品',render:(_,r)=>r.product_name || r.product_id},
      {title:'匹配成功次数',dataIndex:'total_matches'}, {title:'成交次数',dataIndex:'converted_matches'}, {title:'转化率',dataIndex:'conversion_rate',render:v=>`${v.toFixed(2)}%`}
    ]} />
  </Card>;
}
