(function exposeMatcherCore(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.CarpetMatcherCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, () => {
  /** 将可选元数据转换为稳定的界面文案，避免出现 undefined 或虚假默认值。 */
  function buildPresentation(item) {
    const productDetails = [];
    if (item.size) productDetails.push(`建议 ${item.size}`);
    if (item.price !== undefined && item.price !== null && item.price !== '') {
      productDetails.push(`参考价 ¥${item.price}`);
    }

    return {
      productName: item.product_name || item.original_name || '未命名买家秀',
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
    if (item.product_name) sentences.push(`图中搭配的是${item.product_name}。`);
    if (item.selling_point) sentences.push(item.selling_point);
    sentences.push('如果您愿意，我可以再发您更多相似实拍效果。');
    return sentences.join('');
  }

  return { buildPresentation, buildRecommendationScript };
});
