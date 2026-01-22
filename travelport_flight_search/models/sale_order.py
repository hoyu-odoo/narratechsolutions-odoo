from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_open_flight_search_wizard(self):
        """Open the travelport flight search wizard"""
        self.ensure_one()
        return {
            'name': 'Search Flights',
            'type': 'ir.actions.act_window',
            'res_model': 'travelport.flight.search.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
            },
        }
