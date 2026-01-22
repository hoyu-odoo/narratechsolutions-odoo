#!/usr/bin/env python3
"""
Travelport API Mock Server

A simple Flask server that simulates the Travelport Flight Search API
for testing the Odoo Travelport integration module.

Usage:
    python3 travelport_mock_server.py

The server will run on http://localhost:5000 by default.
Update the API URL in Odoo wizard to: http://localhost:5000/11/air/catalog/search/catalogproductofferings
"""

from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import json
import random

app = Flask(__name__)

# Mock flight data
MOCK_FLIGHTS = [
    {
        'carrier': 'BA',
        'number': '117',
        'origin': 'LHR',
        'destination': 'JFK',
        'departure_time': '08:25:00',
        'arrival_time': '11:05:00',
        'aircraft': '777',
    },
    {
        'carrier': 'AA',
        'number': '100',
        'origin': 'LHR',
        'destination': 'JFK',
        'departure_time': '10:30:00',
        'arrival_time': '13:15:00',
        'aircraft': '787',
    },
    {
        'carrier': 'VS',
        'number': '4',
        'origin': 'LHR',
        'destination': 'JFK',
        'departure_time': '12:00:00',
        'arrival_time': '14:45:00',
        'aircraft': 'A350',
    },
    {
        'carrier': 'DL',
        'number': '1',
        'origin': 'JFK',
        'destination': 'LHR',
        'departure_time': '22:00:00',
        'arrival_time': '09:30:00',
        'aircraft': 'A330',
    },
    {
        'carrier': 'BA',
        'number': '178',
        'origin': 'JFK',
        'destination': 'LHR',
        'departure_time': '20:15:00',
        'arrival_time': '07:45:00',
        'aircraft': '777',
    },
]

BASE_PRICES = {
    'Economy': 450.00,
    'Premium Economy': 850.00,
    'Business': 2500.00,
    'First': 5000.00,
}


def generate_flight_id(index):
    """Generate a unique flight ID"""
    return f"Flight_{index}"


def generate_offering_id(index):
    """Generate a unique offering ID"""
    return f"Offer_{index}"


def generate_product_id(index):
    """Generate a unique product ID"""
    return f"Product_{index}"


def get_mock_flights_for_route(origin, destination, departure_date, return_date=None):
    """Get mock flights matching the search criteria"""
    outbound_flights = [f for f in MOCK_FLIGHTS
                       if f['origin'] == origin.upper() and f['destination'] == destination.upper()]

    return_flights = []
    if return_date:
        return_flights = [f for f in MOCK_FLIGHTS
                         if f['origin'] == destination.upper() and f['destination'] == origin.upper()]

    return outbound_flights, return_flights


def build_flight_reference(flight, flight_id, departure_date):
    """Build a flight reference object"""
    return {
        '@type': 'Flight',
        'id': flight_id,
        'carrier': flight['carrier'],
        'number': flight['number'],
        'departureTime': f"{departure_date}T{flight['departure_time']}",
        'arrivalTime': f"{departure_date}T{flight['arrival_time']}",
        'Origin': {
            'value': flight['origin']
        },
        'Destination': {
            'value': flight['destination']
        },
        'Aircraft': {
            'value': flight['aircraft']
        }
    }


def build_product_air(flights, product_id, departure_date):
    """Build a ProductAir object with flight segments"""
    flight_segments = []
    flight_refs = []

    for idx, flight in enumerate(flights):
        flight_id = generate_flight_id(f"{product_id}_{idx}")
        flight_refs.append(flight_id)

        segment = {
            '@type': 'FlightSegment',
            'sequence': idx + 1,
            'Flight': {
                '@type': 'FlightID',
                'FlightRef': flight_id
            }
        }

        if idx < len(flights) - 1:
            segment['connectionDuration'] = 'PT2H30M'

        flight_segments.append(segment)

    return {
        '@type': 'ProductAir',
        'id': product_id,
        'Quantity': 1,
        'FlightSegment': flight_segments
    }, flight_refs


def calculate_price(base_price, cabin_class, num_passengers, is_round_trip):
    """Calculate total price"""
    price = BASE_PRICES.get(cabin_class, BASE_PRICES['Economy'])
    price *= num_passengers
    if is_round_trip:
        price *= 1.8  # Round trip discount
    # Add some random variation
    price *= (1 + random.uniform(-0.1, 0.1))
    return round(price, 2)


