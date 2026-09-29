# -*- coding: utf-8 -*-
"""Install hook: compute the stored traffic lights of every storable variant."""

import logging

_logger = logging.getLogger(__name__)

_CHUNK = 2000


def post_init_hook(env):
    Product = env['product.product'].sudo()
    fnames = ['stock_cover_signal', 'stock_cover_sort_days']
    ids = Product.search([('is_storable', '=', True), ('active', '=', True)]).ids
    _logger.info('stock_coverage_report: recomputing stock coverage of %s storable variants', len(ids))
    for start in range(0, len(ids), _CHUNK):
        chunk = Product.browse(ids[start:start + _CHUNK])
        for fname in fnames:
            env.add_to_compute(Product._fields[fname], chunk)
        chunk.flush_recordset(fnames)
        env.invalidate_all()
