"""目录预筛和入库共用的来源目录规则。"""


def parse_folder(name):
    product, sep, style = name.partition('_')
    if not sep or not style.strip() or not (product.isdigit() or product == '未知商品ID'):
        raise ValueError('目录应为商品ID_款式或未知商品ID_款式')
    return (product if product.isdigit() else None), style.strip()
