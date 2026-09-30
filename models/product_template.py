# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .product_category import DEFAULT_WINDOW_DAYS


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # False / empty = inherit from the category. Clearing the field in the form saves 0,
    # which is normalized to False in create/write.
    stock_cover_window_days = fields.Float(
        string='Consumption window (days)',
        digits=(16, 1),
        default=False,
        help='Closed calendar days (company timezone) used for consumption: day (today - N) 00:00 '
             'to yesterday 23:59, today excluded. Leave empty to use the product category value '
             '(inherited from the parent categories if empty).',
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
        for tmpl in self:
            w = tmpl.stock_cover_window_days
            if w is not False and w is not None and w < 0:
                raise ValidationError(self.env._('The consumption window cannot be negative.'))

    def _stock_cover_effective_window_days(self):
        """Product window if set, else the category chain's (see product.category), never below 1."""
        self.ensure_one()
        w_prod = self.stock_cover_window_days
        if w_prod not in (False, None) and float(w_prod) > 0:
            w = float(w_prod)
        elif self.categ_id:
            w = self.categ_id._stock_cover_effective_window_days()
        else:
            w = DEFAULT_WINDOW_DAYS
        return max(w, 1.0)
