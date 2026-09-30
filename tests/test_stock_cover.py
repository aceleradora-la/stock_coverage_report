# -*- coding: utf-8 -*-

from datetime import datetime, time, timedelta

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStockCover(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.partner_id.tz = 'UTC'
        cls.company.days_to_purchase = 0.0
        cls.env['ir.config_parameter'].sudo().set_param('purchase.use_po_lead', 'False')
        cls.stock_location = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1).lot_stock_id
        cls.vendor = cls.env['res.partner'].create({'name': 'Stock cover vendor'})
        cls.categ = cls.env['product.category'].create({
            'name': 'Stock cover category',
            'stock_cover_window_days': 10.0,
        })
        cls.Product = cls.env['product.product']

    def _create_product(self, delay=None, **vals):
        values = {
            'name': 'Stock cover product',
            'is_storable': True,
            'purchase_ok': True,
            'categ_id': self.categ.id,
        }
        if delay is not None:
            values['seller_ids'] = [Command.create({'partner_id': self.vendor.id, 'delay': delay})]
        values.update(vals)
        return self.Product.create(values)

    def _set_quantity(self, product, qty, date=None):
        """Inventory adjustment; a decrease is an internal -> inventory loss move (consumption)."""
        quant = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': product.id,
            'location_id': self.stock_location.id,
            'inventory_quantity': qty,
        })
        quant.action_apply_inventory(date=date)
        product.invalidate_recordset()

    def _yesterday_noon(self):
        today = fields.Date.context_today(self.Product.with_context(tz='UTC'))
        return datetime.combine(today - timedelta(days=1), time(12, 0))

    def _consume(self, product, start_qty, end_qty):
        """Start at ``start_qty`` and consume down to ``end_qty`` yesterday."""
        self._set_quantity(product, start_qty, date=self._yesterday_noon() - timedelta(days=1))
        self._set_quantity(product, end_qty, date=self._yesterday_noon())

    # ------------------------------------------------------------------
    # Pure logic
    # ------------------------------------------------------------------

    def test_line_metrics(self):
        metrics = self.Product._stock_cover_line_metrics
        # no consumption, no stock -> neutral
        self.assertEqual(metrics(0.0, 0.01, 0.0, 5.0, 7.0)[1:3], ('—', 'neutral'))
        # no consumption, stock -> infinite, green
        self.assertEqual(metrics(0.0, 0.01, 10.0, 5.0, 7.0)[1:3], ('∞', 'green'))
        # no consumption, negative stock -> shortage, red
        self.assertEqual(metrics(0.0, 0.01, -56.0, 5.0, 7.0)[1:3], ('0', 'red'))
        # consumption and negative stock -> red
        self.assertEqual(metrics(2.0, 0.01, -10.0, 5.0, 7.0)[2], 'red')
        # 10 / 2 = 5 days <= lead time 5 -> red
        self.assertEqual(metrics(2.0, 0.01, 10.0, 5.0, 7.0)[0:3:2], (5.0, 'red'))
        # 12 / 2 = 6 days, between 5 and 7 -> yellow
        self.assertEqual(metrics(2.0, 0.01, 12.0, 5.0, 7.0)[2], 'yellow')
        # 7 days is still yellow (upper bound included)
        self.assertEqual(metrics(2.0, 0.01, 14.0, 5.0, 7.0)[2], 'yellow')
        # 16 / 2 = 8 days > 7 -> green, sort key = days
        days, display, signal, sort_key = metrics(2.0, 0.01, 16.0, 5.0, 7.0)
        self.assertEqual((days, display, signal, sort_key), (8.0, '8.0', 'green', 8.0))

    def test_window_fallback(self):
        product = self._create_product()
        tmpl = product.product_tmpl_id
        self.assertFalse(tmpl.stock_cover_window_days)
        self.assertEqual(tmpl._stock_cover_effective_window_days(), 10.0)
        tmpl.stock_cover_window_days = 3.0
        self.assertEqual(tmpl._stock_cover_effective_window_days(), 3.0)
        # clearing the field in the form saves 0: normalized to "inherit from category"
        tmpl.write({'stock_cover_window_days': 0})
        self.assertFalse(tmpl.stock_cover_window_days)
        self.assertEqual(tmpl._stock_cover_effective_window_days(), 10.0)
        # a category without window and without parents falls back to 7 days
        categ = self.env['product.category'].create({'name': 'Default window'})
        self.assertFalse(categ.stock_cover_window_days)
        tmpl.categ_id = categ
        self.assertEqual(tmpl._stock_cover_effective_window_days(), 7.0)

    def test_window_inherited_from_parent_category(self):
        Category = self.env['product.category']
        root = Category.create({'name': 'Raw material', 'stock_cover_window_days': 30.0})
        child = Category.create({'name': 'Juices', 'parent_id': root.id})
        grandchild = Category.create({'name': 'Lemon', 'parent_id': child.id})
        self.assertEqual(grandchild._stock_cover_effective_window_days(), 30.0)
        # 0 (cleared in the form) also means "inherit"
        child.stock_cover_window_days = 0
        self.assertFalse(child.stock_cover_window_days)
        self.assertEqual(child._stock_cover_effective_window_days(), 30.0)
        # the closest ancestor with a value wins
        child.stock_cover_window_days = 14.0
        self.assertEqual(grandchild._stock_cover_effective_window_days(), 14.0)
        grandchild.stock_cover_window_days = 5.0
        self.assertEqual(grandchild._stock_cover_effective_window_days(), 5.0)
        # the product follows its category chain unless it has its own window
        product = self._create_product(categ_id=grandchild.id)
        grandchild.stock_cover_window_days = False
        self.assertEqual(product.product_tmpl_id._stock_cover_effective_window_days(), 14.0)
        product.product_tmpl_id.stock_cover_window_days = 3.0
        self.assertEqual(product.product_tmpl_id._stock_cover_effective_window_days(), 3.0)

    def test_constraints(self):
        with self.assertRaises(ValidationError):
            self.categ.stock_cover_window_days = -1.0
        product = self._create_product()
        with self.assertRaises(ValidationError):
            product.product_tmpl_id.stock_cover_window_days = -2.0

    def test_thresholds(self):
        product = self._create_product(delay=5)
        # no internal delay: a minimal 0.01 yellow band is kept
        lead, yellow = product._stock_cover_threshold_days()
        self.assertEqual(lead, 5.0)
        self.assertAlmostEqual(yellow, 5.01)
        self.company.days_to_purchase = 2.0
        self.assertEqual(product._stock_cover_threshold_days(), (5.0, 7.0))
        # no vendor line: lead time 0
        self.assertEqual(self._create_product()._stock_cover_threshold_days(), (0.0, 2.0))
        # legacy parameter from an upgraded database must not break (po_lead is gone in 19.0)
        self.env['ir.config_parameter'].sudo().set_param('purchase.use_po_lead', 'True')
        lead, yellow = product._stock_cover_threshold_days()
        self.assertEqual(lead, 5.0)
        self.assertGreaterEqual(yellow, 7.0)

    def test_first_vendor_line_is_used(self):
        product = self._create_product()
        product.product_tmpl_id.seller_ids = [
            Command.create({'partner_id': self.vendor.id, 'delay': 20, 'sequence': 2}),
            Command.create({'partner_id': self.vendor.id, 'delay': 3, 'sequence': 1}),
        ]
        self.assertEqual(product._stock_cover_threshold_days()[0], 3.0)

    # ------------------------------------------------------------------
    # With stock moves
    # ------------------------------------------------------------------

    def test_consumption_window(self):
        product = self._create_product(delay=5)
        # 100 -> 70 yesterday: 30 consumed over a 10 day window = 3/day, 70 / 3 = 23.33 days
        self._consume(product, 100.0, 70.0)
        self.assertAlmostEqual(product.stock_cover_daily_avg, 3.0)
        self.assertAlmostEqual(product.stock_cover_days, 23.33)
        self.assertEqual(product.stock_cover_days_display, '23.33')
        self.assertEqual(product.stock_cover_forecast_days_display, '23.33')
        self.assertEqual(product.stock_cover_forecast_signal, 'green')

    def test_moves_of_today_are_not_counted(self):
        product = self._create_product(delay=5)
        self._set_quantity(product, 100.0)
        self._set_quantity(product, 70.0)  # today: outside the window
        self.assertEqual(product.stock_cover_daily_avg, 0.0)
        self.assertEqual(product.stock_cover_days_display, '∞')
        self.assertEqual(product.stock_cover_forecast_signal, 'green')

    def test_signals_and_group_order(self):
        # 23.33 days of coverage for each product
        red = self._create_product(delay=30, name='Red product')
        yellow = self._create_product(delay=20, name='Yellow product')
        green = self._create_product(delay=5, name='Green product')
        self.company.days_to_purchase = 10.0
        for product in red | yellow | green:
            self._consume(product, 100.0, 70.0)

        self.Product.action_open_stock_cover_report()
        self.assertEqual(red.stock_cover_signal, 'red')
        self.assertEqual(yellow.stock_cover_signal, 'yellow')
        self.assertEqual(green.stock_cover_signal, 'green')
        self.assertAlmostEqual(red.stock_cover_sort_days, 23.33)

        # the Kanban columns keep red -> yellow -> green whatever the record counts are
        extra_green = self._create_product(delay=1, name='Another green product')
        self._consume(extra_green, 100.0, 70.0)
        extra_green._compute_stock_cover_metrics_store()
        products = red | yellow | green | extra_green
        rows = self.Product.formatted_read_group(
            [('id', 'in', products.ids)], ['stock_cover_signal'], ['__count'])
        self.assertEqual([row['stock_cover_signal'] for row in rows], ['red', 'yellow', 'green'])

    def test_action_domain(self):
        action = self.Product.action_open_stock_cover_report()
        self.assertEqual(action['res_model'], 'product.product')
        self.assertEqual(action['context']['group_by'], ['stock_cover_signal'])
        self.assertIn(('stock_cover_signal', 'in', ('red', 'yellow', 'green')), action['domain'])
        self.assertIn(('purchase_ok', '=', True), action['domain'])
        self.assertFalse([leaf for leaf in action['domain'] if leaf[0] == 'categ_id'])

        self.company.stock_cover_category_ids = self.categ
        action = self.Product.action_open_stock_cover_report()
        self.assertIn(('categ_id', 'child_of', self.categ.ids), action['domain'])

        # a product outside the company categories is not in the report
        other_categ = self.env['product.category'].create({'name': 'Out of report'})
        inside = self._create_product(delay=5)
        outside = self._create_product(delay=5, categ_id=other_categ.id)
        for product in inside | outside:
            self._consume(product, 100.0, 70.0)
        found = self.Product.search(self.Product.action_open_stock_cover_report()['domain'])
        self.assertIn(inside, found)
        self.assertNotIn(outside, found)

    def test_menu(self):
        menu = self.env.ref('stock_coverage_report.menu_stock_cover_report')
        self.assertEqual(menu.parent_id, self.env.ref('stock.menu_warehouse_report'))