@app.route('/11/air/catalog/search/catalogproductofferings', methods=['POST'])
def search_flights():
    """Handle flight search requests"""
    try:
        data = request.get_json()
        print(f"\n{'='*60}")
        print("Received Travelport API Request:")
        print(json.dumps(data, indent=2))
        print(f"{'='*60}\n")

        # Extract search criteria
        query_request = data.get('CatalogProductOfferingsQueryRequest', {})
        catalog_request = query_request.get('CatalogProductOfferingsRequest', {})

        search_criteria = catalog_request.get('SearchCriteriaFlight', [])
        passenger_criteria = catalog_request.get('PassengerCriteria', [])

        if not search_criteria:
            return jsonify({
                'error': 'No search criteria provided'
            }), 400

        # Get first search criteria (outbound)
        outbound_criteria = search_criteria[0]
        origin = outbound_criteria.get('From', {}).get('value', '')
        destination = outbound_criteria.get('To', {}).get('value', '')
        departure_date = outbound_criteria.get('departureDate', '')

        # Check for return flight
        return_date = None
        if len(search_criteria) > 1:
            return_criteria = search_criteria[1]
            return_date = return_criteria.get('departureDate', '')

        # Count passengers
        total_passengers = sum(p.get('number', 1) for p in passenger_criteria)

        # Get cabin class
        cabin_list = catalog_request.get('Cabin', [])
        cabin_class = cabin_list[0] if cabin_list else 'Economy'

        # Get mock flights
        outbound_flights, return_flights = get_mock_flights_for_route(
            origin, destination, departure_date, return_date
        )

        if not outbound_flights:
            # Return empty result if no flights found
            return jsonify({
                'CatalogProductOfferingsResponse': {
                    'CatalogProductOfferings': {
                        'CatalogProductOffering': []
                    },
                    'ReferenceList': []
                }
            })

        # Build response
        offerings = []
        flight_references = []
        product_references = []
        flight_map = {}

        # Generate 3-5 offers
        num_offers = random.randint(3, 5)

        for offer_idx in range(num_offers):
            # Select flights for this offer
            selected_outbound = random.choice(outbound_flights)
            selected_return = random.choice(return_flights) if return_flights else None

            # Build flight references
            flight_list = [selected_outbound]
            if selected_return:
                flight_list.append(selected_return)

            # Create product
            product_id = generate_product_id(offer_idx)
            product_air, flight_refs = build_product_air(flight_list, product_id, departure_date)
            product_references.append(product_air)

            # Create flight references
            for idx, flight in enumerate(flight_list):
                flight_id = generate_flight_id(f"{product_id}_{idx}")
                flight_date = departure_date if idx == 0 else return_date
                flight_ref = build_flight_reference(flight, flight_id, flight_date)
                flight_map[flight_id] = flight_ref
                flight_references.append(flight_ref)

            # Calculate price
            price = calculate_price(
                BASE_PRICES.get(cabin_class, BASE_PRICES['Economy']),
                cabin_class,
                total_passengers,
                bool(return_date)
            )

            # Create offering
            offering = {
                '@type': 'CatalogProductOffering',
                'id': generate_offering_id(offer_idx),
                'TotalPrice': {
                    'code': 'USD',
                    'value': price
                },
                'ProductOptions': [{
                    '@type': 'ProductOption',
                    'ProductRef': product_id
                }]
            }
            offerings.append(offering)

        # Build reference list
        reference_list = [
            {
                '@type': 'ReferenceListFlight',
                'Flight': list(flight_map.values())
            },
            {
                '@type': 'ReferenceListProduct',
                'Product': product_references
            }
        ]

        response = {
            'CatalogProductOfferingsResponse': {
                'CatalogProductOfferings': {
                    'CatalogProductOffering': offerings
                },
                'ReferenceList': reference_list
            }
        }

        print(f"\n{'='*60}")
        print("Sending Travelport API Response:")
        print(json.dumps(response, indent=2))
        print(f"{'='*60}\n")

        return jsonify(response)

    except Exception as e:
        print(f"Error processing request: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'type': type(e).__name__
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'Travelport Mock API Server',
        'version': '1.0.0'
    })


@app.route('/', methods=['GET'])
def index():
    """Root endpoint with usage information"""
    return jsonify({
        'service': 'Travelport Mock API Server',
        'version': '1.0.0',
        'endpoints': {
            'search': '/11/air/catalog/search/catalogproductofferings (POST)',
            'health': '/health (GET)'
        },
        'usage': 'Send POST requests to /11/air/catalog/search/catalogproductofferings with Travelport API format'
    })


if __name__ == '__main__':
    print("="*60)
    print("Travelport Mock API Server")
    print("="*60)
    print("\nServer starting on http://localhost:5000")
    print("\nTo use with Odoo, set the API URL in the wizard to:")
    print("  http://localhost:5000/11/air/catalog/search/catalogproductofferings")
    print("\nPress Ctrl+C to stop the server\n")
    print("="*60)

    app.run(host='0.0.0.0', port=5000, debug=True)
