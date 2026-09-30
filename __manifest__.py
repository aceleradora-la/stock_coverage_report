# -*- coding: utf-8 -*-
{
    'name': 'Stock Coverage Report',
    'version': '19.0.1.0.3',
    'category': 'Inventory/Inventory',
    'summary': 'Kanban board with days of stock coverage and a traffic light '
               'based on vendor lead time',
    'description': """
Stock coverage report
=====================

Kanban board (Inventory > Reporting > Stock Coverage) for purchasable storable
products: average daily consumption over a configurable window of closed days,
days of coverage for on-hand and forecasted quantity, and a red / yellow / green
traffic light based on the vendor lead time, the company's purchase days and
the purchase order lead time.

Works on Odoo 19 Community and Enterprise.
    """,
    'author': 'aceleradora.la',
    'website': 'https://github.com/aceleradora-la/stock_coverage_report',
    'license': 'LGPL-3',
    'depends': ['stock', 'purchase_stock'],
    'data': [
        'views/stock_cover_report_views.xml',
        'views/product_category_views.xml',
        'views/product_template_views.xml',
        'views/res_company_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'stock_coverage_report/static/src/css/stock_cover_report.css',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
