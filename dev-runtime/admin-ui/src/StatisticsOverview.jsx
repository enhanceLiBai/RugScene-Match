import React from 'react';
import dayjs from 'dayjs';
import { Card, Col, Empty, Row, Skeleton, Statistic, Table, Typography } from 'antd';

export function trendDays(stats, period, dates) {
  if (!stats || (period === 'custom' && dates?.length !== 2)) return [];
  const end = period === 'custom' ? dates[1] : dayjs();
  const starts = {
    today: end, week: end.startOf('week'), month: end.startOf('month'),
    '7d': end.subtract(6, 'day'), '30d': end.subtract(29, 'day'),
    custom: dates?.[0], all: stats.trend.length ? dayjs(stats.trend[0].date) : end,
  };
  const rows = new Map(stats.trend.map(row => [row.date, row]));
  const result = [];
  for (let day = starts[period].startOf('day'); !day.isAfter(end, 'day'); day = day.add(1, 'day')) {
    const date = day.format('YYYY-MM-DD');
    result.push(rows.get(date) || { date, matches: 0, conversions: 0 });
  }
  return result;
}

function TrendChart({ rows }) {
  const width = 900, height = 300, left = 48, right = 24, top = 24, bottom = 48;
  const maximum = Math.max(4, ...rows.map(row => row.matches));
  const step = Math.ceil(maximum / 4), ceiling = step * 4;
  const x = i => rows.length === 1 ? width / 2 : left + i * (width - left - right) / (rows.length - 1);
  const y = value => height - bottom - value / ceiling * (height - top - bottom);
  const ticks = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
  return <>
    <div className="chart-legend"><span><i style={{ background: '#1677ff' }} />匹配次数</span><span><i style={{ background: '#389e0d' }} />成交次数</span></div>
    <svg className="trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="所选日期范围每日匹配次数和成交次数趋势图">
      {[0, 1, 2, 3, 4].map(n => <g key={n}><line x1={left} x2={width - right} y1={y(n * step)} y2={y(n * step)} stroke="#e8edf3" /><text x={left - 10} y={y(n * step) + 4} textAnchor="end">{n * step}</text></g>)}
      {ticks.map(i => <text key={i} x={x(i)} y={height - 16} textAnchor={rows.length === 1 ? 'middle' : i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'}>{rows[i].date}</text>)}
      {[['matches', '#1677ff', '匹配'], ['conversions', '#389e0d', '成交']].map(([key, color, label]) => <g key={key}>
        <polyline points={rows.map((row, i) => `${x(i)},${y(row[key])}`).join(' ')} fill="none" stroke={color} strokeWidth="3" strokeDasharray={key === 'conversions' ? '6 3' : undefined} />
        {rows.map((row, i) => <circle key={row.date} cx={x(i)} cy={y(row[key])} r={rows.length > 60 ? 2 : 4} fill={color}><title>{row.date}：{label} {row[key]} 次</title></circle>)}
      </g>)}
    </svg>
  </>;
}

export default function StatisticsOverview({ stats, loading, period, dates }) {
  const rows = trendDays(stats, period, dates);
  const emptyText = period === 'custom' && !dates ? '请选择开始和结束日期' : '暂无统计数据';
  return <>
    <Row gutter={[16, 16]}>
      {[
        ['匹配次数', stats?.total_matches, '所选范围内发起的匹配查询'],
        ['成交次数', stats?.converted_matches, '上述查询中已登记成交的次数'],
        ['转化率', stats?.conversion_rate, '成交次数 ÷ 匹配次数 × 100%'],
      ].map(([title, value, hint]) => <Col xs={24} md={8} key={title}><Card loading={loading} className="overview-card"><Statistic title={title} value={value ?? '—'} precision={title === '转化率' && stats ? 2 : 0} suffix={title === '转化率' && stats ? '%' : undefined} /><Typography.Text type="secondary">{hint}</Typography.Text></Card></Col>)}
    </Row>
    <Card title="匹配与成交趋势" className="trend">
      <Typography.Paragraph type="secondary">按匹配日期统计，成交归属到原匹配日期；无查询的日期记为 0。</Typography.Paragraph>
      {loading ? <Skeleton active /> : !stats ? <Empty description={emptyText} /> : !stats.total_matches || !rows.length ? <Empty description="所选范围暂无匹配记录" /> : <TrendChart rows={rows} />}
    </Card>
    <Card title="每日数据明细" className="trend"><Table size="small" loading={loading} rowKey="date" dataSource={rows} pagination={{ pageSize: 10, hideOnSinglePage: true, showSizeChanger: false }} locale={{ emptyText }} columns={[{ title: '日期', dataIndex: 'date' }, { title: '匹配次数', dataIndex: 'matches' }, { title: '成交次数', dataIndex: 'conversions' }]} /></Card>
  </>;
}

