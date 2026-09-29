# -*- coding: utf-8 -*-
"""
Stock coverage report (purchasable products only): consumption over a window of closed
calendar days (company timezone) and a traffic light based on the vendor lead time, the
company's purchase days and the purchase order lead time.

A second line shows the same metric for the forecasted quantity (``virtual_available``)
with the same color criteria.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

# Standard product.supplierinfo order (same criteria as the scheduler when taking the first one).
_SUPPLIERINFO_ORDER = 'sequence, min_qty desc, price, id'
# High value to sort last (least urgent) in columns sorted ascending by days.
_SORT_TAIL = 1e9
# Fixed Kanban column order when grouping by signal (Odoo usually sorts groups by count).
_SIGNAL_GROUP_READ_ORDER = {'red': 0, 'yellow': 1, 'green': 2, 'neutral': 3}

_COVER_SIGNAL_SEL = [
    ('red', 'Red'),
    ('yellow', 'Yellow'),
    ('green', 'Green'),
    ('neutral', 'No data'),
]


class ProductProduct(models.Model):
    _inherit = 'product.product'

    stock_cover_daily_avg = fields.Float(
        string='Daily consumption (window)',
        digits='Product Unit',
        compute='_compute_stock_cover_metrics',
        help='Daily average of outgoing moves from internal stock over the configured window '
             '(product unit of measure).',
    )
    stock_cover_days = fields.Float(
        string='Coverage days (on hand)',
        compute='_compute_stock_cover_metrics',
        digits=(16, 2),
        help='On hand quantity / daily consumption. Empty if there was no consumption in the window.',
    )
    stock_cover_days_display = fields.Char(
        string='Coverage days (on hand) display',
        compute='_compute_stock_cover_metrics',
    )
    stock_cover_signal = fields.Selection(
        selection=_COVER_SIGNAL_SEL,
        string='Coverage signal (on hand)',
        compute='_compute_stock_cover_metrics_store',
        store=True,
        index=True,
        group_expand='_group_expand_stock_cover_signal',
    )
    stock_cover_sort_days = fields.Float(
        string='Coverage sort key (days)',
        compute='_compute_stock_cover_metrics_store',
        store=True,
        index=True,
        help='Sort key for the Kanban board: lower = more urgent (internal use only).',
    )
    stock_cover_forecast_days = fields.Float(
        string='Coverage days (forecast)',
        compute='_compute_stock_cover_metrics',
        digits=(16, 2),
        help='Forecasted quantity (virtual_available) / daily consumption.',
    )
    stock_cover_forecast_days_display = fields.Char(
        string='Coverage days (forecast) display',
        compute='_compute_stock_cover_metrics',
    )
    stock_cover_forecast_signal = fields.Selection(
        selection=_COVER_SIGNAL_SEL,
        string='Coverage signal (forecast)',
        compute='_compute_stock_cover_metrics',
    )

    @staticmethod
    def _stock_cover_line_metrics(daily, rounding, qty, lead_th, yellow_th):
        """One traffic light line: (days_float_or_False, text, signal, sort_key)."""
        if float_is_zero(daily, precision_rounding=rounding):
            if float_is_zero(qty, precision_rounding=rounding):
                return False, '—', 'neutral', _SORT_TAIL
            return False, '∞', 'green', _SORT_TAIL
        days = qty / daily if daily else 0.0
        days_rounded = float_round(days, precision_rounding=0.01)
        display = str(days_rounded)
        sort_key = float(days_rounded)
        if float_compare(days, yellow_th, precision_digits=2) > 0:
            sig = 'green'
        elif float_compare(days, lead_th, precision_digits=2) > 0:
            sig = 'yellow'
        else:
            sig = 'red'
        return days_rounded, display, sig, sort_key

    def _stock_cover_first_supplierinfo(self):
        """First vendor line, in the model order (sequence, min_qty desc, ...)."""
        self.ensure_one()
        SupplierInfo = self.env['product.supplierinfo'].sudo()
        company = self.env.company
        domain = [
            ('product_tmpl_id', '=', self.product_tmpl_id.id),
            '|', ('product_id', '=', False), ('product_id', '=', self.id),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ]
        return SupplierInfo.search(domain, order=_SUPPLIERINFO_ORDER, limit=1)

    def _stock_cover_threshold_days(self):
        """Traffic light thresholds: (vendor_lead_time, yellow_limit).

        * **Vendor lead time**: ``delay`` of the first ``product.supplierinfo`` (0 if none).
        * **Internal delay**: company ``days_to_purchase`` (``purchase_stock``).
        * **Buffer**: company ``po_lead`` if ``purchase.use_po_lead`` is enabled and the field
          exists (it does not in standard Odoo 19); else 0.

        - Red: coverage days ``<=`` vendor lead time.
        - Yellow: ``>`` lead time and ``<=`` lead time + internal delay + buffer.
        - Green: ``>`` lead time + internal delay + buffer.

        If internal delay + buffer is 0, 0.01 days are used so that a minimal yellow band remains.
        """
        self.ensure_one()
        company = self.env.company
        info = self._stock_cover_first_supplierinfo()
        lead_time = float(info.delay) if info else 0.0

        days_purchase = 0.0
        if 'days_to_purchase' in company._fields:
            days_purchase = float(company.days_to_purchase or 0.0)

        # ``po_lead`` was removed from res.company in Odoo 19, but a database upgraded from an
        # older version may still carry the ``purchase.use_po_lead`` parameter: guard both.
        buffer_po = 0.0
        use_po_lead = self.env['ir.config_parameter'].sudo().get_param('purchase.use_po_lead') == 'True'
        if use_po_lead and 'po_lead' in company._fields:
            buffer_po = float(company.po_lead or 0.0)

        internal_block = days_purchase + buffer_po
        if internal_block <= 0.0:
            internal_block = 0.01

        return lead_time, lead_time + internal_block

    @api.model
    def _stock_cover_window_datetimes(self, window_days):
        """Consumption window: N **closed** calendar days in the company timezone, today excluded.

        - ``date_to``: end of yesterday (23:59:59) in the company timezone.
        - ``date_from``: start of day ``today - N`` at 00:00:00 in the same timezone.
        - Returns naive UTC bounds for the ``stock.move.line`` domain.
        """
        window_days = max(int(float(window_days)), 1)
        company = self.env.company
        tz_name = company.partner_id.tz or self.env.user.tz or 'UTC'
        today = fields.Date.context_today(self.with_context(tz=tz_name))
        yesterday = today - timedelta(days=1)
        start_day = today - timedelta(days=window_days)

        tz = pytz.timezone(tz_name)
        start_local = tz.localize(datetime.combine(start_day, time.min))
        end_local = tz.localize(datetime.combine(yesterday, time(23, 59, 59)))
        start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        return start_utc, end_utc

    def _stock_cover_sum_outgoing_product_uom(self, product_ids, window_days):
        """Done outgoing quantities in the window: internal stock -> outside useful internal stock.

        Window of closed calendar days (company timezone). Internal -> internal transfers and
        moves to **transit** locations are not counted.
        """
        if not product_ids:
            return {}
        date_from, date_to = self._stock_cover_window_datetimes(window_days)
        domain = [
            ('state', '=', 'done'),
            ('product_id', 'in', list(product_ids)),
            ('location_id.usage', '=', 'internal'),
            ('location_dest_id.usage', 'not in', ('internal', 'transit')),
            '|',
            '&', ('date', '>=', date_from), ('date', '<=', date_to),
            '&', ('move_id.date', '>=', date_from), ('move_id.date', '<=', date_to),
        ]
        MoveLine = self.env['stock.move.line'].sudo()
        # Odoo 19: _read_group returns tuples (groupby_value, *aggregates); for a many2one
        # the value is the record itself.
        groups = MoveLine._read_group(domain, ['product_id'], ['quantity_product_uom:sum'])
        result = {}
        for product, qty in groups:
            if not product:
                continue
            result[product.id] = qty or 0.0
        return result

    _STOCK_COVER_METRICS_DEPENDS = [
        'qty_available',
        'virtual_available',
        'uom_id',
        'product_tmpl_id.stock_cover_window_days',
        'product_tmpl_id.categ_id.stock_cover_window_days',
        'product_tmpl_id.seller_ids',
        'product_tmpl_id.seller_ids.delay',
        'product_tmpl_id.seller_ids.sequence',
        'product_tmpl_id.seller_ids.min_qty',
        'product_tmpl_id.seller_ids.product_id',
        'product_tmpl_id.seller_ids.company_id',
        'product_tmpl_id.purchase_ok',
    ]

    def _stock_cover_build_metrics_data(self):
        """Coverage metrics per product_id (shared by the stored / non-stored computes)."""
        buckets = defaultdict(list)
        for product in self:
            wd = float(product.product_tmpl_id._stock_cover_effective_window_days())
            buckets[wd].append(product.id)

        consumption = {}
        for window_days, pids in buckets.items():
            consumption.update(self._stock_cover_sum_outgoing_product_uom(pids, window_days))

        result = {}
        for product in self:
            tmpl = product.product_tmpl_id
            rounding = product.uom_id.rounding or 0.0001
            window = tmpl._stock_cover_effective_window_days()
            lead_th, yellow_th = product._stock_cover_threshold_days()
            total_out = consumption.get(product.id, 0.0)
            daily = total_out / window if window else 0.0
            daily_avg = float_round(daily, precision_rounding=rounding)

            dr, dstr_r, sig_r, sort_r = self._stock_cover_line_metrics(
                daily, rounding, product.qty_available, lead_th, yellow_th
            )
            df, dstr_f, sig_f, _sort_f = self._stock_cover_line_metrics(
                daily, rounding, product.virtual_available, lead_th, yellow_th
            )
            result[product.id] = {
                'daily_avg': daily_avg,
                'days': dr,
                'days_display': dstr_r,
                'signal': sig_r,
                'sort_days': sort_r,
                'forecast_days': df,
                'forecast_days_display': dstr_f,
                'forecast_signal': sig_f,
            }
        return result

    @api.depends_context('company')
    @api.depends(*_STOCK_COVER_METRICS_DEPENDS)
    def _compute_stock_cover_metrics(self):
        data = self._stock_cover_build_metrics_data()
        for product in self:
            row = data[product.id]
            product.stock_cover_daily_avg = row['daily_avg']
            product.stock_cover_days = row['days']
            product.stock_cover_days_display = row['days_display']
            product.stock_cover_forecast_days = row['forecast_days']
            product.stock_cover_forecast_days_display = row['forecast_days_display']
            product.stock_cover_forecast_signal = row['forecast_signal']

    @api.depends_context('company')
    @api.depends(*_STOCK_COVER_METRICS_DEPENDS)
    def _compute_stock_cover_metrics_store(self):
        data = self._stock_cover_build_metrics_data()
        for product in self:
            row = data[product.id]
            product.stock_cover_signal = row['signal']
            product.stock_cover_sort_days = row['sort_days']

    @api.model
    def _group_expand_stock_cover_signal(self, values, domain):
        """Fixed Kanban columns (red -> yellow -> green); 'no data' is outside the report domain."""
        return ['red', 'yellow', 'green']

    @api.model
    def formatted_read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        """Keep the Red -> Yellow -> Green -> No data column order when grouping by signal.

        Without this, the web client sorts groups by record count.
        """
        rows = super().formatted_read_group(
            domain, groupby, aggregates, having=having, offset=offset, limit=limit, order=order)
        if not groupby:
            return rows
        first = groupby[0] if isinstance(groupby, (list, tuple)) else groupby
        field_name = first.split(':')[0] if isinstance(first, str) else first
        if field_name != 'stock_cover_signal':
            return rows

        def _signal_sort_key(row):
            val = row.get('stock_cover_signal')
            if val is False or val is None:
                return _SIGNAL_GROUP_READ_ORDER['neutral']
            if isinstance(val, (list, tuple)):
                val = val[0]
            return _SIGNAL_GROUP_READ_ORDER.get(val, 99)

        return sorted(rows, key=_signal_sort_key)

    @api.model
    def _stock_cover_report_domain(self):
        """Purchasable storable products, limited to the company's categories if any."""
        domain = [
            ('is_storable', '=', True),
            ('active', '=', True),
            ('purchase_ok', '=', True),
        ]
        cats = self.env.company.stock_cover_category_ids
        if cats:
            domain.append(('categ_id', 'child_of', cats.ids))
        return domain

    @api.model
    def action_open_stock_cover_report(self):
        """Kanban only: grouped and sorted by the on-hand signal; cards also show the forecast."""
        domain = self._stock_cover_report_domain()
        # Refresh the stored signals before filtering by color (avoids mixed columns on first load).
        products = self.search(domain)
        if products:
            products._compute_stock_cover_metrics()
            products._compute_stock_cover_metrics_store()
        domain.append(('stock_cover_signal', 'in', ('red', 'yellow', 'green')))
        kanban_view = self.env.ref('stock_coverage_report.product_product_kanban_stock_cover')
        search_view = self.env.ref('stock_coverage_report.product_product_search_stock_cover')
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Stock Coverage'),
            'res_model': 'product.product',
            'view_mode': 'kanban',
            'views': [(kanban_view.id, 'kanban')],
            'search_view_id': search_view.id,
            'domain': domain,
            'context': {
                'search_default_stock_cover_with_data': 1,
                'group_by': ['stock_cover_signal'],
            },
        }
