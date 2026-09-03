const test = require('node:test');
const assert = require('node:assert/strict');

const {
  rankBySimilarity,
  buildPresentation,
  buildRecommendationScript,
} = require('../matcher-core.js');

test('排序只取决于图片特征，不受结构化元数据影响', () => {
  const query = { v: [120, 130, 140], ratio: 1.5 };
  const visuallyNear = {
    id: 1,
    feature: { v: [122, 132, 142], ratio: 1.5 },
    room: '卧室',
    style: '中古风',
    price: 9999,
    stock: '缺货',
  };
  const visuallyFar = {
    id: 2,
    feature: { v: [230, 230, 230], ratio: 0.7 },
    room: '客厅',
    style: '奶油风',
    price: 100,
    stock: '现货',
  };

  const ranked = rankBySimilarity(query, [visuallyFar, visuallyNear]);

  assert.equal(ranked[0].id, 1);
  assert.equal(ranked[0].reason, '图片色调与构图相近');
  assert.ok(ranked[0].score > ranked[1].score);
});

test('缺少全部结构化元数据时仍能生成完整展示内容', () => {
  const presentation = buildPresentation({});

  assert.deepEqual(presentation, {
    productName: '未命名买家秀',
    sku: '未填写',
    productInfo: '商品信息未填写',
    chips: [],
  });
});

test('缺少商品元数据时生成不包含虚构商品事实的通用话术', () => {
  const words = buildRecommendationScript({});

  assert.equal(words, '这张实拍与客户图片在整体色调和画面构图上较为接近，可以作为空间搭配参考。如果您愿意，我可以再发您更多相似实拍效果。');
});
