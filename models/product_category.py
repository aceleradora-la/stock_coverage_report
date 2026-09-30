# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Window used when neither the product nor any category of the chain defines one.
DEFAULT_WINDOW_DAYS = 7.0


class ProductCategory(models.Model):
    _inherit = 'product.category'

    # False / empty = inherit from the parent category. Clearing the field in the form
    # saves 0, which is normalized to False in create/write.
    stock_cover_window_days = fields.Float(
        string='Consumption window (days)',
        digits=(16, 1),
        default=False,
        help='Closed calendar days (company timezone) used to sum outgoing moves: from day '
             '(today - N) 00:00 to yesterday 23:59. Today is not included. The total is divided by N. '
             'Leave empty to use the parent category value (7 days if no category of the chain has one).',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('stock_cover_window_days') in (0, 0.0):
                vals['stock_cover_window_days'] = False
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('stock_cover_window_days') in (0, 0.0):
            vals['stock_cover_window_days'] = False
        return super().write(vals)

    @api.constrains('stock_cover_window_days')
    def _check_stock_cover_window_days(self):
        for categ in self:
            w = categ.stock_cover_window_days
            if w is not False and w is not None and w < 0:
                raise ValidationError(self.env._('The consumption window cannot be negative.'))

    def _stock_cover_effective_window_days(self):
        """Own window if set, else the closest ancestor's, else 7."""
        self.ensure_one()
        categ = self
        while categ:
            w = categ.stock_cover_window_days
            if w not in (False, None) and float(w) > 0:
                return float(w)
            categ = categ.parent_id
        return DEFAULT_WINDOW_DAYS
