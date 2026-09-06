const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildPresentation,
  buildRecommendationScript,
} = require('../matcher-core.js');

test('展示契约消费后端 snake_case 字段并保留原始文件名兜底', () => {
  const presentation = buildPresentation({
    original_name: 'buyer.png',
    product_name: '云朵地毯',
    sku: 'CT-1',
    size: '160×230cm',
    price: 899,
    room: '客厅',
    style: '奶油风',
    color: '米白',
    stock: '现货',
  });

  assert.deepEqual(presentation, {
    productName: '云朵地毯',
    sku: 'CT-1',
    productInfo: '建议 160×230cm · 参考价 ¥899',
    chips: ['客厅', '奶油风', '米白', '现货'],
  });
  assert.equal(buildPresentation({ original_name: 'buyer.png' }).productName, 'buyer.png');
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

test('推荐话术只使用后端商品名和成交亮点', () => {
  const words = buildRecommendationScript({
    product_name: '云朵地毯',
    selling_point: '短绒易打理。',
    productName: '不应展示',
    sellingPoint: '不应展示',
  });

  assert.equal(
    words,
    '这张实拍与客户图片在整体色调和画面构图上较为接近，可以作为空间搭配参考。图中搭配的是云朵地毯。短绒易打理。如果您愿意，我可以再发您更多相似实拍效果。',
  );
});
