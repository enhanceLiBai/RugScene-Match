(function exposeMatcherCore(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.CarpetMatcherCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, () => {
  /**
   * 计算两张图片的视觉相似度。当前 MVP 只比较九宫格平均色调与宽高比，
   * 结构化商品信息不得参与分数计算，避免缺失元数据扭曲检索结果。
   */
  function visualScore(a, b) {
    let sum = 0;
    for (let i = 0; i < a.v.length; i += 1) {
      sum += Math.abs(a.v[i] - b.v[i]) / 255;
    }
    const color = Math.max(0, 1 - sum / a.v.length);
    const ratio = Math.max(0, 1 - Math.abs(Math.log(a.ratio / b.ratio)));
    return color * 0.84 + ratio * 0.16;
  }

  function rankBySimilarity(queryFeature, items, limit = 5) {
    return items
      .map((item) => ({
        ...item,
        score: Math.max(0, Math.min(99, Math.round(visualScore(queryFeature, item.feature) * 99))),
        reason: '图片色调与构图相近',
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, limit);
  }

  /** 将可选元数据转换为稳定的界面文案，避免出现 undefined 或虚假默认值。 */
  function buildPresentation(item) {
    const productDetails = [];
    if (item.size) productDetails.push(`建议 ${item.size}`);
    if (item.price !== undefined && item.price !== null && item.price !== '') {
      productDetails.push(`参考价 ¥${item.price}`);
    }

    return {
      productName: item.productName || '未命名买家秀',
      sku: item.sku || '未填写',
      productInfo: productDetails.join(' · ') || '商品信息未填写',
      chips: [item.room, item.style, item.color, item.stock].filter(Boolean),
    };
  }

  /**
   * 话术只使用已经填写的事实字段；没有商品信息时退化为纯场景参考话术。
   */
  function buildRecommendationScript(item) {
    const sentences = ['这张实拍与客户图片在整体色调和画面构图上较为接近，可以作为空间搭配参考。'];
    if (item.productName) sentences.push(`图中搭配的是${item.productName}。`);
    if (item.sellingPoint) sentences.push(item.sellingPoint);
    sentences.push('如果您愿意，我可以再发您更多相似实拍效果。');
    return sentences.join('');
  }

  return { visualScore, rankBySimilarity, buildPresentation, buildRecommendationScript };
});
