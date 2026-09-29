# -*- coding: utf-8 -*-
"""Install hook.

On databases that also run ``poultry_management`` (where this report was born), its
configuration lives in ``poultry_*`` columns: copy it once as the starting point. Then
compute the stored traffic lights of every storable variant.
"""

import logging

from odoo.tools import sql

_logger = logging.getLogger(__name__)

_CHUNK = 2000

# (table, old column, new column)
_COLUMNS = [
    ('product_category', 'poultry_cover_window_days', 'stock_cover_window_days'),
    ('product_template', 'poultry_cover_window_days', 'stock_cover_window_days'),
]
_OLD_REL = 'res_company_poultry_stock_dashboard_category_rel'
_NEW_REL = 'res_company_stock_cover_category_rel'


def _copy_legacy_poultry_data(cr):
    for table, old, new in _COLUMNS:
        if not (sql.column_exists(cr, table, old) and sql.column_exists(cr, table, new)):
            continue
        # The new column was created by this very install (defaults only), so the
        # poultry value wins wherever it is set.
        cr.execute(f'UPDATE "{table}" SET "{new}" = "{old}" WHERE "{old}" IS NOT NULL')
        _logger.info('stock_coverage_report: %s rows of %s.%s copied from %s', cr.rowcount, table, new, old)

    if sql.table_exists(cr, _OLD_REL) and sql.table_exists(cr, _NEW_REL):
        cr.execute(f"""
            INSERT INTO "{_NEW_REL}" (company_id, category_id)
            SELECT company_id, category_id FROM "{_OLD_REL}"
            ON CONFLICT DO NOTHING
        """)
        _logger.info('stock_coverage_report: %s company categories copied from %s', cr.rowcount, _OLD_REL)


def _recompute_stock_cover_signals(env):
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


def post_init_hook(env):
    _copy_legacy_poultry_data(env.cr)
    env.invalidate_all()
    _recompute_stock_cover_signals(env)
