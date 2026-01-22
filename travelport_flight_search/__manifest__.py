{
    'name': 'travelport_flight_search',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Integrate Travelport API to search and add flights to Sales Orders',
    'description': """
    - Search for flights directly from Sales Orders
    - Add flight offers as Sales Order Lines
    """,
    'depends': ['sale'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/flight_search_wizard_views.xml',
        'views/sale_order_views.xml',
    ],
    'license': 'LGPL-3',
}
