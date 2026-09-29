# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    stock_cover_category_ids = fields.Many2many(
        'product.category',
        'res_company_stock_cover_category_rel',
        'company_id',
        'category_id',
        string='Stock coverage: categories',
        help='If empty, the stock coverage report includes every purchasable storable product. '
             'If categories are set, only variants in those categories (and their '
             'subcategories) are shown.',
    )
