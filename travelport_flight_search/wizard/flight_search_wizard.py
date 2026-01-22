import json
import logging
from datetime import datetime

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class FlightOffer(models.TransientModel):
    """Temporary model to store flight offers for selection so we use TrasientModel instead of regular model"""
    _name = 'travelport.flight.offer'
    _description = 'Flight Offer'

    wizard_id = fields.Many2one('travelport.flight.search.wizard', string='Wizard', required=True, ondelete='cascade')
    offer_id = fields.Char(string='Offer ID', required=True)
    selected = fields.Boolean(string='Select', default=False)
    price = fields.Float(string='Price', required=True)
    currency = fields.Char(string='Currency', default='USD')
    flight_details = fields.Text(string='Flight Details', required=True)
    flight_summary = fields.Char(string='Summary', compute='_compute_summary', store=False)
    raw_data = fields.Text(string='Raw Data', help='JSON data for this offer')

    @api.depends('flight_details', 'price', 'currency')
    def _compute_summary(self):
        """Compute a short summary for display"""
        for offer in self:
            lines = offer.flight_details.split('\n')
            first_line = lines[0] if lines else 'Flight Offer'
            offer.flight_summary = f"{first_line} - {offer.currency} {offer.price:.2f}"


class FlightSearchWizard(models.TransientModel):
    _name = 'travelport.flight.search.wizard'
    _description = 'Travelport Flight Search Wizard'

    sale_order_id = fields.Many2one('sale.order', string='Sales Order', required=True, default=lambda self: self.env.context.get('active_id'))

    # Search Criteria Fields
    origin = fields.Char('Origin', required=True, default='LHR')
    destination = fields.Char('Destination', required=True, default='JFK')
    departure_date = fields.Date('Departure Date', required=True, default=fields.Date.today)

    # Return trip fields
    is_round_trip = fields.Boolean('Round Trip')
    return_date = fields.Date('Return Date')

    # Passenger Information
    passenger_adult_count = fields.Integer('Adults', default=1, required=True)
    passenger_child_count = fields.Integer('Children', default=0)
    passenger_child_ages = fields.Char('Child Ages (comma-separated)')

    # Cabin Class
    cabin_class = fields.Selection(
        selection=[
            ('Economy', 'Economy'),
            ('Premium Economy', 'Premium Economy'),
            ('Business', 'Business'),
            ('First', 'First'),
        ],
        string='Cabin Class',
        default='Economy'
    )

    # API Configuration (should be moved to system parameters in production)
    travelport_api_url = fields.Char(
        string='Travelport API URL',
        default='http://localhost:5000/11/air/catalog/search/catalogproductofferings'
    )
    travelport_branch_id = fields.Char(
        string='Branch ID',
        help='Travelport Branch ID for authentication'
    )
    travelport_username = fields.Char(
        string='Username',
        help='Travelport API Username'
    )
    travelport_password = fields.Char(
        string='Password',
        help='Travelport API Password'
    )

    # Results display
    search_results = fields.Text(
        string='Search Results',
        readonly=True
    )
    flight_offers = fields.One2many(
        'travelport.flight.offer',
        'wizard_id',
        string='Flight Offers',
        readonly=True
    )
    has_results = fields.Boolean(
        string='Has Results',
        compute='_compute_has_results',
        store=False
    )

    @api.depends('flight_offers')
    def _compute_has_results(self):
        """Check if there are any flight offers"""
        for wizard in self:
            wizard.has_results = bool(wizard.flight_offers)

    @api.constrains('passenger_child_count', 'passenger_child_ages')
    def _check_child_ages(self):
        """Validate that child ages match child count"""
        for wizard in self:
            if wizard.passenger_child_count > 0:
                if not wizard.passenger_child_ages:
                    raise ValidationError(_('Please enter child ages when children are included.'))
                ages = [age.strip() for age in wizard.passenger_child_ages.split(',') if age.strip()]
                if len(ages) != wizard.passenger_child_count:
                    raise ValidationError(_(
                        'Number of child ages (%d) must match number of children (%d).',
                        len(ages), wizard.passenger_child_count
                    ))

    @api.constrains('is_round_trip', 'return_date')
    def _check_return_date(self):
        """Validate return date for round trips"""
        for wizard in self:
            if wizard.is_round_trip and not wizard.return_date:
                raise ValidationError(_('Return date is required for round trip searches.'))
            if wizard.is_round_trip and wizard.return_date and wizard.departure_date:
                if wizard.return_date <= wizard.departure_date:
                    raise ValidationError(_('Return date must be after departure date.'))

    def _prepare_passenger_criteria(self):
        """Prepare passenger criteria for API request"""
        criteria = []

        # Add adults
        if self.passenger_adult_count > 0:
            criteria.append({
                'value': 'ADT',
                'number': self.passenger_adult_count
            })

        # Add children
        if self.passenger_child_count > 0:
            ages = [age.strip() for age in self.passenger_child_ages.split(',') if age.strip()]
            for age in ages:
                try:
                    age_int = int(age)
                    criteria.append({
                        'value': 'CNN',
                        'number': 1,
                        'age': age_int
                    })
                except ValueError:
                    _logger.warning(f'Invalid child age: {age}')

        return criteria

    def _prepare_search_criteria_flight(self):
        """Prepare flight search criteria for API request"""
        search_criteria = [{
            'departureDate': self.departure_date.strftime('%Y-%m-%d'),
            'From': {
                'value': self.origin.upper(),
                'cityOrAirport': 'City or Airport'
            },
            'To': {
                'value': self.destination.upper(),
                'cityOrAirport': 'City or Airport'
            }
        }]

        # Add return flight if round trip
        if self.is_round_trip and self.return_date:
            search_criteria.append({
                'departureDate': self.return_date.strftime('%Y-%m-%d'),
                'From': {
                    'value': self.destination.upper()
                },
                'To': {
                    'value': self.origin.upper()
                }
            })

        return search_criteria

    def _prepare_api_payload(self):
        """Prepare the JSON payload for Travelport API"""
        payload = {
            'CatalogProductOfferingsQueryRequest': {
                'CustomResponseModifiersAir': {
                    'SearchRepresentation': 'Journey',
                    'includeCo2EmissionsDataInd': True,
                    'includeFlightAmenitiesInd': True
                },
                'CatalogProductOfferingsRequest': {
                    'offersPerPage': 50,
                    'sortBy': 'Price-LowToHigh',
                    'contentSourceList': ['GDS', 'NDC'],
                    'PassengerCriteria': self._prepare_passenger_criteria(),
                    'SearchCriteriaFlight': self._prepare_search_criteria_flight()
                }
            }
        }

        # Add cabin filter if specified
        if self.cabin_class and self.cabin_class != 'Economy':
            # Map cabin class to API values
            cabin_map = {
                'Premium Economy': 'PremiumEconomy',
                'Business': 'Business',
                'First': 'First'
            }
            payload['CatalogProductOfferingsQueryRequest']['CatalogProductOfferingsRequest']['Cabin'] = [
                cabin_map.get(self.cabin_class, self.cabin_class)
            ]

        return payload

    def _get_api_headers(self):
        """Get API headers including authentication"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # Add authentication if configured
        # Note: In production, use proper OAuth2 authentication as per Travelport docs
        if self.travelport_branch_id and self.travelport_username and self.travelport_password:
            # This is a simplified example - actual implementation should use OAuth2
            headers['Authorization'] = f'Basic {self._get_basic_auth()}'

        return headers

    def _get_basic_auth(self):
        """Generate basic auth string (for demo purposes only)"""
        import base64
        credentials = f"{self.travelport_username}:{self.travelport_password}"
        return base64.b64encode(credentials.encode()).decode()

    def action_search_flights(self):
        """Search flights using Travelport API"""
        self.ensure_one()

        # Validate inputs
        if not self.origin or not self.destination:
            raise UserError(_('Please provide origin and destination airport codes.'))

        if len(self.origin) != 3 or len(self.destination) != 3:
            raise UserError(_('Airport codes must be 3 characters (IATA format).'))

        # Prepare API request
        payload = self._prepare_api_payload()
        headers = self._get_api_headers()

        _logger.info(f'Travelport API Request: {json.dumps(payload, indent=2)}')

        try:
            # Make API call
            api_url = self.travelport_api_url or 'http://localhost:5000/11/air/catalog/search/catalogproductofferings'
            response = requests.post(
                api_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            # Check for HTTP errors
            if not response.ok:
                error_detail = ''
                try:
                    error_data = response.json()
                    error_detail = json.dumps(error_data, indent=2)
                except:
                    error_detail = response.text

                error_msg = _('Travelport API Error (HTTP %d): %s') % (response.status_code, error_detail)
                _logger.error(error_msg)
                raise UserError(error_msg)

            response_data = response.json()

            _logger.info(f'Travelport API Response: {json.dumps(response_data, indent=2)}')

            # Parse and store results in wizard for user selection
            self._process_flight_results(response_data)

            # Return action to refresh wizard and show results
            return {
                'type': 'ir.actions.act_window',
                'name': 'Search Flights',
                'res_model': 'travelport.flight.search.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        except requests.exceptions.RequestException as e:
            error_msg = _('Error connecting to Travelport API: %s') % str(e)
            _logger.error(error_msg)
            raise UserError(error_msg)
        except json.JSONDecodeError as e:
            error_msg = _('Invalid JSON response from Travelport API: %s') % str(e)
            _logger.error(error_msg)
            raise UserError(error_msg)
        except Exception as e:
            error_msg = _('Unexpected error: %s') % str(e)
            _logger.error(error_msg, exc_info=True)
            raise UserError(error_msg)

    def _process_flight_results(self, response_data):
        """Process Travelport API response and store offers for user selection"""
        self.ensure_one()

        if not response_data.get('CatalogProductOfferingsResponse'):
            raise UserError(_('No valid response from Travelport API.'))

        response = response_data['CatalogProductOfferingsResponse']

        # Extract offers and reference lists
        catalog_offerings = response.get('CatalogProductOfferings', {})
        catalog_offering_list = catalog_offerings.get('CatalogProductOffering', [])

        if not catalog_offering_list:
            raise UserError(_('No flight offers found for the selected criteria.'))

        reference_list = response.get('ReferenceList', [])

        # Build reference maps for flights, products, etc.
        flight_map = {}
        product_map = {}

        for ref_item in reference_list:
            ref_type = ref_item.get('@type', '')

            # Map flights
            if ref_type == 'ReferenceListFlight':
                flights = ref_item.get('Flight', [])
                for flight in flights:
                    flight_id = flight.get('id')
                    if flight_id:
                        flight_map[flight_id] = flight

            # Map products (ProductAir contains flight segments)
            elif ref_type == 'ReferenceListProduct':
                products = ref_item.get('Product', [])
                for product in products:
                    product_id = product.get('id')
                    if product_id:
                        product_map[product_id] = product

        # Clear existing offers
        self.flight_offers.unlink()

        # Create flight offer records for user selection
        offer_records = []
        for idx, offering in enumerate(catalog_offering_list[:50]):  # Limit to first 50 offers
            offering_id = offering.get('id', '')
            total_price = offering.get('TotalPrice', {})
            price_value = total_price.get('value', 0.0)
            price_currency = total_price.get('code', 'USD')

            # Get product references from ProductOptions
            product_options = offering.get('ProductOptions', [])
            product_refs = []
            for option in product_options:
                # ProductOptions can have ProductRef or FlightRefs
                if 'ProductRef' in option:
                    product_refs.append(option['ProductRef'])
                elif 'FlightRefs' in option:
                    # Direct flight references (legacy format)
                    product_refs.extend(option.get('FlightRefs', []))

            # Build description from product details
            description_parts = []
            description_parts.append(f"Flight Offer: {offering_id}")

            # Try to get flight details from products
            flight_details = []
            for product_ref in product_refs[:5]:  # Limit to first 5 products
                product = product_map.get(product_ref)
                if product and product.get('@type') == 'ProductAir':
                    # Extract flight segments
                    flight_segments = product.get('FlightSegment', [])
                    for segment in flight_segments:
                        flight_ref = segment.get('Flight', {})
                        if isinstance(flight_ref, dict):
                            flight_id = flight_ref.get('FlightRef')
                        else:
                            flight_id = flight_ref

                        if flight_id:
                            flight = flight_map.get(flight_id)
                            if flight:
                                carrier = flight.get('carrier', '')
                                number = flight.get('number', '')
                                departure = flight.get('departureTime', '')
                                arrival = flight.get('arrivalTime', '')

                                # Handle different origin/destination formats
                                origin_obj = flight.get('Origin', {})
                                dest_obj = flight.get('Destination', {})

                                origin_code = origin_obj.get('value', '') if isinstance(origin_obj, dict) else origin_obj
                                dest_code = dest_obj.get('value', '') if isinstance(dest_obj, dict) else dest_obj

                                if carrier and number:
                                    flight_info = f"{carrier}{number}: {origin_code} → {dest_code}"
                                    if departure:
                                        flight_info += f" (Dep: {departure})"
                                    if arrival:
                                        flight_info += f" (Arr: {arrival})"
                                    flight_details.append(flight_info)

            # If no product details, try direct flight references
            if not flight_details:
                for product_ref in product_refs:
                    flight = flight_map.get(product_ref)
                    if flight:
                        carrier = flight.get('carrier', '')
                        number = flight.get('number', '')
                        departure = flight.get('departureTime', '')
                        arrival = flight.get('arrivalTime', '')
                        origin_obj = flight.get('Origin', {})
                        dest_obj = flight.get('Destination', {})
                        origin_code = origin_obj.get('value', '') if isinstance(origin_obj, dict) else origin_obj
                        dest_code = dest_obj.get('value', '') if isinstance(dest_obj, dict) else dest_obj

                        if carrier and number:
                            flight_info = f"{carrier}{number}: {origin_code} → {dest_code}"
                            if departure:
                                flight_info += f" (Dep: {departure})"
                            if arrival:
                                flight_info += f" (Arr: {arrival})"
                            flight_details.append(flight_info)

            # Add flight details to description
            if flight_details:
                description_parts.extend(flight_details)
            else:
                description_parts.append(f"Route: {self.origin} → {self.destination}")
                if self.is_round_trip:
                    description_parts.append(f"Return: {self.destination} → {self.origin}")

            # Add price information
            description_parts.append(f"Price: {price_currency} {price_value:.2f}")

            description = '\n'.join(description_parts)

            # Create flight offer record
            # Set first offer as selected by default
            offer_vals = {
                'wizard_id': self.id,
                'offer_id': offering_id,
                'price': price_value,
                'currency': price_currency,
                'flight_details': description,
                'raw_data': json.dumps(offering, indent=2),
                'selected': idx == 0,  # First offer is selected by default
            }
            offer_records.append(offer_vals)

        # Create all offer records
        if offer_records:
            self.env['travelport.flight.offer'].create(offer_records)

    def action_add_selected_offers(self):
        """Add selected flight offers to the sales order"""
        self.ensure_one()

        # For demo purposes: simply use the first record in the dataset
        if not self.flight_offers:
            raise UserError(_('No flight offers available to add.'))

        # Get the first flight offer
        first_offer = self.flight_offers[0]

        # Create sales order line for the first offer
        line_vals = {
            'order_id': self.sale_order_id.id,
            'name': first_offer.flight_details,
            'product_uom_qty': 1,
            'price_unit': first_offer.price,
            'product_id': False,  # No product, it's a service
        }

        # Convert currency if needed
        if first_offer.currency != self.sale_order_id.currency_id.name:
            # In production, implement proper currency conversion
            _logger.warning(f'Currency mismatch: {first_offer.currency} vs {self.sale_order_id.currency_id.name}')

        line = self.env['sale.order.line'].create(line_vals)

        # Show success message and close wizard
        message = _('Successfully added flight offer to the sales order.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sales Order',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'form_view_initial_mode': 'edit'},
        }
