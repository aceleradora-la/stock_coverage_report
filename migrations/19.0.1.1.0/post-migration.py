# -*- coding: utf-8 -*-
"""The category consumption window is now inherited from the parent category.

Until 19.0.1.0.x every category got 7 days by default, so a child category never
followed its parent. Categories left at exactly 7 are cleared so that they inherit
(the root of the chain still falls back to 7); any other value was set on purpose and
is kept. Then the stored traffic lights are recomputed.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.stock_coverage_report.hooks import post_init_hook

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE product_category
           SET stock_cover_window_days = NULL
         WHERE stock_cover_window_days = 7
    """)
    _logger.info('stock_coverage_report: %s categories now inherit the consumption window '
                 'from their parent', cr.rowcount)
    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
