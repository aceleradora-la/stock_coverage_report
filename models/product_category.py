# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductCategory(models.Model):
    _inherit = 'product.category'

    stock_cover_window_days = fields.Float(
        string='Consumption window (days)',
        default=7.0,
        digits=(16, 1),
        help='Closed calendar days (company timezone) used to sum outgoing moves: from day '
             '(today - N) 00:00 to yesterday 23:59. Today is not included. The total is divided by N.',
    )

    @api.constrains('stock_cover_window_days')
    def _check_stock_cover_window_days(self):
        for categ in self:
            if categ.stock_cover_window_days <= 0:
                raise ValidationError(
                    self.env._('The consumption window of a product category must be greater than zero.')
                )
